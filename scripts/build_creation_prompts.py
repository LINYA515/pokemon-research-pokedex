"""固定24条最终生成需求；只导出提示与真实来源，不生成图片。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.creation_prompts import THEMES, BODIES, STAGES, preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "outputs" / "generation-prompts.json")
    args = parser.parse_args()
    rows = []
    for theme in THEMES:
        for body in BODIES:
            for stage in STAGES:
                result = preview(ROOT / "data/pokedex.sqlite", theme, body, stage)
                rows.append({"requirement_id": f"{theme}-{body}-{stage}", "theme": theme, "body": body, "stage": stage, **result})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"requirements": len(rows), "planned_images": len(rows)*3*4, "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
