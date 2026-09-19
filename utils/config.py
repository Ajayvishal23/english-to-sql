"""Application settings loaded from environment variables with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable, falling back on bad values."""
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    """Read a float environment variable, falling back on bad values."""
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    """Runtime configuration. Every value can be overridden via env vars."""

    # --- LLM (LangChain + Hugging Face, runs locally) ---
    model_name: str = field(
        default_factory=lambda: os.getenv(
            "T2S_MODEL", "Qwen/Qwen2.5-Coder-0.5B-Instruct"
        )
    )
    max_new_tokens: int = field(
        default_factory=lambda: _env_int("T2S_MAX_NEW_TOKENS", 256)
    )

    # --- Query execution ---
    max_rows: int = field(
        default_factory=lambda: _env_int("T2S_MAX_ROWS", 1000)
    )
    query_timeout_s: float = field(
        default_factory=lambda: _env_float("T2S_QUERY_TIMEOUT", 15.0)
    )
    max_retries: int = field(
        default_factory=lambda: _env_int("T2S_MAX_RETRIES", 1)
    )

    # --- Prompt building ---
    sample_rows_in_prompt: int = field(
        default_factory=lambda: _env_int("T2S_SAMPLE_ROWS", 2)
    )
    max_question_length: int = 500

    # --- Paths ---
    data_dir: Path = PROJECT_ROOT / "data"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    log_dir: Path = PROJECT_ROOT / "logs"
    default_db_path: Path = PROJECT_ROOT / "data" / "sample.db"


def get_settings() -> Settings:
    """Return a fresh Settings instance."""
    return Settings()
