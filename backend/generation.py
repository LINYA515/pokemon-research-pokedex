"""本机单任务图像生成管理；推理隔离到独立 Python 进程。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from threading import Lock, Thread
import time
import uuid
from functools import lru_cache

from .creation_prompts import preview

ROOT = Path(__file__).resolve().parents[1]
BASE_ID = "stable-diffusion-v1-5/stable-diffusion-v1-5"
BASE_REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"


class GenerationUnavailable(ValueError):
    pass


class GenerationBusy(ValueError):
    pass


@lru_cache(maxsize=2)
def prompt_tokenizer(model_path: str):
    # 直接导入实现，避免语义模型首次加载时并行访问 transformers 懒导出。
    from transformers.models.clip.tokenization_clip import CLIPTokenizer
    return CLIPTokenizer.from_pretrained(str(Path(model_path) / "tokenizer"), local_files_only=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def verified_model_files_present(model: Path, config: dict, probe: dict) -> bool:
    """检查探测时的来源清单与文件仍在；状态查询不重复读取大权重。"""
    manifest_bytes = (model / "source_manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != probe.get("model_manifest_sha256"):
        return False
    manifest = json.loads(manifest_bytes)
    files = manifest.get("files") if isinstance(manifest, dict) else None
    required_weights = {
        "safety_checker/model.fp16.safetensors", "text_encoder/model.fp16.safetensors",
        "unet/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.fp16.safetensors",
    }
    if not isinstance(files, dict) or not required_weights.issubset(files):
        return False
    if manifest.get("model_id") != config["base_model_id"] or manifest.get("revision") != config["base_model_revision"]:
        return False
    return all((model / name).resolve().is_relative_to(model.resolve()) and (model / name).is_file() for name in files)


def settings() -> dict:
    defaults = {
        "python_executable": str(ROOT / ".venv-generation" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
        "base_model_path": str(ROOT / "data/models/sd15"),
        "base_model_id": BASE_ID, "base_model_revision": BASE_REVISION,
        "lora_path": "", "lora_sha256": "", "lora_base_revision": "",
    }
    path = ROOT / "config.generation.local.json"
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("图像模型配置须为 JSON 对象")
        defaults.update({k: v for k, v in loaded.items() if k in defaults})
    return defaults


class GenerationManager:
    def __init__(self, database: Path, directory: Path | None = None):
        self.database = database
        self.directory = directory or ROOT / "data/generations"
        self.lock = Lock()
        self.active = None
        self.process = None
        self.worker = None
        self.closing = False
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in self.directory.glob("*/job.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(job, dict):
                    continue
                if job.get("status") in ("queued", "running"):
                    job.update(status="failed", error="服务在任务完成前重启，请重新生成。", completed_at=now())
                    write_json(path, job)
            except (ValueError, OSError):
                continue

    def status(self) -> dict:
        try:
            config = settings()
            model = Path(config["base_model_path"])
            probe_path = ROOT / "data/generation_runtime.json"
            probe = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.is_file() else {}
            if not isinstance(probe, dict):
                raise ValueError("基础模型探测记录须为 JSON 对象")
            base_ready = bool(
                Path(config["python_executable"]).is_file()
                and (model / "model_index.json").is_file()
                and probe.get("success") is True
                and probe.get("base_model_path") == str(model.resolve())
                and probe.get("base_model_revision") == config["base_model_revision"]
                and probe.get("python_executable") == str(Path(config["python_executable"]).resolve())
                and verified_model_files_present(model, config, probe)
            )
            lora = Path(config["lora_path"]) if config["lora_path"] else None
            lora_ready = bool(base_ready and lora and lora.is_file() and config["lora_sha256"] and config["lora_base_revision"] == config["base_model_revision"])
            if lora_ready:
                with lora.open("rb") as handle:
                    lora_ready = hashlib.file_digest(handle, "sha256").hexdigest() == config["lora_sha256"]
                lora_probe_path = ROOT / "data/generation_lora_runtime.json"
                lora_probe = json.loads(lora_probe_path.read_text(encoding="utf-8")) if lora_probe_path.is_file() else {}
                if not isinstance(lora_probe, dict):
                    raise ValueError("LoRA 探测记录须为 JSON 对象")
                lora_ready = bool(lora_ready and lora_probe.get("success") is True and lora_probe.get("lora_sha256") == config["lora_sha256"] and lora_probe.get("base_model_revision") == config["base_model_revision"] and lora_probe.get("base_model_path") == str(model.resolve()) and lora_probe.get("python_executable") == str(Path(config["python_executable"]).resolve()) and lora_probe.get("model_manifest_sha256") == probe.get("model_manifest_sha256"))
            warning = None if lora_ready else ("基础模型可用；LoRA 尚未导入或完成本机验证，当前可使用基础模型预览。" if base_ready else "本机图像模型尚未完成加载验证；可以先准备提示词，训练权重就绪后再生成。")
            return {"ready": base_ready, "base_ready": base_ready, "lora_ready": lora_ready, "warning": warning, "model_label": "SD1.5 + LoRA" if lora_ready else "SD1.5 基础模型", "busy": self.active is not None}
        except (ValueError, OSError, TypeError):
            return {"ready": False, "base_ready": False, "lora_ready": False, "warning": "图像模型配置无效，请检查本机配置与权重清单。", "model_label": "未就绪", "busy": False}

    def get(self, job_id: str) -> dict:
        try:
            if str(uuid.UUID(job_id)) != job_id:
                raise ValueError
        except ValueError as exc:
            raise KeyError(job_id) from exc
        path = self.directory / job_id / "job.json"
        if not path.is_file():
            raise KeyError(job_id)
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise KeyError(job_id) from exc
        if not isinstance(job, dict) or job.get("id") != job_id:
            raise KeyError(job_id)
        return job

    def history(self) -> list[dict]:
        result = []
        for path in self.directory.glob("*/job.json"):
            try:
                job = self.get(path.parent.name)
                if not isinstance(job, dict) or job.get("id") != path.parent.name or not isinstance(job.get("created_at"), str) or job.get("status") not in ("queued", "running", "succeeded", "failed"):
                    continue
                result.append(job)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(result, key=lambda job: job["created_at"], reverse=True)[:100]

    def submit(self, request: dict) -> dict:
        with self.lock:
            if self.closing:
                raise GenerationUnavailable("生成服务正在退出，请稍后重试。")
            if self.active is not None:
                raise GenerationBusy("已有图片正在生成，请等待当前任务完成。")
            status = self.status()
            if not status["base_ready"] or (request["use_lora"] and not status["lora_ready"]):
                raise GenerationUnavailable(status["warning"] or "模型未就绪。")
            config = settings()
            prompts = preview(self.database, request["theme"], request["body"], request["stage"])
            prompt = request["prompt"].strip() or prompts["enhanced_prompt"]
            tokenizer = prompt_tokenizer(config["base_model_path"])
            tokens = len(tokenizer.encode(prompt, truncation=False))
            if tokens > tokenizer.model_max_length:
                raise ValueError(f"描述包含 {tokens} 个词元，超过 SD1.5 的 {tokenizer.model_max_length} 个词元上限，请缩短描述。")
            job_id = str(uuid.uuid4())
            job = {
                "id": job_id, "status": "queued", "created_at": now(), "completed_at": None,
                **prompts, "prompt": prompt, "prompt_tokens": tokens, "prompt_truncated": False,
                "seed": request["seed"], "use_lora": request["use_lora"],
                "params": {"width": 512, "height": 512, "steps": 30, "guidance_scale": 7.5, "scheduler": "DDIM", "precision": "fp16"},
                "model": {"id": config["base_model_id"], "revision": config["base_model_revision"], "lora_sha256": config["lora_sha256"] if request["use_lora"] else None},
                "image_url": None, "error": None, "duration_s": None,
            }
            write_json(self.directory / job_id / "job.json", job)
            self.active = job_id
            self.worker = Thread(target=self._run, args=(job, config), daemon=True)
            self.worker.start()
            return dict(job)

    def close(self) -> None:
        with self.lock:
            self.closing = True
            process = self.process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if self.worker is not None:
            self.worker.join(timeout=20)

    def _run(self, job: dict, config: dict) -> None:
        directory = self.directory / job["id"]
        started = time.monotonic()
        try:
            job["status"] = "running"
            write_json(directory / "job.json", job)
            worker_request = {**job, "base_model_path": config["base_model_path"], "lora_path": config["lora_path"] if job["use_lora"] else "", "output": str(directory / "image.png"), "gpu_lock_path": str(self.directory / ".gpu.lock")}
            write_json(directory / "request.local.json", worker_request)
            environment = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
            environment.update(HF_HUB_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1", PYTHONIOENCODING="utf-8", USE_TF="0", USE_FLAX="0")
            with (directory / "worker.log").open("w", encoding="utf-8") as log:
                with self.lock:
                    if self.closing:
                        raise RuntimeError("服务正在退出")
                    self.process = subprocess.Popen([config["python_executable"], str(ROOT / "scripts/generate_image.py"), "--request", str(directory / "request.local.json")], stdout=log, stderr=log, env=environment)
                    process = self.process
                try:
                    process.wait(timeout=600)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                    raise
            if process.returncode != 0 or not (directory / "image.png").is_file():
                raise RuntimeError("推理进程未生成有效图片，请检查本机推理环境和任务日志。")
            from PIL import Image
            with Image.open(directory / "image.png") as picture:
                picture.verify()
            job.update(status="succeeded", image_url=f"/api/generations/{job['id']}/image")
        except subprocess.TimeoutExpired:
            job.update(status="failed", error="生成超过10分钟，已结束推理进程。")
        except Exception:
            job.update(status="failed", error="本机生成失败，请检查推理环境、显存及任务日志后重试。")
        finally:
            job.update(completed_at=now(), duration_s=round(time.monotonic() - started, 3))
            try:
                write_json(directory / "job.json", job)
            finally:
                with self.lock:
                    self.active = None
                    self.process = None
