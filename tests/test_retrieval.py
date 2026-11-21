from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3

import pytest

from backend.retrieval import TextRetriever
from scripts.build_embeddings import content_hash, passage_text, read_documents


def documents():
    return [
        {"id": "a", "pokemon_id": 25, "kind": "pokedex", "title": "Pikachu", "text": "An electric mouse with lightning cheeks.", "url": "https://pokeapi.co/api/v2/pokemon/25/", "language": "en"},
        {"id": "b", "pokemon_id": 1, "kind": "pokedex", "title": "Bulbasaur", "text": "A seed grows on its back.", "url": "https://pokeapi.co/api/v2/pokemon/1/", "language": "en"},
    ]


def test_source_hash_changes_when_evidence_changes():
    original = documents()
    changed = deepcopy(original)
    changed[0]["text"] += " Revised."
    assert content_hash(original) != content_hash(changed)
    original[0]["score"] = 0.9
    assert content_hash(original) == content_hash(documents())


def test_read_documents_is_ordered_and_does_not_create_missing_database(tmp_path):
    database = tmp_path / "test.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE documents(id TEXT, pokemon_id INTEGER, kind TEXT, title TEXT, text TEXT, url TEXT, language TEXT)")
        for row in reversed(documents()):
            connection.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", tuple(row.values()))
    assert read_documents(database) == documents()
    missing = tmp_path / "missing.sqlite"
    with pytest.raises(sqlite3.OperationalError):
        read_documents(missing)
    assert not missing.exists()


def test_e5_passage_prefix_and_template():
    assert passage_text(documents()[0]) == "passage: Pikachu\nAn electric mouse with lightning cheeks."


def test_weight_download_resumes_and_checks_official_hash(monkeypatch, tmp_path):
    import hashlib
    import requests
    from scripts import build_embeddings

    payload = b"0123456789"
    monkeypatch.setattr(build_embeddings, "MODEL_WEIGHT_BYTES", len(payload))
    monkeypatch.setattr(build_embeddings, "MODEL_WEIGHT_SHA256", hashlib.sha256(payload).hexdigest())
    (tmp_path / "model.safetensors.part").write_bytes(payload[:3])

    class Response:
        status_code = 206
        headers = {"Content-Range": "bytes 3-9/10"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, chunk_size):
            yield payload[3:]

    def get(url, headers, **kwargs):
        assert headers["Range"] == "bytes=3-9"
        assert build_embeddings.MODEL_REVISION in url
        return Response()

    monkeypatch.setattr(requests, "get", get)
    build_embeddings.download_weights(tmp_path)
    assert (tmp_path / "model.safetensors").read_bytes() == payload
    assert not (tmp_path / "model.safetensors.part").exists()


def test_weight_download_rejects_unverified_existing_model(tmp_path):
    from scripts.build_embeddings import download_weights

    (tmp_path / "model.safetensors").write_bytes(b"not the pinned model")
    with pytest.raises(ValueError, match="pinned official hash"):
        download_weights(tmp_path)


def test_weight_download_rejects_server_ignoring_range(monkeypatch, tmp_path):
    import requests
    from scripts import build_embeddings

    monkeypatch.setattr(build_embeddings, "MODEL_WEIGHT_BYTES", 10)

    class Response:
        status_code = 200
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def iter_content(self, chunk_size):
            raise AssertionError("Must not read a full-model response for a range request")

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="byte range"):
        build_embeddings.download_weights(tmp_path)
    assert not (tmp_path / "model.safetensors").exists()


def test_sparse_fallback_is_explicit_and_retrieves_evidence(monkeypatch):
    monkeypatch.delenv("POKE_EMBEDDING_MODEL_PATH", raising=False)
    retriever = TextRetriever(documents())
    assert "TF-IDF" in retriever.name
    assert retriever.search("electric lightning", 1)[0]["id"] == "a"
    assert retriever.search("seed back", 1)[0]["id"] == "b"
    assert retriever.search("Pikachu", 0) == []
    assert retriever.search("Pikachu", -1) == []
    assert TextRetriever([]).search("Pikachu") == []


def test_invalid_local_model_is_disclosed(monkeypatch, tmp_path):
    monkeypatch.setenv("POKE_EMBEDDING_MODEL_PATH", str(tmp_path / "missing"))
    retriever = TextRetriever(documents())
    assert retriever.warning
    assert "TF-IDF" in retriever.name
    assert retriever.search("Pikachu", 1)[0]["id"] == "a"


def test_stale_index_is_not_silently_used(monkeypatch, tmp_path):
    monkeypatch.delenv("POKE_EMBEDDING_MODEL_PATH", raising=False)
    (tmp_path / "semantic.faiss").write_bytes(b"not a valid index")
    (tmp_path / "semantic_meta.json").write_text(json.dumps({"content_sha256": "stale"}), encoding="utf-8")
    retriever = TextRetriever(documents(), data_dir=tmp_path)
    assert retriever.warning
    assert "TF-IDF" in retriever.name
    assert retriever.search("Pikachu", 1)[0]["id"] == "a"


def test_built_semantic_index_integrity_when_present():
    root = Path(__file__).resolve().parents[1]
    metadata_file = root / "data/semantic_meta.json"
    if not metadata_file.exists():
        pytest.skip("Optional semantic index has not been built.")
    import hashlib
    import numpy as np
    faiss = pytest.importorskip("faiss")

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    rows = read_documents(root / "data/pokedex.sqlite")
    assert metadata["content_sha256"] == content_hash(rows)
    assert metadata["doc_ids"] == [row["id"] for row in rows]
    path = root / "data/semantic.faiss"
    assert metadata["index_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    index = faiss.read_index(str(path))
    assert index.ntotal == len(rows)
    assert index.d == metadata["dimension"] == 384
    assert np.allclose(np.linalg.norm(index.reconstruct_n(0, index.ntotal), axis=1), 1.0, atol=1e-4)
    assert metadata["normalized"] is True
    assert metadata["query_prefix"] == "query: "
    assert metadata["passage_prefix"] == "passage: "
