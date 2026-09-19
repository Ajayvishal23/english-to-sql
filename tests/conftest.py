"""Shared fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build a fresh copy of the sample database for tests."""
    from scripts.create_sample_db import build

    path = tmp_path_factory.mktemp("db") / "sample.db"
    build(path)
    return path


def FakeLLM(replies: list[str]):  # noqa: N802 - behaves like a class
    """A LangChain Runnable that returns queued replies (no model needed).

    ``.calls`` records (system_prompt, user_prompt) for every invocation.
    """
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    queue = list(replies)
    calls: list[tuple[str, str]] = []

    def respond(prompt_value):
        messages = prompt_value.to_messages()
        calls.append((messages[0].content, messages[-1].content))
        return AIMessage(content=queue.pop(0) if queue else "no sql here")

    runnable = RunnableLambda(respond)
    object.__setattr__(runnable, "calls", calls)
    return runnable


@pytest.fixture
def fake_llm_factory():
    return FakeLLM
