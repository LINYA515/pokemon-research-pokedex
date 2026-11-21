import json
import os
import sys
from types import SimpleNamespace

import httpx
import pytest

from backend.llm import explain, model_status
from backend.retrieval import TextRetriever


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("POKE_LLM_MODEL", "test-local-model")
    monkeypatch.setenv("POKE_LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("POKE_LLM_API_KEY", "unit-test-secret-do-not-leak")
    return "unit-test-secret-do-not-leak"


def install_client(monkeypatch, payload=None, error=None):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            if error:
                raise error

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, **kwargs):
            captured["options"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url, **kwargs):
            captured.update(url=url, **kwargs)
            return FakeResponse()

    monkeypatch.setattr("backend.llm.httpx.Client", FakeClient)
    return captured


@pytest.mark.parametrize("payload", [{}, {"choices": []}, {"choices": [{}]}, {"choices": [{"message": {"content": "  "}}]}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": ["unexpected"]}}]}])
def test_malformed_or_empty_model_response_falls_back(monkeypatch, configured, payload):
    install_client(monkeypatch, payload=payload)
    answer, warning = explain("皮卡丘的属性", [{"id": "pokemon-25", "title": "皮卡丘", "text": "电属性"}])
    assert answer is None
    assert "保留确定性证据回答" in warning
    assert configured not in warning
    assert configured not in json.dumps(model_status())


def test_timeout_fallback_does_not_leak_exception_or_key(monkeypatch, configured):
    install_client(monkeypatch, error=httpx.TimeoutException("request failed with " + configured))
    answer, warning = explain("问题", [])
    assert answer is None
    assert warning
    assert configured not in warning
    assert "request failed" not in warning


def test_success_uses_auth_header_not_prompt(monkeypatch, configured):
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": " 电属性 [pokemon-25] "}}]})
    answer, warning = explain("皮卡丘的属性", [{"id": "pokemon-25", "title": "皮卡丘", "text": "电属性"}], "属性：电")
    assert answer == "电属性 [pokemon-25]"
    assert warning is None
    assert captured["headers"]["Authorization"] == "Bearer " + configured
    assert configured not in json.dumps(captured["json"])
    assert "不重写名单或数值" in captured["json"]["messages"][0]["content"]
    assert captured["json"]["stream"] is False
    assert captured["options"] == {"timeout": 35, "trust_env": False}


def test_text_retrieval_prompt_requires_rule_and_ability_evidence(monkeypatch, configured):
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "缺少规则证据。"}}]})
    explain("合成开发问题", [{"id": "synthetic", "title": "资料", "text": "只有属性名称"}])
    prompt = captured["json"]["messages"][0]["content"]
    assert "不凭记忆补齐" in prompt
    assert "不同时归入普通特性" in prompt
    assert "完整性尚未验证" in prompt


def test_team_explanation_distinguishes_all_types_from_weakness_subset(monkeypatch, configured):
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "依据计算证据解释。"}}]})
    explain("合成队伍问题", [{"id": "team-type-chart", "title": "计算证据", "text": "火：1；水：0"}], "弱点：火")
    prompt = captured["json"]["messages"][0]["content"]
    assert "已列出的弱点属性子集" in prompt
    assert "核对人数为0" in prompt


def test_audit_retains_usage_and_cache_avoids_duplicate_requests(monkeypatch, configured, tmp_path):
    audit = tmp_path / "calls.jsonl"
    monkeypatch.setenv("POKE_LLM_AUDIT_PATH", str(audit))
    monkeypatch.setenv("POKE_LLM_CACHE_DIR", str(tmp_path / "cache"))
    payload = {"choices": [{"message": {"content": "320 [pokemon-25]"}}], "usage": {"prompt_tokens": 42, "completion_tokens": 8}}
    install_client(monkeypatch, payload=payload)
    assert explain("种族值总和", [])[0] == "320 [pokemon-25]"
    monkeypatch.setattr("backend.llm.httpx.Client", lambda **kwargs: pytest.fail("相同输入应使用已保存的响应"))
    assert explain("种族值总和", [])[0] == "320 [pokemon-25]"
    content = audit.read_text(encoding="utf-8")
    rows = [json.loads(line) for line in content.splitlines()]
    assert [row["cached"] for row in rows] == [False, True]
    assert rows[0]["response"]["usage"] == payload["usage"]
    assert configured not in content and "Authorization" not in content


def test_unconfigured_model_does_not_create_client(monkeypatch):
    monkeypatch.delenv("POKE_LLM_MODEL", raising=False)

    def forbidden_client(**kwargs):
        pytest.fail("未配置模型时不应发起任何请求")

    monkeypatch.setattr("backend.llm.httpx.Client", forbidden_client)
    assert explain("问题", []) == (None, None)


