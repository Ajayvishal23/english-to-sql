"""Database connection management with read-only enforcement.

For SQLite, three independent safety layers are applied:
1. The file is opened with ``mode=ro`` (the OS-level handle is read-only).
2. ``PRAGMA query_only = ON`` is set on every connection.
3. An SQLite *authorizer* callback denies every operation that is not a read.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from utils.logger import get_logger

logger = get_logger("database.connector")

# SQLite authorizer action codes (see https://sqlite.org/c3ref/c_alter_table.html)
SQLITE_PRAGMA = 19
SQLITE_READ = 20
SQLITE_SELECT = 21
SQLITE_TRANSACTION = 22
SQLITE_FUNCTION = 31
SQLITE_RECURSIVE = 33

_ALLOWED_ACTIONS = {
    SQLITE_READ,
    SQLITE_SELECT,
    SQLITE_FUNCTION,
    SQLITE_RECURSIVE,
    SQLITE_TRANSACTION,
}

# Introspection pragmas SQLAlchemy needs to read the schema.
_ALLOWED_PRAGMAS = {
    "table_info",
    "table_xinfo",
    "foreign_key_list",
    "index_list",
    "index_info",
    "index_xinfo",
    "table_list",
    "database_list",
    "query_only",
    "read_uncommitted",  # SQLAlchemy reads this to detect isolation level
    "encoding",
    "collation_list",
    "compile_options",
}

# Functions that can touch the filesystem or load code.
_BLOCKED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit"}


class DatabaseConnectionError(Exception):
    """Raised when a database cannot be opened or queried."""


def sqlite_authorizer(
    action: int,
    arg1: str | None,
    arg2: str | None,
    db_name: str | None,
    trigger: str | None,
) -> int:
    """Allow only read operations on an SQLite connection."""
    if action == SQLITE_PRAGMA:
        return (
            sqlite3.SQLITE_OK
            if (arg1 or "").lower() in _ALLOWED_PRAGMAS
            else sqlite3.SQLITE_DENY
        )
    if action == SQLITE_FUNCTION:
        return (
            sqlite3.SQLITE_DENY
            if (arg2 or "").lower() in _BLOCKED_FUNCTIONS
            else sqlite3.SQLITE_OK
        )
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def open_readonly_sqlite(path: Path) -> sqlite3.Connection:
    """Open an SQLite file in read-only mode with the authorizer attached."""
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.execute("PRAGMA query_only = ON")
    conn.set_authorizer(sqlite_authorizer)
    return conn


class DatabaseConnector:
    """Owns a SQLAlchemy engine for one database."""

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._label: str = ""
        self._raw_sqlite: bool = False

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #
    def connect_sqlite(self, db_path: str | Path) -> Engine:
        """Connect to a local SQLite file in strict read-only mode."""
        # Windows "Copy as path" wraps the path in quotes.
        path = Path(str(db_path).strip().strip('"').strip("'")).expanduser()
        if path.is_dir():
            found = sorted(p.name for p in path.iterdir()
                           if p.suffix.lower() in {".db", ".sqlite", ".sqlite3"})[:5]
            hint = (f" SQLite files in it: {', '.join(found)}." if found
                    else " No .db/.sqlite files were found in it.")
            raise DatabaseConnectionError(
                f"'{path}' is a folder. Enter the full path of a database file, "
                f"e.g. {path / 'shop.db'}.{hint}"
            )
        if not path.is_file():
            raise DatabaseConnectionError(
                f"No file found at '{path}'. Check the spelling and include the "
                f"file extension (.db, .sqlite)."
            )
        self._validate_sqlite_header(path)

        creator: Callable[[], sqlite3.Connection] = (
            lambda: open_readonly_sqlite(path)
        )
        engine = create_engine(
            "sqlite://", creator=creator, poolclass=NullPool, future=True
        )
        self._set_engine(engine, label=path.name, raw_sqlite=True)
        return engine

    def connect_url(self, url: str) -> Engine:
        """Connect to any SQLAlchemy URL (PostgreSQL, MySQL, ...).

        Read-only enforcement for server databases relies on (a) the SQL
        validator, (b) read-only transactions that are always rolled back,
        and (c) you using a database user with SELECT-only grants.
        """
        if url.strip().lower().startswith("sqlite"):
            path = url.split("///", 1)[-1]
            return self.connect_sqlite(path)
        try:
            engine = create_engine(url, pool_pre_ping=True, future=True)
        except (SQLAlchemyError, ValueError) as exc:
            raise DatabaseConnectionError(f"Invalid database URL: {exc}") from exc

        if engine.dialect.name == "postgresql":
            @event.listens_for(engine, "begin")
            def _read_only(conn: Any) -> None:  # pragma: no cover - needs PG
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")

        self._set_engine(engine, label=engine.url.render_as_string(True),
                         raw_sqlite=False)
        return engine

    def _set_engine(self, engine: Engine, label: str, raw_sqlite: bool) -> None:
        """Test the new engine and swap it in."""
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            engine.dispose()
            raise DatabaseConnectionError(f"Connection test failed: {exc}") from exc
        self.close()
        self._engine = engine
        self._label = label
        self._raw_sqlite = raw_sqlite
        logger.info("Connected to database: %s", label)

    def close(self) -> None:
        """Dispose of the current engine, if any."""
        if self._engine is not None:
            self._engine.dispose()
            logger.info("Closed connection: %s", self._label)
        self._engine = None
        self._label = ""

    # ------------------------------------------------------------------ #
    # Accessors
    # ------------------------------------------------------------------ #
    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise DatabaseConnectionError("No database connected.")
        return self._engine

    @property
    def is_connected(self) -> bool:
        return self._engine is not None

    @property
    def label(self) -> str:
        return self._label

    @property
    def dialect(self) -> str:
        return self.engine.dialect.name

    @property
    def is_sqlite(self) -> bool:
        return self._raw_sqlite

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_sqlite_header(path: Path) -> None:
        """Reject files that are not SQLite databases."""
        try:
            with path.open("rb") as fh:
                header = fh.read(16)
        except OSError as exc:
            raise DatabaseConnectionError(f"Cannot read file: {exc}") from exc
        if header != b"SQLite format 3\x00":
            raise DatabaseConnectionError(f"{path.name} is not an SQLite database.")


def install_sqlite_timeout(
    raw_conn: sqlite3.Connection, timeout_s: float
) -> None:
    """Abort a running SQLite statement after ``timeout_s`` seconds."""
    deadline = time.monotonic() + timeout_s
    raw_conn.set_progress_handler(
        lambda: 1 if time.monotonic() > deadline else 0, 10_000
    )


def clear_sqlite_timeout(raw_conn: sqlite3.Connection) -> None:
    """Remove the progress handler installed by ``install_sqlite_timeout``."""
    raw_conn.set_progress_handler(None, 0)
