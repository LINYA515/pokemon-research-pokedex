"""离线 SD1.5 单图推理入口；不包含训练或模型自动下载。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from contextlib import contextmanager

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_FLAX", "0")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")


@contextmanager
def gpu_lock(path):
    """锁由推理子进程持有，服务异常退出也不会允许第二次并行推理。"""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as handle:
        if lock_path.stat().st_size == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def generate(request: dict) -> dict:
    import torch
    from diffusers import DDIMScheduler, StableDiffusionPipeline
    from PIL.PngImagePlugin import PngInfo

    if not torch.cuda.is_available():
        raise RuntimeError("未检测到可用 CUDA；不会自动转为长时间 CPU 推理。")
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    started = time.monotonic()
    pipe = StableDiffusionPipeline.from_pretrained(request["base_model_path"], torch_dtype=torch.float16, variant="fp16", local_files_only=True)
    pipe.scheduler = DDIMScheduler.from_config(pipe.scheduler.config)
    tokens = len(pipe.tokenizer.encode(request["prompt"], truncation=False))
    if tokens > pipe.tokenizer.model_max_length:
        raise ValueError("提示词超过模型词元上限，请缩短后重试。")
    if request.get("lora_path"):
        lora = Path(request["lora_path"])
        with lora.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() != request["model"]["lora_sha256"]:
                raise ValueError("LoRA 权重哈希发生变化，请重新导入。")
        pipe.load_lora_weights(str(lora.parent), weight_name=lora.name, local_files_only=True)
    # SDPA 与模型 CPU offload 配合；不再叠加会替换 SDPA 的 attention slicing。
    pipe.enable_model_cpu_offload()
    generator = torch.Generator(device="cpu").manual_seed(request["seed"])
    params = request["params"]
    result = pipe(request["prompt"], generator=generator, width=params["width"], height=params["height"], num_inference_steps=params["steps"], guidance_scale=params["guidance_scale"])
    if result.nsfw_content_detected and any(result.nsfw_content_detected):
        raise RuntimeError("生成结果未通过模型图像检查，请修改描述后重试。")
    output = Path(request["output"])
    output.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngInfo()
    metadata.add_text("generation", json.dumps({k: request[k] for k in ("prompt", "seed", "params", "model")}, ensure_ascii=False))
    result.images[0].save(output, pnginfo=metadata)
    return {"success": True, "duration_s": round(time.monotonic() - started, 3), "torch": torch.__version__, "cuda": torch.version.cuda, "gpu": torch.cuda.get_device_name(0), "peak_memory_bytes": torch.cuda.max_memory_allocated(), "prompt_tokens": tokens, "prompt_truncated": False, "lora_sha256": request["model"].get("lora_sha256")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--probe-output", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    with gpu_lock(request.get("gpu_lock_path", Path(request["output"]).parents[1] / ".gpu.lock")):
        result = generate(request)
    if args.probe_output:
        result.update(base_model_path=str(Path(request["base_model_path"]).resolve()), base_model_revision=request["model"]["revision"], python_executable=str(Path(sys.executable).resolve()))
        args.probe_output.parent.mkdir(parents=True, exist_ok=True)
        args.probe_output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
