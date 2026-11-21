import sqlite3

import pytest

from backend.engine import Clarify, Constraints, PokedexEngine


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.delenv("POKE_LLM_MODEL", raising=False)
    monkeypatch.delenv("POKE_EMBEDDING_MODEL_PATH", raising=False)
    path = tmp_path / "pokedex.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
        CREATE TABLE pokemon(id INTEGER PRIMARY KEY,name TEXT,name_en TEXT,genus TEXT,generation INTEGER,height REAL,weight REAL,hp INTEGER,attack INTEGER,defense INTEGER,sp_attack INTEGER,sp_defense INTEGER,speed INTEGER,total INTEGER,is_legendary INTEGER,is_mythical INTEGER,evolves_from INTEGER,description TEXT,description_language TEXT,description_version TEXT,source_url TEXT,artwork TEXT,evolution_hint TEXT);
        CREATE TABLE types(id INTEGER PRIMARY KEY,name TEXT,name_en TEXT);
        CREATE TABLE pokemon_type(pokemon_id INTEGER,type_id INTEGER,slot INTEGER);
        CREATE TABLE efficacy(attack INTEGER,defense INTEGER,factor REAL);
        CREATE TABLE abilities(id INTEGER PRIMARY KEY,name TEXT,name_en TEXT,effect TEXT,language TEXT);
        CREATE TABLE pokemon_ability(pokemon_id INTEGER,ability_id INTEGER,is_hidden INTEGER);
        CREATE TABLE documents(id TEXT PRIMARY KEY,pokemon_id INTEGER,kind TEXT,title TEXT,text TEXT,url TEXT,language TEXT);
        CREATE TABLE metadata(key TEXT,value TEXT);
        """)
        type_rows = [(1, "一般", "normal"), (3, "飞行", "flying"), (5, "地面", "ground"), (10, "火", "fire"), (11, "水", "water"), (12, "草", "grass"), (13, "电", "electric")]
        db.executemany("INSERT INTO types VALUES(?,?,?)", type_rows)
        for attack, _, _ in type_rows:
            for defense, _, _ in type_rows:
                factor = {(12, 11): 2, (12, 5): 2, (13, 11): 2, (13, 5): 0, (5, 13): 2, (11, 10): 2, (5, 3): 0, (12, 10): 0.5, (12, 3): 0.5}.get((attack, defense), 1)
                db.execute("INSERT INTO efficacy VALUES(?,?,?)", (attack, defense, factor))
        rows = [(4, "小火龙", "charmander", 1, 309, None, [10]), (5, "火恐龙", "charmeleon", 1, 405, 4, [10]), (6, "喷火龙", "charizard", 1, 534, 5, [10, 3]), (25, "皮卡丘", "pikachu", 1, 320, None, [13]), (260, "巨沼怪", "swampert", 3, 535, None, [11, 5]), (382, "盖欧卡", "kyogre", 3, 670, None, [11])]
        for pid, name, english, gen, total, parent, types in rows:
            db.execute("INSERT INTO pokemon VALUES(" + ",".join("?" for _ in range(23)) + ")", (pid, name, english, "测试宝可梦", gen, 1.0, 10.0, 35, 55, 40, 50, 50, 90, total, pid == 382, 0, parent, name + "的原始图鉴描述", "zh-Hans", "test", f"https://pokeapi.co/api/v2/pokemon/{pid}/", "", ""))
            db.executemany("INSERT INTO pokemon_type VALUES(?,?,?)", [(pid, t, i + 1) for i, t in enumerate(types)])
            db.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (f"p-{pid}", pid, "flavor", name, name + "描述", "https://pokeapi.co/", "zh-Hans"))
        db.execute("INSERT INTO abilities VALUES(9,'静电','static','可能使对手麻痹','zh-Hans')")
        db.execute("INSERT INTO pokemon_ability VALUES(25,9,0)")
        db.execute("INSERT INTO metadata VALUES('snapshot_date','test-fixture')")
    return PokedexEngine(path)


def test_dual_type_multiplication_and_immunity(engine):
    rows = {d["type_name"]: d["multiplier"] for d in engine.defense([11, 5])}
    assert rows["草"] == 4
    assert rows["电"] == 0


@pytest.mark.parametrize("mode", ["R1", "R2"])
@pytest.mark.parametrize("scope", ["（普通特性或隐藏特性均计入）", "(普通特性与隐藏特性均计入)"])
def test_inclusive_ability_scope_counts_both_slots(engine, mode, scope):
    with sqlite3.connect(engine.db_path) as db:
        db.execute("INSERT INTO pokemon_ability VALUES(6,9,1)")
    result = engine.ask("特性是静电的宝可梦有哪些" + scope + "？", mode)
    assert result["intent"] == "enumeration"
    assert [p["id"] for p in result["pokemon"]] == [6, 25]


@pytest.mark.parametrize("question", [
    "普通特性是静电的宝可梦有哪些？", "隐藏特性是静电的宝可梦有哪些？",
    "特性是静电或火系的宝可梦有哪些？",
    "特性是静电的宝可梦有哪些（只计普通特性）？",
])
def test_ability_scope_not_silently_broadened(engine, question):
    assert engine.ask(question)["intent"] == "clarification"


@pytest.mark.parametrize("mode", ["R1", "R2"])
def test_explicit_tie_break_uses_existing_id_ascending_order(engine, mode):
    result = engine.ask("第一世代按速度降序列出前3只宝可梦；速度相同时按全国图鉴编号升序排列。", mode)
    assert result["intent"] == "enumeration"
    assert [p["id"] for p in result["pokemon"]] == [4, 5, 6]


@pytest.mark.parametrize("suffix", [
    "速度相同时按全国图鉴编号降序排列。",
    "总和相同时按全国图鉴编号升序排列。",
    "速度相同时按体重升序排列。",
])
def test_unsupported_tie_break_is_not_ignored(engine, suffix):
    assert engine.ask("按速度降序列出前3只宝可梦；" + suffix)["intent"] == "clarification"


@pytest.mark.parametrize("name", ["小火龙", "火恐龙", "喷火龙", "charizard"])
def test_type_character_in_entity_name_is_not_extra_condition(engine, name):
    result = engine.ask(name + "有哪些弱点、抗性和免疫？")
    assert result["intent"] == "defense"
    expected = engine.detail(result["pokemon"][0]["id"])["defense"]
    assert result["defense"] == expected


@pytest.mark.parametrize("question", ["水系小火龙的弱点", "喷火龙和水系有哪些弱点", "火系巨沼怪的弱点"])
def test_entity_mask_preserves_explicit_external_types(engine, question):
    assert engine.ask(question)["intent"] == "clarification"


def test_explicit_attack_and_dual_defense_still_work(engine):
    attack = engine.ask("水系攻击打小火龙是几倍？")
    assert attack["intent"] == "defense"
    assert next(d for d in attack["defense"] if d["type_name"] == "水")["multiplier"] == 2
    dual = engine.ask("水+地面有哪些弱点？")
    assert dual["intent"] == "defense"
    assert next(d for d in dual["defense"] if d["type_name"] == "草")["multiplier"] == 4


def test_exact_fact_and_english_name(engine):
    result = engine.ask("Pikachu的种族值")
    assert result["intent"] == "fact"
    assert result["engine"] == "evidence"
    assert "总和 320" in result["answer"]
    assert result["pokemon"][0]["id"] == 25


@pytest.mark.parametrize("mode", ["R1", "R2"])
@pytest.mark.parametrize("question,expected", [
    ("第一世代有哪些火系或水系宝可梦？", [4, 5, 6]),
    ("第3世代有哪些火系或水系宝可梦？", [260, 382]),
])
def test_type_union_with_global_generation(engine, mode, question, expected):
    result = engine.ask(question, mode)
    assert result["intent"] == "enumeration"
    assert [p["id"] for p in result["pokemon"]] == expected
    assert result["total"] == len(expected)


@pytest.mark.parametrize("question", [
    "有哪些火系或第一世代水系宝可梦？",
    "第一世代火系或第二世代水系宝可梦有哪些？",
    "第一世代有哪些火系或非水系宝可梦？",
    "第一世代有哪些火系或传说宝可梦？",
    "第一世代火系或水系且速度大于100的宝可梦有哪些？",
])
def test_type_union_ambiguous_scope_still_clarifies(engine, question):
    assert engine.ask(question)["intent"] == "clarification"


@pytest.mark.parametrize("question,expected", [
    ("列出所有火系宝可梦", [4, 5, 6]),
    ("哪些同时是火系和飞行系的宝可梦", [6]),
    ("有哪些水系或火系宝可梦", [4, 5, 6, 260, 382]),
    ("哪些火系且非飞行系宝可梦", [4, 5]),
    ("第三世代水系且种族值超过600的宝可梦有哪些", [382]),
    ("哪些非传说的水系宝可梦", [260]),
    ("有哪些特性是静电的宝可梦", [25]),
    ("所有水系宝可梦按种族值降序前1只", [382]),
])
def test_complete_constraints(engine, question, expected):
    first = engine.ask(question, "R1")
    second = engine.ask(question, "R2")
    assert first["intent"] == "enumeration", first["answer"]
    assert second["intent"] == "enumeration", second["answer"]
    assert [p["id"] for p in first["pokemon"]] == expected
    assert [p["id"] for p in second["pokemon"]] == expected
    assert second["enumeration"]["checked"] is True


@pytest.mark.parametrize("question", [
    "列出身高超过2米的火系宝可梦", "哪些火系宝可梦可以学习冲浪", "列出速度最快的前十只",
    "列出火系或水系且飞行系宝可梦", "列出火系且非火系宝可梦", "列出前10只宝可梦",
    "特性是未收录特性的宝可梦有哪些", "列出第三世代和第一世代的宝可梦",
    "哪些宝可梦比皮卡丘更快", "列出不包含火系和水系的宝可梦",
    "具有避雷针特性的皮卡丘弱点是什么", "皮卡丘的市场价格是多少",
    "皮卡丘100级能力值是多少",
    "水系克制火系吗", "火系怕水吗", "所有神兽有哪些",
    "喷火龙克制水系吗", "第十世代皮卡丘的弱点", "原始回归盖欧卡的弱点",
    "火系皮卡丘的弱点", "异色皮卡丘的弱点", "巨沼怪在晴天的弱点",
    "有哪些传说或幻宝可梦", "有哪些火系或非飞行系宝可梦", "列出种族值大于9999999999999999999999的宝可梦",
])
def test_unsupported_constraints_are_not_ignored(engine, question):
    result = engine.ask(question)
    assert result["intent"] == "clarification", result
    assert result["pokemon"] == []


def test_longest_entity_name_does_not_match_partial(engine):
    assert [p["id"] for p in engine.find_entities("火恐龙的种族值")] == [5]


def test_evolution_graph(engine):
    result = engine.ask("小火龙的进化链")
    assert result["intent"] == "evolution"
    assert [p["id"] for p in result["pokemon"]] == [4, 5, 6]
    assert "火恐龙 → 喷火龙" in result["answer"]


def test_team_unknown_member_is_not_silently_dropped(engine):
    result = engine.ask("分析皮卡丘、未知兽这支队伍的防御弱点")
    assert result["intent"] == "clarification"
    result = engine.ask("分析皮卡丘、喷火龙、巨沼怪这支队伍的防御弱点")
    assert result["intent"] == "team", result["answer"]
    assert len(result["team"]["members"]) == 3


def test_team_guards(engine):
    with pytest.raises(Clarify):
        engine.team([25, 25])
    with pytest.raises(Clarify):
        engine.team([])


def test_defense_route(engine):
    result = engine.ask("哪些属性克制水+地面组合")
    assert result["intent"] == "defense"
    assert "草 ×4" in result["answer"]
    assert "电 ×0" in result["answer"]


def test_sql_parameters_and_whitelist(engine):
    assert engine.listing("' OR 1=1 --")["total"] == 0
    with pytest.raises(Clarify):
        engine.execute_constraints(Constraints(order="id; DROP TABLE pokemon"))


def test_r0_does_not_claim_structured_complete_answer(engine):
    result = engine.ask("有哪些火系宝可梦", "R0")
    assert result["intent"] == "text"
    assert any("不能保证集合完整" in warning for warning in result["warnings"])


def test_pagination_and_count(engine):
    result = engine.listing(type_id=10, page=2, limit=2)
    assert result["total"] == 3
    assert result["pages"] == 2
    assert [p["id"] for p in result["items"]] == [6]


def test_fact_sources_separate_pokemon_and_species(engine):
    result = engine.ask("皮卡丘的图鉴描述")
    evidence = {item["id"]: item for item in result["evidence"]}
    assert evidence["pokemon-25"]["url"].endswith("/pokemon/25/")
    assert "图鉴描述" not in evidence["pokemon-25"]["text"]
    assert evidence["species-25"]["url"].endswith("/pokemon-species/25/")
    assert "图鉴描述" in evidence["species-25"]["text"]
    evolution = engine.ask("小火龙的进化链")
    graph_evidence = next(e for e in evolution["evidence"] if e["kind"] == "graph")
    assert "/pokemon-species/" in graph_evidence["url"]
    assert all("/pokemon-species/" in url for url in graph_evidence["source_urls"])
