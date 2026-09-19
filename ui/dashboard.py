"""Streamlit user interface."""

from __future__ import annotations

import inspect
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st
from langchain_core.runnables import RunnableLambda

from core.pipeline import PipelineResult, Text2SQLPipeline
from database.connector import DatabaseConnectionError, DatabaseConnector
from database.schema_reader import SchemaReader
from llm.generator import (
    LOAD_MODE,
    RECOMMENDED_MODELS,
    LLMError,
    SQLGenerator,
    build_local_chat_model,
    is_model_downloaded,
    is_model_loaded,
    warm_up,
    warmup_error,
)
from sql.executor import QueryExecutor
from sql.validator import SQLValidator
from ui.charts import suggest_chart
from ui.styles import CSS
from utils.config import Settings, get_settings
from utils.logger import get_logger

logger = get_logger("ui.dashboard")

EXAMPLE_QUESTIONS = [
    "Show all customers from Germany.",
    "What are the top 5 best-selling products by revenue?",
    "How many orders were placed each month in 2024?",
    "Which employee handled the most orders?",
    "List customers who have never placed an order.",
]

REPO_URL = "https://github.com/Ajayvishal23/english-to-sql"


def step(num: int, title: str, hint: str = "") -> None:
    """Numbered section heading."""
    hint_html = f"<span class='hint'>{hint}</span>" if hint else ""
    st.markdown(
        f"<div class='t2s-step'><div class='num'>{num}</div>"
        f"<div class='title'>{title}</div>{hint_html}</div>",
        unsafe_allow_html=True,
    )


def badge(text: str, kind: str = "info") -> None:
    st.markdown(f"<span class='t2s-badge {kind}'>{text}</span>",
                unsafe_allow_html=True)


def _st_version() -> tuple[int, int]:
    try:
        major, minor = st.__version__.split(".")[:2]
        return int(major), int(minor)
    except ValueError:
        return (1, 0)


def fill(fn: Any) -> dict[str, Any]:
    """Full-width kwarg that works on old and new Streamlit versions.

    Newer Streamlit replaced the ``use_container_width`` flag with
    ``width="stretch"``.
    """
    params = inspect.signature(fn).parameters
    if "use_container_width" not in params or (
        _st_version() >= (1, 49) and "width" in params
    ):
        return {"width": "stretch"}
    return {"use_container_width": True}


CUSTOM_MODEL = "Custom Hugging Face model…"


@st.cache_resource(show_spinner=False)
def _background_load(model_id: str) -> Any:
    """Start loading the model once per server process so it is ready early."""
    return warm_up(model_id)


@st.cache_data(ttl=10, show_spinner=False)
def _downloaded(model_id: str) -> bool:
    return is_model_downloaded(model_id)


