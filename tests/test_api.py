"""使用真实冻结快照验证 REST 合约、参数边界和检索完整性。"""

import json
from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend import llm, main


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("POKE_LLM_MODEL", raising=False)
        patch.delenv("POKE_EMBEDDING_MODEL_PATH", raising=False)
        patch.setattr(main, "DB_PATH", ROOT / "data" / "pokedex.sqlite")
        patch.setattr(main, "_engine", None)
        with TestClient(main.app) as test_client:
            yield test_client


def test_status_reflects_real_snapshot_and_model_state(client):
    response = client.get("/api/status")
    assert response.status_code == 200
    payload = response.json()
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    assert payload["ready"] is True
    assert payload["pokemon_count"] == manifest["scope"]["species_count"] == 1025
    assert payload["document_count"] == manifest["document_count"]
    assert payload["metadata"]["commit"] == manifest["commit"]
    assert payload["metadata"]["description_languages"] == {"zh-hans": 722, "en": 303}
    assert manifest["commit"][:12] in payload["data_version"]
    assert payload["model"]["configured"] is False
    assert payload["retrieval"] == main.get_engine().retriever.name


def test_all_eighteen_types(client):
    response = client.get("/api/types")
    assert response.status_code == 200
    types = response.json()
    assert {row["id"] for row in types} == set(range(1, 19))
    assert next(row["name"] for row in types if row["name_en"] == "water") == "水"


def test_missing_database_is_not_reported_ready(client, monkeypatch):
    missing = ROOT / "data" / "__test_missing_database__.sqlite"
    assert not missing.exists()
    monkeypatch.setattr(main, "DB_PATH", missing)
    payload = client.get("/api/status").json()
    assert payload["ready"] is False
    assert payload["pokemon_count"] == 0 and payload["document_count"] == 0
    assert payload["data_version"] is None
    assert payload["warnings"]


def test_pagination_and_filter_match_database(client):
    pages = [client.get("/api/pokemon", params={"page": page, "limit": 24}).json() for page in (1, 2)]
    assert all(page["total"] == 1025 and len(page["items"]) == 24 for page in pages)
    assert not {p["id"] for p in pages[0]["items"]} & {p["id"] for p in pages[1]["items"]}
    payload = client.get("/api/pokemon", params={"type": 11, "generation": 3, "limit": 100}).json()
    with sqlite3.connect(ROOT / "data" / "pokedex.sqlite") as db:
        expected = [row[0] for row in db.execute("SELECT p.id FROM pokemon p JOIN pokemon_type pt ON pt.pokemon_id=p.id WHERE p.generation=3 AND pt.type_id=11 ORDER BY p.id")]
    assert [row["id"] for row in payload["items"]] == expected
    assert payload["total"] == len(expected)


def test_empty_search_and_omitted_filters_are_supported(client):
    assert client.get("/api/pokemon", params={"search": ""}).json()["total"] == 1025
    for key in ("type", "generation"):
        assert client.get("/api/pokemon", params={key: ""}).status_code == 422


@pytest.mark.parametrize("params", [{"page": 0}, {"page": 9223372036854775808}, {"limit": 101}, {"type": 19}, {"generation": 10}])
def test_invalid_list_parameters_return_422(client, params):
    assert client.get("/api/pokemon", params=params).status_code == 422


def test_unknown_detail_and_unknown_team_member_are_404(client):
    assert client.get("/api/pokemon/99999").status_code == 404
    assert client.post("/api/team", json={"pokemon_ids": [25, 99999]}).status_code == 404


@pytest.mark.parametrize("members", [[], [25, 25], [1, 2, 3, 4, 5, 6, 7]])
def test_invalid_teams_are_rejected(client, members):
    assert client.post("/api/team", json={"pokemon_ids": members}).status_code == 422


