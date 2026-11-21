"""记录本机 CUDA 推理环境；矩阵检查不等于真实模型生成验收。"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import sys
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import numpy
    import torch
    import diffusers
    import peft
    import transformers
    available = torch.cuda.is_available()
    if not available:
        raise RuntimeError("CUDA 不可用")
    values = torch.ones((4,4), device="cuda")
    result = float((values@values).sum())
    if result != 64:
        raise RuntimeError("CUDA 矩阵检查未通过")
    data = {"checked_at": datetime.now(timezone.utc).isoformat(), "cuda_tensor_verified": True, "model_inference_verified": False, "matrix_sum": result, "gpu": torch.cuda.get_device_name(0), "cuda_build": torch.version.cuda, "python": sys.version.split()[0], "executable": sys.executable, "base_prefix": sys.base_prefix, "numpy_path": numpy.__file__, "torch_path": torch.__file__, "packages": {name: importlib.metadata.version(name) for name in ("torch", "numpy", "diffusers", "transformers", "accelerate", "peft", "safetensors", "huggingface-hub")}, "environment_note": "记录当前Python与CUDA环境；矩阵检查不能替代实际模型生成验证。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
