"""从冻结的文档表构建可选的本地 E5 + FAISS 索引。

仅显式允许时下载模型。来源：https://huggingface.co/intfloat/multilingual-e5-small
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3
import time


ROOT = Path(__file__).resolve().parents[1]
MODEL_ID = "intfloat/multilingual-e5-small"
MODEL_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
MODEL_WEIGHT_SHA256 = "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
MODEL_WEIGHT_BYTES = 470641600
DOCUMENT_FIELDS = ("id", "pokemon_id", "kind", "title", "text", "url", "language")
QUERY_PREFIX = "query: "
PASSAGE_PREFIX = "passage: "
MAX_LENGTH = 512


def read_documents(database: Path) -> list[dict]:
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, pokemon_id, kind, title, text, url, language FROM documents ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def content_hash(documents: list[dict]) -> str:
    """仅计算原始字段的哈希，不受调用方附加检索得分影响。"""
    records = [{field: doc[field] for field in DOCUMENT_FIELDS} for doc in documents]
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def passage_text(document: dict) -> str:
    return PASSAGE_PREFIX + document["title"] + "\n" + document["text"]


def download_weights(destination: Path) -> None:
    """按固定版本的 8 MiB 范围续传权重，并验证官方 LFS 哈希。"""
    import requests

    final = destination / "model.safetensors"
    temporary = destination / "model.safetensors.part"
    if final.exists():
        with final.open("rb") as handle:
            if hashlib.file_digest(handle, "sha256").hexdigest() == MODEL_WEIGHT_SHA256:
                return
        raise ValueError("Existing model.safetensors does not match the pinned official hash.")
    # 兼容此前 Hugging Face 下载器留下的相同权重断点，只移动本目录下的目标文件。
    old_parts = list((destination / ".cache/huggingface/download").glob(f"*.{MODEL_WEIGHT_SHA256}.incomplete"))
    if not temporary.exists() and len(old_parts) == 1:
        old_parts[0].replace(temporary)
    offset = temporary.stat().st_size if temporary.exists() else 0
    if offset > MODEL_WEIGHT_BYTES:
        raise ValueError("Partial weight file is larger than the pinned model.")
    url = f"https://huggingface.co/{MODEL_ID}/resolve/{MODEL_REVISION}/model.safetensors"
    started = time.monotonic()
    def fetch_range(start: int, end: int) -> bytes:
        for attempt in range(3):
            try:
                with requests.get(url, headers={"Range": f"bytes={start}-{end}"}, timeout=(15, 30), stream=True) as response:
                    expected = f"bytes {start}-{end}/{MODEL_WEIGHT_BYTES}"
                    if response.status_code != 206 or response.headers.get("Content-Range") != expected:
                        raise ValueError("Server did not honor the requested byte range.")
                    chunks = []
                    size = 0
                    for chunk in response.iter_content(64 * 1024):
                        if time.monotonic() - started > 600:
                            raise TimeoutError("Download exceeded ten minutes; the partial file is retained.")
                        size += len(chunk)
                        if size > end - start + 1:
                            raise ValueError("Server returned more data than requested.")
                        chunks.append(chunk)
                    if size != end - start + 1:
                        raise ValueError("Incomplete byte range received.")
                return b"".join(chunks)
            except requests.RequestException:
                if attempt == 2:
                    raise
                time.sleep(attempt + 1)
        raise RuntimeError("Range retry loop ended unexpectedly.")

    # 同时最多获取三段；严格按顺序落盘，失败后仍保留连续、可续传的前缀。
    with ThreadPoolExecutor(max_workers=3) as pool:
        while offset < MODEL_WEIGHT_BYTES:
            ranges = [
                (start, min(start + 8 * 1024 * 1024, MODEL_WEIGHT_BYTES) - 1)
                for start in range(offset, min(offset + 3 * 8 * 1024 * 1024, MODEL_WEIGHT_BYTES), 8 * 1024 * 1024)
            ]
            futures = [pool.submit(fetch_range, start, end) for start, end in ranges]
            for (_, end), future in zip(ranges, futures):
                with temporary.open("ab") as handle:
                    handle.write(future.result())
                offset = end + 1
                print(f"Model weights: {offset}/{MODEL_WEIGHT_BYTES} bytes", flush=True)
    with temporary.open("rb") as handle:
        actual = hashlib.file_digest(handle, "sha256").hexdigest()
    if actual != MODEL_WEIGHT_SHA256:
        raise ValueError("Downloaded model does not match the pinned official SHA256.")
    temporary.replace(final)


def download_model(destination: Path) -> None:
    # 将缓存限制在项目内，采用普通 HTTP 以兼容不支持 Xet 的网络环境。
    os.environ.setdefault("HF_HOME", str(ROOT / "data/hf-cache"))
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from huggingface_hub import snapshot_download

    destination.mkdir(parents=True, exist_ok=True)
    # 只下载一种权重，避免额外获取 PyTorch、ONNX、OpenVINO 的重复模型。
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=str(destination),
        token=False,
        allow_patterns=[
            "config.json", "modules.json",
            "1_Pooling/config.json", "sentence_bert_config.json",
            "sentencepiece.bpe.model", "special_tokens_map.json",
            "tokenizer.json", "tokenizer_config.json",
        ],
    )
    download_weights(destination)
    (destination / "source_revision.json").write_text(
        json.dumps({"model": MODEL_ID, "revision": MODEL_REVISION, "weight_sha256": MODEL_WEIGHT_SHA256}, indent=2),
        encoding="utf-8",
    )


def build_index(database: Path, model_path: Path, output_dir: Path, batch_size: int) -> dict:
    # 本项目只使用 PyTorch，避免意外加载系统环境中的 TensorFlow。
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("USE_FLAX", "0")
    import faiss
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not model_path.is_dir():
        raise FileNotFoundError("Local model is missing; use --allow-download explicitly.")
    documents = read_documents(database)
    if not documents:
        raise ValueError("The documents table is empty; run scripts/build_data.py first.")

    torch.manual_seed(0)
    # 限制 CPU 线程数量，避免小型编码器在笔记本上产生过高的调度开销。
    torch.set_num_threads(min(8, os.cpu_count() or 1))
    encoder = SentenceTransformer(str(model_path), device="cpu", local_files_only=True)
    encoder.max_seq_length = MAX_LENGTH
    passages = [passage_text(document) for document in documents]
    lengths = [len(encoder.tokenizer.encode(text, truncation=False, verbose=False)) for text in passages]
    embeddings = np.asarray(
        encoder.encode(
            passages, batch_size=batch_size, normalize_embeddings=True,
            show_progress_bar=True, convert_to_numpy=True,
        ), dtype="float32",
    )
    if not np.isfinite(embeddings).all():
        raise ValueError("Encoder returned non-finite embeddings.")
    if not np.allclose(np.linalg.norm(embeddings, axis=1), 1.0, atol=1e-4):
        raise ValueError("Expected unit-normalized passage embeddings.")
    index = faiss.IndexFlatIP(embeddings.shape[1])
    index.add(embeddings)
    source_record = model_path / "source_revision.json"
    source = json.loads(source_record.read_text(encoding="utf-8")) if source_record.exists() else {}
    truncated = [doc["id"] for doc, length in zip(documents, lengths) if length > MAX_LENGTH]
    metadata = {
        "schema_version": 1,
        "model": source.get("model", str(model_path.resolve())),
        "revision": source.get("revision", "local-unversioned"),
        "model_path": str(model_path.resolve()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "database": str(database.resolve()),
        "content_sha256": content_hash(documents),
        "doc_ids": [document["id"] for document in documents],
        "document_count": len(documents),
        "dimension": int(embeddings.shape[1]),
        "index_type": "IndexFlatIP",
        "normalized": True,
        "query_prefix": QUERY_PREFIX,
        "passage_prefix": PASSAGE_PREFIX,
        "text_template": "{title}\n{text}",
        "max_seq_length": MAX_LENGTH,
        "truncation": "one vector per document; first 512 tokenizer tokens including prefix",
        "truncated_document_count": len(truncated),
        "truncated_doc_ids": truncated,
        "device": "cpu",
        "batch_size": batch_size,
        "packages": {name: version(name) for name in ("sentence-transformers", "transformers", "torch", "faiss-cpu", "numpy")},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    index_temporary = output_dir / "semantic.faiss.tmp"
    metadata_temporary = output_dir / "semantic_meta.json.tmp"
    faiss.write_index(index, str(index_temporary))
    metadata["index_sha256"] = hashlib.sha256(index_temporary.read_bytes()).hexdigest()
    metadata_temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    index_temporary.replace(output_dir / "semantic.faiss")
    metadata_temporary.replace(output_dir / "semantic_meta.json")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "data/pokedex.sqlite")
    parser.add_argument("--model", type=Path, default=ROOT / "data/models/multilingual-e5-small")
    parser.add_argument("--output", type=Path, default=ROOT / "data")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--allow-download", action="store_true", help="Download the pinned public E5 model into --model (about 480 MB).")
    args = parser.parse_args()
    if args.allow_download:
        download_model(args.model)
    result = build_index(args.db, args.model, args.output, args.batch_size)
    print(json.dumps({key: result[key] for key in ("model", "revision", "document_count", "dimension", "truncated_document_count", "content_sha256")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
