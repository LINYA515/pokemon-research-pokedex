from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from contextlib import contextmanager
from pathlib import Path

import networkx as nx

from .llm import explain, model_status
from .retrieval import TextRetriever


STATS = {"hp": "HP", "attack": "攻击", "defense": "防御", "sp_attack": "特攻", "sp_defense": "特防", "speed": "速度"}
STAT_ALIASES = {"种族值总和": "total", "种族值总计": "total", "总种族值": "total", "种族值": "total", "总和": "total", "总计": "total", "特攻": "sp_attack", "特防": "sp_defense", "攻击": "attack", "防御": "defense", "速度": "speed", "生命值": "hp", "HP": "hp", "hp": "hp"}
NUMBERS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
BOUNDARY = "仅按当前数据快照的默认形态和18属性基础防御倍率分析；不包含特性、道具、招式、天气或太晶化效果，不代表完整对战建议。"


class Clarify(ValueError):
    pass


@dataclass
class Constraints:
    types_all: list[int] = field(default_factory=list)
    types_any: list[int] = field(default_factory=list)
    types_not: list[int] = field(default_factory=list)
    generation: int | None = None
    legendary: bool | None = None
    mythical: bool | None = None
    ability: int | None = None
    stats: list[tuple[str, str, int]] = field(default_factory=list)
    order: str = "id"
    descending: bool = False
    top: int | None = None


