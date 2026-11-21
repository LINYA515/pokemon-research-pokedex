"""遗传组队REST合约；无需创建RAG引擎。"""

from pathlib import Path
import shutil

from fastapi.testclient import TestClient
import pytest

from backend import main


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", ROOT / "data" / "pokedex.sqlite")
    monkeypatch.setattr(main, "_optimizer", None)

    def forbidden():
        pytest.fail("优化接口不得初始化RAG引擎")

    monkeypatch.setattr(main, "get_engine", forbidden)
    with TestClient(main.app) as test_client:
        yield test_client


def test_default_contract_and_no_rag_initialization(client):
    response = client.post("/api/team/optimize", json={})
    assert response.status_code == 200
    result = response.json()
    assert result["candidate_count"] == 931
    assert result["evaluations"] == 7880
    assert result["parameters"]["seed"] == 42
    assert len(result["members"]) == 6
    assert len(result["history"]) == 101
    assert result["constraints"] == {"generation": None, "include_special": False, "locked_ids": []}
    assert result["data_commit"]
    assert result["warnings"]


@pytest.mark.parametrize("payload", [
    {"seed": -1}, {"seed": 4294967296}, {"seed": True}, {"seed": "42"},
    {"generation": 0}, {"generation": 10}, {"generation": "1"}, {"generation": True},
    {"include_special": "false"}, {"include_special": 1},
    {"locked_ids": [25, 25]}, {"locked_ids": [True]}, {"locked_ids": [25.0]},
    {"locked_ids": [1, 2, 3, 4, 5, 6, 7]}, {"locked_ids": [99999]},
    {"locked_ids": [493]}, {"generation": 1, "locked_ids": [260]},
    {"generations": 10000},
])
def test_invalid_requests_return_422(client, payload):
    assert client.post("/api/team/optimize", json=payload).status_code == 422


def test_allowed_special_and_six_locked(client):
    ids = [1, 2, 3, 4, 5, 493]
    response = client.post("/api/team/optimize", json={"include_special": True, "locked_ids": ids, "seed": 4294967295})
    assert response.status_code == 200
    result = response.json()
    assert result["pokemon_ids"] == ids
    assert result["search_performed"] is False
    assert result["evaluations"] == 1


def test_optimizer_cache_changes_with_database_path(client, monkeypatch, tmp_path):
    original = main.get_optimizer()
    copied = tmp_path / "copied.sqlite"
    shutil.copy2(ROOT / "data" / "pokedex.sqlite", copied)
    monkeypatch.setattr(main, "DB_PATH", copied)
    replacement = main.get_optimizer()
    assert replacement is not original
    assert replacement.db_path == copied.resolve()
    assert main.get_optimizer() is replacement


def test_missing_database_returns_503(client, monkeypatch, tmp_path):
    missing = tmp_path / "missing.sqlite"
    monkeypatch.setattr(main, "DB_PATH", missing)
    assert client.post("/api/team/optimize", json={}).status_code == 503
    assert not missing.exists()
