"""复现宝可梦组队算法的固定场景对照，并保存原始结果与汇报图表。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import importlib.metadata
from itertools import combinations
import json
import math
from pathlib import Path
import platform
import random
import statistics
import sys
import time
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.team_optimizer import PARAMETERS, TeamOptimizer


SEEDS = list(range(20))
BUDGET = 7880
SMALL_POOL = [3, 6, 9, 25, 65, 94, 130, 143, 149, 196, 197, 212]
SCENARIOS = [
    {"id": "default", "label": "全国默认候选", "settings": {}},
    {"id": "generation1", "label": "第一世代首次登场", "settings": {"generation": 1}},
    {"id": "locked", "label": "锁定三名成员", "settings": {"locked_ids": [25, 6, 260]}},
]
COLORS = {"ga": "#d74746", "random": "#8b929c", "greedy": "#24988c"}
METHOD_NAMES = {"ga": "遗传算法", "random": "随机搜索", "greedy": "贪心组队"}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def best_index(teams: list[tuple[int, ...]], scores: np.ndarray) -> int:
    """使用与遗传算法相同的分数及编号顺序破同分。"""
    return min(range(len(teams)), key=lambda i: (-float(scores[i]), teams[i]))


def random_search(optimizer: TeamOptimizer, pool: list[int], locked: list[int], seed: int) -> dict:
    start = time.perf_counter()
    rng = random.Random(seed)
    free = [pid for pid in pool if pid not in locked]
    teams = [tuple(sorted(locked + rng.sample(free, 6 - len(locked)))) for _ in range(BUDGET)]
    values = optimizer.scores(teams)
    chosen = teams[best_index(teams, values)]
    detail = optimizer.evaluate(chosen)
    return {
        "pokemon_ids": list(chosen), **detail, "evaluations": BUDGET,
        "elapsed_ms": (time.perf_counter() - start) * 1000,
    }


def greedy_search(optimizer: TeamOptimizer, pool: list[int], locked: list[int]) -> dict:
    """以同一目标逐个加入成员；部分队伍降分时仍然补满六只。"""
    start = time.perf_counter()
    selected = tuple(sorted(locked))
    evaluations = 0
    steps = []
    while len(selected) < 6:
        teams = [tuple(sorted((*selected, pid))) for pid in pool if pid not in selected]
        values = optimizer.scores(teams)
        chosen = best_index(teams, values)
        evaluations += len(teams)
        selected = teams[chosen]
        steps.append({"size": len(selected), "pokemon_ids": list(selected), "score": float(values[chosen])})
    detail = optimizer.evaluate(selected)
    return {
        "pokemon_ids": list(selected), **detail, "evaluations": evaluations,
        "elapsed_ms": (time.perf_counter() - start) * 1000, "steps": steps,
    }


def scalar_score(optimizer: TeamOptimizer, team: tuple[int, ...]) -> float:
    """用独立的标量循环核对批量评分，避免穷举只重复同一个向量化实现。"""
    rows = [optimizer.multipliers[optimizer.id_to_index[pid]].tolist() for pid in team]
    coverage = sum(any(member[kind] < 1 for member in rows) for kind in range(18)) / 18
    largest_weak = max(sum(member[kind] > 1 for member in rows) for kind in range(18))
    weakness = max(0, largest_weak - 2) / 4
    stats = sum(optimizer.by_id[pid]["total"] for pid in team) / (6 * 720)
    return 100 * (0.5 * coverage + 0.25 * (1 - weakness) + 0.25 * stats)


def aggregate(records: list[dict]) -> dict:
    scores = [row["score"] for row in records]
    return {
        "n": len(records), "score_mean": statistics.mean(scores),
        "score_std": statistics.stdev(scores) if len(scores) > 1 else None,
        "score_min": min(scores), "score_max": max(scores),
        "elapsed_ms_mean": statistics.mean(row["elapsed_ms"] for row in records),
        "elapsed_ms_std": statistics.stdev(row["elapsed_ms"] for row in records) if len(records) > 1 else None,
        "evaluations": records[0]["evaluations"],
    }


def compare(left: list[dict], right: list[dict]) -> dict:
    differences = [a["score"] - right[i if len(right) > 1 else 0]["score"] for i, a in enumerate(left)]
    return {
        "wins": sum(value > 1e-9 for value in differences),
        "ties": sum(abs(value) <= 1e-9 for value in differences),
        "losses": sum(value < -1e-9 for value in differences),
        "score_difference_mean": statistics.mean(differences),
    }


def run_experiments(db: Path, output: Path) -> dict:
    results = output / "results"
    results.mkdir(parents=True, exist_ok=True)
    started_at = now()
    optimizer = TeamOptimizer(db)
    all_runs, history_rows, summaries = [], [], []
    for scenario in SCENARIOS:
        settings = scenario["settings"]
        pool = optimizer.candidate_ids(generation=settings.get("generation"), include_special=False)
        locked = settings.get("locked_ids", [])
        runs = {"ga": [], "random": [], "greedy": []}
        for seed in SEEDS:
            for method, result in (
                ("ga", optimizer.optimize(**settings, seed=seed)),
                ("random", random_search(optimizer, pool, locked, seed)),
            ):
                if result["evaluations"] != BUDGET:
                    raise AssertionError("搜索评价预算与预注册参数不一致。")
                row = {"scenario": scenario["id"], "method": method, "seed": seed, **result}
                runs[method].append(row)
                all_runs.append(row)
                for generation in result.get("history", []):
                    history_rows.append({"scenario": scenario["id"], "seed": seed, **generation})
        greedy = {"scenario": scenario["id"], "method": "greedy", "seed": None,
                  **greedy_search(optimizer, pool, locked)}
        runs["greedy"].append(greedy)
        all_runs.append(greedy)
        summaries.append({
            **scenario, "candidate_count": len(pool), "methods": {method: aggregate(rows) for method, rows in runs.items()},
            "ga_vs_random": compare(runs["ga"], runs["random"]),
            "ga_vs_greedy": compare(runs["ga"], runs["greedy"]),
        })
        print(json.dumps({"scenario": scenario["id"], "candidates": len(pool),
                          "mean_scores": {method: aggregate(rows)["score_mean"] for method, rows in runs.items()}}, ensure_ascii=False), flush=True)

    small_teams = list(combinations(SMALL_POOL, 6))
    if len(small_teams) != math.comb(12, 6):
        raise AssertionError("小候选池组合枚举不完整。")
    small_scores = optimizer.scores(small_teams)
    scalar_error = max(abs(float(value) - scalar_score(optimizer, team)) for team, value in zip(small_teams, small_scores))
    if scalar_error > 1e-10:
        raise AssertionError("标量公式与批量评分不一致。")
    best = best_index(small_teams, small_scores)
    optimum_score = float(small_scores[best])
    exhaustive_rows = [{"pokemon_ids": ",".join(map(str, team)), "score": float(score)} for team, score in zip(small_teams, small_scores)]
    save_csv(results / "small_pool.csv", exhaustive_rows)
    small_runs = []
    for seed in SEEDS:
        result = optimizer.optimize(seed=seed, candidate_ids=SMALL_POOL)
        gap = optimum_score - result["score"]
        if gap < -1e-9:
            raise AssertionError("遗传算法分数高于穷举最优，评分或候选约束有错误。")
        small_runs.append({"seed": seed, "score": result["score"], "gap": max(0.0, gap),
                           "pokemon_ids": result["pokemon_ids"], "evaluations": result["evaluations"],
                           "elapsed_ms": result["elapsed_ms"]})
    small = {
        "candidate_ids": SMALL_POOL, "combinations": len(small_teams), "optimum_score": optimum_score,
        "independent_scalar_max_error": scalar_error,
        "optimum_ids": list(small_teams[best]),
        "optimal_team_count": sum(abs(float(value) - optimum_score) <= 1e-9 for value in small_scores),
        "ga_gap_mean": statistics.mean(row["gap"] for row in small_runs),
        "ga_gap_max": max(row["gap"] for row in small_runs),
        "ga_optimal_runs": sum(row["gap"] <= 1e-9 for row in small_runs), "runs": small_runs,
    }
    demo = optimizer.optimize(seed=42)
    save_json(results / "demo_default.json", demo)
    flattened = []
    for row in all_runs:
        comp = row["components"]
        flattened.append({
            "scenario": row["scenario"], "method": row["method"], "seed": row["seed"],
            "score": row["score"], "evaluations": row["evaluations"], "elapsed_ms": row["elapsed_ms"],
            "pokemon_ids": ",".join(map(str, row["pokemon_ids"])),
            "coverage_count": comp["coverage_count"], "max_weak_count": comp["max_weak_count"],
            "stat_total": comp["stat_total"],
        })
    save_csv(results / "runs.csv", flattened)
    save_csv(results / "history.csv", history_rows, ["scenario", "seed", "generation", "best", "mean"])
    save_json(results / "runs.json", all_runs)
    source_files = {"run_team_experiments.py": digest(Path(__file__)),
                    "team_optimizer.py": digest(ROOT / "backend" / "team_optimizer.py")}
    summary = {
        "metadata": {
            "started_at": started_at, "finished_at": now(), "timezone": "Asia/Shanghai",
            "db_filename": db.name, "db_sha256": digest(db), "data_version": demo["data_version"],
            "data_commit": optimizer.metadata.get("commit"), "source_sha256": source_files,
            "environment": {"python": platform.python_version(), "numpy": np.__version__,
                            "matplotlib": importlib.metadata.version("matplotlib"),
                            "platform": platform.platform(), "processor": platform.processor()},
            "parameters": PARAMETERS, "seeds": SEEDS, "search_evaluation_budget": BUDGET,
            "timing_scope": "本机已加载数据后的算法运行，包含最终结果解释；不包含服务冷启动、网络或绘图。不同方法按顺序运行，耗时仅作本机观测。",
            "budget_scope": "评价预算统计用于搜索的候选队伍评价，重复队伍仍计数；最终队伍解释不作为新增搜索。贪心使用实际评价数。",
            "score_definition": {"formula": "100*(0.50*C+0.25*(1-W)+0.25*S)",
                                 "C": "至少一名成员抵抗或免疫的来袭属性数/18",
                                 "W": "max(0,同一属性下最多弱点人数-2)/4",
                                 "S": "成员种族值总和/(6*720)"},
            "notes": ["贪心为确定性单次结果，标准差不适用。", "GA与随机方法按相同seed配对比较，不表示共享完全相同的候选样本。",
                      "世代仅筛选首次登场物种，全部场景使用固定快照当前18属性规则。", "这是基础属性与种族值教学评分，不是对战胜率。"],
        },
        "scenarios": summaries, "small_pool": small,
        "demo": {"seed": 42, "score": demo["score"], "pokemon_ids": demo["pokemon_ids"],
                 "names": [member["name"] for member in demo["members"]], "elapsed_ms": demo["elapsed_ms"]},
    }
    save_json(results / "summary.json", summary)
    save_csv(results / "summary.csv", [
        {"scenario": scene["id"], "label": scene["label"], "method": method, **values}
        for scene in summaries for method, values in scene["methods"].items()
    ])
    return summary


def make_figures(output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import BoundaryNorm, ListedColormap
    from matplotlib.patches import Patch

    plt.rcParams.update({"font.family": "Microsoft YaHei", "axes.unicode_minus": False,
                         "font.size": 17, "axes.titlesize": 24, "axes.labelsize": 18,
                         "svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False,
                         "figure.facecolor": "#ffffff", "axes.edgecolor": "#d6d9de"})
    results, figures = output / "results", output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    summary = json.loads((results / "summary.json").read_text(encoding="utf-8"))
    runs = json.loads((results / "runs.json").read_text(encoding="utf-8"))
    demo = json.loads((results / "demo_default.json").read_text(encoding="utf-8"))

    def save(fig, name):
        fig.savefig(figures / f"{name}.png", dpi=160, facecolor="white")
        fig.savefig(figures / f"{name}.svg", facecolor="white")
        plt.close(fig)

    fig, ax = plt.subplots(figsize=(16, 9))
    positions = np.arange(len(summary["scenarios"]))
    for offset, method in enumerate(("ga", "random", "greedy")):
        values = [scene["methods"][method]["score_mean"] for scene in summary["scenarios"]]
        errors = [scene["methods"][method]["score_std"] or 0 for scene in summary["scenarios"]]
        bars = ax.bar(positions + (offset - 1) * .24, values, width=.22, yerr=errors, capsize=5,
                      color=COLORS[method], label=METHOD_NAMES[method], zorder=3)
        for bar, value, error in zip(bars, values, errors):
            ax.text(bar.get_x() + bar.get_width() / 2, value + error + .7, f"{value:.2f}", ha="center", fontsize=17)
    ax.set_xticks(positions, [scene["label"] for scene in summary["scenarios"]])
    ax.set_ylim(0, 105)
    ax.set_ylabel("固定教学评分（0–100）")
    ax.set_title("相同评分下，遗传算法与简单方法表现如何？", loc="left", pad=24, fontweight="bold")
    ax.grid(axis="y", color="#e9ebef", zorder=0)
    ax.legend(ncols=3, frameon=False, loc="upper center", bbox_to_anchor=(.5, -0.08))
    fig.text(.08, .03, "GA / 随机：20 个固定种子，误差线为样本标准差；贪心：确定性单次结果。", fontsize=15, color="#646c78")
    fig.subplots_adjust(left=.08, right=.96, top=.86, bottom=.19)
    save(fig, "scenario_comparison")

    defaults = [row for row in runs if row["scenario"] == "default" and row["method"] == "ga"]
    best = np.asarray([[entry["best"] for entry in row["history"]] for row in defaults])
    mean = np.asarray([[entry["mean"] for entry in row["history"]] for row in defaults])
    xs = np.arange(best.shape[1])
    fig, ax = plt.subplots(figsize=(16, 9))
    for matrix, color, label in ((best, COLORS["ga"], "每代最佳分（20次均值）"), (mean, COLORS["greedy"], "种群平均分（20次均值）")):
        center, spread = matrix.mean(axis=0), matrix.std(axis=0, ddof=1)
        ax.plot(xs, center, color=color, lw=3, label=label)
        ax.fill_between(xs, center - spread, center + spread, color=color, alpha=.15)
    ax.set_xlabel("进化代数（0 为初始种群）")
    ax.set_ylabel("固定教学评分")
    ax.set_title("默认候选池：分数如何随迭代变化", loc="left", pad=24, fontweight="bold")
    ax.grid(color="#e9ebef")
    ax.legend(frameon=False, loc="lower right")
    fig.text(.09, .035, "阴影为不同种子之间的 ±1 样本标准差，不是置信区间；精英保留保证每次运行最佳分不下降。", fontsize=15, color="#646c78")
    fig.subplots_adjust(left=.09, right=.96, top=.86, bottom=.15)
    save(fig, "default_convergence")

    matrix = np.asarray([row["multipliers"] for row in demo["matchups"]])
    colors = ["#217f75", "#83c8bb", "#c6e5dd", "#f2f3f6", "#f4c29c", "#d74746"]
    cmap = ListedColormap(colors)
    norm = BoundaryNorm([-.1, .1, .3, .7, 1.5, 3, 5], cmap.N)
    fig, ax = plt.subplots(figsize=(16, 9))
    ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(range(6), [member["name"] for member in demo["members"]], fontsize=17)
    ax.set_yticks(range(18), [row["type_name"] for row in demo["matchups"]], fontsize=15)
    ax.xaxis.tick_top()
    ax.tick_params(length=0, pad=10)
    for (row, col), value in np.ndenumerate(matrix):
        ax.text(col, row, f"×{value:g}", ha="center", va="center", fontsize=13,
                color="white" if value == 0 or value >= 4 else "#283242")
    for line in np.arange(.5, 18, 1):
        ax.axhline(line, color="white", lw=2)
    for line in np.arange(.5, 6, 1):
        ax.axvline(line, color="white", lw=3)
    fig.suptitle(f"默认场景 seed=42：推荐队伍的基础防御倍率（得分 {demo['score']:.2f}）", x=.08, ha="left", fontsize=24, fontweight="bold", y=.97)
    handles = [Patch(color=color, label=label) for color, label in zip(colors, ("免疫 ×0", "抵抗 ×0.25", "抵抗 ×0.5", "普通 ×1", "弱点 ×2", "弱点 ×4"))]
    fig.legend(handles=handles, ncols=6, loc="lower center", bbox_to_anchor=(.5, .03), frameon=False, fontsize=14)
    fig.subplots_adjust(left=.09, right=.96, top=.85, bottom=.14)
    save(fig, "demo_defense_matrix")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "pokedex.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "genetic-team")
    parser.add_argument("--plots-only", action="store_true", help="仅由已存在的实验结果重新绘图，不重跑实验。")
    args = parser.parse_args()
    if not args.plots_only:
        run_experiments(args.db.resolve(), args.output.resolve())
    make_figures(args.output.resolve())
    print(f"实验与图表目录：{args.output.resolve()}")


if __name__ == "__main__":
    main()
