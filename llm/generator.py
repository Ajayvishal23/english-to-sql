"""Local LLM access through LangChain + Hugging Face, and the SQL generator.

The model (default: Qwen/Qwen2.5-Coder-0.5B-Instruct) is downloaded once from
the Hugging Face Hub into the local cache and then runs entirely on this
computer with ``transformers``. No API keys, no cloud inference.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda

from llm import prompts
from utils.config import PROJECT_ROOT
from utils.logger import get_logger

logger = get_logger("llm.generator")

_FENCE_RE = re.compile(r"```(?:sql|sqlite|postgresql|mysql)?\s*(.*?)```",
                       re.IGNORECASE | re.DOTALL)
_OPEN_FENCE_RE = re.compile(r"```(?:sql|sqlite)?\s*", re.IGNORECASE)
_START_RE = re.compile(r"\b(WITH|SELECT)\b", re.IGNORECASE)

# Tuned for an 8 GB RAM laptop without a usable GPU (CPU inference, float32).
RECOMMENDED_MODELS: dict[str, str] = {
    "Qwen/Qwen2.5-Coder-0.5B-Instruct":
        "Qwen2.5-Coder 0.5B — fast, ~2 GB RAM (recommended for 8 GB PCs)",
    "Qwen/Qwen2.5-Coder-1.5B-Instruct":
        "Qwen2.5-Coder 1.5B — more accurate, needs ~6.5 GB free RAM",
}
DEFAULT_MODEL = "Qwen/Qwen2.5-Coder-0.5B-Instruct"

_ROLE_MAP = {"system": "system", "human": "user", "ai": "assistant"}


class LLMError(Exception):
    """Raised when the model cannot be loaded or fails to answer."""


# --------------------------------------------------------------------------- #
# Hugging Face model loading (LangChain wrapper)
# --------------------------------------------------------------------------- #
_MODEL_CACHE: dict[str, Any] = {}
_MODEL_LOCK = threading.Lock()


_GB = 1024 ** 3
LOAD_MODE: dict[str, str] = {}  # model_id -> human readable precision used


def _memory_gb() -> tuple[float, float]:
    """(available RAM, free swap/page file) in GB; generous if unknown."""
    try:
        import psutil

        return (psutil.virtual_memory().available / _GB,
                psutil.swap_memory().free / _GB)
    except Exception:  # noqa: BLE001
        return 64.0, 0.0


def _choose_precision(folder: Path) -> str:
    """Pick float32 / float16 / bfloat16 for the hardware and free memory.

    * CUDA GPU (compute capability >= 7.0): float16.
    * CPU with enough free RAM: float32 (fastest on laptop CPUs).
    * CPU with little free RAM: bfloat16 (half the memory, slower).
    Raises ``LLMError`` if even the low-memory mode cannot fit.
    """
    import torch

    if torch.cuda.is_available():
        try:
            if torch.cuda.get_device_capability(0)[0] >= 7:
                return "float16-gpu"
        except Exception:  # noqa: BLE001
            pass

    weights_gb = sum(f.stat().st_size for f in folder.glob("*.safetensors")) / _GB
    need_fp32 = weights_gb * 2 + 0.6   # files are 16-bit; float32 doubles them
    need_half = weights_gb + 0.5
    ram, swap = _memory_gb()
    if ram >= need_fp32:
        return "float32"
    if ram >= need_half:
        return "bfloat16"
    if ram + swap * 0.5 >= need_half:
        logger.warning("Low memory (%.1f GB free); model will partly use the "
                       "page file and run slowly", ram)
        return "bfloat16"
    raise LLMError(
        f"Not enough free memory to load this model: it needs at least "
        f"{need_half:.1f} GB but only {ram:.1f} GB is free. Close other "
        f"programs (web browsers, Discord, games) and try again"
        + ("." if "0.5B" in folder.name else ", or choose the 0.5B model.")
    )


def _load_kwargs(precision: str) -> dict[str, Any]:
    """transformers ``from_pretrained`` options for the chosen precision."""
    import torch
    import transformers

    dtype = {"float32": torch.float32, "bfloat16": torch.bfloat16,
             "float16-gpu": torch.float16}[precision]
    major, minor = (int(p) for p in transformers.__version__.split(".")[:2])
    key = "dtype" if (major, minor) >= (4, 56) else "torch_dtype"
    kwargs: dict[str, Any] = {key: dtype, "low_cpu_mem_usage": True}
    if precision == "float16-gpu":
        kwargs["device_map"] = "cuda"
    else:
        # Use the physical cores; hyper-threads slow matrix maths down.
        try:
            import psutil

            cores = psutil.cpu_count(logical=False) or 4
        except ImportError:
            cores = 4
        torch.set_num_threads(max(1, cores))
    return kwargs


MODELS_DIR: Path = PROJECT_ROOT / "models"
_DOWNLOAD_PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model", "*.py",
                      "*.tiktoken"]


def local_model_dir(model_id: str) -> Path:
    """Folder inside the project where a model's files are stored.

    Plain files are used (no Hugging Face cache symlinks), which avoids the
    Windows "A required privilege is not held by the client" error.
    """
    if Path(model_id).is_dir():  # already a local path
        return Path(model_id)
    return MODELS_DIR / model_id.replace("/", "--")


def is_model_downloaded(model_id: str) -> bool:
    """True if the model's weights are present locally."""
    folder = local_model_dir(model_id)
    return (folder / "config.json").is_file() and any(
        folder.glob("*.safetensors"))


