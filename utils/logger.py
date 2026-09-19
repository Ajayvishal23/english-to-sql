"""Centralised logging: console + rotating file handler."""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_configured = False


def _configure_root() -> None:
    """Configure the package-level logger exactly once."""
    global _configured
    if _configured:
        return

    level = os.getenv("T2S_LOG_LEVEL", "INFO").upper()
    root = logging.getLogger("text2sql")
    root.setLevel(level)
    root.propagate = False
    formatter = logging.Formatter(_FORMAT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_DIR / "text2sql.log",
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:  # read-only filesystem etc.
        root.warning("File logging disabled: %s", exc)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the 'text2sql' namespace."""
    _configure_root()
    return logging.getLogger(f"text2sql.{name}")
