from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Lock
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, Path as ApiPath, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictInt

from .engine import Clarify, PokedexEngine
from .llm import model_status
from .artwork import ArtworkCache, ArtworkUnavailable, artwork_headers, etag_matches
from .creation_prompts import preview as creation_preview
from .generation import GenerationManager, GenerationUnavailable, GenerationBusy
from .team_optimizer import TeamOptimizer


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("POKE_DB_PATH", ROOT / "data" / "pokedex.sqlite"))
@asynccontextmanager
async def lifespan(application):
    yield
    if _generations is not None:
        _generations.close()


app = FastAPI(title="宝可梦图鉴多表示检索助手", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"], allow_headers=["Content-Type"],
)
_engine = None
_engine_lock = Lock()
artwork_cache = ArtworkCache(ROOT / "data" / "artwork")
_generations = None
_generations_lock = Lock()
_optimizer = None
_optimizer_lock = Lock()


def get_optimizer() -> TeamOptimizer:
    global _optimizer
    path = Path(DB_PATH).resolve()
    if not path.is_file():
        raise HTTPException(503, "图鉴数据库不存在，请先执行数据构建脚本。")
    if _optimizer is None or _optimizer.db_path != path:
        with _optimizer_lock:
            if _optimizer is None or _optimizer.db_path != path:
                _optimizer = TeamOptimizer(path)
    return _optimizer


def get_generations() -> GenerationManager:
    global _generations
    if _generations is None:
        with _generations_lock:
            if _generations is None:
                _generations = GenerationManager(DB_PATH)
    return _generations


def get_engine() -> PokedexEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                try:
                    _engine = PokedexEngine(DB_PATH)
                except FileNotFoundError as exc:
                    raise HTTPException(503, str(exc)) from exc
    return _engine


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    mode: Literal["R0", "R1", "R2"] = "R2"


class TeamRequest(BaseModel):
    pokemon_ids: list[int] = Field(min_length=1, max_length=6)


class TeamOptimizeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    generation: int | None = Field(default=None, ge=1, le=9, strict=True)
    include_special: bool = Field(default=False, strict=True)
    locked_ids: list[StrictInt] = Field(default_factory=list, max_length=6)
    seed: int = Field(default=42, ge=0, le=4294967295, strict=True)


class CreationRequest(BaseModel):
    theme: Literal["fire", "water", "grass", "electric"] = "fire"
    body: Literal["biped", "quadruped", "serpentine"] = "biped"
    stage: Literal["juvenile", "adult"] = "juvenile"


class GenerationRequest(CreationRequest):
    prompt: str = Field(default="", max_length=2000)
    seed: int = Field(default=42, ge=0, le=4294967295, strict=True)
    use_lora: bool = True


@app.exception_handler(Clarify)
async def clarification_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/status")
def status():
    if not DB_PATH.is_file():
        return {"ready": False, "pokemon_count": 0, "document_count": 0, "data_version": None, "retrieval": "未构建", "model": model_status(), "capabilities": [], "warnings": ["缺少数据库，请先运行 scripts/build_data.py。"]}
    return get_engine().status()


@app.get("/api/types")
def types():
    return get_engine().types


@app.get("/api/artwork/{pokemon_id}")
def artwork(pokemon_id: int = ApiPath(ge=1, le=1025), size: int = Query(256), if_none_match: str | None = Header(None)):
    if size not in (256, 512):
        raise HTTPException(422, "图片尺寸仅支持 256 或 512。")
    try:
        content = artwork_cache.get(pokemon_id, size)
    except ArtworkUnavailable as exc:
        raise HTTPException(503, str(exc), headers={"Cache-Control": "no-store", "Retry-After": "30"}) from exc
    headers = artwork_headers(content)
    if etag_matches(if_none_match, headers["ETag"]):
        return Response(status_code=304, headers=headers)
    return Response(content, media_type="image/webp", headers=headers)


@app.get("/api/pokemon")
def pokemon_list(search: str = Query("", max_length=100), type: int | None = Query(None, ge=1, le=18), generation: int | None = Query(None, ge=1, le=9), page: int = Query(1, ge=1, le=1025), limit: int = Query(24, ge=1, le=100), sort: Literal["number", "id_desc", "total_desc", "speed_desc", "name"] = "number", type2: int | None = Query(None, ge=1, le=18), ids: str | None = Query(None, max_length=6000)):
    pokemon_ids = None
    if ids is not None:
        parts = ids.split(",") if ids.strip() else []
        if len(parts) > 1025 or any(not re.fullmatch(r"[0-9]{1,4}", part.strip()) for part in parts):
            raise HTTPException(422, "图鉴编号集合须为逗号分隔的整数，最多1025项。")
        pokemon_ids = [int(part.strip()) for part in parts]
        if any(not 1 <= item <= 1025 for item in pokemon_ids):
            raise HTTPException(422, "图鉴编号须在1至1025之间。")
    return get_engine().listing(search, type, generation, page, limit, sort=sort, type2=type2, ids=pokemon_ids)


@app.get("/api/pokemon/{pokemon_id}")
def pokemon_detail(pokemon_id: int):
    try:
        return get_engine().detail(pokemon_id)
    except KeyError as exc:
        raise HTTPException(404, "图鉴中没有该宝可梦。") from exc


@app.post("/api/ask")
def ask(payload: AskRequest):
    return get_engine().ask(payload.question, payload.mode)


@app.post("/api/team")
def team(payload: TeamRequest):
    try:
        return get_engine().team(payload.pokemon_ids)
    except KeyError as exc:
        raise HTTPException(404, "队伍包含未收录的宝可梦。") from exc


@app.get("/api/model")
def model():
    return model_status()


@app.post("/api/team/optimize")
def optimize_team(payload: TeamOptimizeRequest):
    try:
        return get_optimizer().optimize(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/generations/status")
def generation_status():
    return get_generations().status()


@app.post("/api/generations/preview")
def generation_preview(payload: CreationRequest):
    return creation_preview(DB_PATH, payload.theme, payload.body, payload.stage)


@app.post("/api/generations", status_code=202)
def create_generation(payload: GenerationRequest):
    try:
        return get_generations().submit(payload.model_dump())
    except GenerationUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except GenerationBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/generations")
def generation_history():
    return {"items": get_generations().history()}


@app.get("/api/generations/{job_id}")
def generation_detail(job_id: str):
    try:
        return get_generations().get(job_id)
    except KeyError as exc:
        raise HTTPException(404, "未找到该创作记录。") from exc


@app.get("/api/generations/{job_id}/image")
def generation_image(job_id: str):
    job = generation_detail(job_id)
    if job["status"] != "succeeded":
        raise HTTPException(404, "图片尚未生成。")
    image = get_generations().directory / job_id / "image.png"
    if not image.is_file():
        raise HTTPException(404, "生成图片文件已缺失，请重新生成。")
    return FileResponse(image, media_type="image/png", filename=f"creation-{job_id}.png")


if (ROOT / "frontend" / "dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "frontend" / "dist", html=True), name="frontend")