def download_model(model_id: str) -> Path:
    """Download a model into ``models/`` (no-op if already complete)."""
    folder = local_model_dir(model_id)
    if is_model_downloaded(model_id):
        return folder
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise LLMError("huggingface_hub is not installed.") from exc
    logger.info("Downloading %s to %s", model_id, folder)
    try:
        snapshot_download(model_id, local_dir=str(folder),
                          allow_patterns=_DOWNLOAD_PATTERNS)
    except Exception as exc:  # noqa: BLE001 - network / auth / disk errors
        raise LLMError(
            f"Could not download model '{model_id}'. Check the model name and "
            f"your internet connection. Details: {exc}"
        ) from exc
    if not is_model_downloaded(model_id):
        raise LLMError(f"Download of '{model_id}' is incomplete.")
    return folder


def is_model_loaded(model_id: str) -> bool:
    """True if the model is already in memory in this process."""
    return model_id in _MODEL_CACHE


def _quiet_transformers() -> None:
    """Hide transformers' deprecation chatter in the console."""
    import warnings

    try:
        from transformers.utils import logging as hf_logging

        hf_logging.set_verbosity_error()
    except ImportError:
        pass
    warnings.filterwarnings("ignore", module="transformers")


_WARMUP_ERRORS: dict[str, str] = {}


def warm_up(model_id: str) -> threading.Thread:
    """Start loading a model in a background thread (returns immediately)."""

    def _run() -> None:
        try:
            load_hf_llm(model_id)
        except LLMError as exc:
            _WARMUP_ERRORS[model_id] = str(exc)
            logger.warning("Background model load failed: %s", exc)

    thread = threading.Thread(target=_run, name=f"warmup-{model_id}",
                              daemon=True)
    thread.start()
    return thread


def warmup_error(model_id: str) -> str | None:
    """Error message from the last background load attempt, if any."""
    return _WARMUP_ERRORS.get(model_id)


def load_hf_llm(model_id: str) -> Any:
    """Load a LangChain ``HuggingFacePipeline`` (one model in memory at a time)."""
    with _MODEL_LOCK:
        if model_id in _MODEL_CACHE:
            return _MODEL_CACHE[model_id]
        try:
            from langchain_huggingface import HuggingFacePipeline
        except ImportError as exc:
            raise LLMError(
                "langchain-huggingface is not installed. "
                "Run: pip install -r requirements.txt"
            ) from exc

        _WARMUP_ERRORS.pop(model_id, None)
        folder = download_model(model_id)
        if _MODEL_CACHE:  # free the previous model before loading another
            _MODEL_CACHE.clear()
            import gc

            gc.collect()
        precision = _choose_precision(folder)
        logger.info("Loading Hugging Face model %s from %s (%s)",
                    model_id, folder, precision)
        _quiet_transformers()
        try:
            llm = HuggingFacePipeline.from_model_id(
                model_id=str(folder),
                task="text-generation",
                model_kwargs=_load_kwargs(precision),
            )
            # Greedy decoding: drop sampling defaults shipped with the model
            # (avoids "generation flags are not valid" warnings).
            gen_cfg = llm.pipeline.model.generation_config
            for attr in ("temperature", "top_p", "top_k", "repetition_penalty"):
                if hasattr(gen_cfg, attr):
                    setattr(gen_cfg, attr, None)
            gen_cfg.do_sample = False
        except MemoryError as exc:
            raise LLMError("Ran out of memory while loading the model. Close "
                           "other programs or pick the 0.5B model.") from exc
        except Exception as exc:  # noqa: BLE001 - torch/transformers errors
            raise LLMError(f"Failed to load model '{model_id}': {exc}") from exc
        _MODEL_CACHE[model_id] = llm
        LOAD_MODE[model_id] = {
            "float32": "CPU, full precision",
            "bfloat16": "CPU, low-memory mode",
            "float16-gpu": "GPU",
        }[precision]
        logger.info("Model %s loaded", model_id)
        return llm


