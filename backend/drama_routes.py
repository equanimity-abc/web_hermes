"""Drama workbench REST — humans edit here, not via the agent loop."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
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
    generate_character_ref,
    refine_character_ref,
    choose_character_candidate,
    delete_character_candidate,
    generate_episode_script,
    lock_character_ref,
    patch_episode,
    patch_project,
    patch_shot,
    patch_shots,
    patch_timeline,
    preview_script,
    remove_character,
    remove_project,
    rerender_dirty_shots,
    rerender_one_shot,
    retry_render_job,
    save_character,
    save_script,
    upload_character_ref,
    upload_shot_scene,
    choose_candidate,
    delete_candidate,
    generate_candidates,
    generate_i2v_shot,
    generate_lip_shot,
    generate_keys_shot,
    choose_key,
    upload_key,
    lock_key,
    qc_shot,
    qc_episode,
    qc_checklist,
    reject_all_qc,
    pass_episode_qc,
    pass_shot_qc,
    reject_shot_qc,
    remix_loudness,
    suggest_coverage,
    apply_coverage,
    dismiss_coverage,
    lock_coverage,
    classify_shots,
    apply_style,
    list_snapshots,
    restore_snapshot,
    drop_snapshot,
    get_models,
    get_mix,
    mix_episode,
    patch_mix_episode,
    patch_models,
    upload_episode_bgm,
)
from tools.drama_config import apply_preset, get_config, put_node_config

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
    voice: str | None = None
    locked: list[str] | None = None
    lock: list[str] | str | None = None
    unlock: list[str] | str | None = None


class TimelinePatch(BaseModel):
    order: list[int] | None = None
    fade_sec: float | None = None
    shots: dict[str, dict[str, float | str]] | None = None


class RerenderRequest(BaseModel):
    layers: list[str] | None = Field(default=None)


class ShotsPatch(BaseModel):
    shots: list[int]
    field: str
    value: Any


class CandidateCount(BaseModel):
    count: int | None = Field(default=4, ge=1, le=4)


class ScriptBody(BaseModel):
    content: str
    title: str | None = None


class ScriptGenerateBody(BaseModel):
    premise: str
    title: str | None = None


class CharacterBody(BaseModel):
    id: str | None = None
    name: str | None = None
    category: str | None = None
    aliases: list[str] | str | None = None
    look: str | None = None
    colors: str | None = None
    ref_size: int | None = None
    ref_image_provider: str | None = None
    ref_image_model: str | None = None
    catchphrase: str | None = None
    voice: str | None = None
    ref_locked: bool | None = None


class RefLockBody(BaseModel):
    locked: bool = True


class RefineRefBody(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


class JobCreate(BaseModel):
    kind: str = Field(description="rerender_dirty | rerender_shot | export | render_episode | i2v_shot | lip_shot | keys_shot")
    shot: int | None = None
    layers: list[str] | None = None
    force: bool | None = None


class ClassifyBody(BaseModel):
    force: bool = False


class StyleBody(BaseModel):
    style_id: str = ""


class KeysBody(BaseModel):
    count: int | None = None


class ModelsPatch(BaseModel):
    provider: str | None = None
    available: bool | None = None
    currency: str | None = None
    budget: dict | None = None


class ExportBody(BaseModel):
    background: bool = True


class MixPatch(BaseModel):
    bgm: dict | None = None
    volume: float | None = None
    duck_db: float | None = None
    fade_in: float | None = None
    fade_out: float | None = None
    start: float | None = None
    license_ok: bool | None = None
    license: str | None = None
    catalog_id: str | None = None
    clear: bool | None = None
    sfx: list[dict] | None = None
    title: str | None = None
    id: str | None = None
    path: str | None = None


class MixApplyBody(BaseModel):
    background: bool = False


class PresetBody(BaseModel):
    preset_id: str


class NodeBody(BaseModel):
    value: dict
    scope: str = "project"
    episode: int | None = None
    shot: int | None = None


@router.get("/projects")
def drama_list_projects():
    return list_projects()


@router.get("/projects/{slug}")
def drama_get_project(slug: str):
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


@router.delete("/projects/{slug}")
async def drama_delete_project(slug: str):
    try:
        return remove_project(slug)
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


@router.get("/projects/{slug}/config")
async def drama_get_config(slug: str):
    try:
        return get_config(slug)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/config/preset")
async def drama_apply_preset(slug: str, body: PresetBody):
    try:
        return apply_preset(slug, body.preset_id)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.put("/projects/{slug}/config/nodes/{node}")
async def drama_put_node_config(slug: str, node: str, body: NodeBody):
    try:
        return put_node_config(
            slug,
            node,
            body.value,
            scope=body.scope,
            episode=body.episode,
            shot=body.shot,
        )
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}/snapshots")
async def drama_list_snapshots(slug: str, episode: int):
    try:
        return list_snapshots(slug, episode)
    except (DramaNotFound, DramaBadRequest) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/snapshots/restore/{sid}")
async def drama_restore_snapshot(slug: str, episode: int, sid: str):
    try:
        return restore_snapshot(slug, episode, sid)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.delete("/projects/{slug}/episodes/{episode}/snapshots/{sid}")
async def drama_drop_snapshot(slug: str, episode: int, sid: str):
    try:
        return drop_snapshot(slug, episode, sid)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/classify")
async def drama_classify_shots(slug: str, episode: int, body: ClassifyBody | None = None):
    try:
        force = bool(body.force) if body else False
        return classify_shots(slug, episode, force=force)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/style")
async def drama_apply_style(slug: str, episode: int, body: StyleBody | None = None):
    try:
        return apply_style(slug, episode, body.style_id if body else "")
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/coverage")
async def drama_suggest_coverage(slug: str, episode: int):
    try:
        return suggest_coverage(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/coverage/{sid}/apply")
async def drama_apply_coverage(slug: str, episode: int, sid: str):
    try:
        return apply_coverage(slug, episode, sid)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/coverage/{sid}/dismiss")
async def drama_dismiss_coverage(slug: str, episode: int, sid: str):
    try:
        return dismiss_coverage(slug, episode, sid)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/coverage/{sid}/lock")
async def drama_lock_coverage(slug: str, episode: int, sid: str):
    try:
        return lock_coverage(slug, episode, sid)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}")
def drama_get_episode(slug: str, episode: int):
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
def drama_list_shots(slug: str, episode: int):
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


@router.patch("/projects/{slug}/episodes/{episode}/shots")
async def drama_patch_shots(slug: str, episode: int, body: ShotsPatch):
    try:
        return patch_shots(slug, episode, body.shots, body.field, body.value)
    except (DramaNotFound, DramaBadRequest, ValueError, KeyError) as e:
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


@router.delete("/projects/{slug}/episodes/{episode}/shots/{shot}/candidates/{cid}")
async def drama_delete_candidate(slug: str, episode: int, shot: int, cid: str):
    try:
        return delete_candidate(slug, episode, shot, cid)
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


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/lip")
async def drama_generate_lip(slug: str, episode: int, shot: int):
    try:
        return generate_lip_shot(slug, episode, shot)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/keys")
async def drama_generate_keys(slug: str, episode: int, shot: int, body: KeysBody | None = None):
    try:
        return generate_keys_shot(slug, episode, shot, count=body.count if body else None)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/keys/{kid}/choose/{cid}")
async def drama_choose_key(slug: str, episode: int, shot: int, kid: str, cid: str):
    try:
        return choose_key(slug, episode, shot, kid, cid)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/keys/{kid}/upload")
async def drama_upload_key(slug: str, episode: int, shot: int, kid: str, file: UploadFile = File(...)):
    try:
        data = await file.read()
        return upload_key(slug, episode, shot, kid, data)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/keys/{kid}/lock")
async def drama_lock_key(slug: str, episode: int, shot: int, kid: str, body: RefLockBody | None = None):
    try:
        locked = True if body is None else bool(body.locked)
        return lock_key(slug, episode, shot, kid, locked)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/qc")
async def drama_qc_shot(slug: str, episode: int, shot: int):
    try:
        return qc_shot(slug, episode, shot)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/qc")
async def drama_qc_episode(slug: str, episode: int):
    try:
        return qc_episode(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}/qc/checklist")
async def drama_qc_checklist(slug: str, episode: int):
    try:
        return qc_checklist(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/qc/reject-all")
async def drama_reject_all_qc(slug: str, episode: int):
    try:
        return reject_all_qc(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/qc/pass")
async def drama_pass_episode_qc(slug: str, episode: int):
    try:
        return pass_episode_qc(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/qc/remix")
async def drama_remix_loudness(slug: str, episode: int):
    try:
        return remix_loudness(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/qc/pass")
async def drama_pass_shot_qc(slug: str, episode: int, shot: int):
    try:
        return pass_shot_qc(slug, episode, shot)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/shots/{shot}/qc/reject")
async def drama_reject_shot_qc(slug: str, episode: int, shot: int):
    try:
        return reject_shot_qc(slug, episode, shot)
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


@router.post("/projects/{slug}/episodes/{episode}/script/generate")
def drama_generate_script(slug: str, episode: int, body: ScriptGenerateBody):
    # 注意：必须是 def（同步），否则 generate_episode_script → draft_text_sync
    # 内部的 asyncio.run() 会在事件循环里抛 RuntimeError（500）。
    try:
        return generate_episode_script(slug, episode, body.premise)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/rerender-dirty")
async def drama_rerender_dirty(slug: str, episode: int):
    try:
        return rerender_dirty_shots(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError, RuntimeError, KeyError) as e:
        raise _http(e) from e


@router.get("/projects/{slug}/episodes/{episode}/timeline")
def drama_get_timeline(slug: str, episode: int):
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


@router.get("/projects/{slug}/episodes/{episode}/mix")
async def drama_get_mix(slug: str, episode: int):
    try:
        return get_mix(slug, episode)
    except (DramaNotFound, DramaBadRequest, FileNotFoundError, ValueError) as e:
        raise _http(e) from e


@router.patch("/projects/{slug}/episodes/{episode}/mix")
async def drama_patch_mix(slug: str, episode: int, body: MixPatch):
    try:
        return patch_mix_episode(slug, episode, body.model_dump(exclude_unset=True))
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/mix/bgm")
async def drama_upload_episode_bgm(
    slug: str,
    episode: int,
    file: UploadFile = File(...),
    license_ok: bool = Form(False),
    title: str = Form(""),
):
    try:
        data = await file.read()
        return upload_episode_bgm(
            slug,
            episode,
            data,
            filename=file.filename or "bgm.mp3",
            license_ok=bool(license_ok),
            title=title or "",
        )
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/episodes/{episode}/mix")
async def drama_mix_episode(slug: str, episode: int, body: MixApplyBody | None = None):
    try:
        background = body.background if body else False
        return mix_episode(slug, episode, background=background)
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


@router.post("/projects/{slug}/characters/{cid}/generate-ref")
def drama_generate_character_ref(slug: str, cid: str):
    # 同步 def：真出图是长阻塞网络调用，放线程池避免卡死事件循环。
    try:
        return generate_character_ref(slug, cid)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/characters/{cid}/refine-ref")
def drama_refine_character_ref(slug: str, cid: str, body: RefineRefBody):
    try:
        return refine_character_ref(slug, cid, body.instruction)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.post("/projects/{slug}/characters/{cid}/candidates/{cand_id}/choose")
def drama_choose_character_candidate(slug: str, cid: str, cand_id: str):
    try:
        return choose_character_candidate(slug, cid, cand_id)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e


@router.delete("/projects/{slug}/characters/{cid}/candidates/{cand_id}")
def drama_delete_character_candidate(slug: str, cid: str, cand_id: str):
    try:
        return delete_character_candidate(slug, cid, cand_id)
    except (DramaNotFound, DramaBadRequest, ValueError) as e:
        raise _http(e) from e