class PokedexEngine:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        with self.connect() as db:
            self.types = [dict(r) for r in db.execute("SELECT * FROM types ORDER BY id")]
            self.pokemon = [dict(r) for r in db.execute("SELECT * FROM pokemon ORDER BY id")]
            self.abilities = [dict(r) for r in db.execute("SELECT * FROM abilities ORDER BY id")]
            self.documents = [dict(r) for r in db.execute("SELECT * FROM documents ORDER BY id")]
            raw_metadata = dict(db.execute("SELECT key,value FROM metadata"))
            self.type_rows = [dict(r) for r in db.execute("SELECT * FROM pokemon_type ORDER BY slot")]
            self.ability_rows = [dict(r) for r in db.execute("SELECT * FROM pokemon_ability")]
            self.efficacy = {(r[0], r[1]): float(r[2]) for r in db.execute("SELECT attack,defense,factor FROM efficacy")}
        self.metadata = {}
        for key, value in raw_metadata.items():
            try:
                self.metadata[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                self.metadata[key] = value
        self.by_id = {p["id"]: p for p in self.pokemon}
        self.by_type = {t["id"]: t for t in self.types}
        self.by_ability = {a["id"]: a for a in self.abilities}
        self.graph = nx.DiGraph()
        self.graph.add_nodes_from(self.by_id)
        for p in self.pokemon:
            if p.get("evolves_from") in self.by_id:
                self.graph.add_edge(p["evolves_from"], p["id"])
        self.retriever = TextRetriever(self.documents, self.db_path.parent)

    @contextmanager
    def connect(self):
        if not self.db_path.is_file():
            raise FileNotFoundError("图鉴数据库不存在，请先执行数据构建脚本。")
        connection = sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            connection.close()

    def summary(self, pokemon: dict) -> dict:
        return {
            **{k: pokemon[k] for k in ("id", "name", "name_en", "generation", "artwork", "total")},
            "types": [self.by_type[r["type_id"]] for r in self.type_rows if r["pokemon_id"] == pokemon["id"]],
        }

    def status(self) -> dict:
        return {
            "ready": True, "pokemon_count": len(self.pokemon), "document_count": len(self.documents),
            "data_version": f"PokéAPI · {self.metadata['commit'][:12]}" if self.metadata.get("commit") else self.metadata.get("snapshot_date", "本地快照"),
            "metadata": self.metadata, "retrieval": self.retriever.name, "model": model_status(),
            "capabilities": ["实体事实", "完整条件列举", "进化图遍历", "双属性防御计算", "队伍防御分析", "证据引用", "R0/R1/R2"],
            "warnings": [self.retriever.warning] if self.retriever.warning else [],
        }

    def listing(self, search="", type_id=None, generation=None, page=1, limit=24, *, sort="number", type2=None, ids=None):
        orders = {
            "number": "p.id ASC", "id_desc": "p.id DESC",
            "total_desc": "p.total DESC, p.id ASC", "speed_desc": "p.speed DESC, p.id ASC",
            "name": "p.name COLLATE NOCASE ASC, p.id ASC",
        }
        if sort not in orders:
            raise Clarify("不支持该图鉴排序方式。")
        if type2 is not None and (type(type2) is not int or type2 not in self.by_type):
            raise Clarify("第二属性必须是已收录的常规属性。")
        if ids is not None:
            if len(ids) > 1025 or any(type(i) is not int or not 1 <= i <= 1025 for i in ids):
                raise Clarify("图鉴编号集合最多包含1025项，编号须为1至1025的整数。")
            ids = list(dict.fromkeys(ids))
        clauses, params = [], []
        if search:
            clauses.append("(p.name LIKE ? OR p.name_en LIKE ? OR CAST(p.id AS TEXT)=?)")
            escaped = search.strip().replace("%", "").replace("_", "")
            params.extend([f"%{escaped}%", f"%{escaped}%", escaped.lstrip("#0")])
        for selected_type in dict.fromkeys(t for t in (type_id, type2) if t is not None):
            clauses.append("EXISTS (SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id=?)")
            params.append(selected_type)
        if generation:
            clauses.append("p.generation=?")
            params.append(generation)
        if ids is not None:
            # 空收藏集合不能退化成未筛选的全国图鉴。
            clauses.append("p.id IN (" + ",".join("?" for _ in ids) + ")" if ids else "0")
            params.extend(ids)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as db:
            total = db.execute("SELECT COUNT(*) FROM pokemon p" + where, params).fetchone()[0]
            rows = db.execute("SELECT p.* FROM pokemon p" + where + " ORDER BY " + orders[sort] + " LIMIT ? OFFSET ?", params + [limit, (page - 1) * limit])
            items = [self.summary(dict(r)) for r in rows]
        return {"items": items, "total": total, "page": page, "pages": max(1, math.ceil(total / limit))}

    def detail(self, pokemon_id: int) -> dict:
        if pokemon_id not in self.by_id:
            raise KeyError("未找到该宝可梦。")
        p = self.by_id[pokemon_id]
        relatives = nx.node_connected_component(self.graph.to_undirected(as_view=True), pokemon_id)
        evolution = [
            {"id": i, "name": self.by_id[i]["name"], "artwork": self.by_id[i]["artwork"],
             "from": self.by_id[i].get("evolves_from"), "hint": self.by_id[i].get("evolution_hint", ""),
             "source_url": f"https://pokeapi.co/api/v2/pokemon-species/{i}/"}
            for i in sorted(relatives)
        ]
        abilities = [{**self.by_ability[r["ability_id"]], "is_hidden": bool(r["is_hidden"])} for r in self.ability_rows if r["pokemon_id"] == pokemon_id]
        summary = self.summary(p)
        return {
            **p, **summary, "stats": {k: p[k] for k in STATS}, "abilities": abilities,
            "evolution": evolution, "defense": self.defense([t["id"] for t in summary["types"]]),
            "sources": [{"title": "种族值、属性与形态（当前接口）", "url": p["source_url"]}, {"title": "物种、图鉴描述与进化（当前接口）", "url": f"https://pokeapi.co/api/v2/pokemon-species/{pokemon_id}/"}] + ([{"title": "固定版本源数据", "url": self.metadata["commit_url"]}] if self.metadata.get("commit_url") else []),
        }

    def defense(self, type_ids: list[int]) -> list[dict]:
        if not 1 <= len(type_ids) <= 2 or len(set(type_ids)) != len(type_ids):
            raise Clarify("请指定一个或两个不同的防御属性。")
        return [
            {"type_id": t["id"], "type_name": t["name"], "multiplier": math.prod(self.efficacy.get((t["id"], d), 1.0) for d in type_ids)}
            for t in self.types
        ]

    def team(self, pokemon_ids: list[int]) -> dict:
        if not 1 <= len(pokemon_ids) <= 6:
            raise Clarify("队伍需包含1至6只宝可梦。")
        if len(set(pokemon_ids)) != len(pokemon_ids):
            raise Clarify("队伍存在重复成员，请使用不同的宝可梦。")
        members = [self.detail(i) for i in pokemon_ids]
        matchups = []
        for index, t in enumerate(self.types):
            values = [m["defense"][index]["multiplier"] for m in members]
            matchups.append({"type_id": t["id"], "type_name": t["name"], "multipliers": values, "weak_count": sum(v > 1 for v in values), "resist_count": sum(0 < v < 1 for v in values), "immune_count": sum(v == 0 for v in values)})
        ranked = sorted(matchups, key=lambda m: (-m["weak_count"], -sum(m["multipliers"])))
        weak = [f"{m['type_name']}：{m['weak_count']}只弱点、{m['resist_count']}只抗性、{m['immune_count']}只免疫" for m in ranked if m["weak_count"] > 0]
        summary = "防御弱点汇总（至少一名成员受到超有效攻击）：\n" + "\n".join(weak) if weak else "基础属性表中未发现使任一成员受到大于1倍伤害的攻击属性。"
        return {"members": [self.summary(self.by_id[i]) for i in pokemon_ids], "matchups": matchups, "summary": summary, "warnings": [BOUNDARY]}

    def find_entities(self, text: str) -> list[dict]:
        found = []
        occupied: list[tuple[int, int]] = []
        candidates = []
        for p in self.pokemon:
            for name in (p["name"], p["name_en"]):
                pattern = re.escape(name)
                if name.isascii():
                    pattern = r"(?<![a-z])" + pattern + r"(?![a-z])"
                for match in re.finditer(pattern, text, re.I):
                    candidates.append((match.start(), match.end(), p))
        for start, end, p in sorted(candidates, key=lambda x: -(x[1] - x[0])):
            if any(start < b and end > a for a, b in occupied):
                continue
            occupied.append((start, end))
            found.append((start, p))
        return [p for _, p in sorted(found, key=lambda x: x[0])]

    def type_mentions(self, text: str) -> list[tuple[re.Match, dict]]:
        names = {t["name"]: t for t in self.types}
        names.update({t["name_en"]: t for t in self.types})
        if any(t["name"] == "一般" for t in self.types):
            names["普通"] = next(t for t in self.types if t["name"] == "一般")
        pattern = "|".join(sorted(map(re.escape, names), key=len, reverse=True))
        return [(m, names[m.group().lower()]) for m in re.finditer(pattern, text.lower())]

    def parse_constraints(self, text: str) -> Constraints:
        c = Constraints()
        rest = text.strip()
        # 此明确范围说明与现有查询（普通及隐藏槽位均计入）一致，不是跨条件的逻辑或。
        rest = re.sub(r"[（(]\s*普通特性\s*(?:或|和|与|及)\s*隐藏特性\s*均计入\s*[）)]", "", rest)
        if "神兽" in rest or "幻兽" in rest:
            raise Clarify("“神兽/幻兽”不是严格的数据标签，请明确使用“传说”或“幻”宝可梦。")
        if re.search(r"(?:或|或者).*(?:且|并且)|(?:且|并且).*(?:或|或者)", rest):
            raise Clarify("混合“且/或”需要明确分组；请拆成一个属性交集或并集，再添加排除条件。")
        abilities = [a for a in self.abilities if a["name"] and a["name"] in rest]
        if "特性" in rest:
            if len(abilities) != 1:
                raise Clarify("请写出一个完整的特性名称，例如“特性是静电的宝可梦”。")
            c.ability = abilities[0]["id"]
            rest = rest.replace(abilities[0]["name"], "")
            rest = re.sub("隐藏特性|普通特性", "待指定特性槽位", rest)
            rest = rest.replace("特性", "")
        for attr, words in (("legendary", "传说|传说的|神兽"), ("mythical", "幻之|幻的|幻兽|幻")):
            matches = list(re.finditer(r"(非|不是|不包含|排除)?(" + words + r")", rest))
            if matches:
                values = {not bool(m[1]) for m in matches}
                if len(values) > 1:
                    raise Clarify("传说/幻条件相互矛盾，请重新表述。")
                setattr(c, attr, values.pop())
                rest = re.sub(r"(非|不是|不包含|排除)?(" + words + r")", "", rest)
        generation = re.findall(r"第?([1-9一二三四五六七八九])(?:世代|代)", rest)
        if generation:
            if len(set(generation)) != 1:
                raise Clarify("一次查询目前支持一个首次登场世代，请分别查询。")
            generation_match = re.search(r"第?([1-9一二三四五六七八九])(?:世代|代)", rest)
            if re.search("或|或者|任一", rest) and self.type_mentions(rest[:generation_match.start()]):
                raise Clarify("属性并集中的世代范围不明确，请将统一世代放在属性之前，例如“第一世代火系或水系宝可梦”。")
            value = generation[0]
            c.generation = int(value) if value.isdigit() else NUMBERS[value]
            rest = re.sub(r"第?([1-9一二三四五六七八九])(?:世代|代)", "", rest)
        aliases = "|".join(sorted(map(re.escape, STAT_ALIASES), key=len, reverse=True))
        comparator = r"至少|不低于|大于等于|>=|≥|至多|不超过|小于等于|<=|≤|超过|高于|大于|>|低于|小于|<|等于|为|=|是"
        for m in list(re.finditer(r"(" + aliases + r")\s*(" + comparator + r")\s*(\d+)", rest)):
            operators = {"至少": ">=", "不低于": ">=", "大于等于": ">=", "≥": ">=", "至多": "<=", "不超过": "<=", "小于等于": "<=", "≤": "<=", "超过": ">", "高于": ">", "大于": ">", "低于": "<", "小于": "<", "等于": "=", "为": "=", "是": "="}
            c.stats.append((STAT_ALIASES[m[1]], operators.get(m[2], m[2]), int(m[3])))
            if int(m[3]) > 10000:
                raise Clarify("种族值筛选阈值请使用0至10000之间的整数。")
            rest = rest.replace(m[0], "", 1)
        order_match = re.search(r"(?:按)?(" + aliases + r")(最高|最大|最低|最小|降序|升序|从高到低|从低到高|排序)", rest)
        if order_match:
            c.order = STAT_ALIASES[order_match[1]]
            c.descending = order_match[2] not in ("最低", "最小", "升序", "从低到高")
            rest = rest.replace(order_match[0], "")
            tie = re.search(r"[；;，,]\s*(" + aliases + r")相同时按全国图鉴编号升序排列[。.]?$", rest)
            if tie and STAT_ALIASES[tie[1]] == c.order:
                rest = rest[:tie.start()]
        top = re.search(r"(?:前|top\s*)(\d+)\s*(?:只|个|名)?", rest, re.I)
        if top:
            c.top = int(top[1])
            if not 1 <= c.top <= 1025:
                raise Clarify("Top数量应在1至1025之间。")
            if c.order == "id":
                raise Clarify("请指定Top排序依据，例如“按速度降序前10只”。")
            rest = rest.replace(top[0], "")
        mentions = self.type_mentions(rest)
        if re.search(r"(?:不含|不包含|排除)[^，,。]*(?:和|与|或|、|\+)", rest):
            raise Clarify("多个排除属性请分别注明，例如“非火系且非水系”，避免否定范围歧义。")
        positive = []
        spans = []
        for m, t in mentions:
            before = rest[:m.start()]
            # 排除作用于紧邻的一个属性；多个排除条件需逐一注明。
            negative = re.search(r"(?:非|不是|不含|不包含|排除)\s*$", before)
            if negative:
                c.types_not.append(t["id"])
                spans.append((negative.start(), m.end()))
            else:
                positive.append(t["id"])
                spans.append(m.span())
        if re.search("或|或者|任一", rest):
            if c.legendary is not None or c.mythical is not None or c.ability is not None or c.stats or c.types_not:
                raise Clarify("“或”目前支持属性并集及前置的统一世代；跨标签、排除或数值条件的逻辑分组请拆分查询，避免改变原意。")
            c.types_any = sorted(set(positive))
        else:
            c.types_all = sorted(set(positive))
        if len(c.types_all) > 2:
            raise Clarify("默认形态最多两个属性；三个以上属性请明确使用“或”。")
        if set(c.types_not) & (set(c.types_all) | set(c.types_any)):
            raise Clarify("属性包含与排除条件冲突，请重新表述。")
        for start, end in sorted(spans, reverse=True):
            rest = rest[:start] + " " + rest[end:]
        fillers = ["宝可梦", "神奇宝贝", "口袋妖怪", "有哪些", "哪些", "所有", "全部", "列出", "列举", "查找", "查询", "筛选", "请问", "帮我", "请", "总共有", "共有", "多少", "几只", "数量", "统计", "同时", "而且", "并且", "以及", "或者", "任一", "但是", "并", "且", "或", "和", "与", "及", "属性", "系", "满足", "条件", "包含", "拥有", "具有", "是", "为", "的", "有", "只", "个", "吗", "呢", "中", "？", "?", "。", ",", "，", "、", "+", "＆", "&", "/", "：", ":", " ", "\n"]
        for filler in sorted(fillers, key=len, reverse=True):
            rest = rest.replace(filler, "")
        if rest:
            raise Clarify(f"暂不能可靠解析条件“{rest[:30]}”。目前支持属性交/并集及排除、首次登场世代、传说/幻、单个特性、种族值阈值及排序。请拆分或改写。")
        return c

    def execute_constraints(self, c: Constraints, mode="R2") -> tuple[list[dict], dict]:
        clauses, params = [], []
        for type_id in c.types_all:
            clauses.append("EXISTS(SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id=?)")
            params.append(type_id)
        if c.types_any:
            clauses.append("EXISTS(SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id IN (" + ",".join("?" for _ in c.types_any) + "))")
            params.extend(c.types_any)
        for type_id in c.types_not:
            clauses.append("NOT EXISTS(SELECT 1 FROM pokemon_type pt WHERE pt.pokemon_id=p.id AND pt.type_id=?)")
            params.append(type_id)
        for attr, column in (("generation", "generation"), ("legendary", "is_legendary"), ("mythical", "is_mythical")):
            value = getattr(c, attr)
            if value is not None:
                clauses.append(f"p.{column}=?")
                params.append(int(value))
        if c.ability is not None:
            clauses.append("EXISTS(SELECT 1 FROM pokemon_ability pa WHERE pa.pokemon_id=p.id AND pa.ability_id=?)")
            params.append(c.ability)
        for name, operator, value in c.stats:
            if name not in (*STATS, "total") or operator not in ("=", ">", "<", ">=", "<="):
                raise Clarify("筛选字段或运算符不在白名单内。")
            clauses.append(f"p.{name}{operator}?")
            params.append(value)
        if c.order not in ("id", "total", *STATS):
            raise Clarify("排序字段不在白名单内。")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        query = "SELECT p.* FROM pokemon p" + where + f" ORDER BY p.{c.order} {'DESC' if c.descending else 'ASC'},p.id ASC"
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM pokemon p" + where, params).fetchone()[0]
            target = min(count, c.top) if c.top else count
            if mode == "R1":
                rows = [dict(r) for r in db.execute(query + " LIMIT ?", params + [target])]
                pages = 1 if rows else 0
            else:
                collected = {}
                pages = 0
                for offset in range(0, target, 64):
                    batch = db.execute(query + " LIMIT ? OFFSET ?", params + [min(64, target - offset), offset])
                    for row in batch:
                        collected[row["id"]] = dict(row)
                    pages += 1
                rows = list(collected.values())
                if len(rows) != target:
                    raise RuntimeError("枚举结果数与数据库计数不一致，拒绝输出不完整名单。")
        return rows, {"matched": count, "returned": len(rows), "pages": pages, "checked": mode == "R2", "top": c.top}

    def pokemon_evidence(self, p: dict) -> dict:
        detail = self.detail(p["id"])
        stats = "；".join(f"{label} {p[key]}" for key, label in STATS.items())
        ability_names = "、".join(a["name"] + ("（隐藏）" if a["is_hidden"] else "") for a in detail["abilities"])
        text = f"{p['name']} / {p['name_en']}，#{p['id']:04d}；属性：{' / '.join(t['name'] for t in detail['types'])}。{stats}；总和 {p['total']}。特性：{ability_names}。身高 {p['height']:g} m；体重 {p['weight']:g} kg。"
        return {"id": f"pokemon-{p['id']}", "title": f"{p['name']} · 结构化图鉴", "text": text, "url": p["source_url"], "kind": "structured"}

    def species_evidence(self, p: dict) -> dict:
        text = f"{p['name']}：第{p['generation']}世代首次登场。图鉴描述（{p['description_language']} / {p['description_version']}）：{p['description']}"
        return {"id": f"species-{p['id']}", "title": f"{p['name']} · 物种与图鉴描述", "text": text, "url": f"https://pokeapi.co/api/v2/pokemon-species/{p['id']}/", "kind": "description"}

    def ask(self, question: str, mode="R2") -> dict:
        start = time.perf_counter()
        question = question.strip()
        if not question:
            raise Clarify("请输入问题。")
        if mode not in ("R0", "R1", "R2"):
            raise Clarify("仅支持R0、R1、R2模式。")
        result = {"answer": "", "intent": "text", "mode": mode, "engine": "evidence", "pokemon": [], "evidence": [], "trace": [], "warnings": [], "total": 0}
        result["trace"].append({"step": "检索配置", "detail": self.retriever.name})
        if not model_status()["configured"]:
            result["warnings"].append("当前未配置语言模型，使用程序计算与原始证据回答，不是LLM生成结果。")
        if self.retriever.warning:
            result["warnings"].append(self.retriever.warning)
        try:
            self._answer(question, mode, result)
        except Clarify as exc:
            result.update(answer=str(exc), intent="clarification", pokemon=[], evidence=[], total=0)
            result["trace"].append({"step": "边界检查", "detail": "未执行不完整或有歧义的条件。"})
        if result["intent"] != "clarification" and result["evidence"]:
            explanation, warning = explain(question, result["evidence"], result["answer"] if result["intent"] != "text" else None)
            if explanation:
                if result["intent"] == "text":
                    result["answer"] = explanation
                else:
                    result["answer"] += "\n\n模型解读：\n" + explanation
                result["engine"] = "llm"
                result["trace"].append({"step": "语言模型", "detail": "证据限定生成；结构化结果保持原样。"})
            if warning:
                result["warnings"].append(warning)
        result["trace"].append({"step": "数据来源", "detail": "SQLite、文本索引和NetworkX是同一PokéAPI快照的不同表示，不是独立事实来源。"})
        result["latency_ms"] = round((time.perf_counter() - start) * 1000)
        return result

    def _answer(self, question: str, mode: str, result: dict):
        entities = self.find_entities(question)
        if mode == "R0":
            self._text_answer(question, result)
            result["warnings"].append("R0仅检索文本Top-6；不能保证集合完整或执行属性规则。")
            return
        if re.search(r"第[一二三四五六七八九十0-9]+(?:世代|代).*(?:版本|对战规则)|第(?:十|1[0-9])(?:世代|代)|朱紫|剑盾|红宝石|太晶|Mega|超级进化|超极巨|洗翠|阿罗拉|伽勒尔|帕底亚|原始回归|黑色形态|白色形态|起源形态|地区形态", question, re.I):
            raise Clarify("当前只支持当前快照中的默认形态及18属性规则，不支持指定版本、地区形态、Mega或太晶化。")
        if re.search("队伍|队中|团队|这队", question):
            if not entities:
                raise Clarify("请列出1至6只宝可梦，例如“分析皮卡丘、喷火龙、巨沼怪这支队伍的防御弱点”。")
            unknown = question
            for p in entities:
                unknown = re.sub(re.escape(p["name"]), "", unknown, flags=re.I)
                unknown = re.sub(re.escape(p["name_en"]), "", unknown, flags=re.I)
            unknown = re.sub(r"分析|这支|这只|这队|队伍|团队|队中|防御|属性|弱点|抗性|免疫|组合|帮我|请|有什么|有哪些|哪些|如何|怎么样|我|的|和|与|及|、|，|,|\s|[?？。:]", "", unknown)
            if unknown:
                raise Clarify(f"队伍中存在未识别名称或条件“{unknown[:30]}”，请使用图鉴中的标准名称，只分析基础属性防御。")
            team = self.team([p["id"] for p in entities])
            result.update(intent="team", answer=team["summary"], pokemon=team["members"], total=len(entities), team=team)
            result["warnings"].extend(team["warnings"])
            result["evidence"] = [self.pokemon_evidence(p) for p in entities]
            matrix = [
                f"{m['type_name']}：" + "、".join(f"{p['name']} ×{value:g}" for p, value in zip(entities, m["multipliers"]))
                + f"；弱点{m['weak_count']}只、抗性{m['resist_count']}只、免疫{m['immune_count']}只"
                for m in team["matchups"]
            ]
            result["evidence"].append({"id": "team-type-chart", "title": "队伍18属性防御计算", "text": BOUNDARY + "\n每名成员的倍率为其各防御属性倍率的乘积；大于1计为弱点，0计为免疫，0与1之间计为抗性。\n" + "\n".join(matrix), "url": "https://pokeapi.co/docs/v2#types", "kind": "rule"})
            result["trace"].append({"step": "队伍规则计算", "detail": f"对{len(entities)}名成员分别计算18类攻击倍率。"})
            return
        if re.search("进化|退化", question):
            if len(entities) != 1:
                raise Clarify("进化链查询请指定一只宝可梦，例如“伊布的进化链”。")
            remainder = question
            for name in (entities[0]["name"], entities[0]["name_en"]):
                remainder = re.sub(re.escape(name), "", remainder, flags=re.I)
            remainder = re.sub(r"进化链|进化形态|进化关系|进化|退化|是什么|有哪些|哪些|如何|怎么|介绍|请问|请|的|了|是|会|能|到|成|为|[?？。，、\s]", "", remainder)
            if remainder:
                raise Clarify(f"进化查询中有未支持条件“{remainder[:30]}”。当前仅查询默认形态的进化关系，具体进化条件未导入。")
            detail = self.detail(entities[0]["id"])
            lines = []
            for p in detail["evolution"]:
                if p["from"] in self.by_id:
                    lines.append(f"{self.by_id[p['from']]['name']} → {p['name']}" + (f"（{p['hint']}）" if p["hint"] else ""))
            result.update(intent="evolution", answer="进化关系：\n" + ("\n".join(lines) or "当前快照未记录其他进化阶段。"), pokemon=[self.summary(self.by_id[p["id"]]) for p in detail["evolution"]], total=len(detail["evolution"]))
            result["evidence"] = [self.species_evidence(entities[0]), {"id": f"evolution-{entities[0]['id']}", "title": "进化关系图", "text": "\n".join(lines), "url": f"https://pokeapi.co/api/v2/pokemon-species/{entities[0]['id']}/", "kind": "graph", "source_urls": [p["source_url"] for p in detail["evolution"]]}]
            result["trace"].append({"step": "NetworkX关系遍历", "detail": "查找进化链无向连通分量，保留有向进化边；形态变化不视作进化。"})
            return
        if re.search("克制|弱点|弱什么|弱哪些|怕|免疫|抗性|倍率|几倍|防御分析", question):
            if re.search("特性|道具|天气|暴雨|下雨|晴天|地形|重力|双打|沙暴|雪天|技能|招式|漂浮", question):
                raise Clarify("当前仅计算基础属性防御，不会忽略特性、道具、天气或招式条件。请去掉这些条件后查询。")
            if len(entities) > 1:
                raise Clarify("请用“队伍”明确进行多成员防御分析，或只查询一只宝可梦。")
            if re.search(r"(?:系|属性)(?:能)?克制(?:什么|哪些|谁)|克制哪些属性|克制什么属性", question):
                raise Clarify("当前问答计算的是承受攻击的防御倍率。请改写为“哪些攻击属性克制水+地面组合”。")
            if "克制" in question:
                prefix = question.split("克制", 1)[0]
                if (self.type_mentions(prefix) or self.find_entities(prefix)) and not re.search("被|受|受到", prefix):
                    raise Clarify("这句话包含主动攻击方向。请明确防御方，例如“哪些攻击属性克制火系”，或查询防御方的弱点。")
            if entities:
                p = entities[0]
                outside_name = question
                for name in (p["name"], p["name_en"]):
                    pattern = re.escape(name)
                    if name.isascii():
                        pattern = r"(?<![a-z])" + pattern + r"(?![a-z])"
                    outside_name = re.sub(pattern, "", outside_name, flags=re.I)
                if self.type_mentions(outside_name) and not re.search("攻击|受到|被|打", outside_name):
                    raise Clarify("请明确宝可梦名称之外的属性是攻击方还是条件；例如“电系攻击打巨沼怪是几倍”。默认形态的属性不能任意替换。")
                type_ids = [t["id"] for t in self.summary(p)["types"]]
                title = p["name"]
                result["pokemon"] = [self.summary(p)]
                result["evidence"] = [self.pokemon_evidence(p)]
            else:
                mentions = self.type_mentions(question)
                type_ids = list(dict.fromkeys(t["id"] for _, t in mentions))
                if len(mentions) == 2:
                    between = question[mentions[0][0].end():mentions[1][0].start()]
                    if not re.fullmatch(r"(?:系|属性)?[\s+、/和与及]*", between):
                        raise Clarify("请区分攻击属性与防御组合，例如“水+地面有哪些弱点”；当前不会把有歧义的两个属性自动合并。")
                title = "+".join(self.by_type[i]["name"] for i in type_ids)
            if not 1 <= len(type_ids) <= 2:
                raise Clarify("请明确一个或两个防御属性，例如“水+地面怕什么属性”。")
            remainder = question
            for p in entities:
                for name in (p["name"], p["name_en"]):
                    remainder = re.sub(re.escape(name), "", remainder, flags=re.I)
            for match, _ in reversed(self.type_mentions(remainder)):
                remainder = remainder[:match.start()] + remainder[match.end():]
            terms = ["双属性", "攻击属性", "防御属性", "防御分析", "属性", "攻击", "防御", "组合", "克制", "弱点", "弱什么", "弱哪些", "抗性", "免疫", "倍率", "几倍", "受到", "承受", "哪些", "有哪些", "有什么", "是什么", "什么", "请问", "帮我", "分析", "请", "怕", "被", "打", "是", "的", "有", "吗", "呢", "系", "和", "与", "及", "?", "？", "。", "，", ",", "+", "/", "、", " "]
            for term in sorted(terms, key=len, reverse=True):
                remainder = remainder.replace(term, "")
            if remainder:
                raise Clarify(f"防御问题包含未支持的条件“{remainder[:30]}”。请仅指定默认形态名称或一个/两个防御属性。")
            defense = self.defense(type_ids)
            groups = []
            for label, predicate in (("弱点", lambda v: v > 1), ("抗性", lambda v: 0 < v < 1), ("免疫", lambda v: v == 0)):
                values = [f"{d['type_name']} ×{d['multiplier']:g}" for d in defense if predicate(d["multiplier"])]
                groups.append(label + "：" + ("、".join(values) or "无"))
            result.update(intent="defense", answer=f"{title}的基础防御倍率：\n" + "\n".join(groups), defense=defense, total=len(result["pokemon"]))
            factors = [f"{d['type_name']}：" + " × ".join(f"{self.efficacy.get((d['type_id'], target), 1):g}" for target in type_ids) + f" = {d['multiplier']:g}" for d in defense]
            result["evidence"].append({"id": "type-chart", "title": "18属性防御规则", "text": "\n".join(factors), "url": "https://pokeapi.co/docs/v2#types", "kind": "rule"})
            result["warnings"].append(BOUNDARY)
            result["trace"].append({"step": "规则执行", "detail": "双属性倍率为两列倍率的乘积；任何一列免疫均使乘积为0。"})
            return
        enumeration = re.search(r"哪些|有哪些|列出|列举|所有|全部|多少|几只|筛选|前\d+|top\s*\d+|最高|最低|降序|升序", question, re.I)
        if enumeration and not entities:
            constraints = self.parse_constraints(question)
            rows, audit = self.execute_constraints(constraints, mode)
            titles = [f"#{p['id']:04d} {p['name']}" + (f"（{STATS.get(constraints.order, '总种族值')} {p[constraints.order]}）" if constraints.order != "id" else "") for p in rows]
            heading = f"符合条件的宝可梦共 {audit['matched']} 只。"
            if constraints.top:
                heading += f"以下按指定顺序返回前 {len(rows)} 只。"
            result.update(intent="enumeration", answer=heading + ("\n\n" + "、".join(titles) if rows else "当前快照中没有符合全部条件的记录。"), pokemon=[self.summary(p) for p in rows], total=audit["matched"], enumeration=audit)
            criteria = {k: v for k, v in vars(constraints).items() if v not in (None, [], False)}
            result["evidence"] = [{"id": "query-result", "title": "SQLite完整条件查询", "text": f"解析后的约束：{criteria}。匹配{audit['matched']}条，输出{audit['returned']}条。实体ID：" + ",".join(str(p["id"]) for p in rows), "url": "https://pokeapi.co/docs/v2#pokemon", "kind": "structured"}]
            result["trace"].append({"step": "参数化条件执行", "detail": str(criteria)})
            result["trace"].append({"step": "完整性核对" if mode == "R2" else "完整SQL查询", "detail": f"匹配{audit['matched']}条；返回{audit['returned']}条；读取{audit['pages']}批。R1和R2均不截断合法结果。"})
            result["warnings"].append("数量核对仅检查执行和输出完整性，不能证明自然语言条件解析正确；请核对检索轨迹。")
            if constraints.legendary is not None and constraints.mythical is None:
                result["warnings"].append("传说与幻是独立标签；“非传说”不自动排除幻之宝可梦。")
            return
        if entities:
            if len(entities) > 1:
                raise Clarify("一次事实查询请指定一只宝可梦；多只防御分析请明确写“队伍”。")
            p = entities[0]
            unsupported = re.search("配招|招式|技能|种族排名|捕获|捕捉|栖息|地点|蛋组|努力值|性格|伤害|对战|胜率|最强|推荐|身高.*[><超过低]|体重.*[><超过低]", question)
            if unsupported:
                raise Clarify("当前事实模块支持属性、种族值、身高体重、特性和图鉴描述；不支持配招、捕获地点或完整对战推断。")
            rest = question
            for name in (p["name"], p["name_en"]):
                rest = re.sub(re.escape(name), "", rest, flags=re.I)
            fact_terms = ["种族值总和", "六项种族值", "6项种族值", "种族值", "总种族值", "总和", "图鉴描述", "首次登场世代", "首次登场", "图鉴", "属性", "普通特性", "隐藏特性", "特性", "身高", "体重", "攻击", "防御", "特攻", "特防", "速度", "HP", "hp", "世代", "介绍一下", "介绍", "告诉我", "关于", "信息", "资料", "看看", "查询", "查一下", "请问", "请", "分别", "区分", "什么", "哪些", "多少", "有哪些", "怎么样", "怎么", "是", "的", "有", "和", "与", "及", "为", "吗", "呢", "？", "?", "。", "，", ",", " "]
            for term in sorted(fact_terms, key=len, reverse=True):
                rest = rest.replace(term, "")
            if rest:
                raise Clarify(f"已识别{p['name']}，但无法可靠处理附加条件“{rest[:30]}”。请单独询问其属性、种族值、特性、身高体重或图鉴描述。")
            evidence = [self.pokemon_evidence(p), self.species_evidence(p)]
            detail = self.detail(p["id"])
            lines = [f"{p['name']} / {p['name_en']} · 全国图鉴 #{p['id']:04d}", "属性：" + " / ".join(t["name"] for t in detail["types"]), "种族值：" + " / ".join(f"{label} {p[key]}" for key, label in STATS.items()) + f"；总和 {p['total']}", "特性：" + "、".join(a["name"] + ("（隐藏）" if a["is_hidden"] else "") for a in detail["abilities"]), f"身高 {p['height']:g} m；体重 {p['weight']:g} kg；第{p['generation']}世代首次登场。"]
            if p["description"]:
                lines.append("图鉴描述：" + p["description"])
            result.update(intent="fact", answer="\n".join(lines), pokemon=[self.summary(p)], evidence=evidence, total=1)
            result["trace"].append({"step": "实体精确查询", "detail": f"已解析为标准实体 #{p['id']:04d}；从SQLite读取数值。"})
            return
        self._text_answer(question, result)

    def _text_answer(self, question: str, result: dict):
        hits = self.retriever.search(question, 6)
        result["evidence"] = [{"id": str(d["id"]), "title": d["title"], "text": d["text"], "url": d["url"], "kind": d["kind"], "score": d["score"]} for d in hits]
        ids = list(dict.fromkeys(d["pokemon_id"] for d in hits if d.get("pokemon_id") in self.by_id))
        result["pokemon"] = [self.summary(self.by_id[i]) for i in ids]
        result["total"] = len(ids)
        if hits:
            result["answer"] = "检索到以下相关原始资料。相关度不是事实正确性的保证；未配置语言模型时不作超出资料的推断。\n\n" + "\n\n".join(f"[{d['id']}] {d['title']}\n{d['text']}" for d in hits[:3])
        else:
            result.update(intent="clarification", answer="未检索到相关证据。请使用标准宝可梦名称，或明确属性、世代、种族值等条件。")
        result["trace"].append({"step": "文本Top-k", "detail": f"{self.retriever.name}返回{len(hits)}条；k=6。"})