def build_local_chat_model(model_id: str, max_new_tokens: int = 256) -> Runnable:
    """Return a Runnable: ChatPromptValue -> generated text.

    Messages are rendered with the model's own chat template, then passed to
    the LangChain ``HuggingFacePipeline``.
    """
    llm = load_hf_llm(model_id)
    tokenizer = llm.pipeline.tokenizer

    def to_chat_text(prompt_value: Any) -> str:
        messages: list[BaseMessage] = prompt_value.to_messages()
        chat = [
            {"role": _ROLE_MAP.get(m.type, "user"), "content": str(m.content)}
            for m in messages
        ]
        return tokenizer.apply_chat_template(
            chat, tokenize=False, add_generation_prompt=True
        )

    generation = {"max_new_tokens": max_new_tokens, "do_sample": False,
                  "return_full_text": False}
    return RunnableLambda(to_chat_text) | llm.bind(pipeline_kwargs=generation)


# --------------------------------------------------------------------------- #
# SQL extraction
# --------------------------------------------------------------------------- #
def extract_sql(text: str) -> str:
    """Pull the SQL statement out of an LLM reply.

    Handles fenced code blocks (closed or not), leading chatter and trailing
    explanations.
    """
    if not text:
        return ""
    match = _FENCE_RE.search(text)
    if match:
        candidate = match.group(1)
    else:
        candidate = _OPEN_FENCE_RE.sub("", text)
    start = _START_RE.search(candidate)
    if not start:
        return ""
    candidate = _first_statement(candidate[start.start():]).strip()
    return candidate.rstrip(";").strip() + ";" if candidate else ""


def _first_statement(sql: str) -> str:
    """Cut at the first semicolon that is not inside a string literal."""
    quote: str | None = None
    for i, ch in enumerate(sql):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == ";":
            return sql[:i]
    return sql


# --------------------------------------------------------------------------- #
# LangChain chains
# --------------------------------------------------------------------------- #
class SQLGenerator:
    """Turns English into SQL, explains SQL and repairs failing SQL.

    ``llm`` is any LangChain Runnable that accepts a chat prompt and returns
    text or a message (a chat model, ``build_local_chat_model(...)``, or a
    fake model in tests).
    """

    def __init__(self, llm: Runnable, dialect: str = "sqlite",
                 default_limit: int = 100) -> None:
        self.llm = llm
        self.dialect = dialect
        self.default_limit = default_limit
        parser = StrOutputParser()
        system = ("system", prompts.SYSTEM_PROMPT)
        self._generate_chain = (
            ChatPromptTemplate.from_messages(
                [system, ("human", prompts.GENERATION_PROMPT)])
            | llm | parser
        )
        self._fix_chain = (
            ChatPromptTemplate.from_messages(
                [system, ("human", prompts.CORRECTION_PROMPT)])
            | llm | parser
        )
        self._explain_chain = (
            ChatPromptTemplate.from_messages(
                [("system", prompts.EXPLANATION_SYSTEM_PROMPT),
                 ("human", prompts.EXPLANATION_PROMPT)])
            | llm | parser
        )

    def _base_vars(self) -> dict[str, Any]:
        return {"dialect": self.dialect.upper(), "limit": self.default_limit}

    @staticmethod
    def _invoke(chain: Runnable, variables: dict[str, Any]) -> str:
        try:
            return str(chain.invoke(variables))
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface any model failure
            logger.exception("LLM call failed")
            raise LLMError(f"The language model failed: {exc}") from exc

    def generate_sql(self, question: str, schema: str) -> str:
        """Generate SQL for a question given the schema context."""
        logger.info("Generating SQL for: %s", question)
        reply = self._invoke(self._generate_chain, {
            **self._base_vars(), "schema": schema, "question": question})
        sql = extract_sql(reply)
        if not sql:
            raise LLMError("The model did not return a SQL query. "
                           "Try rephrasing the question.")
        logger.info("Generated SQL: %s", sql)
        return sql

    def fix_sql(self, question: str, schema: str, sql: str, error: str) -> str:
        """Ask the model to repair a query that failed."""
        logger.info("Requesting correction for error: %s", error)
        reply = self._invoke(self._fix_chain, {
            **self._base_vars(), "schema": schema, "question": question,
            "sql": sql, "error": error[:1000]})
        fixed = extract_sql(reply)
        if not fixed:
            raise LLMError("The model did not return a corrected query.")
        logger.info("Corrected SQL: %s", fixed)
        return fixed

    def explain_sql(self, question: str, sql: str) -> str:
        """Explain a query in plain English."""
        return self._invoke(self._explain_chain,
                            {"question": question, "sql": sql}).strip()
