"""创作接口的真实证据、状态和本机任务边界；不把替身推理视作模型验证。"""
import json
import hashlib
from pathlib import Path
import uuid

from fastapi.testclient import TestClient
import pytest

from backend import generation, main
from backend.creation_prompts import preview

DB = Path(__file__).resolve().parents[1] / "data/pokedex.sqlite"


@pytest.fixture
def client(tmp_path, monkeypatch):
    manager = generation.GenerationManager(DB, tmp_path / "jobs")
    monkeypatch.setattr(main, "_generations", manager)
    monkeypatch.setattr(manager, "status", lambda: {"ready": False, "base_ready": False, "lora_ready": False, "warning": "模型未就绪", "model_label": "未就绪"})
    with TestClient(main.app) as value:
        yield value


def test_preview_retains_real_sources_without_generation(client):
    response = client.post("/api/generations/preview", json={"theme": "fire", "body": "biped", "stage": "juvenile"})
    assert response.status_code == 200
    data = response.json()
    assert "bipedal" in data["raw_prompt"] and "juvenile" in data["raw_prompt"]
    assert data["evidence"] and all(row["source"].startswith("https://") and row["snapshot"] for row in data["evidence"])
    assert data["raw_prompt"] != data["enhanced_prompt"]
    assert client.get("/api/generations").json() == {"items": []}


def test_all_24_prompts_are_distinct_and_reproducible():
    from backend.creation_prompts import THEMES, BODIES, STAGES
    prompts = [preview(DB, theme, body, stage) for theme in THEMES for body in BODIES for stage in STAGES]
    assert len({p["raw_prompt"] for p in prompts}) == 24
    assert all(p["evidence"] for p in prompts)
    assert prompts[0] == preview(DB, "fire", "biped", "juvenile")


@pytest.mark.parametrize("payload", [{"theme": "unknown"}, {"seed": -1}, {"seed": 4294967296}, {"seed": True}, {"seed": 2.5}, {"prompt": "x"*2001}])
def test_invalid_generation_request_is_422(client, payload):
    assert client.post("/api/generations", json=payload).status_code == 422


def test_missing_model_is_503_without_creating_job(client):
    assert client.post("/api/generations", json={"use_lora": False}).status_code == 503
    assert client.get("/api/generations").json()["items"] == []


def test_unknown_record_is_404(client):
    assert client.get("/api/generations/not-a-uuid").status_code == 404
    assert client.get(f"/api/generations/{uuid.uuid4()}/image").status_code == 404


def test_missing_image_file_returns_useful_404(client):
    job_id = str(uuid.uuid4())
    generation.write_json(main._generations.directory / job_id / "job.json", {
        "id": job_id, "status": "succeeded", "created_at": "2026-11-20",
    })
    response = client.get(f"/api/generations/{job_id}/image")
    assert response.status_code == 404
    assert "缺失" in response.json()["detail"]


def test_corrupted_record_is_404_and_does_not_break_history(client):
    job_id = str(uuid.uuid4())
    path = main._generations.directory / job_id / "job.json"
    path.parent.mkdir()
    path.write_text('{"id":', encoding="utf-8")
    assert client.get(f"/api/generations/{job_id}").status_code == 404
    assert client.get("/api/generations").json()["items"] == []


def test_busy_generation_is_rejected(tmp_path, monkeypatch):
    manager = generation.GenerationManager(DB, tmp_path)
    manager.active = "existing"
    with pytest.raises(generation.GenerationBusy):
        manager.submit({"use_lora": False})


def test_restart_does_not_silently_rerun_incomplete_job(tmp_path):
    job_id = str(uuid.uuid4())
    generation.write_json(tmp_path / job_id / "job.json", {"id": job_id, "status": "running", "created_at": "2026-01-01"})
    manager = generation.GenerationManager(DB, tmp_path)
    assert manager.get(job_id)["status"] == "failed"
    assert manager.active is None


def test_failed_worker_releases_single_task_slot(tmp_path, monkeypatch):
    manager = generation.GenerationManager(DB, tmp_path)
    job = {"id": str(uuid.uuid4()), "status": "queued", "use_lora": False}
    generation.write_json(tmp_path / job["id"] / "job.json", job)
    manager.active = job["id"]
    monkeypatch.setattr(generation.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("worker unavailable")))
    manager._run(job, {"base_model_path": "missing", "python_executable": "missing", "lora_path": ""})
    assert manager.get(job["id"])["status"] == "failed"
    assert manager.active is None


