"""核对图鉴筛选、排序与收藏集合的完整分页行为。"""

from pathlib import Path
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend import main
from backend.engine import Clarify


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def client():
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("POKE_EMBEDDING_MODEL_PATH", raising=False)
        patch.setattr(main, "DB_PATH", ROOT / "data" / "pokedex.sqlite")
        patch.setattr(main, "_engine", None)
        with TestClient(main.app) as test_client:
            yield test_client


def query_ids(statement, params=()):
    with sqlite3.connect(f"file:{(ROOT / 'data' / 'pokedex.sqlite').as_posix()}?mode=ro", uri=True) as db:
        return [row[0] for row in db.execute(statement, params)]


@pytest.mark.parametrize("sort,order", [
    ("number", "id ASC"), ("id_desc", "id DESC"),
    ("total_desc", "total DESC, id ASC"), ("speed_desc", "speed DESC, id ASC"),
    ("name", "name COLLATE NOCASE ASC, id ASC"),
])
def test_sort_is_stable_across_pages(client, sort, order):
    expected = query_ids("SELECT id FROM pokemon ORDER BY " + order + " LIMIT 48")
    pages = [client.get("/api/pokemon", params={"sort": sort, "page": page, "limit": 24}).json() for page in (1, 2)]
    assert [item["id"] for page in pages for item in page["items"]] == expected
    assert all(page["total"] == 1025 and page["pages"] == 43 for page in pages)


def test_dual_type_intersection_is_filtered_before_paging(client):
    expected = query_ids("""SELECT p.id FROM pokemon p
        WHERE p.generation=3
        AND EXISTS (SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id=11)
        AND EXISTS (SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id=5)
        ORDER BY p.total DESC, p.id ASC""")
    payloads = [client.get("/api/pokemon", params={"type": 11, "type2": 5, "generation": 3, "sort": "total_desc", "limit": 1, "page": page}).json() for page in range(1, len(expected) + 1)]
    assert len(expected) > 1
    assert [item["id"] for payload in payloads for item in payload["items"]] == expected
    assert all(payload["total"] == len(expected) and payload["pages"] == len(expected) for payload in payloads)


def test_second_type_alone_and_repeated_type_are_consistent(client):
    first = client.get("/api/pokemon", params={"type": 10, "limit": 100}).json()
    assert client.get("/api/pokemon", params={"type2": 10, "limit": 100}).json() == first
    assert client.get("/api/pokemon", params={"type": 10, "type2": 10, "limit": 100}).json() == first


def test_favorites_are_deduplicated_sorted_and_paged(client):
    params = {"ids": " 25,6,25,4 ", "sort": "total_desc", "limit": 2}
    first = client.get("/api/pokemon", params=params).json()
    second = client.get("/api/pokemon", params={**params, "page": 2}).json()
    assert [item["id"] for item in first["items"]] == [6, 25]
    assert [item["id"] for item in second["items"]] == [4]
    assert first["total"] == second["total"] == 3
    assert first["pages"] == second["pages"] == 2


def test_favorites_combine_with_name_type_and_generation(client):
    payload = client.get("/api/pokemon", params={"ids": "4,6,25,7", "type": 10, "type2": 3, "generation": 1, "search": "喷火"}).json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["items"]] == [6]


@pytest.mark.parametrize("ids", ["", "   "])
def test_empty_favorites_are_not_all_pokemon(client, ids):
    response = client.get("/api/pokemon", params={"ids": ids})
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "pages": 1}


def test_full_id_collection_is_supported(client):
    response = client.get("/api/pokemon", params={"ids": ",".join(map(str, range(1, 1026))), "sort": "id_desc", "limit": 100})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1025
    assert [item["id"] for item in payload["items"]] == list(range(1025, 925, -1))


@pytest.mark.parametrize("params", [
    {"sort": "unknown"}, {"sort": "id; DROP TABLE pokemon"}, {"type2": 0}, {"type2": 19},
    {"ids": "0"}, {"ids": "1026"}, {"ids": "1,,2"}, {"ids": "1,"}, {"ids": "x"},
    {"ids": "1 OR 1=1"}, {"ids": "1.5"}, {"ids": "-1"}, {"ids": ",".join(["1"] * 1026)},
])
def test_invalid_filters_return_422(client, params):
    assert client.get("/api/pokemon", params=params).status_code == 422


def test_listing_positional_contract_and_keyword_validation(client):
    engine = main.get_engine()
    original = engine.listing("", 10, 1, 1, 24)
    assert original["total"] == 12
    assert [item["id"] for item in original["items"]] == [4, 5, 6, 37, 38, 58, 59, 77, 78, 126, 136, 146]
    for invalid in ({"sort": "p.id"}, {"ids": [True]}, {"ids": [1026]}, {"type2": 19}):
        with pytest.raises(Clarify):
            engine.listing(**invalid)
