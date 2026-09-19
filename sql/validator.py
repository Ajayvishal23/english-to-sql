"""SQL safety validation and user-input sanitisation.

The validator uses a small quote/comment-aware tokenizer so that keywords
inside string literals (e.g. ``WHERE note = 'please delete'``) do not cause
false positives, while keywords hidden behind comments are still caught.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger("sql.validator")

FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "DROP", "DELETE", "ALTER", "TRUNCATE", "UPDATE", "INSERT", "CREATE",
    "MERGE", "UPSERT", "GRANT", "REVOKE", "ATTACH", "DETACH", "PRAGMA",
    "VACUUM", "REINDEX", "ANALYZE", "EXEC", "EXECUTE", "CALL", "COPY",
    "INTO", "RENAME", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE",
    "BEGIN", "LOCK", "UNLOCK", "SHUTDOWN", "KILL", "HANDLER", "LOAD",
    "OUTFILE", "DUMPFILE",
})

FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset({
    "LOAD_EXTENSION", "READFILE", "WRITEFILE", "EDIT", "FTS3_TOKENIZER",
    "PG_READ_FILE", "PG_SLEEP", "SLEEP", "BENCHMARK", "LO_IMPORT", "LO_EXPORT",
})

ALLOWED_START: frozenset[str] = frozenset({"SELECT", "WITH"})
MAX_SQL_LENGTH = 10_000

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")


class SQLValidationError(Exception):
    """Raised when a query is rejected by the validator."""


@dataclass
class Token:
    kind: str  # word | string | ident | comment | semicolon | lparen | other
    value: str


@dataclass
class ValidationResult:
    is_valid: bool
    sql: str
    errors: list[str] = field(default_factory=list)

    def raise_if_invalid(self) -> None:
        if not self.is_valid:
            raise SQLValidationError(" ".join(self.errors))


def tokenize(sql: str) -> list[Token]:
    """Split SQL into coarse tokens. Raises on unterminated quotes/comments."""
    tokens: list[Token] = []
    i, n = 0, len(sql)
    closers = {"'": "'", '"': '"', "`": "`", "[": "]"}
    while i < n:
        ch = sql[i]
        if ch.isspace():
            i += 1
        elif sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end == -1 else end
            tokens.append(Token("comment", sql[i:end]))
            i = end
        elif sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            if end == -1:
                raise SQLValidationError("Unterminated block comment.")
            tokens.append(Token("comment", sql[i:end + 2]))
            i = end + 2
        elif ch in closers:
            close = closers[ch]
            j = i + 1
            while True:
                j = sql.find(close, j)
                if j == -1:
                    raise SQLValidationError("Unterminated quoted value.")
                # Doubled quote ('' or "") is an escaped quote.
                if close != "]" and j + 1 < n and sql[j + 1] == close:
                    j += 2
                    continue
                break
            kind = "string" if ch == "'" else "ident"
            tokens.append(Token(kind, sql[i:j + 1]))
            i = j + 1
        elif _WORD_RE.match(sql, i):
            m = _WORD_RE.match(sql, i)
            assert m is not None
            tokens.append(Token("word", m.group(0)))
            i = m.end()
        elif ch == ";":
            tokens.append(Token("semicolon", ch))
            i += 1
        elif ch == "(":
            tokens.append(Token("lparen", ch))
            i += 1
        else:
            tokens.append(Token("other", ch))
            i += 1
    return tokens


class SQLValidator:
    """Allows exactly one read-only SELECT statement."""

    def __init__(self, max_length: int = MAX_SQL_LENGTH) -> None:
        self.max_length = max_length

    def validate(self, sql: str) -> ValidationResult:
        errors: list[str] = []
        sql = (sql or "").strip()

        if not sql:
            return ValidationResult(False, sql, ["Query is empty."])
        if len(sql) > self.max_length:
            return ValidationResult(
                False, sql, [f"Query exceeds {self.max_length} characters."]
            )
        if "\x00" in sql:
            return ValidationResult(False, sql, ["Query contains a null byte."])

        try:
            tokens = tokenize(sql)
        except SQLValidationError as exc:
            return ValidationResult(False, sql, [str(exc)])

        code = [t for t in tokens if t.kind != "comment"]

        # --- exactly one statement -------------------------------------
        while code and code[-1].kind == "semicolon":
            code.pop()
        if not code:
            return ValidationResult(False, sql, ["Query is empty."])
        if any(t.kind == "semicolon" for t in code):
            errors.append("Multiple SQL statements are not allowed.")

        # --- must start with SELECT / WITH -----------------------------
        first = code[0]
        if first.kind != "word" or first.value.upper() not in ALLOWED_START:
            errors.append("Only SELECT queries are allowed.")

        words = [t.value.upper() for t in code if t.kind == "word"]
        if first.value.upper() == "WITH" and "SELECT" not in words:
            errors.append("WITH clause must be followed by a SELECT.")

        # --- forbidden keywords & functions ----------------------------
        found = sorted({w for w in words if w in FORBIDDEN_KEYWORDS})
        if found:
            errors.append(f"Forbidden keyword(s): {', '.join(found)}.")

        for idx, tok in enumerate(code[:-1]):
            if (tok.kind == "word" and tok.value.upper() in FORBIDDEN_FUNCTIONS
                    and code[idx + 1].kind == "lparen"):
                errors.append(f"Forbidden function: {tok.value}().")

        # Clean SQL: comments removed, single trailing semicolon.
        clean = _rebuild(sql, tokens)
        result = ValidationResult(not errors, clean, errors)
        if errors:
            logger.warning("Rejected SQL (%s): %s", " ".join(errors), sql)
        return result


def _rebuild(sql: str, tokens: list[Token]) -> str:
    """Return the SQL with comments stripped and whitespace normalised."""
    out = sql
    for t in tokens:
        if t.kind == "comment":
            out = out.replace(t.value, " ", 1)
    out = re.sub(r"[ \t]+\n", "\n", out).strip().rstrip(";").strip()
    return out + ";"


def sanitize_question(question: str, max_length: int = 500) -> str:
    """Normalise a user question before it is sent to the LLM.

    Removes control characters, collapses whitespace and enforces a length
    limit. Raises ``ValueError`` for empty input.
    """
    text = unicodedata.normalize("NFKC", question or "")
    text = "".join(
        ch for ch in text
        if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    )
    text = re.sub(r"\s+", " ", text).strip()
    # Neutralise our own prompt delimiters to limit prompt injection.
    text = re.sub(r"</?question>", "", text, flags=re.IGNORECASE)
    text = text.replace("```", "'''")
    if not text:
        raise ValueError("Please enter a question.")
    if len(text) > max_length:
        raise ValueError(f"Question is too long (max {max_length} characters).")
    return text
