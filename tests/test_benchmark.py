"""The benchmark's row comparison accepts any correct formulation."""

from scripts.benchmark import compare


def test_identical_rows() -> None:
    ok, _ = compare([(1, "a"), (2, "b")], [(2, "b"), (1, "a")])
    assert ok


def test_column_order_ignored() -> None:
    ok, why = compare([("a", 1)], [(1, "a")])
    assert ok and "column order" in why


def test_extra_columns_allowed() -> None:
    ok, why = compare([("Germany", 16)], [("Germany", 16, "DE")])
    assert ok and "extra columns" in why


def test_fewer_columns_allowed() -> None:
    """SELECT * vs SELECT first_name, last_name — same customers either way."""
    expected = [(1, "Anna", "Berlin"), (2, "Ben", "Munich")]
    produced = [("Anna",), ("Ben",)]
    ok, why = compare(expected, produced)
    assert ok and "fewer columns" in why


def test_fewer_columns_in_a_different_row_order() -> None:
    """Dropping the id column changes the sort order of the rows."""
    expected = [(1, "Zoe"), (2, "Adam")]      # sorted by id
    produced = [("Adam",), ("Zoe",)]          # sorted by name
    ok, why = compare(expected, produced)
    assert ok and "fewer columns" in why


def test_subset_rows_still_fail() -> None:
    expected = [(1, "Zoe"), (2, "Adam")]
    produced = [("Zoe",), ("Zoe",)]
    assert not compare(expected, produced)[0]


def test_wrong_values_fail() -> None:
    ok, why = compare([("Germany", 16)], [("France", 16)])
    assert not ok and why == "different values"


def test_wrong_row_count_fails() -> None:
    ok, why = compare([(1,), (2,)], [(1,)])
    assert not ok and "instead of" in why


def test_float_rounding_happens_when_reading_rows() -> None:
    from scripts.benchmark import _norm

    assert _norm(1.2300000001) == 1.23
    assert compare([(_norm(1.23),)], [(_norm(1.2300000001),)])[0]