def test_local_embedding_import_disables_unused_frameworks(monkeypatch, tmp_path):
    monkeypatch.delenv("USE_TF", raising=False)
    monkeypatch.delenv("USE_FLAX", raising=False)
    monkeypatch.setenv("POKE_EMBEDDING_MODEL_PATH", str(tmp_path))

    class FakeEncoder:
        def __init__(self, *args, **kwargs):
            assert os.environ["USE_TF"] == "0"
            assert os.environ["USE_FLAX"] == "0"
            assert kwargs["local_files_only"] is True
            raise ValueError("用于测试确定性回退的模型加载失败")

    monkeypatch.setitem(sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=FakeEncoder))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(set_num_threads=lambda _: None))
    retriever = TextRetriever([{"id": "p25", "title": "皮卡丘", "text": "电属性宝可梦"}])
    assert retriever.name.startswith("TF-IDF")
    assert "回退" in retriever.warning
    assert retriever.search("皮卡丘")[0]["id"] == "p25"


@pytest.mark.parametrize("base", ["https://api.example.com:invalid", "https://[invalid", "https://api.example.com:99999", "api.example.com", "https://user:unit-test-secret@example.com"])
def test_invalid_base_never_calls_network(monkeypatch, configured, base):
    monkeypatch.setenv("POKE_LLM_BASE_URL", base)

    def forbidden_client(**kwargs):
        pytest.fail("地址无效时不应创建网络客户端")

    monkeypatch.setattr("backend.llm.httpx.Client", forbidden_client)
    answer, warning = explain("问题", [])
    assert answer is None
    assert "地址格式无效" in warning
    assert "unit-test-secret" not in warning
    assert model_status()["configured"] is False


def test_invalid_url_from_transport_is_caught(monkeypatch, configured):
    install_client(monkeypatch, error=httpx.InvalidURL("bad URL " + configured))
    answer, warning = explain("问题", [])
    assert answer is None
    assert "保留确定性证据回答" in warning
    assert configured not in warning


@pytest.mark.parametrize("base", ["http://api.deepseek.com", "http://example.com/v1", "http://localhost.evil.example/v1"])
def test_remote_plaintext_http_is_blocked(monkeypatch, configured, base):
    monkeypatch.setenv("POKE_LLM_BASE_URL", base)

    def forbidden_client(**kwargs):
        pytest.fail("不能向远端明文HTTP服务发送认证头")

    monkeypatch.setattr("backend.llm.httpx.Client", forbidden_client)
    answer, warning = explain("问题", [])
    assert answer is None
    assert "阻止远端明文HTTP" in warning
    assert model_status()["configured"] is False


def test_whitespace_and_deepseek_specific_payload(monkeypatch, configured):
    monkeypatch.setenv("POKE_LLM_BASE_URL", "  https://api.deepseek.com/  ")
    monkeypatch.setenv("POKE_LLM_MODEL", " deepseek-flash ")
    monkeypatch.setenv("POKE_LLM_API_KEY", "  " + configured + "\n")
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "回答"}}]})
    assert explain("问题", [])[0] == "回答"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer " + configured
    assert captured["json"]["model"] == "deepseek-flash"
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert captured["json"]["max_tokens"] == 500
    assert model_status()["configured"] is True
    assert configured not in json.dumps(model_status())


def test_other_provider_does_not_get_deepseek_fields(monkeypatch, configured):
    monkeypatch.setenv("POKE_LLM_BASE_URL", "https://example.com/v1")
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "回答"}}]})
    assert explain("问题", [])[0] == "回答"
    assert "thinking" not in captured["json"]


def test_evaluation_context_and_budget_are_explicit_and_in_payload(monkeypatch, configured):
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "合成回答"}}]})
    answer, _ = explain("合成问题", [], task_context="统一范围，不含参考答案", max_tokens=4096)
    assert answer == "合成回答"
    assert captured["json"]["max_tokens"] == 4096
    assert "统一范围，不含参考答案" in captured["json"]["messages"][0]["content"]


@pytest.mark.parametrize("authoritative", [None, "程序结果：中性倍率不属于弱点。"])
def test_defense_terminology_constraint_shared_by_all_modes(monkeypatch, configured, authoritative):
    captured = install_client(monkeypatch, payload={"choices": [{"message": {"content": "合成回答"}}]})
    explain("合成防御问题", [], authoritative)
    system = captured["json"]["messages"][0]["content"]
    assert "等于1为中性" in system and "没有弱点不等于不受伤" in system
    assert "不得用‘有效’代替‘具有抗性’" in system
    assert "合成防御问题" in captured["json"]["messages"][1]["content"]


@pytest.mark.parametrize("budget", [0, 8193, True, "4096"])
def test_invalid_evaluation_budget_is_rejected_before_network(monkeypatch, configured, budget):
    monkeypatch.setattr("backend.llm.httpx.Client", lambda **kwargs: pytest.fail("无效预算不应发起网络请求"))
    with pytest.raises(ValueError, match="预算"):
        explain("合成问题", [], max_tokens=budget)


def test_deepseek_missing_key_is_not_configured_and_never_calls_network(monkeypatch):
    monkeypatch.setenv("POKE_LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("POKE_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("POKE_LLM_API_KEY", "  ")

    def forbidden_client(**kwargs):
        pytest.fail("DeepSeek未配置密钥时不能发起网络请求")

    monkeypatch.setattr("backend.llm.httpx.Client", forbidden_client)
    answer, warning = explain("问题", [])
    assert answer is None
    assert "缺少本机DeepSeek API密钥" in warning
    status = model_status()
    assert status["configured"] is False
    assert "尚未接入" in status["note"]
