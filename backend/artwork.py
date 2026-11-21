from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic
from uuid import uuid4

import httpx
from PIL import Image, UnidentifiedImageError


UPSTREAM = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/{pokemon_id}.png"
MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 4_000_000
SIZES = (256, 512)
CACHE_CONTROL = "public, max-age=604800"


class ArtworkUnavailable(Exception):
    pass


class ArtworkCache:
    def __init__(self, directory: Path):
        self.directory = directory / "v1"
        self._locks = [Lock() for _ in range(1026)]
        self._downloads = BoundedSemaphore(4)
        self._failed_until = [0.0] * 1026

    def get(self, pokemon_id: int, size: int = 256) -> bytes:
        if type(pokemon_id) is not int or not 1 <= pokemon_id <= 1025 or size not in SIZES:
            raise ValueError("无效的宝可梦编号或图片尺寸。")
        path = self.directory / f"{pokemon_id}-{size}.webp"
        if path.is_file():
            return path.read_bytes()
        if not self._locks[pokemon_id].acquire(timeout=12):
            raise ArtworkUnavailable("图片正在准备，请稍后重试。")
        try:
            if path.is_file():
                return path.read_bytes()
            if self._failed_until[pokemon_id] > monotonic():
                raise ArtworkUnavailable("图片来源暂不可用，请稍后重试。")
            if not self._downloads.acquire(timeout=8):
                raise ArtworkUnavailable("图片请求较多，请稍后重试。")
            try:
                variants = self._encode(self._download(pokemon_id))
                self.directory.mkdir(parents=True, exist_ok=True)
                for variant_size, content in variants.items():
                    target = self.directory / f"{pokemon_id}-{variant_size}.webp"
                    temporary = target.with_suffix(f".{uuid4().hex}.tmp")
                    try:
                        temporary.write_bytes(content)
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
                return variants[size]
            except (httpx.HTTPError, OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                self._failed_until[pokemon_id] = monotonic() + 30
                raise ArtworkUnavailable("图片来源暂不可用，请稍后重试。") from exc
            finally:
                self._downloads.release()
        finally:
            self._locks[pokemon_id].release()

    @staticmethod
    def _download(pokemon_id: int) -> bytes:
        # 固定来源且不跟随重定向，避免将图片接口变成任意地址代理。
        started = monotonic()
        content = bytearray()
        with httpx.Client(timeout=httpx.Timeout(5.0, connect=3.0), trust_env=True, follow_redirects=False) as client:
            with client.stream("GET", UPSTREAM.format(pokemon_id=pokemon_id)) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", "0")) > MAX_BYTES:
                    raise ValueError("图片文件过大。")
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_BYTES or monotonic() - started > 10:
                        raise ValueError("图片文件过大或下载超时。")
        return bytes(content)

    @staticmethod
    def _encode(content: bytes) -> dict[int, bytes]:
        with Image.open(BytesIO(content)) as source:
            if source.format != "PNG" or source.width * source.height > MAX_PIXELS:
                raise ValueError("无效的来源图片。")
            source.load()
            rgba = source.convert("RGBA")
        variants = {}
        for size in SIZES:
            image = rgba.copy()
            bound = min(size, 475)
            image.thumbnail((bound, bound), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            image.save(buffer, format="WEBP", quality=82 if size == 256 else 90, method=4)
            variants[size] = buffer.getvalue()
        return variants


def artwork_headers(content: bytes) -> dict[str, str]:
    return {"Cache-Control": CACHE_CONTROL, "ETag": f'"{sha256(content).hexdigest()}"', "X-Content-Type-Options": "nosniff"}


def etag_matches(header: str | None, etag: str) -> bool:
    return bool(header and any(value.strip().removeprefix("W/") in (etag, "*") for value in header.split(",")))
