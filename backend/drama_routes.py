"""Drama workbench REST — humans edit here, not via the agent loop."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from tools.drama_studio import (
    CAMERAS,
    DramaBadRequest,
    DramaNotFound,
    cancel_render_job,
    enqueue_job,
    export_episode,
    get_characters,
    get_episode,
    get_project,
    get_render_job,
    get_timeline,
    list_projects,
    list_render_jobs,
    lock_character_ref,
    patch_episode,
    patch_project,
    patch_shot,
    patch_timeline,
    preview_script,
    remove_character,
    rerender_dirty_shots,
    rerender_one_shot,
    retry_render_job,
    save_character,
    save_script,
    upload_character_ref,
    upload_shot_scene,
    choose_candidate,
    generate_candidates,
    generate_i2v_shot,
    classify_shots,
    get_models,
    patch_models,
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
    角色: list[str] | str | None = None
    camera: str | None = None
    duration: float | None = None
    timing: str | None = None
    trim_in: float | None = None
    trim_out: float | None = None
    volume: float | None = None
    transition: str | None = None
    i2v: str | None = None
    kind: str | None = None
    size: str | None = None
    speaker: str | None = None
    locked: list[str] | None = None
    lock: list[str] | str | None = None
    unlock: list[str] | str | None = None


class TimelinePatch(BaseModel):
    order: list[int] | None = None
    fade_sec: float | None = None
    shots: dict[str, dict[str, float | str]] | None = None


class RerenderRequest(BaseModel):
    layers: list[str] | None = Field(default=None)


class CandidateCount(BaseModel):
    count: int | None = Field(default=4, ge=2, le=4)


class ScriptBody(BaseModel):
    content: str
    title: str | None = None


class CharacterBody(BaseModel):
    id: str | None = None
    name: str | None = None
    aliases: list[str] | str | None = None
    look: str | None = None
    colors: str | None = None
    catchphrase: str | None = None
    voice: str | None = None
    ref_locked: bool | None = None


class RefLockBody(BaseModel):
    locked: bool = True


class JobCreate(BaseModel):
    kind: str = Field(description="rerender_dirty | rerender_shot | export | render_episode | i2v_shot")
    shot: int | None = None
    layers: list[str] | None = None
    force: bool | None = None


class ClassifyBody(BaseModel):
    force: bool = False


class ModelsPatch(BaseModel):
    provider: str | None = None
    available: bool | None = None
    currency: str | None = None


class ExportBody(BaseModel):
    background: bool = True


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


@router.get("/projects/{slug}/models")
async def drama_get_models(slug: str):
    try:
        return get_models(slug)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}/models")
async def drama_patch_models(slug: str, body: ModelsPatch):
    try:
        return patch_models(slug, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/classify")
async def drama_classify_shots(slug: str, episode: int, body: ClassifyBody | None = None):
    try:
        force = bool(body.force) if body else False
        return classify_shots(slug, episode, force=force)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
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


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/candidates")
async def drama_generate_candidates(slug: str, episode: int, shot: int, body: CandidateCount | None = None):
    try:
        count = (body.count if body else None) or 4
        return generate_candidates(slug, episode, shot, count)
    except (DramaNotFound, DramaBadRequest, ValueError, KeyError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/choose/{cid}")
async def drama_choose_candidate(slug: str, episode: int, shot: int, cid: str):
    try:
        return choose_candidate(slug, episode, shot, cid)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/scene")
async def drama_upload_shot_scene(slug: str, episode: int, shot: int, file: UploadFile = File(...)):
    try:
        data = await file.read()
        return upload_shot_scene(slug, episode, shot, data)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/i2v")
async def drama_generate_i2v(slug: str, episode: int, shot: int):
    try:
        return generate_i2v_shot(slug, episode, shot)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
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


@router.get("/projects/{slug}/episodes/{episode}/timeline")
async def drama_get_timeline(slug: str, episode: int):
    try:
        return get_timeline(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}/episodes/{episode}/timeline")
async def drama_patch_timeline(slug: str, episode: int, body: TimelinePatch):
    try:
        return patch_timeline(slug, episode, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/export")
async def drama_export_episode(slug: str, episode: int, body: ExportBody | None = None):
    try:
        background = body.background if body else True
        return export_episode(slug, episode, background=background)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/jobs")
async def drama_create_job(slug: str, episode: int, body: JobCreate):
    try:
        params: dict = {}
        if body.shot is not None:
            params["shot"] = body.shot
        if body.layers is not None:
            params["layers"] = body.layers
        if body.force is not None:
            params["force"] = body.force
        return enqueue_job(slug, episode, body.kind, params=params or None)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.get("/jobs")
async def drama_list_jobs(slug: str | None = None, active: bool = False, limit: int = 20):
    try:
        return list_render_jobs(slug=slug, active_only=active, limit=limit)
    except DramaBadRequest as e:
        raise _http(e) from e


@router.get("/jobs/{job_id}")
async def drama_get_job(job_id: str):
    try:
        return get_render_job(job_id)
    except DramaNotFound as e:
        raise _http(e) from e


@router.post("/jobs/{job_id}/cancel")
async def drama_cancel_job(job_id: str):
    try:
        return cancel_render_job(job_id)
    except DramaNotFound as e:
        raise _http(e) from e


@router.post("/jobs/{job_id}/retry")
async def drama_retry_job(job_id: str):
    try:
        return retry_render_job(job_id)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/characters")
async def drama_list_characters(slug: str):
    try:
        return get_characters(slug)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.put("/projects/{slug}/characters/{cid}")
async def drama_save_character(slug: str, cid: str, body: CharacterBody):
    try:
        payload = body.model_dump(exclude_unset=True)
        payload["id"] = cid
        return save_character(slug, payload)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/characters")
async def drama_create_character(slug: str, body: CharacterBody):
    try:
        return save_character(slug, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.delete("/projects/{slug}/characters/{cid}")
async def drama_delete_character(slug: str, cid: str):
    try:
        return remove_character(slug, cid)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/characters/{cid}/lock-ref")
async def drama_lock_character_ref(slug: str, cid: str, body: RefLockBody):
    try:
        return lock_character_ref(slug, cid, body.locked)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/characters/{cid}/ref")
async def drama_upload_character_ref(slug: str, cid: str, file: UploadFile = File(...)):
    try:
        data = await file.read()
        return upload_character_ref(slug, cid, data)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e
