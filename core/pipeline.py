"""Orchestrates: question -> SQL -> validate -> execute -> self-correct."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from llm.generator import LLMError, SQLGenerator
from sql.executor import ExecutionResult, QueryExecutor
from sql.schema_guard import check_sql, parse_schema_text
from sql.validator import SQLValidator, sanitize_question
from utils.logger import get_logger

logger = get_logger("core.pipeline")

_UNKNOWN_COLUMN = re.compile(r"no such column:?\s*([\w.]+)", re.IGNORECASE)
_UNKNOWN_TABLE = re.compile(r"no such table:?\s*([\w.]+)", re.IGNORECASE)


def error_hint(error: str, schema: str) -> str:
    """Tell the model where a missing column actually lives.

    Small models often join the wrong table (e.g. ``o.quantity`` when
    ``quantity`` is in ``order_items``). Repeating the error alone makes them
    return the same query, so we add the fact they are missing.
    """
    match = _UNKNOWN_COLUMN.search(error or "")
    if match:
        column = match.group(1).split(".")[-1]
        tables = [
            name for name, body in re.findall(
                r"CREATE TABLE (\w+) \(((?:[^;]|\n)*?)\n\);", schema)
            if re.search(rf"^\s*{re.escape(column)}\s", body, re.MULTILINE)
        ]
        if tables:
            return (f" The column '{column}' does not exist in that table; it "
                    f"belongs to: {', '.join(tables)}. Join that table (or use "
                    f"the right alias) instead of inventing the column.")
        return (f" No table has a column named '{column}'. Use only the column "
                f"names listed in the schema.")
    match = _UNKNOWN_TABLE.search(error or "")
    if match:
        names = re.findall(r"CREATE TABLE (\w+) \(", schema)
        return (f" There is no table '{match.group(1)}'. The tables are: "
                f"{', '.join(names)}.")
    return ""


@dataclass
class Attempt:
    sql: str
    error: str | None


@dataclass
class PipelineResult:
    question: str
    sql: str
    execution: ExecutionResult | None = None
    attempts: list[Attempt] = field(default_factory=list)
    error: str | None = None
    notes: list[str] = field(default_factory=list)  # what was fixed silently

    @property
    def success(self) -> bool:
        return self.execution is not None and self.execution.success


class Text2SQLPipeline:
    """Application service tying the generator, validator and executor."""

    def __init__(self, generator: SQLGenerator, executor: QueryExecutor,
                 validator: SQLValidator | None = None,
                 max_question_length: int = 500,
                 max_schema_retries: int = 1) -> None:
        self.generator = generator
        self.executor = executor
        self.validator = validator or executor.validator
        self.max_question_length = max_question_length
        # How many times the model may be asked to fix a query that does not
        # match the schema (checked before it is ever executed).
        self.max_schema_retries = max_schema_retries

    def _schema_repair(self, sql: str, schema: str) -> tuple[str, list[str], str]:
        """Fix wrong aliases against the real schema; report what is left.

        Returns ``(sql, notes, error_for_the_model)``.
        """
        tables = parse_schema_text(schema)
        if not tables:
            return sql, [], ""
        check = check_sql(sql, tables)
        if check.ok:
            return sql, [], ""
        if check.fixed_sql:
            logger.info("Repaired query against the schema: %s", check.fixed_sql)
            return check.fixed_sql, [
                "Fixed automatically: " + "; ".join(check.problems)], ""
        return sql, [], "; ".join(check.problems) + "." + check.hint

    def generate(self, question: str, schema: str) -> PipelineResult:
        """Step 1: English -> SQL (not executed, so the user can review it)."""
        try:
            clean_q = sanitize_question(question, self.max_question_length)
        except ValueError as exc:
            return PipelineResult(question, "", error=str(exc))
        try:
            sql = self.generator.generate_sql(clean_q, schema)
        except LLMError as exc:
            return PipelineResult(clean_q, "", error=str(exc))

        sql, notes, schema_error = self._schema_repair(sql, schema)
        if schema_error and self.max_schema_retries:
            # The query does not match the database: give the model the facts.
            try:
                sql = self.generator.fix_sql(clean_q, schema, sql, schema_error)
            except LLMError as exc:
                return PipelineResult(clean_q, sql, error=str(exc), notes=notes)
            sql, more_notes, schema_error = self._schema_repair(sql, schema)
            notes += more_notes

        check = self.validator.validate(sql)
        if not check.is_valid:
            # Give the model one chance to produce a safe query.
            try:
                sql = self.generator.fix_sql(
                    clean_q, schema, sql,
                    "Rejected by safety policy: " + " ".join(check.errors)
                    + " Only a single read-only SELECT is allowed.",
                )
                check = self.validator.validate(sql)
            except LLMError as exc:
                return PipelineResult(clean_q, sql, error=str(exc))
            if not check.is_valid:
                return PipelineResult(
                    clean_q, sql, notes=notes,
                    error="Generated query is not allowed: " + " ".join(check.errors),
                )
        if schema_error:
            notes.append("The query may still not match the database: "
                         + schema_error.strip())
        return PipelineResult(clean_q, check.sql, notes=notes)

    def run(self, question: str, sql: str, schema: str,
            max_retries: int = 2) -> PipelineResult:
        """Step 2: execute SQL, asking the LLM to fix it on failure."""
        result = PipelineResult(question, sql)
        current, notes, _ = self._schema_repair(sql, schema)
        result.notes += notes
        for attempt_no in range(max_retries + 1):
            execution = self.executor.execute(current)
            result.attempts.append(Attempt(current, execution.error))
            result.sql = execution.sql
            result.execution = execution
            if execution.success or attempt_no == max_retries:
                break
            logger.info("Attempt %d failed, asking model to fix", attempt_no + 1)
            error_text = (execution.error or "unknown error")
            error_text += error_hint(execution.error or "", schema)
            try:
                current = self.generator.fix_sql(
                    question, schema, current, error_text
                )
            except LLMError as exc:
                result.error = f"Could not auto-correct the query: {exc}"
                break
        if not result.success and result.error is None and result.execution:
            result.error = result.execution.error
        return result

    def explain(self, question: str, sql: str) -> str:
        """Plain-English explanation of ``sql``."""
        try:
            return self.generator.explain_sql(question, sql)
        except LLMError as exc:
            return f"Explanation unavailable: {exc}"
