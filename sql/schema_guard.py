"""Check generated SQL against the real schema before running it.

Small language models often invent table or column names, or attach a column
to the wrong alias (``o.quantity`` when ``quantity`` lives in
``order_items``). Catching that here — without touching the database — means
the user sees a corrected query instead of a driver error, and the model gets
a precise hint when it has to try again.

Pure Python: no SQL parser dependency, no Streamlit, no database access.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

from sql.validator import tokenize

# Words that follow FROM/JOIN but are not table names.
_NOT_TABLES = {"SELECT", "LATERAL", "ONLY", "UNNEST", "VALUES", "TABLE"}
# Words that may follow a table name without being an alias.
_AFTER_TABLE = {
    "ON", "USING", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "OFFSET",
    "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "OUTER", "NATURAL",
    "UNION", "EXCEPT", "INTERSECT", "AS", "WINDOW", "AND", "OR", "ON",
}
_CREATE_TABLE_RE = re.compile(r"CREATE\s+TABLE\s+(\w+)\s*\(", re.IGNORECASE)


def parse_schema_text(schema: str) -> dict[str, list[str]]:
    """Read ``{table: [columns]}`` out of the CREATE TABLE prompt context."""
    tables: dict[str, list[str]] = {}
    for match in _CREATE_TABLE_RE.finditer(schema or ""):
        name = match.group(1)
        body, depth, i = [], 1, match.end()
        while i < len(schema) and depth:
            char = schema[i]
            depth += (char == "(") - (char == ")")
            if depth:
                body.append(char)
            i += 1
        tables[name] = _split_columns("".join(body))
    return tables


def _split_columns(body: str) -> list[str]:
    """Column names from a CREATE TABLE body (one line or many)."""
    parts, depth, current = [], 0, []
    for char in body:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    columns = []
    for part in parts:
        part = part.strip()
        if not part or part.upper().startswith(
                ("FOREIGN KEY", "PRIMARY KEY", "UNIQUE", "CHECK",
                 "CONSTRAINT")):
            continue
        columns.append(_first_identifier(part))
    return columns


_QUOTES = {'"': '"', "`": "`", "[": "]"}


def _first_identifier(text: str) -> str:
    """The column name at the start of a definition, quotes removed."""
    text = text.strip()
    if text[:1] in _QUOTES:
        closing = _QUOTES[text[0]]
        end = text.find(closing, 1)
        if end > 0:
            return text[1:end]
    return text.split()[0].strip('"`[]')
    return tables


@dataclass
class SchemaCheck:
    """What a generated query gets wrong about the schema."""

    problems: list[str] = field(default_factory=list)
    hint: str = ""
    fixed_sql: str | None = None   # set when it could be repaired safely

    @property
    def ok(self) -> bool:
        return not self.problems


def _duplicate_aliases(tokens: list) -> list[str]:
    """Aliases used for more than one table (makes columns ambiguous)."""
    seen: dict[str, str] = {}
    duplicates = []
    words = [t for t in tokens if t.kind in {"word", "other", "lparen"}]
    for i, token in enumerate(words):
        if token.kind != "word" or token.value.upper() not in {"FROM", "JOIN"}:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        if not nxt or nxt.kind != "word" or nxt.value.upper() in _NOT_TABLES:
            continue
        table = nxt.value
        after = words[i + 2] if i + 2 < len(words) else None
        if after and after.kind == "word" and after.value.upper() == "AS":
            after = words[i + 3] if i + 3 < len(words) else None
        alias = (after.value if after and after.kind == "word"
                 and after.value.upper() not in _AFTER_TABLE else table)
        if alias.lower() in seen and seen[alias.lower()].lower() != table.lower():
            duplicates.append(alias)
        seen[alias.lower()] = table
    return duplicates


def _table_refs(tokens: list) -> dict[str, str]:
    """Map every alias (and table name) used in the query to its table."""
    refs: dict[str, str] = {}
    words = [t for t in tokens if t.kind in {"word", "other", "lparen"}]
    for i, token in enumerate(words):
        if token.kind != "word" or token.value.upper() not in {"FROM", "JOIN"}:
            continue
        nxt = words[i + 1] if i + 1 < len(words) else None
        if not nxt or nxt.kind != "word" or nxt.value.upper() in _NOT_TABLES:
            continue
        table = nxt.value
        refs[table.lower()] = table
        after = words[i + 2] if i + 2 < len(words) else None
        if after and after.kind == "word" and after.value.upper() == "AS":
            after = words[i + 3] if i + 3 < len(words) else None
        if (after and after.kind == "word"
                and after.value.upper() not in _AFTER_TABLE):
            refs[after.value.lower()] = table
    return refs


def _qualified_columns(tokens: list) -> list[tuple[str, str]]:
    """Every ``alias.column`` pair in the query, in order."""
    pairs = []
    for i in range(len(tokens) - 2):
        a, dot, b = tokens[i], tokens[i + 1], tokens[i + 2]
        if (a.kind == "word" and dot.kind == "other" and dot.value == "."
                and b.kind == "word"):
            pairs.append((a.value, b.value))
    return pairs


def check_sql(sql: str, tables: dict[str, list[str]]) -> SchemaCheck:
    """Compare a query with the schema; repair wrong aliases when possible."""
    result = SchemaCheck()
    if not sql or not tables:
        return result
    try:
        tokens = tokenize(sql)
    except Exception:  # noqa: BLE001 - the safety validator reports syntax issues
        return result
    tokens = [t for t in tokens if t.kind != "comment"]

    lower_tables = {name.lower(): name for name in tables}
    columns_of = {name.lower(): {c.lower() for c in cols}
                  for name, cols in tables.items()}
    refs = _table_refs(tokens)

    # 0. the same alias used for two tables makes every column ambiguous
    for alias in _duplicate_aliases(tokens):
        result.problems.append(f"alias '{alias}' is used for two tables")
        result.hint += (f" The alias '{alias}' is given to two different "
                        f"tables, so its columns are ambiguous. Give each "
                        f"table its own alias.")

    # 1. tables that do not exist
    unknown_tables = sorted({
        table for table in refs.values() if table.lower() not in lower_tables
    })
    for table in unknown_tables:
        result.problems.append(f"table '{table}' does not exist")
    if unknown_tables:
        result.hint += (" There is no table named "
                        + ", ".join(f"'{t}'" for t in unknown_tables)
                        + f". The tables are: {', '.join(tables)}.")
        return result  # alias repair is meaningless without valid tables

    # 2. columns attached to the wrong/undefined alias, or missing entirely
    fixed = sql
    for alias, column in _qualified_columns(tokens):
        table = refs.get(alias.lower())
        if table is not None and column.lower() in columns_of.get(
                table.lower(), set()):
            continue
        if table is None:
            # The alias was never defined (e.g. "i.quantity" when the table
            # was aliased "oi") - point it at the table that has the column.
            owners = [a for a, tbl in refs.items()
                      if column.lower() in columns_of.get(tbl.lower(), set())]
            # Prefer a real alias over the bare table name.
            owners.sort(key=lambda a: a in {t.lower() for t in refs.values()})
            result.problems.append(f"alias '{alias}' is not defined")
            if len(set(refs[a] for a in owners)) == 1:
                fixed = re.sub(
                    rf"\b{re.escape(alias)}\.{re.escape(column)}\b",
                    f"{owners[0]}.{column}", fixed)
            else:
                result.hint += (f" The alias '{alias}' is never defined in the "
                                f"query; use one of the aliases you declared "
                                f"after FROM/JOIN.")
            continue
        owners = [name for name, cols in columns_of.items()
                  if column.lower() in cols]
        in_query = [alias_ for alias_, tbl in refs.items()
                    if tbl.lower() in owners and alias_ != tbl.lower()] or [
            name for name in owners if name in {t.lower() for t in refs.values()}]
        result.problems.append(
            f"'{alias}.{column}' does not exist in table '{table}'")
        if owners:
            owner_names = ", ".join(lower_tables[o] for o in owners)
            result.hint += (f" The column '{column}' is in {owner_names}, "
                            f"not in '{table}'.")
            if len(in_query) == 1:
                # The right table is already joined - just fix the prefix.
                fixed = re.sub(rf"\b{re.escape(alias)}\.{re.escape(column)}\b",
                               f"{in_query[0]}.{column}", fixed)
            else:
                result.hint += (f" Join {lower_tables[owners[0]]} "
                                f"(or select the column from it).")
        else:
            # Near miss? "specialty" when the column is "speciality".
            everywhere = {c: name for name, cols in tables.items() for c in cols}
            close = difflib.get_close_matches(column, list(everywhere), n=1,
                                              cutoff=0.82)
            if close:
                right = close[0]
                result.hint += (f" There is no '{column}'; the column is called "
                                f"'{right}' (in {everywhere[right]}).")
                if everywhere[right].lower() in {t.lower()
                                                 for t in refs.values()}:
                    fixed = re.sub(
                        rf"\b{re.escape(alias)}\.{re.escape(column)}\b",
                        f"{alias}.{right}", fixed)
            else:
                result.hint += (f" No table has a column named '{column}'; use "
                                f"only the columns listed in the schema.")
    # 3. unqualified names that are almost a column ("specialty" -> "speciality")
    fixed = _fix_unqualified(fixed, tokens, refs, tables, columns_of, result)

    if result.problems and fixed != sql and not _self_comparison(fixed):
        # Re-check the repaired query; only offer it if it is now clean.
        if check_sql(fixed, tables).ok:
            result.fixed_sql = fixed
    return result


_SQL_WORDS = {
    "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL",
    "OUTER", "CROSS", "NATURAL", "ON", "USING", "GROUP", "ORDER", "BY", "AS",
    "AND", "OR", "NOT", "IN", "IS", "NULL", "LIKE", "BETWEEN", "HAVING",
    "LIMIT", "OFFSET", "DISTINCT", "COUNT", "SUM", "AVG", "MIN", "MAX", "ASC",
    "DESC", "CASE", "WHEN", "THEN", "ELSE", "END", "UNION", "ALL", "EXCEPT",
    "INTERSECT", "WITH", "EXISTS", "CAST", "ROUND", "COALESCE", "IFNULL",
    "SUBSTR", "STRFTIME", "DATE", "JULIANDAY", "LOWER", "UPPER", "TRIM",
    "LENGTH", "ABS", "TRUE", "FALSE", "OVER", "PARTITION", "ROW_NUMBER",
    "RANK", "DENSE_RANK", "NULLS", "FIRST", "LAST", "REPLACE", "INSTR",
}


def _fix_unqualified(sql: str, tokens: list, refs: dict[str, str],
                     tables: dict[str, list[str]],
                     columns_of: dict[str, set[str]],
                     result: SchemaCheck) -> str:
    """Repair a bare column name that is almost right (typo or variant).

    Only near-misses are touched: anything else is left alone, because bare
    words can also be output aliases or SQL functions.
    """
    known: set[str] = set()
    for table in {t.lower() for t in refs.values()}:
        known |= columns_of.get(table, set())
    candidates = {c for table in {t.lower() for t in refs.values()}
                  for c in columns_of.get(table, set())}
    skip_next = False
    for i, token in enumerate(tokens):
        if token.kind != "word":
            continue
        word = token.value
        upper = word.upper()
        if skip_next:                      # the name right after AS is an alias
            skip_next = False
            continue
        if upper == "AS":
            skip_next = True
            continue
        if upper in _SQL_WORDS or word.lower() in known:
            continue
        if word.lower() in refs or word.lower() in {t.lower() for t in tables}:
            continue
        prev = tokens[i - 1] if i else None
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if prev is not None and prev.kind == "other" and prev.value == ".":
            continue                        # already handled as alias.column
        if nxt is not None and (nxt.kind == "lparen"
                                or (nxt.kind == "other" and nxt.value == ".")):
            continue                        # function call or table prefix
        close = difflib.get_close_matches(word.lower(), sorted(candidates),
                                          n=1, cutoff=0.85)
        if close:
            result.problems.append(f"'{word}' is not a column")
            result.hint += (f" There is no column '{word}'; it is called "
                            f"'{close[0]}'.")
            sql = re.sub(rf"(?<![.\w]){re.escape(word)}\b", close[0], sql)
    return sql


_SELF_EQ_RE = re.compile(r"\b(\w+\.\w+)\s*=\s*\1\b", re.IGNORECASE)


def _self_comparison(sql: str) -> bool:
    """True if a repair produced a meaningless ``x.y = x.y`` condition."""
    return bool(_SELF_EQ_RE.search(sql))
