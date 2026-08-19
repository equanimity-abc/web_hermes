"""Q2 smoke: lip only on dialogue CU/MCU with speaker; fallback; LSE score."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

os.environ["IMAGE_GEN_PROVIDER"] = "none"
os.environ["LIP_PROVIDER"] = "mock"

import agent.loop  # noqa: F401

from config import config
from tools.drama_lip import generate_shot_lip, lip_eligible, lip_rel
from tools.drama_shots import load_doc, save_doc, shot_assets
from tools.drama_studio import DramaBadRequest, generate_lip_shot, patch_shot, save_character, save_script
from tools.workspace import resolve_safe

config.IMAGE_GEN_PROVIDER = "none"

SLUG = "q2-smoke"
MD = """# Q2 验收
- 时长: 12s
- 钩子: 开场
- 悬念: 结尾

## 分镜
### Shot 1 (0-4s)
- 画面: 宫殿远景
- 对白:
- 字幕:

### Shot 2 (4-8s)
- 画面: 角色特写
- 对白: 今夜入宫
- 字幕: 今夜入宫
- 角色: hero

### Shot 3 (8-12s)
- 画面: 对打
- 对白: 喝
- 字幕:
- 角色: hero
"""


def _shot(doc: dict, n: int) -> dict:
    return next(s for s in doc["shots"] if int(s["n"]) == n)


def _png(path, color: str = "c0a070") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=1080x1920:d=0.04", "-frames:v", "1", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg png failed")


def _voice(path, duration: float = 2.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=180:duration={duration}",
            "-c:a",
            "pcm_s16le",
            str(path.with_suffix(".wav")),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or "ffmpeg voice failed")
    wav = path.with_suffix(".wav")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "96k", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        wav.replace(path)
    else:
        try:
            wav.unlink()
        except OSError:
            pass


def main() -> None:
    if shutil.which("ffmpeg") is None:
        print("skip Q2 smoke: ffmpeg not in PATH")
        return

    root = resolve_safe(f"dramas/{SLUG}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    (root / "project.json").write_text(
        json.dumps({"slug": SLUG, "title": "Q2", "logline": "口型", "episodes": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    save_character(SLUG, {"id": "hero", "name": "主角", "look": "黑发", "voice": "zh-CN-YunxiNeural"})
    save_script(SLUG, 1, MD)
    doc = load_doc(SLUG, 1)
    s1, s2, s3 = _shot(doc, 1), _shot(doc, 2), _shot(doc, 3)
    s3["kind"] = "action"
    s3["size"] = "MS"
    s2["kind"] = "dialogue"
    s2["size"] = "CU"
    s2["speaker"] = "hero"
    s2["locked"] = ["scene"]
    for n, color in ((1, "334155"), (2, "c0a070"), (3, "7c2d12")):
        assets = shot_assets(SLUG, 1, n)
        _png(resolve_safe(assets["scene"]), color)
        shot = _shot(doc, n)
        shot.setdefault("assets", {}).update({"scene": assets["scene"], "voice": assets["voice"], "lip": assets["lip"]})
    _voice(resolve_safe(shot_assets(SLUG, 1, 2)["voice"]))
    save_doc(doc)

    assert lip_eligible(_shot(load_doc(SLUG, 1), 1))["ok"] is False
    assert lip_eligible(_shot(load_doc(SLUG, 1), 3))["ok"] is False
    try:
        generate_lip_shot(SLUG, 1, 1)
        raise AssertionError("establishing must refuse lip")
    except DramaBadRequest:
        pass

    wide = patch_shot(SLUG, 1, 2, {"size": "WS"})
    assert lip_eligible(wide["shot"])["ok"] is False
    patch_shot(SLUG, 1, 2, {"size": "CU", "speaker": "hero"})

    no_spk = dict(_shot(load_doc(SLUG, 1), 2))
    no_spk["speaker"] = ""
    no_spk["角色"] = []
    assert "speaker" in lip_eligible(no_spk)["reason"]

    doc = load_doc(SLUG, 1)
    s2 = _shot(doc, 2)
    info = generate_shot_lip(SLUG, 1, s2)
    save_doc(doc)
    assert info["lip_source"] == "mock", info
    lip_path = resolve_safe(lip_rel(SLUG, 1, 2))
    assert lip_path.is_file() and lip_path.stat().st_size > 500
    score = info.get("score") or {}
    assert score.get("status") in ("ok", "skipped"), score
    if score.get("status") == "ok":
        assert score.get("lse_c") is not None

    os.environ["LIP_PROVIDER"] = "fail"
    info_fail = generate_shot_lip(SLUG, 1, _shot(load_doc(SLUG, 1), 2))
    assert info_fail["lip_source"] == "fallback", info_fail
    os.environ["LIP_PROVIDER"] = "mock"

    patched = patch_shot(SLUG, 1, 2, {"对白": "换一句"})
    assert "lip" in (patched.get("dirty") or patched["shot"]["dirty"]), patched

    print("Q2 smoke ok: dialogue CU lip, far/action blocked, fallback, LSE")


if __name__ == "__main__":
    try:
        main()
    finally:
        root = resolve_safe(f"dramas/{SLUG}")
        if root.exists():
            shutil.rmtree(root)
