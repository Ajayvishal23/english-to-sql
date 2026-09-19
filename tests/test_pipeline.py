"""End-to-end tests with SQLAlchemy and a fake LLM (no model download needed)."""

import pytest

pytest.importorskip("sqlalchemy")

from core.pipeline import Text2SQLPipeline  # noqa: E402
from database.connector import DatabaseConnectionError, DatabaseConnector  # noqa: E402
from database.schema_reader import SchemaReader  # noqa: E402
from llm.generator import SQLGenerator  # noqa: E402
from sql.executor import QueryExecutor  # noqa: E402


@pytest.fixture
def connector(sample_db):
    c = DatabaseConnector()
    c.connect_sqlite(sample_db)
    yield c
    c.close()


def test_schema_reader(connector) -> None:
    reader = SchemaReader(connector)
    tables = reader.get_tables()
    assert {"customers", "orders", "order_items", "products"} <= set(tables)
    assert tables["customers"].row_count == 120
    assert any(c.primary_key for c in tables["customers"].columns)
    rels = {str(r) for r in reader.get_relationships()}
    assert "orders(customer_id) -> customers(customer_id)" in rels
    ctx = reader.to_prompt_context(2)
    assert "CREATE TABLE customers" in ctx and "sample rows" in ctx
    assert len(reader.preview_table("products", 5)) == 5


def test_executor_success_and_limits(connector) -> None:
    ex = QueryExecutor(connector, max_rows=10)
    res = ex.execute("SELECT * FROM customers WHERE country = 'Germany'")
    assert res.success and 0 < res.row_count <= 10
    res = ex.execute("SELECT * FROM order_items")
    assert res.truncated and res.row_count == 10
    res = ex.execute("SELECT strftime('%H:%M', 'now') AS t")  # ':' is not a bind
    assert res.success


def test_executor_blocks_and_errors(connector) -> None:
    ex = QueryExecutor(connector)
    assert not ex.execute("DELETE FROM customers").success
    bad = ex.execute("SELECT nope FROM customers")
    assert not bad.success and "nope" in bad.error


def test_executor_timeout(connector) -> None:
    ex = QueryExecutor(connector, timeout_s=0.2)
    res = ex.execute(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n) "
        "SELECT COUNT(*) FROM n")
    assert not res.success and "longer than" in res.error


def test_pipeline_self_correction(connector, fake_llm_factory) -> None:
    llm = fake_llm_factory([
        "```sql\nSELECT * FROM customer WHERE country='Germany'\n```",
        "```sql\nSELECT * FROM customers WHERE country='Germany'\n```",
    ])
    pipe = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(connector))
    schema = SchemaReader(connector).to_prompt_context(0)
    gen = pipe.generate("Show all customers from Germany.", schema)
    assert gen.error is None
    run = pipe.run(gen.question, gen.sql, schema, max_retries=2)
    assert run.success
    assert len(run.attempts) == 2
    assert "no such table" in run.attempts[0].error
    assert set(run.execution.data["country"]) == {"Germany"}


def test_pipeline_rejects_unsafe_generation(connector, fake_llm_factory) -> None:
    sneaky = "WITH d AS (DELETE FROM customers RETURNING *) SELECT * FROM d"
    llm = fake_llm_factory([sneaky, sneaky])
    pipe = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(connector))
    res = pipe.generate("delete everything", "")
    assert res.error and "not allowed" in res.error

    # A reply that is not a SELECT at all is never treated as SQL.
    llm = fake_llm_factory(["DROP TABLE customers"])
    pipe = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(connector))
    res = pipe.generate("delete everything", "")
    assert res.error and not res.sql


def test_rejects_non_sqlite_file(tmp_path) -> None:
    f = tmp_path / "fake.db"
    f.write_text("hello")
    with pytest.raises(DatabaseConnectionError):
        DatabaseConnector().connect_sqlite(f)


def test_connect_folder_and_quoted_path(tmp_path, sample_db) -> None:
    with pytest.raises(DatabaseConnectionError, match="is a folder"):
        DatabaseConnector().connect_sqlite(tmp_path)
    conn = DatabaseConnector()
    conn.connect_sqlite(f'"{sample_db}"')
    assert conn.is_connected
    conn.close()


def test_error_hint_points_at_the_right_table(connector) -> None:
    from core.pipeline import error_hint

    schema = SchemaReader(connector).to_prompt_context(0)
    hint = error_hint("no such column: o.quantity", schema)
    assert "order_items" in hint
    assert "no table 'sales'" in error_hint("no such table: sales", schema)
    assert error_hint("syntax error", schema) == ""


def test_relevant_tables_for_big_schemas(connector) -> None:
    reader = SchemaReader(connector)
    picked = reader.relevant_tables("Which products sell the most?", max_tables=3)
    assert "products" in picked
    assert len(picked) <= 7  # 3 matches + linked tables
    # With room for everything, nothing is dropped.
    assert set(reader.relevant_tables("anything", max_tables=50)) == set(
        reader.get_tables())


def test_prompt_context_limits_tables(connector) -> None:
    reader = SchemaReader(connector)
    context = reader.to_prompt_context(0, question="list the products",
                                       max_tables=2)
    assert "CREATE TABLE products" in context
    assert "tables shown" in context


def test_pipeline_repairs_wrong_alias_without_running_it(
        connector, fake_llm_factory) -> None:
    """A wrong alias is fixed from the schema, with no extra model call."""
    bad = ("```sql\nSELECT p.name, SUM(p.unit_price * o.quantity) AS revenue "
           "FROM products p JOIN order_items i ON i.product_id = p.product_id "
           "JOIN orders o ON o.order_id = i.order_id GROUP BY p.name "
           "ORDER BY revenue DESC LIMIT 5\n```")
    llm = fake_llm_factory([bad])
    pipe = Text2SQLPipeline(SQLGenerator(llm), QueryExecutor(connector))
    schema = SchemaReader(connector).to_prompt_context(0)
    result = pipe.generate("top products by revenue", schema)
    assert result.error is None
    assert "i.quantity" in result.sql          # repaired
    assert len(llm.calls) == 1                 # no second model call
    assert any("Fixed automatically" in n for n in result.notes)
    run = pipe.run(result.question, result.sql, schema, max_retries=0)
    assert run.success and run.execution.row_count == 5
