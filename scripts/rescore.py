"""Re-score a finished benchmark run without calling the model again.

Useful after improving the comparison rules: the generated SQL is already in
benchmark_results.json, so only the row comparison is redone.

    python scripts/rescore.py [benchmark_results.json]
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.benchmark import _norm, compare, report, Case  # noqa: E402

DB_PATHS = {
    "retail": ROOT / "data" / "sample.db",
    "music_store": ROOT / "data" / "benchmark" / "music_store.db",
    "hr": ROOT / "data" / "benchmark" / "hr.db",
    "library": ROOT / "data" / "benchmark" / "library.db",
    "clinic": ROOT / "data" / "benchmark" / "clinic.db",
}


def rows(con: sqlite3.Connection, sql: str):
    cur = con.execute(sql.rstrip(";"))
    return sorted(tuple(_norm(v) for v in row) for row in cur.fetchmany(2000))


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "benchmark_results.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = []
    for item in data:
        case = Case(**item)
        if case.generated_sql:
            con = sqlite3.connect(DB_PATHS[case.database])
            try:
                case.correct, case.reason = compare(
                    rows(con, case.expected_sql), rows(con, case.generated_sql))
            except sqlite3.Error as exc:
                case.correct, case.reason = False, f"failed to run: {exc}"
            con.close()
        cases.append(case)
    text = report(cases, "Qwen/Qwen2.5-Coder-0.5B-Instruct (re-scored)")
    print(text)
    (ROOT / "benchmark_results.md").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
