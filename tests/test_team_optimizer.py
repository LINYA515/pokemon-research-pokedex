"""优化器的独立手算、约束和可重复性验证。"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3

import pytest

from backend.team_optimizer import TeamOptimizer


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def optimizer():
    return TeamOptimizer(ROOT / "data" / "pokedex.sqlite")


@pytest.fixture
def synthetic(tmp_path):
    """六只同属性成员：抵抗t1、免疫t3，分别弱于t2和t4。"""
    path = tmp_path / "small.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE pokemon(id INTEGER,name TEXT,name_en TEXT,generation INTEGER,total INTEGER,is_legendary INTEGER,is_mythical INTEGER,artwork TEXT);
        CREATE TABLE types(id INTEGER,name TEXT,name_en TEXT);
        CREATE TABLE pokemon_type(pokemon_id INTEGER,type_id INTEGER,slot INTEGER);
        CREATE TABLE efficacy(attack INTEGER,defense INTEGER,factor REAL);
        CREATE TABLE metadata(key TEXT,value TEXT);
        """)
        db.executemany("INSERT INTO types VALUES(?,?,?)", [(i, f"t{i}", f"t{i}") for i in range(1, 19)])
        factors = {(1, 1): 0.5, (2, 1): 2, (3, 1): 0, (4, 1): 4}
        db.executemany("INSERT INTO efficacy VALUES(?,?,?)", [(a, d, factors.get((a, d), 1)) for a in range(1, 19) for d in range(1, 19)])
        db.executemany("INSERT INTO pokemon VALUES(?,?,?,?,?,?,?,?)", [(i, f"p{i}", f"p{i}", 1 if i <= 6 else 2, i * 50, i == 11, i == 12, "") for i in range(1, 13)])
        db.executemany("INSERT INTO pokemon_type VALUES(?,?,1)", [(i, 1 if i <= 6 else 2) for i in range(1, 13)])
        db.execute("INSERT INTO metadata VALUES('snapshot_date','synthetic')")
    return TeamOptimizer(path)


def test_snapshot_pool_and_readonly_arrays(optimizer):
    assert len(optimizer.candidate_ids()) == 931
    assert len(optimizer.candidate_ids(include_special=True)) == 1025
    assert len(optimizer.candidate_ids(generation=1)) == 146
    assert 493 not in optimizer.candidate_ids()
    assert 493 in optimizer.candidate_ids(include_special=True)
    assert not optimizer.multipliers.flags.writeable


def test_known_dual_type_multiplication(optimizer):
    result = optimizer.evaluate([260])
    multipliers = {row["type_id"]: row["multipliers"][0] for row in result["matchups"]}
    assert multipliers[12] == 4
    assert multipliers[13] == 0
    assert multipliers[10] == 0.5


def test_six_member_score_by_hand(synthetic):
    result = synthetic.evaluate([1, 2, 3, 4, 5, 6])
    # 手算：覆盖2种，最严重6只弱点，种族值50×(1+…+6)=1050。
    assert result["score"] == pytest.approx(50 * 2 / 18 + 25 * 1050 / 4320)
    c = result["components"]
    assert (c["coverage_count"], c["max_weak_count"], c["stat_total"]) == (2, 6, 1050)
    assert c["weakness_penalty"] == 1
    assert [row["type_id"] for row in c["worst_types"]] == [2, 4]
    assert sum(c["weighted"].values()) == pytest.approx(result["score"])
    assert result["matchups"][1]["weak_count"] == result["matchups"][3]["weak_count"] == 6
    assert result["matchups"][1]["multipliers"] == [2] * 6
    assert result["matchups"][3]["multipliers"] == [4] * 6


@pytest.mark.parametrize("ids,expected", [([1, 2], 0), ([1, 2, 3], 0.25), ([1, 2, 3, 4, 5, 6], 1)])
def test_weakness_thresholds(synthetic, ids, expected):
    assert synthetic.evaluate(ids)["components"]["weakness_penalty"] == expected


