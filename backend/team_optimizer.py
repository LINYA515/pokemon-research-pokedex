"""固定快照上的六成员属性互补优化，不依赖检索或生成模型。"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from pathlib import Path

import numpy as np


PARAMETERS = {
    "population_size": 80,
    "generations": 100,
    "tournament_size": 3,
    "elite_count": 2,
    "crossover_rate": 0.9,
    "mutation_rate": 0.2,
    "score_version": "defense-complement-v1",
    "weights": {"coverage": 0.5, "weakness_safety": 0.25, "stats": 0.25},
}
WARNINGS = [
    "基础属性与种族值的教学优化，不代表真实对战胜率或全局最优。",
    "不计算特性、招式、道具、天气或太晶化；2倍与4倍弱点在人数统计中均计一人。",
    "世代筛选仅指首次登场世代，仍使用当前快照的18属性规则。",
]


class TeamOptimizer:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).resolve()
        if not self.db_path.is_file():
            raise FileNotFoundError("图鉴数据库不存在，请先执行数据构建脚本。")
        with sqlite3.connect(f"file:{self.db_path.as_posix()}?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            self.types = [dict(row) for row in db.execute("SELECT * FROM types ORDER BY id")]
            rows = [dict(row) for row in db.execute("SELECT id,name,name_en,generation,total,is_legendary,is_mythical,artwork FROM pokemon ORDER BY id")]
            type_rows = list(db.execute("SELECT pokemon_id,type_id FROM pokemon_type ORDER BY slot"))
            efficacy = {(row[0], row[1]): float(row[2]) for row in db.execute("SELECT attack,defense,factor FROM efficacy")}
            raw_metadata = dict(db.execute("SELECT key,value FROM metadata"))
        self.metadata = {}
        for key, value in raw_metadata.items():
            try:
                self.metadata[key] = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                self.metadata[key] = value
        if [item["id"] for item in self.types] != list(range(1, 19)) or len(efficacy) != 324:
            raise ValueError("组队优化需要完整的18属性及324条克制关系。")
        self.by_id = {row["id"]: row for row in rows}
        self.id_to_index = {row["id"]: i for i, row in enumerate(rows)}
        by_type = {row["id"]: row for row in self.types}
        for row in rows:
            row["types"] = []
        for pokemon_id, type_id in type_rows:
            self.by_id[pokemon_id]["types"].append(by_type[type_id])
        self.multipliers = np.asarray([
            [np.prod([efficacy[(attack["id"], kind["id"])] for kind in row["types"]]) for attack in self.types]
            for row in rows
        ], dtype=np.float64)
        self.totals = np.asarray([row["total"] for row in rows], dtype=np.float64)
        self.multipliers.flags.writeable = False
        self.totals.flags.writeable = False
        self.data_version = f"PokéAPI · {self.metadata['commit'][:12]}" if self.metadata.get("commit") else str(self.metadata.get("snapshot_date", "本地快照"))

    def candidate_ids(self, generation: int | None = None, include_special: bool = False) -> list[int]:
        if generation is not None and (type(generation) is not int or not 1 <= generation <= 9):
            raise ValueError("首次登场世代须为1至9的整数或全部。")
        if type(include_special) is not bool:
            raise ValueError("是否包含传说与幻须为布尔值。")
        return [pid for pid, row in self.by_id.items()
                if (generation is None or row["generation"] == generation)
                and (include_special or not (row["is_legendary"] or row["is_mythical"]))]

    def _validate_ids(self, pokemon_ids, *, maximum: int | None = 6) -> tuple[int, ...]:
        if not isinstance(pokemon_ids, (list, tuple)):
            raise ValueError("宝可梦编号须为列表。")
        if maximum is not None and len(pokemon_ids) > maximum:
            raise ValueError(f"最多允许{maximum}个成员。")
        if any(type(pid) is not int or pid not in self.by_id for pid in pokemon_ids):
            raise ValueError("队伍包含无效或未收录的宝可梦编号。")
        if len(set(pokemon_ids)) != len(pokemon_ids):
            raise ValueError("队伍存在重复成员，请使用不同的宝可梦。")
        return tuple(sorted(pokemon_ids))

    def scores(self, teams) -> np.ndarray:
        """同长度队伍的批量评分，包含供贪心使用的未满六人队伍。"""
        teams = list(teams)
        if not teams:
            return np.empty(0, dtype=np.float64)
        canonical = [self._validate_ids(team) for team in teams]
        if len({len(team) for team in canonical}) != 1:
            raise ValueError("批量评分的队伍长度须一致。")
        indices = np.asarray([[self.id_to_index[pid] for pid in team] for team in canonical], dtype=np.int64)
        values = self.multipliers[indices]
        coverage = np.any(values < 1, axis=1).sum(axis=1) / 18
        max_weak = (values > 1).sum(axis=1).max(axis=1)
        weakness = np.maximum(0, max_weak - 2) / 4
        stats = self.totals[indices].sum(axis=1) / (6 * 720)
        return 100 * (0.5 * coverage + 0.25 * (1 - weakness) + 0.25 * stats)

    def evaluate(self, pokemon_ids) -> dict:
        """返回可解释分数与18属性矩阵；固定分母也用于部分队伍。"""
        ids = self._validate_ids(pokemon_ids)
        indices = [self.id_to_index[pid] for pid in ids]
        values = self.multipliers[indices]
        weak_counts = (values > 1).sum(axis=0)
        coverage_count = int(np.any(values < 1, axis=0).sum())
        max_weak = int(weak_counts.max())
        weakness = max(0, max_weak - 2) / 4
        stat_total = int(self.totals[indices].sum())
        components = {
            "coverage_count": coverage_count, "coverage": coverage_count / 18,
            "max_weak_count": max_weak, "weakness_penalty": weakness,
            "stat_total": stat_total, "stat_score": stat_total / (6 * 720),
            "worst_types": [{"type_id": kind["id"], "type_name": kind["name"]}
                            for kind, count in zip(self.types, weak_counts) if max_weak > 0 and count == max_weak],
            "weighted": {"coverage": 50 * coverage_count / 18,
                         "weakness_safety": 25 * (1 - weakness),
                         "stats": 25 * stat_total / (6 * 720)},
        }
        matchups = [{
            "type_id": kind["id"], "type_name": kind["name"],
            "multipliers": values[:, i].tolist(), "weak_count": int(weak_counts[i]),
            "resist_count": int(((values[:, i] > 0) & (values[:, i] < 1)).sum()),
            "immune_count": int((values[:, i] == 0).sum()),
        } for i, kind in enumerate(self.types)]
        # 与批量评分使用相同运算顺序，避免同分破除受舍入次序影响。
        score = float(self.scores([ids])[0])
        return {"score": score, "components": components, "matchups": matchups}

    def optimize(self, generation: int | None = None, include_special: bool = False,
                 locked_ids: list[int] | None = None, seed: int = 42, *,
                 candidate_ids: list[int] | None = None) -> dict:
        """每次独立随机源；完整搜索固定评价80+100×78=7880支队伍。"""
        started = time.perf_counter()
        if type(seed) is not int or not 0 <= seed <= 4294967295:
            raise ValueError("随机种子须为0至4294967295的整数。")
        available = self.candidate_ids(generation, include_special)
        pool = available if candidate_ids is None else list(self._validate_ids(candidate_ids, maximum=None))
        if not set(pool).issubset(available):
            raise ValueError("指定候选不符合世代或传说与幻筛选条件。")
        locked = self._validate_ids([] if locked_ids is None else locked_ids)
        if not set(locked).issubset(pool):
            raise ValueError("锁定成员不符合候选筛选条件，请调整筛选或取消锁定。")
        if len(pool) < 6:
            raise ValueError("符合条件的候选不足六只，无法组成完整队伍。")
        rng = random.Random(seed)
        free_pool = [pid for pid in pool if pid not in locked]
        free_count = 6 - len(locked)
        search_performed = len(pool) > 6 and free_count > 0
        if not search_performed:
            best = locked if len(locked) == 6 else tuple(pool)
            value = float(self.scores([best])[0])
            history = [{"generation": 0, "best": value, "mean": value}]
            evaluations = 1
        else:
            population = [tuple(sorted(locked + tuple(rng.sample(free_pool, free_count))))
                          for _ in range(PARAMETERS["population_size"])]
            scores = self.scores(population)
            evaluations = len(population)
            history = [{"generation": 0, "best": float(scores.max()), "mean": float(scores.mean())}]
            for step in range(1, PARAMETERS["generations"] + 1):
                ranked = sorted(range(len(population)), key=lambda i: (-scores[i], population[i]))
                elite_indices = ranked[:PARAMETERS["elite_count"]]
                children = []

                def select():
                    contestants = rng.sample(range(len(population)), PARAMETERS["tournament_size"])
                    return population[min(contestants, key=lambda i: (-scores[i], population[i]))]

                while len(children) < PARAMETERS["population_size"] - PARAMETERS["elite_count"]:
                    first, second = select(), select()
                    if rng.random() < PARAMETERS["crossover_rate"]:
                        genes = sorted((set(first) | set(second)) - set(locked))
                        child = list(locked) + rng.sample(genes, free_count)
                    else:
                        child = list(first)
                    if rng.random() < PARAMETERS["mutation_rate"]:
                        replace = rng.choice([i for i, pid in enumerate(child) if pid not in locked])
                        child[replace] = rng.choice([pid for pid in pool if pid not in child])
                    children.append(tuple(sorted(child)))
                child_scores = self.scores(children)
                population = [population[i] for i in elite_indices] + children
                scores = np.concatenate((scores[elite_indices], child_scores))
                evaluations += len(children)
                history.append({"generation": step, "best": float(scores.max()), "mean": float(scores.mean())})
            best = population[min(range(len(population)), key=lambda i: (-scores[i], population[i]))]
        evaluated = self.evaluate(best)
        members = [{key: self.by_id[pid][key] for key in ("id", "name", "name_en", "generation", "artwork", "total", "types")} for pid in best]
        return {
            "pokemon_ids": list(best), "members": members, **evaluated,
            "history": history, "parameters": {**PARAMETERS, "seed": seed},
            "constraints": {"generation": generation, "include_special": include_special, "locked_ids": list(locked)},
            "candidate_count": len(pool), "evaluations": evaluations,
            "search_performed": search_performed,
            "elapsed_ms": (time.perf_counter() - started) * 1000,
            "data_version": self.data_version, "data_commit": self.metadata.get("commit"),
            "warnings": list(WARNINGS),
        }
