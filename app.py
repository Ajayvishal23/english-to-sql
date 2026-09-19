"""Entry point: `streamlit run app.py`."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Make project packages importable regardless of the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ui.dashboard import Dashboard  # noqa: E402


def main() -> None:
    st.set_page_config(
        page_title="English → SQL",
        page_icon="💬",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    Dashboard().run()


if __name__ == "__main__":
    main()