def test_partial_score_and_batch_consistency(synthetic):
    assert synthetic.evaluate([])["score"] == 25
    assert synthetic.scores([[]]).tolist() == [25]
    assert synthetic.scores([]).size == 0
    # 固定分母下，加入第三个共同弱点成员可使部分队伍分数下降。
    assert synthetic.evaluate([1, 2, 3])["score"] < synthetic.evaluate([1, 2])["score"]
    teams = [[1, 3, 5], [2, 4, 6]]
    assert synthetic.scores(teams).tolist() == [synthetic.evaluate(t)["score"] for t in teams]
    assert synthetic.evaluate([3, 2, 1]) == synthetic.evaluate([1, 2, 3])


@pytest.mark.parametrize("ids", [[1, 1], [99999], [True], [1.0], list(range(1, 8))])
def test_invalid_scoring_members(synthetic, ids):
    with pytest.raises(ValueError):
        synthetic.evaluate(ids)


@pytest.mark.parametrize("kwargs", [
    {"seed": -1}, {"seed": 4294967296}, {"seed": True}, {"seed": 1.2},
    {"generation": 0}, {"generation": True}, {"include_special": 1},
    {"locked_ids": [25, 25]}, {"locked_ids": [493]}, {"locked_ids": [99999]},
    {"generation": 1, "locked_ids": [260]},
    {"candidate_ids": [1, 2, 3, 4, 5]},
    {"candidate_ids": [1, 2, 3, 4, 5, 493]},
    {"candidate_ids": [1, 2, 3, 4, 5, 6], "locked_ids": [25]},
])
def test_invalid_search_constraints(optimizer, kwargs):
    with pytest.raises(ValueError):
        optimizer.optimize(**kwargs)


def test_ga_invariants_and_budget(optimizer):
    result = optimizer.optimize(locked_ids=[25, 6, 260], seed=42)
    assert len(result["pokemon_ids"]) == len(set(result["pokemon_ids"])) == 6
    assert {25, 6, 260}.issubset(result["pokemon_ids"])
    assert set(result["pokemon_ids"]).issubset(optimizer.candidate_ids())
    assert result["evaluations"] == 7880
    assert result["search_performed"]
    assert len(result["history"]) == 101
    assert [row["generation"] for row in result["history"]] == list(range(101))
    best = [row["best"] for row in result["history"]]
    assert all(b >= a for a, b in zip(best, best[1:]))
    assert best[-1] == result["score"] == optimizer.evaluate(result["pokemon_ids"])["score"]
    assert all(row["mean"] <= row["best"] + 1e-12 for row in result["history"])
    assert len(result["matchups"]) == 18


def test_same_seed_is_reproducible_without_global_randomness(optimizer):
    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(lambda _: optimizer.optimize(seed=123), range(2)))
    for run in runs:
        run.pop("elapsed_ms")
    assert runs[0] == runs[1]


def test_six_locked_members_only_score(optimizer):
    ids = [1, 2, 3, 4, 5, 6]
    result = optimizer.optimize(locked_ids=ids)
    assert result["pokemon_ids"] == ids
    assert not result["search_performed"]
    assert result["evaluations"] == 1
    assert len(result["history"]) == 1


def test_six_candidates_only_score_and_locked_members_persist(synthetic):
    result = synthetic.optimize(generation=1, locked_ids=[1])
    assert result["pokemon_ids"] == [1, 2, 3, 4, 5, 6]
    assert result["candidate_count"] == 6
    assert not result["search_performed"]
    assert result["evaluations"] == 1
    with pytest.raises(ValueError, match="不足六"):
        synthetic.optimize(generation=2)


def test_small_candidate_pool_is_respected(synthetic):
    pool = list(range(1, 8))
    result = synthetic.optimize(candidate_ids=pool, locked_ids=[1, 3, 5, 6, 7])
    assert set(result["pokemon_ids"]).issubset(pool)
    assert {1, 3, 5, 6, 7}.issubset(result["pokemon_ids"])


def test_missing_database_is_not_created(tmp_path):
    path = tmp_path / "missing.sqlite"
    with pytest.raises(FileNotFoundError):
        TeamOptimizer(path)
    assert not path.exists()