def test_file_presence_without_real_probe_is_not_ready(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, "ROOT", tmp_path)
    python = tmp_path / "python.exe"
    python.touch()
    model = tmp_path / "model"
    model.mkdir()
    (model / "model_index.json").write_text("{}")
    monkeypatch.setattr(generation, "settings", lambda: {"python_executable": str(python), "base_model_path": str(model), "base_model_revision": "rev", "lora_path": ""})
    assert generation.GenerationManager(DB, tmp_path / "jobs").status()["base_ready"] is False


def test_malformed_history_record_does_not_hide_other_jobs(tmp_path):
    broken_id = str(uuid.uuid4())
    good_id = str(uuid.uuid4())
    generation.write_json(tmp_path / broken_id / "job.json", {"status": "failed"})
    generation.write_json(tmp_path / good_id / "job.json", {"id": good_id, "status": "failed", "created_at": "2026-01-01"})
    manager = generation.GenerationManager(DB, tmp_path)
    assert [job["id"] for job in manager.history()] == [good_id]


def test_overlong_token_prompt_does_not_create_job(tmp_path, monkeypatch):
    manager = generation.GenerationManager(DB, tmp_path)
    monkeypatch.setattr(manager, "status", lambda: {"base_ready": True, "lora_ready": False})
    class Tokenizer:
        model_max_length = 77
        def encode(self, prompt, **kwargs):
            return list(range(80))
    monkeypatch.setattr(generation, "prompt_tokenizer", lambda path: Tokenizer())
    with pytest.raises(ValueError, match="80"):
        manager.submit({"theme":"fire","body":"biped","stage":"adult","use_lora":False,"seed":42,"prompt":"long"})
    assert manager.history() == [] and manager.active is None


def test_worker_gpu_lock_is_exclusive(tmp_path):
    from scripts.generate_image import gpu_lock
    with gpu_lock(tmp_path / "gpu.lock"):
        with pytest.raises(OSError):
            with gpu_lock(tmp_path / "gpu.lock"):
                pass


def test_shutdown_terminates_active_worker(tmp_path):
    manager = generation.GenerationManager(DB, tmp_path)
    class Process:
        terminated = False
        def poll(self):
            return None
        def terminate(self):
            self.terminated = True
        def wait(self, timeout):
            return 0
    process = Process()
    manager.process = process
    manager.close()
    assert process.terminated and manager.closing


def test_adapter_hash_alone_does_not_claim_lora_ready(tmp_path, monkeypatch):
    manager, config, model = ready_status_fixture(tmp_path, monkeypatch)
    lora = tmp_path / "adapter.safetensors"
    lora.write_bytes(b"not-a-trained-model")
    config.update(lora_path=str(lora), lora_sha256=hashlib.sha256(lora.read_bytes()).hexdigest(), lora_base_revision="rev")
    status = manager.status()
    assert status["base_ready"] and not status["lora_ready"]


