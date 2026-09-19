"""The schema guard catches wrong tables/columns before a query runs."""

from sql.schema_guard import check_sql, parse_schema_text

SCHEMA = """CREATE TABLE orders (
  order_id INTEGER PRIMARY KEY,
  customer_id INTEGER,
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
  order_item_id INTEGER PRIMARY KEY,
  order_id INTEGER,
  product_id INTEGER,
  quantity INTEGER
);

CREATE TABLE products (
  product_id INTEGER PRIMARY KEY,
  name TEXT,
  unit_price REAL
);"""

TABLES = parse_schema_text(SCHEMA)


def test_parse_schema_text() -> None:
    assert set(TABLES) == {"orders", "order_items", "products"}
    assert TABLES["order_items"] == ["order_item_id", "order_id", "product_id",
                                     "quantity"]
    assert "FOREIGN" not in " ".join(TABLES["orders"])


def test_valid_query_passes() -> None:
    sql = ("SELECT p.name, SUM(i.quantity) FROM products p "
           "JOIN order_items i ON i.product_id = p.product_id GROUP BY p.name")
    assert check_sql(sql, TABLES).ok


def test_wrong_alias_is_repaired() -> None:
    sql = ("SELECT p.name, SUM(p.unit_price * o.quantity) AS revenue "
           "FROM products p "
           "JOIN order_items i ON i.product_id = p.product_id "
           "JOIN orders o ON o.order_id = i.order_id GROUP BY p.name")
    result = check_sql(sql, TABLES)
    assert not result.ok
    assert "order_items" in result.hint
    assert result.fixed_sql and "i.quantity" in result.fixed_sql
    assert check_sql(result.fixed_sql, TABLES).ok


def test_unknown_table_reported_not_repaired() -> None:
    result = check_sql("SELECT * FROM sales", TABLES)
    assert not result.ok and result.fixed_sql is None
    assert "no table named 'sales'" in result.hint


def test_unknown_column_anywhere() -> None:
    result = check_sql("SELECT p.colour FROM products p", TABLES)
    assert not result.ok and result.fixed_sql is None
    assert "No table has a column named 'colour'" in result.hint


def test_no_schema_no_opinion() -> None:
    assert check_sql("SELECT 1", {}).ok
    assert check_sql("", TABLES).ok


def test_undefined_alias_is_repaired() -> None:
    """The model aliased the table 'oi' but wrote 'i.quantity'."""
    sql = ("SELECT p.name, SUM(i.quantity) AS total FROM products p "
           "JOIN order_items oi ON oi.product_id = p.product_id "
           "GROUP BY p.name")
    result = check_sql(sql, TABLES)
    assert "alias 'i' is not defined" in result.problems
    assert result.fixed_sql and "oi.quantity" in result.fixed_sql
    assert check_sql(result.fixed_sql, TABLES).ok


def test_single_line_create_table_is_parsed() -> None:
    tables = parse_schema_text(
        "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT, price REAL);")
    assert tables == {"t": ["id", "name", "price"]}


def test_quoted_column_names() -> None:
    tables = parse_schema_text('CREATE TABLE t ("order id" INTEGER, [x] TEXT);')
    assert tables["t"] == ["order id", "x"]


def test_near_miss_column_name_is_corrected() -> None:
    tables = parse_schema_text(
        "CREATE TABLE doctors (doctor_id INTEGER, name TEXT, speciality TEXT);")
    result = check_sql(
        "SELECT name FROM doctors WHERE specialty = 'Cardiology'", tables)
    assert result.fixed_sql == (
        "SELECT name FROM doctors WHERE speciality = 'Cardiology'")


def test_output_aliases_are_left_alone() -> None:
    sql = ("SELECT COUNT(*) AS quantities FROM order_items "
           "GROUP BY product_id ORDER BY quantities DESC")
    assert check_sql(sql, TABLES).ok


def test_duplicate_alias_is_reported() -> None:
    tables = parse_schema_text(
        "CREATE TABLE albums (album_id INTEGER, artist_id INTEGER);\n"
        "CREATE TABLE artists (artist_id INTEGER, name TEXT);")
    result = check_sql(
        "SELECT a.name FROM albums a JOIN artists a ON a.artist_id = a.artist_id",
        tables)
    assert any("used for two tables" in p for p in result.problems)
    assert "own alias" in result.hint
