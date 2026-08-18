"""Drama workbench REST — humans edit here, not via the agent loop."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tools.drama_studio import (
    CAMERAS,
    DramaBadRequest,
    DramaNotFound,
    get_episode,
    get_project,
    list_projects,
    patch_episode,
    patch_project,
    patch_shot,
    preview_script,
    rerender_dirty_shots,
    rerender_one_shot,
    save_script,
)

router = APIRouter(prefix="/api/drama", tags=["drama"])


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, DramaNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DramaBadRequest):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


class ProjectPatch(BaseModel):
    title: str | None = None
    logline: str | None = None


class EpisodePatch(BaseModel):
    title: str | None = None
    seconds: int | None = None


class ShotPatch(BaseModel):
    画面: str | None = None
    对白: str | None = None
    字幕: str | None = None
    camera: str | None = None
    duration: float | None = None
    timing: str | None = None
    locked: list[str] | None = None
    lock: list[str] | str | None = None
    unlock: list[str] | str | None = None


class RerenderRequest(BaseModel):
    layers: list[str] | None = Field(default=None)


class ScriptBody(BaseModel):
    content: str
    title: str | None = None


@router.get("/projects")
async def drama_list_projects():
    return list_projects()


@router.get("/projects/{slug}")
async def drama_get_project(slug: str):
    try:
        return get_project(slug)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}")
async def drama_patch_project(slug: str, body: ProjectPatch):
    try:
        return patch_project(slug, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}")
async def drama_get_episode(slug: str, episode: int):
    try:
        return get_episode(slug, episode)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}/episodes/{episode}")
async def drama_patch_episode(slug: str, episode: int, body: EpisodePatch):
    try:
        return patch_episode(slug, episode, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}/shots")
async def drama_list_shots(slug: str, episode: int):
    try:
        data = get_episode(slug, episode)
        return {
            "slug": data["slug"],
            "episode": data["episode"],
            "shots_json": data.get("shots_json"),
            "count": data.get("count") or 0,
            "shots": data.get("shots") or [],
            "cameras": list(CAMERAS),
        }
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}/episodes/{episode}/shots/{shot}")
async def drama_patch_shot(slug: str, episode: int, shot: int, body: ShotPatch):
    try:
        return patch_shot(slug, episode, shot, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest, ValueError, KeyError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/rerender")
async def drama_rerender_shot(slug: str, episode: int, shot: int, body: RerenderRequest | None = None):
    try:
        layers = (body.layers if body else None) or None
        return rerender_one_shot(slug, episode, shot, layers)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/script/preview")
async def drama_preview_script(slug: str, episode: int, body: ScriptBody):
    try:
        return preview_script(slug, episode, body.content)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.put("/projects/{slug}/episodes/{episode}/script")
async def drama_save_script(slug: str, episode: int, body: ScriptBody):
    try:
        return save_script(slug, episode, body.content, title=body.title)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/rerender-dirty")
async def drama_rerender_dirty(slug: str, episode: int):
    try:
        return rerender_dirty_shots(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
        raise _http(e) from e
