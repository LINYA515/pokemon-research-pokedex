"""校验服务器部署包后导入本机；不接受完整训练断点包。"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.generation import BASE_ID, BASE_REVISION, settings, write_json


def import_bundle(bundle: Path, expected_sha256: str) -> Path:
    with bundle.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != expected_sha256.lower():
        raise ValueError("部署包 SHA256 与服务器记录不一致")
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != {"bundle_manifest.json", "pytorch_lora_weights.safetensors"}:
            raise ValueError("仅接受包含清单和单个 LoRA 权重的部署包")
        manifest = json.loads(archive.read("bundle_manifest.json"))
        if manifest.get("kind") != "deployment_adapter" or manifest.get("model_id") != BASE_ID or manifest.get("revision") != BASE_REVISION:
            raise ValueError("部署包类型或基础模型版本不匹配")
        adapter = archive.read("pytorch_lora_weights.safetensors")
    digest = hashlib.sha256(adapter).hexdigest()
    if digest != manifest["files"].get("pytorch_lora_weights.safetensors"):
        raise ValueError("LoRA 权重 SHA256 不匹配")
    directory = ROOT / "data/models/lora" / digest[:16]
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "pytorch_lora_weights.safetensors"
    destination.write_bytes(adapter)
    write_json(directory / "bundle_manifest.json", manifest)
    config = settings()
    config.update(lora_path=str(destination), lora_sha256=digest, lora_base_revision=BASE_REVISION)
    write_json(ROOT / "config.generation.local.json", config)
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(import_bundle(args.bundle, args.sha256))
