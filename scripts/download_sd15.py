"""下载固定版本的 SD1.5 半精度安全权重，支持断点续传并核验官方哈希。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
import requests

MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"
REVISION = "451f4fe16113bff5a5d2269ed5ad43b0592e9a14"
ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = {
    "safety_checker/model.fp16.safetensors": (608018440, "08902f19b1cfebd7c989f152fc0507bef6898c706a91d666509383122324b511"),
    "text_encoder/model.fp16.safetensors": (246144864, "77795e2023adcf39bc29a884661950380bd093cf0750a966d473d1718dc9ef4e"),
    "unet/diffusion_pytorch_model.fp16.safetensors": (1719125304, "c83908253f9a64d08c25fc90874c9c8aef9a329ce1ca5fb909d73b0c83d1ea21"),
    "vae/diffusion_pytorch_model.fp16.safetensors": (167335342, "4fbcf0ebe55a0984f5a5e00d8c4521d52359af7229bb4d81890039d2aa16dd7c"),
}
SMALL = ["model_index.json", "feature_extractor/preprocessor_config.json", "safety_checker/config.json", "scheduler/scheduler_config.json", "text_encoder/config.json", "tokenizer/merges.txt", "tokenizer/special_tokens_map.json", "tokenizer/tokenizer_config.json", "tokenizer/vocab.json", "unet/config.json", "vae/config.json"]


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download_weight(directory: Path, name: str):
    size, digest = WEIGHTS[name]
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        if sha(path) != digest:
            raise ValueError(f"已存在权重校验失败：{name}")
        return
    part = path.with_suffix(path.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        raise ValueError("断点文件大于预期权重")
    url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"
    block = 1024 * 1024
    def fetch(start, end):
        for attempt in range(4):
            try:
                response = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=(20, 90))
                response.raise_for_status()
                if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}" or len(response.content) != end-start+1:
                    raise ValueError("服务器未按请求返回权重范围")
                return response.content
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(attempt + 1)
    with ThreadPoolExecutor(max_workers=32) as pool:
        while offset < size:
            ranges = [(start, min(start+block, size)-1) for start in range(offset, min(offset+block*32,size),block)]
            pending = [pool.submit(fetch, start, end) for start,end in ranges]
            for (_,end), result in zip(ranges,pending):
                with part.open("ab") as handle:
                    handle.write(result.result())
                offset=end+1
            print(f"{name}: {offset}/{size}",flush=True)
    if sha(part) != digest:
        raise ValueError(f"权重 SHA256 不匹配：{name}")
    part.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"data/models/sd15")
    args=parser.parse_args()
    for name in SMALL:
        path=args.output/name
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.is_file():
            response=requests.get(f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}",timeout=30)
            response.raise_for_status()
            path.write_bytes(response.content)
    for name in WEIGHTS:
        download_weight(args.output,name)
    manifest={"model_id":MODEL,"revision":REVISION,"variant":"fp16","files":{name:sha(args.output/name) for name in SMALL+list(WEIGHTS)}}
    (args.output/"source_manifest.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    print(json.dumps({"ready":True,"files":len(manifest["files"]),"revision":REVISION}))


if __name__=="__main__":
    main()