def test_sql_injection_is_data_not_sql(client):
    response = client.get("/api/pokemon", params={"search": "' OR 1=1 --"})
    assert response.status_code == 200
    assert response.json()["total"] == 0
    response = client.post("/api/ask", json={"question": "列出火系宝可梦; DROP TABLE pokemon;"})
    assert response.json()["intent"] == "clarification"
    assert client.get("/api/pokemon").json()["total"] == 1025


@pytest.mark.parametrize("question,intent", [
    ("皮卡丘的种族值", "fact"),
    ("哪些同时是水系和地面系的宝可梦", "enumeration"),
    ("哪些属性克制水+地面组合", "defense"),
    ("分析皮卡丘、喷火龙、巨沼怪这支队伍的防御弱点", "team"),
    ("伊布的进化链", "evolution"),
])
def test_natural_question_routes(client, question, intent):
    response = client.post("/api/ask", json={"question": question})
    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == intent, payload["answer"]
    assert payload["engine"] == "evidence"
    assert payload["evidence"] and payload["trace"]
    if intent == "fact":
        assert "总和 320" in payload["answer"]
    elif intent == "defense":
        defense = {item["type_name"]: item["multiplier"] for item in payload["defense"]}
        assert defense["草"] == 4 and defense["电"] == 0


def test_r1_r2_return_every_matching_species(client):
    outputs = [client.post("/api/ask", json={"question": "列出全部水系宝可梦", "mode": mode}).json() for mode in ("R1", "R2")]
    with sqlite3.connect(ROOT / "data" / "pokedex.sqlite") as db:
        expected = [row[0] for row in db.execute("SELECT pokemon_id FROM pokemon_type WHERE type_id=11 ORDER BY pokemon_id")]
    for payload in outputs:
        assert payload["intent"] == "enumeration"
        assert [item["id"] for item in payload["pokemon"]] == expected
        assert payload["enumeration"]["returned"] == len(expected) == payload["total"]
    assert outputs[1]["enumeration"]["pages"] > 1
    assert outputs[1]["enumeration"]["checked"] is True


@pytest.mark.parametrize("question", [
    "隐藏特性是避雷针的宝可梦有哪些", "列出所有第十世代水系宝可梦",
    "哪些宝可梦能学习冲浪", "皮卡丘有哪些招式", "Mega喷火龙的属性",
    "帕底亚乌波的弱点", "原始回归盖欧卡的弱点", "酋雷姆黑色形态弱点",
    "第十世代皮卡丘的弱点", "喷火龙克制水系吗",
])
def test_unsupported_conditions_do_not_look_successful(client, question):
    payload = client.post("/api/ask", json={"question": question}).json()
    assert payload["intent"] == "clarification", payload["answer"]
    assert payload["pokemon"] == []
    assert payload["total"] == 0


def test_empty_question_and_invalid_mode(client):
    assert client.post("/api/ask", json={"question": ""}).status_code == 422
    assert client.post("/api/ask", json={"question": "皮卡丘", "mode": "R3"}).status_code == 422
    whitespace = client.post("/api/ask", json={"question": "   "})
    assert whitespace.status_code == 422
    assert whitespace.json()["detail"]


def test_r0_discloses_top_k_boundary(client):
    payload = client.post("/api/ask", json={"question": "列出全部水系宝可梦", "mode": "R0"}).json()
    assert payload["intent"] == "text"
    assert len(payload["evidence"]) <= 6
    assert "enumeration" not in payload
    assert any("不能保证集合完整" in warning for warning in payload["warnings"])


def test_model_prompt_preserves_retrieval_limit(client, monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "这里只是相关资料，不代表全量名单。"}}]}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

    monkeypatch.setenv("POKE_LLM_MODEL", "test-no-network")
    monkeypatch.setattr(llm.httpx, "Client", FakeClient)
    payload = client.post("/api/ask", json={"question": "列出全部水系宝可梦", "mode": "R0"}).json()
    assert payload["engine"] == "llm"
    system = captured["messages"][0]["content"]
    assert any(term in system.lower() for term in ("top-k", "top-6", "非全量", "不代表全量"))
    assert any("不能保证集合完整" in warning for warning in payload["warnings"])