def ready_status_fixture(tmp_path, monkeypatch):
    """只用于状态逻辑的微型文件替身，不代表模型推理已验证。"""
    monkeypatch.setattr(generation, "ROOT", tmp_path)
    python = tmp_path / "python.exe"
    python.touch()
    model = tmp_path / "model"
    names = ["model_index.json", "safety_checker/model.fp16.safetensors", "text_encoder/model.fp16.safetensors", "unet/diffusion_pytorch_model.fp16.safetensors", "vae/diffusion_pytorch_model.fp16.safetensors"]
    for name in names:
        path = model / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test fixture")
    manifest_path = model / "source_manifest.json"
    generation.write_json(manifest_path, {"model_id": "test-model", "revision": "rev", "files": {name: hashlib.sha256((model / name).read_bytes()).hexdigest() for name in names}})
    config = {"python_executable": str(python), "base_model_path": str(model), "base_model_id": "test-model", "base_model_revision": "rev", "lora_path": "", "lora_sha256": "", "lora_base_revision": ""}
    monkeypatch.setattr(generation, "settings", lambda: config)
    generation.write_json(tmp_path / "data/generation_runtime.json", {"success": True, "base_model_path": str(model.resolve()), "base_model_revision": "rev", "python_executable": str(python.resolve()), "model_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()})
    return generation.GenerationManager(DB, tmp_path / "jobs"), config, model


def test_ready_probe_does_not_survive_missing_model_file(tmp_path, monkeypatch):
    manager, _, model = ready_status_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(generation.hashlib, "file_digest", lambda *args: (_ for _ in ()).throw(AssertionError("状态查询不应重算大权重哈希")))
    assert manager.status()["base_ready"]
    (model / "unet/diffusion_pytorch_model.fp16.safetensors").unlink()
    assert not manager.status()["base_ready"]


def test_ready_probe_is_bound_to_verified_manifest(tmp_path, monkeypatch):
    manager, _, model = ready_status_fixture(tmp_path, monkeypatch)
    assert manager.status()["base_ready"]
    path = model / "source_manifest.json"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert not manager.status()["base_ready"]


@pytest.mark.parametrize("bad_record", [[], {"status": "succeeded", "created_at": "2026-01-01"}])
def test_non_object_or_missing_id_history_is_ignored(tmp_path, bad_record):
    bad_id = str(uuid.uuid4())
    generation.write_json(tmp_path / bad_id / "job.json", bad_record)
    manager = generation.GenerationManager(DB, tmp_path)
    assert manager.history() == []
    with pytest.raises(KeyError):
        manager.get(bad_id)


@pytest.mark.parametrize("use_lora", [False, True])
def test_probe_revokes_old_success_before_manifest_validation(tmp_path, monkeypatch, use_lora):
    from scripts import probe_generation
    monkeypatch.setattr(probe_generation, "ROOT", tmp_path)
    monkeypatch.setattr(probe_generation, "settings", lambda: {"base_model_path": str(tmp_path / "missing-model")})
    monkeypatch.setattr(probe_generation.sys, "argv", ["probe_generation.py"] + (["--use-lora"] if use_lora else []))
    probe = tmp_path / "data" / ("generation_lora_runtime.json" if use_lora else "generation_runtime.json")
    other = tmp_path / "data" / ("generation_runtime.json" if use_lora else "generation_lora_runtime.json")
    generation.write_json(probe, {"success": True})
    generation.write_json(other, {"success": True})
    with pytest.raises(FileNotFoundError):
        probe_generation.main()
    assert json.loads(probe.read_text())["success"] is False
    assert json.loads(other.read_text())["success"] is True


def test_failed_probe_worker_does_not_restore_old_success(tmp_path, monkeypatch):
    from scripts import probe_generation
    _, config, _ = ready_status_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(probe_generation, "ROOT", tmp_path)
    monkeypatch.setattr(probe_generation, "settings", lambda: config)
    monkeypatch.setattr(probe_generation, "preview", lambda *args: {"enhanced_prompt": "fixture"})
    monkeypatch.setattr(probe_generation.sys, "argv", ["probe_generation.py"])
    def fail(*args, **kwargs):
        assert not json.loads((tmp_path / "data/generation_runtime.json").read_text())["success"]
        raise probe_generation.subprocess.CalledProcessError(1, "test worker")
    monkeypatch.setattr(probe_generation.subprocess, "run", fail)
    with pytest.raises(probe_generation.subprocess.CalledProcessError):
        probe_generation.main()
    assert json.loads((tmp_path / "data/generation_runtime.json").read_text())["success"] is False


def test_successful_probe_records_verified_manifest_hash(tmp_path, monkeypatch):
    from scripts import probe_generation
    _, config, model = ready_status_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(probe_generation, "ROOT", tmp_path)
    monkeypatch.setattr(probe_generation, "settings", lambda: config)
    monkeypatch.setattr(probe_generation, "preview", lambda *args: {"enhanced_prompt": "fixture"})
    monkeypatch.setattr(probe_generation.sys, "argv", ["probe_generation.py"])
    probe = tmp_path / "data/generation_runtime.json"
    def succeed(*args, **kwargs):
        generation.write_json(probe, {"success": True})
    monkeypatch.setattr(probe_generation.subprocess, "run", succeed)
    probe_generation.main()
    assert json.loads(probe.read_text())["model_manifest_sha256"] == hashlib.sha256((model / "source_manifest.json").read_bytes()).hexdigest()
