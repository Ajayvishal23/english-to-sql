"""Pick a sensible chart for a result table (no Streamlit import, testable)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

_TIME_HINTS = ("date", "month", "year", "day", "week", "time", "period", "quarter")


@dataclass
class ChartSpec:
    kind: str            # "bar" or "line"
    x: str               # category / time column
    y: list[str]         # numeric columns to plot


def suggest_chart(df: pd.DataFrame, max_points: int = 200) -> ChartSpec | None:
    """Return a chart suggestion, or ``None`` if a chart would not help.

    A chart is suggested when the result has one label-like column and at
    least one numeric measure (ids are ignored), e.g. "revenue per product".
    """
    if df is None or df.empty or not 2 <= len(df) <= max_points:
        return None
    numeric = df.select_dtypes("number").columns.tolist()
    measures = [c for c in numeric
                if not (c.lower() == "id" or c.lower().endswith("_id"))]
    labels = [c for c in df.columns if c not in numeric]
    if not measures or not labels:
        return None
    x = labels[0]
    if df[x].nunique() < 2:
        return None
    is_time = any(h in x.lower() for h in _TIME_HINTS)
    return ChartSpec("line" if is_time else "bar", x, measures[:3])
