from llm.generator import SQLGenerator, extract_sql


def test_extract_from_fence() -> None:
    text = "Sure!\n```sql\nSELECT * FROM t WHERE a = 'x;y'\n```\nHope it helps"
    assert extract_sql(text) == "SELECT * FROM t WHERE a = 'x;y';"


def test_extract_plain_with_chatter() -> None:
    text = "Here is the query: SELECT 1; This returns one."
    assert extract_sql(text) == "SELECT 1;"


def test_extract_empty() -> None:
    assert extract_sql("") == ""
    assert extract_sql("I cannot answer that.") == ""


def test_extract_unclosed_fence() -> None:
    assert extract_sql("```sql\nSELECT name FROM products") == \
        "SELECT name FROM products;"


def test_explain_and_fix(fake_llm_factory) -> None:
    llm = fake_llm_factory(["- Looks at customers", "```sql\nSELECT 2\n```"])
    gen = SQLGenerator(llm)
    assert gen.explain_sql("q", "SELECT 1") == "- Looks at customers"
    assert gen.fix_sql("q", "schema", "SELECT x", "no such column: x") == "SELECT 2;"
    assert "no such column: x" in llm.calls[1][1]


def test_model_failure_becomes_llm_error() -> None:
    import pytest
    from langchain_core.runnables import RunnableLambda

    from llm.generator import LLMError

    def boom(_):
        raise RuntimeError("out of memory")

    gen = SQLGenerator(RunnableLambda(boom))
    with pytest.raises(LLMError):
        gen.generate_sql("q", "schema")


def test_generator_uses_schema(fake_llm_factory) -> None:
    llm = fake_llm_factory(["```sql\nSELECT * FROM customers\n```"])
    gen = SQLGenerator(llm)
    sql = gen.generate_sql("all customers", "CREATE TABLE customers (id INT);")
    assert sql == "SELECT * FROM customers;"
    system, user = llm.calls[0]
    assert "SQLITE" in system
    assert "CREATE TABLE customers" in user
    assert "all customers" in user


def test_local_model_dir_uses_plain_folder() -> None:
    from llm.generator import MODELS_DIR, is_model_downloaded, local_model_dir

    path = local_model_dir("Qwen/Qwen2.5-Coder-0.5B-Instruct")
    assert path == MODELS_DIR / "Qwen--Qwen2.5-Coder-0.5B-Instruct"
    assert not is_model_downloaded("someone/does-not-exist")
