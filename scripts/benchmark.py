"""Measure how often the app turns English into a correct SQL query.

For every question the model's query is executed and its rows are compared
with the rows of a reference query written by hand. Column order and row
order are ignored, so any correct formulation passes.

Usage:
    python scripts/benchmark.py                 # all databases
    python scripts/benchmark.py --db hr library # only these
    python scripts/benchmark.py --limit 3       # first 3 questions per database
    python scripts/benchmark.py --model Qwen/Qwen2.5-Coder-1.5B-Instruct
Results are written to benchmark_results.json and benchmark_results.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.pipeline import Text2SQLPipeline  # noqa: E402
from database.connector import DatabaseConnector  # noqa: E402
from database.schema_reader import SchemaReader  # noqa: E402
from llm.generator import SQLGenerator, build_local_chat_model  # noqa: E402
from scripts.benchmark_questions import QUESTIONS  # noqa: E402
from scripts.create_sample_db import build as build_retail  # noqa: E402
from scripts.sample_databases import BUILDERS  # noqa: E402
from sql.executor import QueryExecutor  # noqa: E402
from utils.config import get_settings  # noqa: E402


@dataclass
class Case:
    database: str
    question: str
    expected_sql: str
    generated_sql: str = ""
    correct: bool = False
    reason: str = ""
    seconds: float = 0.0


def _databases(folder: Path) -> dict[str, Path]:
    """Create every benchmark database (retail = the app's sample database)."""
    paths = {"retail": ROOT / "data" / "sample.db"}
    if not paths["retail"].exists():
        build_retail(paths["retail"])
    for name, builder in BUILDERS.items():
        path = folder / f"{name}.db"
        if not path.exists():
            builder(path)
        paths[name] = path
    return paths


def _rows(connector: DatabaseConnector, sql: str, limit: int = 2000):
    """Run a query and return its rows as a comparable multiset."""
    with connector.engine.connect() as conn:
        result = conn.exec_driver_sql(sql.rstrip(";"))
        rows = result.fetchmany(limit)
    return sorted(tuple(_norm(v) for v in row) for row in rows)


def _norm(value: object) -> object:
    """Round floats so 1234.5600000001 equals 1234.56."""
    if isinstance(value, float):
        return round(value, 2)
    return value


def compare(expected, produced) -> tuple[bool, str]:
    """Do two queries answer the same question?

    Row order and column order are ignored, and a query that returns the same
    rows with fewer or extra columns still counts: asked for "customers from
    Germany", both ``SELECT *`` and ``SELECT first_name, last_name`` are right.
    """
    if expected == produced:
        return True, "exact rows"
    if len(expected) != len(produced):
        return False, f"{len(produced)} rows instead of {len(expected)}"
    as_sets_e = [set(map(str, row)) for row in expected]
    as_sets_p = [set(map(str, row)) for row in produced]
    if sorted(map(sorted, as_sets_e)) == sorted(map(sorted, as_sets_p)):
        return True, "same values, different column order"
    # Rows may be in a different order once columns differ, so pair them up.
    if _pairs_up(as_sets_p, as_sets_e):
        return True, "same rows, fewer columns"
    if _pairs_up(as_sets_e, as_sets_p):
        return True, "same rows plus extra columns"
    return False, "different values"


def _pairs_up(small: list[set], big: list[set]) -> bool:
    """Can every row on the left be matched to its own superset on the right?"""
    if not small or not all(small):
        return False
    unused = list(big)
    for row in small:
        for i, candidate in enumerate(unused):
            if row <= candidate:
                unused.pop(i)
                break
        else:
            return False
    return True


def run(dbs: list[str], limit: int | None, model_id: str,
        max_retries: int) -> list[Case]:
    settings = get_settings()
    folder = ROOT / "data" / "benchmark"
    paths = _databases(folder)
    print(f"Loading model {model_id} …", flush=True)
    llm = build_local_chat_model(model_id, settings.max_new_tokens)

    cases: list[Case] = []
    for name in dbs:
        questions = QUESTIONS[name][:limit] if limit else QUESTIONS[name]
        connector = DatabaseConnector()
        connector.connect_sqlite(paths[name])
        reader = SchemaReader(connector)
        pipeline = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(connector))
        print(f"\n=== {name} ({len(questions)} questions) ===", flush=True)
        for question, reference in questions:
            case = Case(name, question, reference)
            started = time.perf_counter()
            schema = reader.to_prompt_context(
                settings.sample_rows_in_prompt, question=question)
            generated = pipeline.generate(question, schema)
            if generated.error:
                case.reason = f"no query: {generated.error}"
            else:
                result = pipeline.run(generated.question, generated.sql, schema,
                                      max_retries=max_retries)
                case.generated_sql = result.sql
                if not result.success:
                    case.reason = f"failed to run: {result.error}"
                else:
                    try:
                        case.correct, case.reason = compare(
                            _rows(connector, reference),
                            _rows(connector, result.sql))
                    except Exception as exc:  # noqa: BLE001
                        case.reason = f"comparison failed: {exc}"
            case.seconds = round(time.perf_counter() - started, 1)
            cases.append(case)
            # Write after every question so progress can be watched live.
            (ROOT / "benchmark_results.json").write_text(
                json.dumps([asdict(c) for c in cases], indent=2),
                encoding="utf-8")
            mark = "PASS" if case.correct else "FAIL"
            print(f"[{mark}] {question}  ({case.seconds}s)", flush=True)
            print(f"       {case.generated_sql or '-'}", flush=True)
            if not case.correct:
                print(f"       reason: {case.reason}", flush=True)
        connector.close()
    return cases


def report(cases: list[Case], model_id: str) -> str:
    total = len(cases)
    passed = sum(c.correct for c in cases)
    pct = 100.0 * passed / total if total else 0.0
    lines = [f"# Accuracy benchmark", "",
             f"Model: `{model_id}`", "",
             f"**{passed}/{total} correct = {pct:.0f}%**", "",
             "| Database | Correct | Questions | Accuracy | Avg time |",
             "|---|---|---|---|---|"]
    for name in sorted({c.database for c in cases}):
        group = [c for c in cases if c.database == name]
        ok = sum(c.correct for c in group)
        avg = sum(c.seconds for c in group) / len(group)
        lines.append(f"| {name} | {ok} | {len(group)} | "
                     f"{100.0 * ok / len(group):.0f}% | {avg:.0f}s |")
    lines += ["", "## Questions that failed", ""]
    for case in cases:
        if not case.correct:
            lines.append(f"- **{case.database}** — {case.question}  \n"
                         f"  `{case.generated_sql or 'no query'}`  \n"
                         f"  {case.reason}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", nargs="*", default=list(QUESTIONS),
                        choices=list(QUESTIONS))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--model", default=get_settings().model_name)
    parser.add_argument("--retries", type=int, default=1)
    args = parser.parse_args()

    started = time.perf_counter()
    cases = run(args.db, args.limit, args.model, args.retries)
    text = report(cases, args.model)
    (ROOT / "benchmark_results.md").write_text(text, encoding="utf-8")
    (ROOT / "benchmark_results.json").write_text(
        json.dumps([asdict(c) for c in cases], indent=2), encoding="utf-8")
    print("\n" + text)
    print(f"Finished in {(time.perf_counter() - started) / 60:.1f} minutes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
