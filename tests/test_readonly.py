"""The SQLite connection must refuse every write, even if validation is bypassed."""

import sqlite3

import pytest

from database.connector import open_readonly_sqlite


@pytest.mark.parametrize("stmt", [
    "DELETE FROM customers",
    "UPDATE customers SET country = 'X'",
    "INSERT INTO categories(name) VALUES ('x')",
    "DROP TABLE customers",
    "CREATE TABLE x (a)",
    "PRAGMA writable_schema = ON",
    "ATTACH DATABASE ':memory:' AS other",
])
def test_writes_are_denied(sample_db, stmt: str) -> None:
    conn = open_readonly_sqlite(sample_db)
    with pytest.raises(sqlite3.Error):
        conn.execute(stmt)
    conn.close()


def test_reads_and_introspection_work(sample_db) -> None:
    conn = open_readonly_sqlite(sample_db)
    assert conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 120
    assert conn.execute("SELECT COUNT(*) FROM order_totals").fetchone()[0] > 0
    assert conn.execute(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<3)"
        " SELECT COUNT(*) FROM n").fetchone()[0] == 3
    # Pragmas SQLAlchemy uses for reflection / isolation level detection.
    conn.execute('PRAGMA main.table_xinfo("customers")').fetchall()
    conn.execute('PRAGMA main.foreign_key_list("orders")').fetchall()
    conn.execute("PRAGMA read_uncommitted").fetchall()
    conn.close()
