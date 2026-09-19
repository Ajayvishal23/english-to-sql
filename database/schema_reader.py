"""Schema discovery and prompt-context generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.exc import SQLAlchemyError

from database.connector import DatabaseConnector
from utils.logger import get_logger

logger = get_logger("database.schema_reader")


@dataclass
class ColumnInfo:
    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False


@dataclass
class ForeignKeyInfo:
    columns: list[str]
    referred_table: str
    referred_columns: list[str]


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    row_count: int | None = None

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]


@dataclass
class Relationship:
    from_table: str
    from_columns: list[str]
    to_table: str
    to_columns: list[str]

    def __str__(self) -> str:
        return (
            f"{self.from_table}({', '.join(self.from_columns)}) -> "
            f"{self.to_table}({', '.join(self.to_columns)})"
        )


class SchemaReader:
    """Reads tables, columns and relationships from a connected database."""

    def __init__(self, connector: DatabaseConnector) -> None:
        self.connector = connector
        self._tables: dict[str, TableInfo] | None = None
        self._metadata = MetaData()
        self._context_cache: dict[tuple[int, tuple[str, ...]], str] = {}

    # ------------------------------------------------------------------ #
    # Discovery
    # ------------------------------------------------------------------ #
    def refresh(self) -> None:
        """Clear cached schema so the next call re-reads it."""
        self._tables = None
        self._metadata = MetaData()
        self._context_cache = {}

    def get_tables(self) -> dict[str, TableInfo]:
        """Return all user tables and views keyed by name (cached)."""
        if self._tables is not None:
            return self._tables

        insp = inspect(self.connector.engine)
        names = [
            n for n in insp.get_table_names() + insp.get_view_names()
            if not n.startswith("sqlite_")
        ]
        tables: dict[str, TableInfo] = {}
        for name in sorted(names):
            try:
                pk_cols = set(
                    insp.get_pk_constraint(name).get("constrained_columns") or []
                )
                columns = [
                    ColumnInfo(
                        name=c["name"],
                        type=str(c["type"]),
                        nullable=bool(c.get("nullable", True)),
                        primary_key=c["name"] in pk_cols,
                    )
                    for c in insp.get_columns(name)
                ]
                fks = [
                    ForeignKeyInfo(
                        columns=fk["constrained_columns"],
                        referred_table=fk["referred_table"],
                        referred_columns=fk["referred_columns"],
                    )
                    for fk in insp.get_foreign_keys(name)
                    if fk.get("referred_table")
                ]
                tables[name] = TableInfo(name, columns, fks, self._count(name))
            except SQLAlchemyError as exc:
                logger.warning("Skipping table %s: %s", name, exc)
        logger.info("Discovered %d tables", len(tables))
        self._tables = tables
        return tables

    def get_relationships(self) -> list[Relationship]:
        """Flatten all foreign keys into a relationship list."""
        return [
            Relationship(t.name, fk.columns, fk.referred_table, fk.referred_columns)
            for t in self.get_tables().values()
            for fk in t.foreign_keys
        ]

    def _reflect(self, table_name: str) -> Table:
        """Reflect a table object (safely quoted identifiers)."""
        if table_name not in self.get_tables():
            raise ValueError(f"Unknown table: {table_name}")
        if table_name in self._metadata.tables:
            return self._metadata.tables[table_name]
        return Table(table_name, self._metadata, autoload_with=self.connector.engine)

    def _count(self, table_name: str) -> int | None:
        try:
            from sqlalchemy import func, table as sa_table

            stmt = select(func.count()).select_from(sa_table(table_name))
            with self.connector.engine.connect() as conn:
                return int(conn.execute(stmt).scalar_one())
        except SQLAlchemyError:
            return None

    def preview_table(self, table_name: str, limit: int = 20) -> pd.DataFrame:
        """Return the first ``limit`` rows of a table."""
        tbl = self._reflect(table_name)
        stmt = select(tbl).limit(max(1, min(limit, 1000)))
        with self.connector.engine.connect() as conn:
            result = conn.execute(stmt)
            return pd.DataFrame(result.fetchall(), columns=list(result.keys()))

    # ------------------------------------------------------------------ #
    # Prompt context
    # ------------------------------------------------------------------ #
    def relevant_tables(self, question: str, max_tables: int = 12) -> list[str]:
        """Tables worth showing the model for this question.

        Big databases do not fit in a small model's context, so tables are
        scored by how well their name and columns match the question, and the
        tables they are linked to by foreign keys are pulled in as well.
        """
        tables = self.get_tables()
        names = list(tables)
        if len(names) <= max_tables or not question:
            return names
        asked = _words(question)
        scored: list[tuple[float, str]] = []
        for name, info in tables.items():
            score = 3.0 * len(asked & _words(name))
            score += sum(0.7 for c in info.columns if asked & _words(c.name))
            scored.append((score, name))
        scored.sort(key=lambda item: (-item[0], item[1]))
        chosen = [name for score, name in scored if score > 0][:max_tables]
        if not chosen:  # nothing matched: fall back to the biggest tables
            by_rows = sorted(tables.values(), key=lambda t: -(t.row_count or 0))
            return [t.name for t in by_rows[:max_tables]]
        # Pull in directly linked tables so JOINs stay possible.
        linked: list[str] = []
        for name in chosen:
            for fk in tables[name].foreign_keys:
                if fk.referred_table in tables:
                    linked.append(fk.referred_table)
            for other, info in tables.items():
                if any(fk.referred_table == name for fk in info.foreign_keys):
                    linked.append(other)
        for name in linked:
            if name not in chosen and len(chosen) < max_tables + 4:
                chosen.append(name)
        return chosen

    def to_prompt_context(self, sample_rows: int = 3, question: str = "",
                          max_tables: int = 12) -> str:
        """Render the schema as compact CREATE TABLE statements + samples.

        Sample rows help the model learn value formats (e.g. 'Germany'
        vs 'DE'), which dramatically improves WHERE-clause accuracy.
        """
        wanted = self.relevant_tables(question, max_tables)
        key = (sample_rows, tuple(wanted))
        if key in self._context_cache:
            return self._context_cache[key]
        blocks: list[str] = []
        for t in (self.get_tables()[name] for name in wanted):
            lines = []
            for c in t.columns:
                flags = " PRIMARY KEY" if c.primary_key else ""
                flags += "" if c.nullable or c.primary_key else " NOT NULL"
                lines.append(f"  {c.name} {c.type}{flags}")
            for fk in t.foreign_keys:
                lines.append(
                    f"  FOREIGN KEY ({', '.join(fk.columns)}) REFERENCES "
                    f"{fk.referred_table}({', '.join(fk.referred_columns)})"
                )
            block = f"CREATE TABLE {t.name} (\n" + ",\n".join(lines) + "\n);"

            if sample_rows > 0:
                try:
                    df = self.preview_table(t.name, sample_rows)
                    if not df.empty:
                        df = df.map(lambda v: _truncate(v))
                        block += (
                            f"\n/* {len(df)} sample rows from {t.name}:\n"
                            + df.to_csv(index=False).strip()
                            + "\n*/"
                        )
                except (SQLAlchemyError, ValueError) as exc:
                    logger.debug("No samples for %s: %s", t.name, exc)
            blocks.append(block)
        context = "\n\n".join(blocks)
        total = len(self.get_tables())
        if len(wanted) < total:
            context += (f"\n\n/* {len(wanted)} of {total} tables shown: the ones "
                        f"that match the question. */")
        self._context_cache[key] = context
        return context


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "show", "list", "give", "find", "get", "all", "the", "a", "an", "of", "in",
    "for", "by", "with", "and", "or", "me", "my", "how", "many", "much", "what",
    "which", "who", "when", "where", "top", "most", "least", "per", "each",
    "from", "that", "have", "has", "are", "is", "was", "were", "do", "does",
    "count", "total", "sum", "average", "avg", "number", "last", "first",
}


def _words(text: str) -> set[str]:
    """Lower-case word stems of a question or identifier (plural-insensitive)."""
    out = set()
    for word in _WORD_RE.findall((text or "").lower().replace("_", " ")):
        if word in _STOP or len(word) < 3:
            continue
        out.add(word)
        if word.endswith("ies"):
            out.add(word[:-3] + "y")
        elif word.endswith("es"):
            out.add(word[:-2])
        if word.endswith("s"):
            out.add(word[:-1])
        else:
            out.add(word + "s")
    return out


def _truncate(value: object, limit: int = 40) -> object:
    """Shorten long text values so they don't bloat the prompt."""
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    return value
