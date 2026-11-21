"""根据冻结图鉴生成可审计的创作提示；创作设定不作为物种事实。"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

THEMES = {
    "fire": ("火", "flame accents and warm orange colors", 10),
    "water": ("水", "aquatic details and cool blue colors", 11),
    "grass": ("草", "leaf details and natural green colors", 12),
    "electric": ("电", "lightning accents and bright yellow colors", 13),
}
BODIES = {"biped": ("双足", "a bipedal body"), "quadruped": ("四足", "a quadrupedal body"), "serpentine": ("蛇形", "a serpentine body")}
STAGES = {"juvenile": ("幼年", "a cute juvenile creature"), "adult": ("成年", "an adult creature")}


def preview(database: Path, theme: str, body: str, stage: str) -> dict:
    if theme not in THEMES or body not in BODIES or stage not in STAGES:
        raise ValueError("请选择已支持的主题、身体形态和成长阶段。")
    label, appearance, type_id = THEMES[theme]
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT d.* FROM documents d JOIN pokemon_type pt ON pt.pokemon_id=d.pokemon_id "
            "WHERE pt.type_id=? AND d.kind='description' ORDER BY d.pokemon_id LIMIT 3", (type_id,),
        ).fetchall()
        # 兼容已有快照的文档类别命名，优先使用完整图鉴描述。
        if not rows:
            rows = db.execute(
                "SELECT d.* FROM documents d JOIN pokemon_type pt ON pt.pokemon_id=d.pokemon_id "
                "WHERE pt.type_id=? AND d.id LIKE 'description:%' ORDER BY d.pokemon_id LIMIT 3", (type_id,),
            ).fetchall()
        commit_row = db.execute("SELECT value FROM metadata WHERE key='commit'").fetchone()
    commit = json.loads(commit_row[0]) if commit_row and commit_row[0].startswith('"') else (commit_row[0] if commit_row else None)
    evidence = [{"id": row["id"], "title": row["title"], "text": row["text"], "source": row["url"], "language": row["language"], "snapshot": commit} for row in rows]
    raw = f"Original {theme}-themed monster, {STAGES[stage][1]}, {BODIES[body][1]}, {appearance}; full-body line illustration, plain background."
    # 抽取描述中的视觉线索；英文转写是明确标注的创作规则，不冒充来源原句。
    visual_rules = [
        (("火焰", "燃烧", "火花", "flame", "burn", "fire"), "small flame-shaped details"),
        (("尾巴", "tail"), "a clearly visible expressive tail"),
        (("甲壳", "龟壳", "shell"), "a rounded protective shell motif"),
        (("种子", "seed"), "a seed-shaped ornament"),
        (("花", "flower", "blossom"), "a flower-shaped ornament"),
        (("叶", "leaf", "leaves"), "leaf-shaped details"),
        (("电", "electric", "lightning"), "small lightning-shaped details"),
        (("水", "water", "swim"), "smooth aquatic contours"),
    ]
    joined = " ".join(e["text"].lower() for e in evidence)
    cues = [cue for words, cue in visual_rules if any(word in joined for word in words)][:3]
    enhanced = raw
    if cues:
        enhanced += " Reference-inspired motifs: " + ", ".join(cues) + "."
    enhanced += " Distinct character silhouette."
    return {
        "raw_prompt": raw, "enhanced_prompt": enhanced, "evidence": evidence,
        "requirements": {"theme": theme, "body": body, "stage": stage, "label": f"{label}主题 · {BODIES[body][0]} · {STAGES[stage][0]}"},
        "note": "来源是图鉴事实；视觉线索转写、身体形态与成长阶段是创作设定，不代表官方物种或属性认证。",
        "enhancement_method": "type-filtered descriptions + explicit visual cue rules v1",
    }