class Dashboard:
    """Builds and runs the Streamlit page."""

    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self._init_state()

    # ------------------------------------------------------------------ #
    # State
    # ------------------------------------------------------------------ #
    def _init_state(self) -> None:
        defaults: dict[str, Any] = {
            "connector": DatabaseConnector(),
            "schema_reader": None,
            "question_input": "",
            "sql_editor": "",
            "last_question": "",
            "result": None,
            "explanation": "",
            "history": [],
            "model": self.settings.model_name,
            "custom_model": "",
            "max_new_tokens": self.settings.max_new_tokens,
            "max_rows": self.settings.max_rows,
            "max_retries": self.settings.max_retries,
            "sample_rows": self.settings.sample_rows_in_prompt,
            "auto_explain": False,
            "auto_run": False,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

        # Auto-connect the bundled sample database on first load
        # (built on the fly if it is missing, e.g. after a fresh git clone).
        conn: DatabaseConnector = st.session_state.connector
        if not conn.is_connected and not self.settings.default_db_path.exists():
            try:
                from scripts.create_sample_db import build

                build(self.settings.default_db_path)
            except Exception as exc:  # noqa: BLE001
                logger.error("Could not create sample database: %s", exc)
        if not conn.is_connected and self.settings.default_db_path.exists():
            self._connect(lambda c: c.connect_sqlite(self.settings.default_db_path),
                          quiet=True)

    @property
    def connector(self) -> DatabaseConnector:
        return st.session_state.connector

    @property
    def schema(self) -> SchemaReader | None:
        return st.session_state.schema_reader

    def _connect(self, action: Any, quiet: bool = False) -> None:
        try:
            action(self.connector)
            st.session_state.schema_reader = SchemaReader(self.connector)
            st.session_state.result = None
            st.session_state.explanation = ""
            st.session_state.sql_editor = ""
            if not quiet:
                st.toast(f"Connected to {self.connector.label}", icon="✅")
        except DatabaseConnectionError as exc:
            logger.error("Connection failed: %s", exc)
            if not quiet:
                st.sidebar.error(str(exc))

    def _pipeline(self) -> Text2SQLPipeline:
        s = st.session_state
        model_id = self.model_id
        max_tokens = int(s.max_new_tokens)
        # Lazy: the model is only loaded when a chain actually calls it.
        client = RunnableLambda(
            lambda prompt: build_local_chat_model(model_id, max_tokens)
            .invoke(prompt)
        )
        dialect = self.connector.dialect if self.connector.is_connected else "sqlite"
        generator = SQLGenerator(client, dialect=dialect)
        validator = SQLValidator()
        executor = QueryExecutor(
            self.connector, validator,
            max_rows=int(s.max_rows), timeout_s=self.settings.query_timeout_s,
        )
        return Text2SQLPipeline(generator, executor, validator,
                                self.settings.max_question_length)

    @property
    def model_id(self) -> str:
        s = st.session_state
        if s.model == CUSTOM_MODEL:
            return s.custom_model.strip() or self.settings.model_name
        return s.model or self.settings.model_name

    def _model_spinner(self, action: str) -> str:
        if is_model_loaded(self.model_id):
            return action
        if _downloaded(self.model_id):
            return f"Loading {self.model_id} into memory (first use)…"
        return (f"Downloading {self.model_id} "
                "(first use only, this can take several minutes)…")

    def _schema_context(self) -> str:
        assert self.schema is not None
        return self.schema.to_prompt_context(int(st.session_state.sample_rows))

    # ------------------------------------------------------------------ #
    # Sidebar
    # ------------------------------------------------------------------ #
    def render_sidebar(self) -> None:
        with st.sidebar:
            st.markdown("<div class='t2s-side-title'>💬 English → SQL</div>",
                        unsafe_allow_html=True)
            st.caption("Talk to your database in plain English.")
            with st.expander("🗄️ Database", expanded=not self.connector.is_connected):
                self._sidebar_connection()
            if self.connector.is_connected:
                st.success(f"**{self.connector.label}** · read-only", icon="🔒")
            st.markdown("##### 📚 Tables")
            self._sidebar_schema()
            st.divider()
            with st.expander("⚙️ Settings"):
                self._sidebar_settings()
            st.caption(f"[⭐ Source code on GitHub]({REPO_URL})")

    def _sidebar_connection(self) -> None:
        source = st.radio(
            "Source",
            ["Sample database", "Upload SQLite file", "Local file path",
             "Connection URL"],
            label_visibility="collapsed",
        )
        if source == "Sample database":
            if st.button("Connect sample.db", **fill(st.button)):
                if not self.settings.default_db_path.exists():
                    st.error("Run `python scripts/create_sample_db.py` first.")
                else:
                    self._connect(lambda c: c.connect_sqlite(
                        self.settings.default_db_path))
        elif source == "Upload SQLite file":
            upload = st.file_uploader(
                "SQLite file", type=["db", "sqlite", "sqlite3"],
                label_visibility="collapsed",
            )
            if upload is not None and st.button("Connect upload",
                                                 **fill(st.button)):
                safe = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(upload.name).name)
                self.settings.upload_dir.mkdir(parents=True, exist_ok=True)
                target = self.settings.upload_dir / safe
                target.write_bytes(upload.getvalue())
                self._connect(lambda c: c.connect_sqlite(target))
        elif source == "Local file path":
            path = st.text_input("Path to .db file",
                                 placeholder="C:/data/shop.db")
            if st.button("Connect", **fill(st.button), disabled=not path):
                self._connect(lambda c: c.connect_sqlite(path))
        else:
            url = st.text_input(
                "SQLAlchemy URL", type="password",
                placeholder="postgresql+psycopg://readonly@localhost/db",
                help="Use a database user that only has SELECT permission.",
            )
            if st.button("Connect", **fill(st.button), disabled=not url):
                self._connect(lambda c: c.connect_url(url))

        if not self.connector.is_connected:
            st.info("No database connected.")

    def _sidebar_schema(self) -> None:
        if self.schema is None:
            st.caption("Connect a database to see its tables.")
            return
        try:
            tables = self.schema.get_tables()
        except Exception as exc:  # noqa: BLE001 - show any driver error
            st.error(f"Could not read schema: {exc}")
            return
        c1, c2 = st.columns([3, 1])
        search = c1.text_input("Filter tables", placeholder="Filter…",
                               label_visibility="collapsed").strip().lower()
        if c2.button("↻", help="Refresh schema", **fill(st.button)):
            self.schema.refresh()
            st.rerun()
        shown = [t for t in tables.values()
                 if not search or search in t.name.lower()
                 or any(search in c.name.lower() for c in t.columns)]
        st.caption(f"{len(shown)} of {len(tables)} tables · click to see columns")
        for t in shown:
            rows = f" · {t.row_count:,} rows" if t.row_count is not None else ""
            with st.expander(f"**{t.name}**{rows}"):
                lines = []
                for c in t.columns:
                    key = "🔑 " if c.primary_key else ""
                    lines.append(f"{key}`{c.name}` <small style='opacity:.6'>"
                                 f"{c.type.lower()}</small>")
                st.markdown("<br>".join(lines), unsafe_allow_html=True)
                for fk in t.foreign_keys:
                    st.caption(f"🔗 {', '.join(fk.columns)} → "
                               f"{fk.referred_table}.{', '.join(fk.referred_columns)}")

    @staticmethod
    def _bind(widget: Any, label: str, cfg_key: str, **kwargs: Any) -> Any:
        """Render a settings widget whose value survives reruns.

        Streamlit deletes the state of widgets that were not rendered in an
        interrupted run, so the real value lives in a plain session key
        (``cfg_key``) and the widget uses its own ``w_`` key.
        """
        s = st.session_state
        wkey = f"w_{cfg_key}"

        def _sync() -> None:
            s[cfg_key] = s[wkey]

        if widget is st.selectbox:
            options = kwargs.pop("options")
            idx = options.index(s[cfg_key]) if s[cfg_key] in options else 0
            s[cfg_key] = options[idx]
            return widget(label, options, index=idx, key=wkey,
                          on_change=_sync, **kwargs)
        return widget(label, value=s[cfg_key], key=wkey, on_change=_sync,
                      **kwargs)

    def _sidebar_settings(self) -> None:
        s = st.session_state
        options = list(RECOMMENDED_MODELS) + [CUSTOM_MODEL]
        if s.model not in options:
            s.custom_model, s.model = s.model, CUSTOM_MODEL
        self._bind(st.selectbox, "Model (Hugging Face)", "model",
                   options=options,
                   format_func=lambda m: RECOMMENDED_MODELS.get(m, m),
                   help="Runs locally with LangChain + transformers. "
                        "Downloaded once from huggingface.co.")
        if s.model == CUSTOM_MODEL:
            self._bind(st.text_input, "Model id", "custom_model",
                       placeholder="e.g. Qwen/Qwen2.5-0.5B-Instruct")
        ready = _downloaded(self.model_id)
        st.caption("✅ Downloaded" if ready else "⬇ Will download on first use")
        if st.button("Load model now", **fill(st.button)):
            with st.spinner(self._model_spinner("Ready")):
                try:
                    build_local_chat_model(self.model_id, int(s.max_new_tokens))
                    _downloaded.clear()
                    st.success("Model loaded.")
                except LLMError as exc:
                    st.error(str(exc))
        st.markdown("**Behaviour**")
        self._bind(st.toggle, "Explain queries automatically", "auto_explain",
                   help="Off by default: it costs a second model call per "
                        "question. Use the 💡 Explain button when you need it.")
        self._bind(st.toggle, "Run immediately after generating", "auto_run",
                   help="Off = review the SQL before it runs.")
        st.markdown("**Advanced**")
        self._bind(st.number_input, "Max answer length (tokens)",
                   "max_new_tokens", min_value=128, max_value=1024, step=64,
                   help="SQL answers are short; lower values are faster.")
        self._bind(st.number_input, "Max rows returned", "max_rows",
                   min_value=10, max_value=100_000, step=100)
        self._bind(st.number_input, "Auto-fix retries", "max_retries",
                   min_value=0, max_value=5)
        self._bind(st.number_input, "Sample rows in prompt", "sample_rows",
                   min_value=0, max_value=10,
                   help="Example rows help the model learn value formats.")

    # ------------------------------------------------------------------ #
    # Main area
    # ------------------------------------------------------------------ #
    def render_header(self) -> None:
        st.markdown(CSS, unsafe_allow_html=True)
        st.markdown(
            "<div class='t2s-hero'><h1>💬 English → SQL</h1>"
            "<p>Ask questions about your data in plain English — no SQL "
            "knowledge needed. Everything runs privately on your computer.</p>"
            "<div class='t2s-tags'><span class='t2s-tag'>🔒 Read-only</span>"
            "<span class='t2s-tag'>🧠 LangChain + Hugging Face</span>"
            "<span class='t2s-tag'>💻 100% local</span>"
            "<span class='t2s-tag'>🛠️ Auto-fixes errors</span></div></div>",
            unsafe_allow_html=True,
        )
        loaded = is_model_loaded(self.model_id)
        downloaded = loaded or _downloaded(self.model_id)
        error = warmup_error(self.model_id)
        if loaded:
            dot, state = "ok", "Ready"
        elif error:
            dot, state = "bad", "Could not load"
        elif downloaded:
            dot, state = "warn", "Loading…"
        else:
            dot, state = "warn", "Downloads on first question"
        if self.connector.is_connected and self.schema is not None:
            try:
                n_tables = len(self.schema.get_tables())
            except Exception:  # noqa: BLE001
                n_tables = 0
            db = (f"<span class='t2s-dot ok'></span>{self.connector.label}"
                  f" · {n_tables} tables")
        else:
            db = "<span class='t2s-dot bad'></span>Not connected"
        model = self.model_id.split("/")[-1]
        mode = LOAD_MODE.get(self.model_id, "—")
        cards = [
            ("Database", db),
            ("AI model", f"<span class='t2s-dot {dot}'></span>{state}"),
            ("Model", model),
            ("Runs on", mode),
        ]
        html = "".join(
            f"<div class='t2s-stat'><div class='lbl'>{label}</div>"
            f"<div class='val'>{value}</div></div>"
            for label, value in cards
        )
        st.markdown(f"<div class='t2s-stats'>{html}</div>", unsafe_allow_html=True)
        if error and not loaded:
            st.warning(error)
        elif downloaded and not loaded:
            st.caption("⏳ The AI model is loading in the background (up to 1–2 minutes "
                       "on laptops). You can explore your data meanwhile.")
        elif not downloaded:
            st.info("The AI model (about 1 GB) downloads automatically the first "
                    "time you ask a question. After that everything works offline.")

    def _example_picker(self) -> None:
        s = st.session_state

        def use_example(q: str | None) -> None:
            if q:
                s.question_input = q
                s._generate_now = True

        if hasattr(st, "pills"):
            def on_pick() -> None:
                use_example(s.get("example_pick"))
                s.example_pick = None

            st.pills("Try an example", EXAMPLE_QUESTIONS, selection_mode="single",
                     key="example_pick", on_change=on_pick)
        else:  # older Streamlit
            st.caption("Try an example")
            cols = st.columns(len(EXAMPLE_QUESTIONS))
            for col, q in zip(cols, EXAMPLE_QUESTIONS):
                col.button(q, key=f"ex_{q}", on_click=use_example, args=(q,),
                           **fill(st.button))

    @staticmethod
    def _clear() -> None:
        s = st.session_state
        s.question_input = ""
        s.sql_editor = ""
        s.last_question = ""
        s.result = None
        s.explanation = ""

    def render_ask_tab(self) -> None:
        if not self.connector.is_connected:
            st.markdown("<div class='t2s-empty'>👈 Connect a database in the sidebar "
                        "to get started.</div>", unsafe_allow_html=True)
            return
        s = st.session_state

        # ---- 1. question -------------------------------------------------
        step(1, "Ask a question", "in everyday English")
        self._example_picker()
        st.text_area("Your question", key="question_input", height=90,
                     label_visibility="collapsed",
                     placeholder="e.g. Which 10 products sold the most last year?")
        c1, c2, _ = st.columns([2, 1, 4])
        generate = c1.button("✨ Generate SQL", type="primary", **fill(st.button))
        c2.button("Clear", on_click=self._clear, **fill(st.button))
        if generate or s.pop("_generate_now", False):
            self._on_generate()

        # ---- 2. SQL ------------------------------------------------------
        step(2, "Check the SQL", "edit it if you like — nothing runs until you click Run")
        sql = s.sql_editor.strip()
        if sql:
            check = SQLValidator().validate(sql)
            if check.is_valid:
                badge("✔ Safe read-only query", "ok")
            else:
                badge("✖ " + " ".join(check.errors), "bad")
        st.text_area("SQL", key="sql_editor", height=150,
                     label_visibility="collapsed",
                     placeholder="The generated SQL will appear here. "
                                 "You can also type your own SELECT query.")
        c1, c2, _ = st.columns([2, 1, 4])
        run = c1.button("▶ Run query", type="primary", **fill(st.button))
        explain = c2.button("💡 Explain", **fill(st.button))
        if run or s.pop("_auto_run_now", False):
            self._on_run()
        if explain:
            self._on_explain()

        # ---- 3. results --------------------------------------------------
        self._render_result()

    def _on_generate(self) -> None:
        question = st.session_state.question_input
        if not question.strip():
            st.warning("Type a question first, or pick an example above.")
            return
        with st.spinner(self._model_spinner("Thinking…")):
            result = self._pipeline().generate(question, self._schema_context())
        if result.error:
            st.error(result.error)
            return
        st.session_state.sql_editor = result.sql
        st.session_state.last_question = result.question
        st.session_state.result = None
        st.session_state.explanation = ""
        if st.session_state.auto_run:
            st.session_state._auto_run_now = True

    def _on_run(self) -> None:
        s = st.session_state
        if not s.sql_editor.strip():
            st.warning("There is no SQL to run yet — generate or type a query first.")
            return
        question = s.last_question or s.question_input or "(manual query)"
        pipeline = self._pipeline()
        with st.spinner("Running query…"):
            result = pipeline.run(question, s.sql_editor, self._schema_context(),
                                  max_retries=int(s.max_retries))
        s.result = result
        s.explanation = ""
        if result.success and result.sql.strip() != s.sql_editor.strip():
            # The query was auto-corrected: show the fixed version next run.
            s["_pending_sql"] = result.sql
        if result.success and s.auto_explain:
            with st.spinner("Explaining…"):
                s.explanation = pipeline.explain(question, result.sql)
        s.history.insert(0, {
            "time": datetime.now().strftime("%H:%M:%S"),
            "question": question,
            "sql": result.sql,
            "rows": result.execution.row_count if result.success else None,
            "status": "✅" if result.success else "❌",
        })
        del s.history[50:]
        if "_pending_sql" in s:
            st.rerun()  # refresh the editor with the auto-corrected SQL

    def _on_explain(self) -> None:
        s = st.session_state
        if not s.sql_editor.strip():
            st.warning("There is no SQL to explain yet.")
            return
        with st.spinner("Explaining…"):
            s.explanation = self._pipeline().explain(
                s.last_question or "(manual query)", s.sql_editor)

    def _render_result(self) -> None:
        s = st.session_state
        result: PipelineResult | None = s.result
        if result is None or result.execution is None:
            if s.explanation:
                step(3, "Explanation")
                st.info(s.explanation, icon="💡")
            return

        ex = result.execution
        step(3, "Results")
        if len(result.attempts) > 1:
            fixed = "fixed automatically ✅" if ex.success else "could not be fixed"
            with st.expander(f"🔧 The first query failed and was {fixed} "
                             f"({len(result.attempts)} attempts)"):
                for i, a in enumerate(result.attempts, 1):
                    st.markdown(f"**Attempt {i}** — "
                                f"{'✅ success' if not a.error else '❌ ' + a.error}")
                    st.code(a.sql, language="sql")
        if not ex.success:
            st.error(f"The query could not run: {result.error or ex.error}", icon="🚫")
            st.caption("Tip: rephrase the question, mention exact table or column "
                       "names, or edit the SQL above.")
            return

        m1, m2, m3 = st.columns(3)
        m1.metric("Rows", f"{ex.row_count:,}")
        m2.metric("Columns", len(ex.data.columns))
        m3.metric("Query time", f"{ex.elapsed_ms:.0f} ms")
        if ex.truncated:
            st.warning(f"Showing the first {ex.row_count:,} rows. Raise "
                       "“Max rows returned” in Settings to see more.")
        if ex.data.empty:
            st.info("The query worked but found no matching rows.", icon="🔍")
            if s.explanation:
                st.info(s.explanation, icon="💡")
            return

        chart = suggest_chart(ex.data)
        names = ["📋 Table"] + (["📊 Chart"] if chart else []) + ["💡 Explanation",
                                                                   "🧾 SQL"]
        tabs = dict(zip(names, st.tabs(names)))
        with tabs["📋 Table"]:
            st.dataframe(ex.data, **fill(st.dataframe), hide_index=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            d1, d2, _ = st.columns([1, 1, 4])
            d1.download_button(
                "⬇ CSV", ex.data.to_csv(index=False).encode("utf-8"),
                file_name=f"results_{stamp}.csv", mime="text/csv",
                **fill(st.download_button),
            )
            d2.download_button(
                "⬇ JSON", ex.data.to_json(orient="records", indent=2,
                                         date_format="iso").encode("utf-8"),
                file_name=f"results_{stamp}.json", mime="application/json",
                **fill(st.download_button),
            )
        if chart:
            with tabs["📊 Chart"]:
                data = ex.data.set_index(chart.x)[chart.y]
                if chart.kind == "line":
                    st.line_chart(data)
                else:
                    st.bar_chart(data)
                st.caption(f"{', '.join(chart.y)} by {chart.x}")
        with tabs["💡 Explanation"]:
            if s.explanation:
                st.markdown(s.explanation)
            else:
                st.caption("Click **💡 Explain** above to get a plain-English "
                           "explanation of this query.")
        with tabs["🧾 SQL"]:
            st.code(result.sql, language="sql")
            if result.question:
                st.caption(f"Question: {result.question}")

    def render_explorer_tab(self) -> None:
        if self.schema is None:
            st.info("Connect a database to explore it.")
            return
        tables = self.schema.get_tables()
        if not tables:
            st.warning("This database has no tables.")
            return

        name = st.selectbox("Choose a table", list(tables))
        t = tables[name]
        m1, m2, m3 = st.columns(3)
        m1.metric("Rows", f"{t.row_count:,}" if t.row_count is not None else "—")
        m2.metric("Columns", len(t.columns))
        m3.metric("Links to other tables", len(t.foreign_keys))
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("**Columns**")
            st.dataframe(
                [{"column": c.name, "type": c.type,
                  "PK": "🔑" if c.primary_key else "",
                  "nullable": c.nullable} for c in t.columns],
                hide_index=True, **fill(st.dataframe),
            )
        with c2:
            limit = st.slider("Preview rows", 5, 200, 20)
            try:
                st.dataframe(self.schema.preview_table(name, limit),
                             hide_index=True, **fill(st.dataframe))
            except Exception as exc:  # noqa: BLE001
                st.error(f"Preview failed: {exc}")

        st.markdown("**How the tables are connected**")
        rels = self.schema.get_relationships()
        if not rels:
            st.caption("No foreign keys defined.")
            return
        dot = ["digraph G {", "rankdir=LR;",
               'node [shape=box, style="rounded,filled", fillcolor="#eef2ff", '
               'color="#4F46E5", fontname="Helvetica"];']
        for r in rels:
            label = ", ".join(r.from_columns)
            dot.append(f'"{r.from_table}" -> "{r.to_table}" [label="{label}"];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot))
        for r in rels:
            st.caption(str(r))

    def render_history_tab(self) -> None:
        history = st.session_state.history
        if not history:
            st.markdown("<div class='t2s-empty'>Queries you run will appear here.</div>",
                        unsafe_allow_html=True)
            return
        c1, c2 = st.columns([4, 1])
        c1.caption(f"{len(history)} recent queries (this session)")
        if c2.button("Clear history", **fill(st.button)):
            history.clear()
            st.rerun()
        for i, h in enumerate(history):
            rows = f"{h['rows']:,} rows" if h["rows"] is not None else "failed"
            with st.expander(f"{h['status']} {h['time']} — {h['question']} · {rows}"):
                st.code(h["sql"], language="sql")
                if st.button("↩ Load into editor", key=f"hist_{i}"):
                    st.session_state["_pending_sql"] = h["sql"]
                    st.session_state["_pending_question"] = h["question"]
                    st.session_state.last_question = h["question"]
                    st.rerun()

    # ------------------------------------------------------------------ #
    def run(self) -> None:
        # Apply SQL set by a previous run before the editor widget exists.
        pending = st.session_state.pop("_pending_sql", None)
        if pending is not None:
            st.session_state.sql_editor = pending
        question = st.session_state.pop("_pending_question", None)
        if question is not None:
            st.session_state.question_input = question

        if _downloaded(self.model_id) and not is_model_loaded(self.model_id):
            _background_load(self.model_id)

        self.render_sidebar()
        self.render_header()
        ask, explorer, history = st.tabs(
            ["💬 Ask", "🔍 Explore data", "🕘 History"])
        with ask:
            self.render_ask_tab()
        with explorer:
            self.render_explorer_tab()
        with history:
            self.render_history_tab()
        st.markdown(
            "<div class='t2s-footer'>Built with Streamlit · LangChain · Hugging Face · "
            f"SQLAlchemy — <a href='{REPO_URL}' target='_blank'>open source on "
            "GitHub</a></div>",
            unsafe_allow_html=True,
        )
