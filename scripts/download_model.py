"""Download the Hugging Face model and run one real English -> SQL check.

Usage:
    python scripts/download_model.py [MODEL_ID] [--if-needed]

``--if-needed`` skips everything when the check already passed for the model.
Output is shown on screen and written to ``model_check.txt``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm.generator import LOAD_MODE, local_model_dir  # noqa: E402
from utils.config import get_settings  # noqa: E402

LOG_FILE = ROOT / "model_check.txt"


def log(message: str) -> None:
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(message + "\n")


def log_memory_hogs() -> None:
    """Show which programs use the most RAM (helps free memory)."""
    try:
        import psutil
    except ImportError:
        return
    usage: dict[str, int] = {}
    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            name = proc.info["name"] or "?"
            usage[name] = usage.get(name, 0) + proc.info["memory_info"].rss
        except (psutil.Error, TypeError):
            continue
    log("Programs using the most memory right now:")
    for name, rss in sorted(usage.items(), key=lambda kv: -kv[1])[:8]:
        log(f"  {name:<30} {rss / 1024**3:5.2f} GB")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if_needed = "--if-needed" in sys.argv
    settings = get_settings()
    model_id = args[0] if args else settings.model_name
    marker = local_model_dir(model_id) / ".check_ok"
    if if_needed and marker.is_file():
        print(f"Model {model_id} already downloaded and verified.")
        return 0

    LOG_FILE.write_text("", encoding="utf-8")
    from core.pipeline import Text2SQLPipeline
    from database.connector import DatabaseConnector
    from database.schema_reader import SchemaReader
    from llm.generator import (
        LLMError,
        SQLGenerator,
        build_local_chat_model,
        download_model,
    )
    from sql.executor import QueryExecutor

    try:
        log(f"Downloading {model_id} (skipped if already present)...")
        folder = download_model(model_id)
        log(f"Model files: {folder}")

        log("Loading model...")
        start = time.perf_counter()
        llm = build_local_chat_model(model_id, settings.max_new_tokens)
        log(f"Loaded in {time.perf_counter() - start:.1f}s "
            f"({LOAD_MODE.get(model_id, '?')})")
    except LLMError as exc:
        log(f"MODEL_CHECK_FAILED: {exc}")
        log_memory_hogs()
        return 1

    conn = DatabaseConnector()
    conn.connect_sqlite(settings.default_db_path)
    schema = SchemaReader(conn).to_prompt_context(settings.sample_rows_in_prompt)
    pipe = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(conn))

    question = "Show all customers from Germany."
    start = time.perf_counter()
    gen = pipe.generate(question, schema)
    log(f"Question : {question}")
    log(f"SQL      : {gen.sql}  ({time.perf_counter() - start:.1f}s)")
    if gen.error:
        log(f"MODEL_CHECK_FAILED: {gen.error}")
        return 1
    run = pipe.run(question, gen.sql, schema)
    if not run.success:
        log(f"MODEL_CHECK_FAILED: {run.error}")
        return 1
    data = run.execution.data
    countries = sorted(set(data["country"])) if "country" in data else []
    log(f"Rows     : {run.execution.row_count}  countries={countries}")
    marker.write_text(model_id, encoding="utf-8")
    log("MODEL_CHECK_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
