"""Safe, read-only query execution."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError

from database.connector import (
    DatabaseConnector,
    clear_sqlite_timeout,
    install_sqlite_timeout,
)
from sql.validator import SQLValidator
from utils.logger import get_logger

logger = get_logger("sql.executor")


@dataclass
class ExecutionResult:
    success: bool
    sql: str
    data: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: str | None = None
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0


class QueryExecutor:
    """Validates and executes SELECT statements in a rolled-back transaction."""

    def __init__(self, connector: DatabaseConnector,
                 validator: SQLValidator | None = None,
                 max_rows: int = 1000, timeout_s: float = 15.0) -> None:
        self.connector = connector
        self.validator = validator or SQLValidator()
        self.max_rows = max_rows
        self.timeout_s = timeout_s

    def execute(self, sql: str) -> ExecutionResult:
        """Validate then run ``sql``. Never raises for query errors."""
        check = self.validator.validate(sql)
        if not check.is_valid:
            return ExecutionResult(False, sql, error="Blocked by safety check: "
                                   + " ".join(check.errors))

        start = time.perf_counter()
        try:
            with self.connector.engine.connect() as conn:
                raw = None
                if self.connector.is_sqlite:
                    raw = conn.connection.driver_connection
                    install_sqlite_timeout(raw, self.timeout_s)
                try:
                    # exec_driver_sql avoids SQLAlchemy treating ':name'
                    # inside the query as a bind parameter.
                    result = conn.exec_driver_sql(check.sql.rstrip(";"))
                    columns = list(result.keys())
                    rows = result.fetchmany(self.max_rows + 1)
                finally:
                    if raw is not None:
                        clear_sqlite_timeout(raw)
                    conn.rollback()  # guarantee nothing is persisted
        except (SQLAlchemyError, sqlite3.Error) as exc:
            message = _clean_error(exc)
            if "interrupted" in message.lower():
                message = f"Query took longer than {self.timeout_s:g}s and was stopped."
            logger.warning("Query failed: %s | %s", message, check.sql)
            return ExecutionResult(
                False, check.sql, error=message,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )

        truncated = len(rows) > self.max_rows
        rows = rows[: self.max_rows]
        df = pd.DataFrame([tuple(r) for r in rows], columns=_dedupe(columns))
        elapsed = (time.perf_counter() - start) * 1000
        logger.info("Query OK: %d rows in %.1f ms", len(df), elapsed)
        return ExecutionResult(True, check.sql, df, None, len(df), truncated, elapsed)


def _clean_error(exc: Exception) -> str:
    """Return the driver's message without SQLAlchemy boilerplate."""
    orig = getattr(exc, "orig", None)
    msg = str(orig if orig is not None else exc)
    return msg.split("\n[SQL:")[0].split("\n(Background")[0].strip()


def _dedupe(columns: list[str]) -> list[str]:
    """Make duplicate column names unique (e.g. two 'id' columns in a JOIN)."""
    seen: dict[str, int] = {}
    out = []
    for c in columns:
        if c in seen:
            seen[c] += 1
            out.append(f"{c}_{seen[c]}")
        else:
            seen[c] = 0
            out.append(c)
    return out
