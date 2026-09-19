import pandas as pd

from ui.charts import suggest_chart


def test_bar_chart_for_category_measure() -> None:
    df = pd.DataFrame({"product": ["A", "B", "C"], "revenue": [10.0, 5.0, 1.0]})
    spec = suggest_chart(df)
    assert spec and spec.kind == "bar" and spec.x == "product"
    assert spec.y == ["revenue"]


def test_line_chart_for_time_column() -> None:
    df = pd.DataFrame({"month": ["2024-01", "2024-02"], "orders": [3, 4]})
    spec = suggest_chart(df)
    assert spec and spec.kind == "line"


def test_no_chart_when_not_useful() -> None:
    assert suggest_chart(pd.DataFrame()) is None
    assert suggest_chart(pd.DataFrame({"name": ["a", "b"]})) is None
    assert suggest_chart(pd.DataFrame({"customer_id": [1, 2], "name": ["a", "b"]})) is None
    assert suggest_chart(pd.DataFrame({"n": ["x"], "v": [1]})) is None
