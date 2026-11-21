"""通过实际HTTP接口验证本机工坊；只生成一张图，不调用聊天模型。"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--use-lora", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    # 本机验收直接连接服务，避免系统代理将回环请求转发到外部。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(path, payload=None):
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        query = urllib.request.Request(args.base_url.rstrip("/") + "/api" + path,
                                       data=body, headers={"Content-Type": "application/json"})
        with opener.open(query, timeout=60) as response:
            return response.read()

    def api(path, payload=None):
        return json.loads(request(path, payload))

    report = {"success": False, "use_lora": args.use_lora, "base_url": args.base_url}
    started = time.monotonic()
    try:
        status = api("/generations/status")
        assert status["base_ready"] and (not args.use_lora or status["lora_ready"]), status
        requirements = {"theme": "fire", "body": "quadruped", "stage": "juvenile"}
        preview = api("/generations/preview", requirements)
        assert preview["evidence"] and preview["raw_prompt"] != preview["enhanced_prompt"]
        prompt = preview["enhanced_prompt"] + " Single creature."
        job = api("/generations", {**requirements, "prompt": prompt, "seed": 42, "use_lora": args.use_lora})
        report["job_id"] = job["id"]
        print(json.dumps({"job_id": job["id"], "status": job["status"]}), flush=True)
        deadline = time.monotonic() + 660
        while job["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(1.5)
            job = api("/generations/" + job["id"])
        assert job["status"] == "succeeded", job.get("error") or job["status"]
        image = request("/generations/" + job["id"] + "/image")
        with Image.open(io.BytesIO(image)) as picture:
            picture.load()
            assert picture.size == (512, 512)
            metadata = json.loads(picture.info["generation"])
        assert metadata["prompt"] == prompt and metadata["seed"] == 42
        assert metadata["model"] == job["model"] and metadata["params"] == job["params"]
        assert job["evidence"] == preview["evidence"] and job["use_lora"] == args.use_lora
        assert bool(job["model"]["lora_sha256"]) == args.use_lora
        history = api("/generations")["items"]
        assert any(row["id"] == job["id"] and row["status"] == "succeeded" for row in history)
        (args.output / "image.png").write_bytes(image)
        (args.output / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        report.update(success=True, image_sha256=hashlib.sha256(image).hexdigest(),
                      image_size=[512, 512], evidence_count=len(job["evidence"]),
                      history_verified=True, png_metadata_verified=True,
                      edited_prompt_verified=True, generation_seconds=job["duration_s"])
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
