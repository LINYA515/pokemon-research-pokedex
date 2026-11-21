"""通过真实单图生成验证本机基础模型或导入 LoRA；不启动训练。"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.generation import settings, write_json, now
from backend.creation_prompts import preview


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-lora", action="store_true")
    args = parser.parse_args()
    probe = ROOT / "data" / ("generation_lora_runtime.json" if args.use_lora else "generation_runtime.json")
    # 在配置与文件校验之前撤销旧成功记录，失败重测不能沿用旧就绪状态。
    write_json(probe, {"success": False, "status": "checking", "checked_at": now()})
    try:
        config = settings()
        model = Path(config["base_model_path"])
        manifest_bytes = (model / "source_manifest.json").read_bytes()
        manifest = json.loads(manifest_bytes)
        if manifest["model_id"] != config["base_model_id"] or manifest["revision"] != config["base_model_revision"]:
            raise ValueError("基础模型清单与配置不一致")
        for name, expected in manifest["files"].items():
            path = (model / name).resolve()
            if not path.is_relative_to(model.resolve()):
                raise ValueError("模型清单含越界路径")
            with path.open("rb") as handle:
                if hashlib.file_digest(handle, "sha256").hexdigest() != expected:
                    raise ValueError("模型文件校验失败：" + name)
        if args.use_lora and (not config["lora_path"] or config["lora_base_revision"] != config["base_model_revision"]):
            raise ValueError("请先导入与基础模型版本一致的 LoRA 部署包")
        directory = ROOT / "data/generations" / ("lora-probe" if args.use_lora else "base-probe")
        request = {"base_model_path": str(model), "lora_path": config["lora_path"] if args.use_lora else "", "prompt": preview(ROOT / "data/pokedex.sqlite", "fire", "quadruped", "juvenile")["enhanced_prompt"], "seed": 42, "params": {"width": 512,"height": 512,"steps": 30,"guidance_scale": 7.5}, "model": {"id": config["base_model_id"], "revision": config["base_model_revision"], "lora_sha256": config["lora_sha256"] if args.use_lora else None}, "output": str(directory / "image.png")}
        write_json(directory / "request.local.json", request)
        environment = {k: v for k,v in os.environ.items() if not any(word in k.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
        environment.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", USE_TF="0", USE_FLAX="0", PYTHONUTF8="1")
        subprocess.run([config["python_executable"], str(ROOT / "scripts/generate_image.py"), "--request", str(directory / "request.local.json"), "--probe-output", str(probe)], env=environment, check=True, timeout=600)
        result = json.loads(probe.read_text(encoding="utf-8"))
        if result.get("success") is not True:
            raise RuntimeError("推理进程未返回成功探测记录")
        result.update(model_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(), checked_at=now())
        write_json(probe, result)
    except BaseException:
        write_json(probe, {"success": False, "status": "failed", "checked_at": now()})
        raise


if __name__ == "__main__":
    main()
