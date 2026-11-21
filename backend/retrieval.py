from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer


class TextRetriever:
    """默认采用字符 TF-IDF；显式提供本地模型时才启用稠密检索。"""

    def __init__(self, documents: list[dict], data_dir: Path | None = None):
        self.documents = documents
        self.warning = None
        self.encoder = None
        self.faiss = None
        self.vectorizer = None
        self.matrix = None
        self.name = "TF-IDF 字符 n-gram（稀疏词面检索）"
        if not documents:
            return
        texts = [f"{d['title']}\n{d['text']}" for d in documents]
        model_path = os.environ.get("POKE_EMBEDDING_MODEL_PATH", "")
        index_path = data_dir / "semantic.faiss" if data_dir else None
        metadata_path = data_dir / "semantic_meta.json" if data_dir else None
        metadata = None
        if metadata_path and metadata_path.is_file() and index_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                fields = ("id", "pokemon_id", "kind", "title", "text", "url", "language")
                payload = json.dumps([{key: d[key] for key in fields} for d in documents], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if metadata["content_sha256"] != hashlib.sha256(payload.encode("utf-8")).hexdigest():
                    raise ValueError("文档快照不匹配")
                if metadata["doc_ids"] != [d["id"] for d in documents]:
                    raise ValueError("索引文档顺序不匹配")
                if metadata["index_sha256"] != hashlib.sha256(index_path.read_bytes()).hexdigest():
                    raise ValueError("索引校验失败")
                if metadata["query_prefix"] != "query: " or not metadata["normalized"]:
                    raise ValueError("不支持的索引归一化或前缀")
                cached_model = Path(metadata["model_path"])
                if model_path and Path(model_path).resolve() != cached_model.resolve():
                    raise ValueError("模型路径与索引记录不一致")
                model_path = str(cached_model)
            except (KeyError, ValueError, OSError):
                metadata = None
                self.warning = "离线语义索引与当前文档或模型不匹配，未加载旧索引。"
        if model_path:
            try:
                if not Path(model_path).is_dir():
                    raise ValueError("模型路径不是本地目录")
                # 本项目仅使用 PyTorch，避免误加载系统中的 TensorFlow/Keras。
                os.environ.setdefault("USE_TF", "0")
                os.environ.setdefault("USE_FLAX", "0")
                from sentence_transformers import SentenceTransformer
                import torch

                torch.set_num_threads(min(8, os.cpu_count() or 1))
                self.encoder = SentenceTransformer(model_path, device="cpu", local_files_only=True)
                self.encoder.max_seq_length = 512
                if metadata is not None:
                    import faiss

                    revision_path = Path(model_path) / "source_revision.json"
                    if revision_path.is_file():
                        revision = json.loads(revision_path.read_text(encoding="utf-8"))
                        if any(revision.get(key) != metadata.get(key) for key in ("model", "revision")):
                            raise ValueError("模型版本与离线索引不匹配")
                    self.faiss = faiss.read_index(str(index_path))
                    if self.faiss.ntotal != len(documents) or self.faiss.d != metadata["dimension"]:
                        raise ValueError("索引维度或记录数不匹配")
                    if self.encoder.get_sentence_embedding_dimension() != self.faiss.d:
                        raise ValueError("模型输出维度与索引不一致")
                    self.name = f"{metadata.get('model', '本地E5兼容模型')} 稠密嵌入 + FAISS IndexFlatIP（已校验快照）"
                    if metadata.get("truncated_document_count"):
                        self.warning = f"语义索引中有{metadata['truncated_document_count']}篇资料按512 token截断；原文仍可查看。"
                    return
                self.matrix = np.asarray(
                    self.encoder.encode(
                        ["passage: " + t for t in texts],
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    ),
                    dtype="float32",
                )
                self.name = "本地 E5 兼容稠密嵌入 + NumPy 精确内积"
                try:
                    import faiss

                    self.faiss = faiss.IndexFlatIP(self.matrix.shape[1])
                    self.faiss.add(self.matrix)
                    self.name = "本地 E5 兼容稠密嵌入 + FAISS IndexFlatIP"
                except ImportError:
                    pass
                return
            except Exception as exc:
                self.encoder = None
                self.faiss = None
                self.warning = f"本地稠密索引未启用（{type(exc).__name__}），已回退 TF-IDF。"
        self.vectorizer = TfidfVectorizer(
            analyzer="char", ngram_range=(1, 3), max_features=100000,
            sublinear_tf=True, dtype=np.float32,
        )
        self.matrix = self.vectorizer.fit_transform(texts)

    def search(self, question: str, k: int = 6) -> list[dict]:
        if k <= 0 or (self.matrix is None and self.faiss is None):
            return []
        k = min(k, len(self.documents))
        if self.encoder is not None:
            vector = np.asarray(
                self.encoder.encode(["query: " + question], normalize_embeddings=True),
                dtype="float32",
            )
            if self.faiss is not None:
                scores, ids = self.faiss.search(vector, k)
                pairs = zip(ids[0], scores[0])
            else:
                scores = (self.matrix @ vector.T).ravel()
                ids = np.argsort(-scores, kind="stable")[:k]
                pairs = ((i, scores[i]) for i in ids)
        else:
            vector = self.vectorizer.transform([question])
            scores = (self.matrix @ vector.T).toarray().ravel()
            ids = np.argsort(-scores, kind="stable")[:k]
            pairs = ((i, scores[i]) for i in ids)
        return [
            {**self.documents[int(i)], "score": round(float(score), 4)}
            for i, score in pairs if score > 0
        ]
