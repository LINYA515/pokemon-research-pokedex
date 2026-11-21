"""图片缩略、受限下载和本地缓存的回归测试，不访问外网。"""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Event, Lock
from time import sleep

from fastapi.testclient import TestClient
import httpx
from PIL import Image
import pytest

from backend import artwork, main


def png_bytes(size=(475, 475)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    image.paste((220, 40, 30, 255), (10, 10, min(50, size[0]), min(50, size[1])))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def cache(tmp_path):
    return artwork.ArtworkCache(tmp_path / "artwork")


@pytest.fixture
def client(cache, monkeypatch):
    monkeypatch.setattr(main, "artwork_cache", cache)
    with TestClient(main.app) as test_client:
        yield test_client


def test_one_download_builds_transparent_variants_and_persists(cache, monkeypatch):
    calls = []
    monkeypatch.setattr(cache, "_download", lambda pokemon_id: calls.append(pokemon_id) or png_bytes())
    small = cache.get(25, 256)
    large = cache.get(25, 512)
    assert calls == [25]
    for content, size in ((small, 256), (large, 475)):
        with Image.open(BytesIO(content)) as image:
            assert image.format == "WEBP" and image.size == (size, size)
            assert image.getpixel((0, 0))[3] == 0
    fresh = artwork.ArtworkCache(cache.directory.parent)
    monkeypatch.setattr(fresh, "_download", lambda _: pytest.fail("本地缓存不应访问来源"))
    assert fresh.get(25, 256) == small
    assert fresh.get(25, 512) == large


def test_small_source_is_not_upscaled(cache, monkeypatch):
    monkeypatch.setattr(cache, "_download", lambda _: png_bytes((80, 100)))
    for size in (256, 512):
        with Image.open(BytesIO(cache.get(1, size))) as image:
            assert image.size == (80, 100)


def test_same_id_concurrent_requests_share_download(cache, monkeypatch):
    calls = []
    def download(pokemon_id):
        calls.append(pokemon_id)
        sleep(0.05)
        return png_bytes()
    monkeypatch.setattr(cache, "_download", download)
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda size: cache.get(1, size), [256, 512] * 4))
    assert calls == [1]
    assert all(results[index] == results[index % 2] for index in range(len(results)))


def test_download_concurrency_is_bounded_and_cached_hit_does_not_wait(cache, monkeypatch):
    monkeypatch.setattr(cache, "_download", lambda _: png_bytes())
    cached = cache.get(25, 256)
    guard = Lock()
    started = Event()
    release = Event()
    active = 0
    peak = 0
    def download(_):
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(active, peak)
            if active == 4:
                started.set()
        assert release.wait(2)
        with guard:
            active -= 1
        return png_bytes()
    monkeypatch.setattr(cache, "_download", download)
    with ThreadPoolExecutor(max_workers=8) as executor:
        pending = [executor.submit(cache.get, pokemon_id, 256) for pokemon_id in range(1, 9)]
        try:
            assert started.wait(2)
            assert cache.get(25, 256) == cached
        finally:
            release.set()
        assert all(future.result() for future in pending)
    assert peak == 4


@pytest.mark.parametrize("source", [b"not an image", b"<html>unavailable</html>"])
def test_malformed_image_is_not_cached_and_failure_is_throttled(cache, monkeypatch, source):
    calls = []
    monkeypatch.setattr(cache, "_download", lambda pokemon_id: calls.append(pokemon_id) or source)
    for _ in range(2):
        with pytest.raises(artwork.ArtworkUnavailable):
            cache.get(1, 256)
    assert calls == [1]
    assert not list(cache.directory.glob("*"))


def test_failure_cooldown_expires(cache, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(artwork, "monotonic", lambda: clock[0])
    monkeypatch.setattr(cache, "_download", lambda _: b"bad")
    with pytest.raises(artwork.ArtworkUnavailable):
        cache.get(1)
    clock[0] = 131.0
    monkeypatch.setattr(cache, "_download", lambda _: png_bytes())
    assert cache.get(1)


def test_atomic_write_cleans_temporary_file_on_error(cache, monkeypatch):
    monkeypatch.setattr(cache, "_download", lambda _: png_bytes())
    def fail_replace(*_):
        raise OSError("test disk failure")
    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(artwork.ArtworkUnavailable):
        cache.get(1)
    assert not list(cache.directory.glob("*"))


def test_image_pixel_limit_and_png_only():
    buffer = BytesIO()
    Image.new("RGB", (20, 20)).save(buffer, format="JPEG")
    with pytest.raises(ValueError):
        artwork.ArtworkCache._encode(buffer.getvalue())
    with pytest.raises(ValueError):
        artwork.ArtworkCache._encode(png_bytes((2001, 2000)))


@pytest.mark.parametrize("url", ["/api/artwork/0", "/api/artwork/1026", "/api/artwork/nope", "/api/artwork/1?size=128", "/api/artwork/1?size=abc"])
def test_invalid_parameters_do_not_fetch(client, cache, monkeypatch, url):
    monkeypatch.setattr(cache, "_download", lambda _: pytest.fail("参数验证失败时不能下载"))
    assert client.get(url).status_code == 422


def test_response_cache_headers_and_conditional_get(client, cache, monkeypatch):
    monkeypatch.setattr(cache, "_download", lambda _: png_bytes())
    response = client.get("/api/artwork/25?size=256")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["cache-control"] == "public, max-age=604800"
    assert response.headers["x-content-type-options"] == "nosniff"
    etag = response.headers["etag"]
    for header in (etag, "W/" + etag, f'"other", {etag}', "*"):
        not_modified = client.get("/api/artwork/25", headers={"If-None-Match": header})
        assert not_modified.status_code == 304 and not not_modified.content
        assert not_modified.headers["etag"] == etag
    assert client.get("/api/artwork/25", headers={"If-None-Match": '"different"'}).status_code == 200
    assert client.get("/api/artwork/25?size=512").headers["etag"] != etag


def test_upstream_failure_is_not_browser_cached(client, cache, monkeypatch):
    def timeout(_):
        raise httpx.ReadTimeout("test timeout")
    monkeypatch.setattr(cache, "_download", timeout)
    response = client.get("/api/artwork/1")
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == "30"


@pytest.mark.parametrize("status,headers,body", [
    (302, {"location": "http://127.0.0.1/private"}, b""),
    (404, {}, b"missing"),
    (200, {"content-length": str(artwork.MAX_BYTES + 1)}, b"x"),
    (200, {}, b"x" * (artwork.MAX_BYTES + 1)),
], ids=["redirect", "not-found", "oversized-header", "oversized-stream"])
def test_download_rejects_redirect_error_and_oversized_payload(cache, monkeypatch, status, headers, body):
    seen = []
    options = {}
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, headers=headers, content=body)
    network = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    def client_factory(**kwargs):
        options.update(kwargs)
        return network
    monkeypatch.setattr(artwork.httpx, "Client", client_factory)
    with pytest.raises(artwork.ArtworkUnavailable):
        cache.get(25)
    assert seen == [artwork.UPSTREAM.format(pokemon_id=25)]
    assert options["trust_env"] is True and options["follow_redirects"] is False
    assert options["timeout"].connect == 3 and options["timeout"].read == 5
    assert not list(cache.directory.glob("*"))
