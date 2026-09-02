"""Face-crop fallback without InsightFace must pick pink side for warm-accent cards."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from tools.drama_lip import _lock_dual_speaker_layout, _speaker_face_crop_box_fallback


def test_fallback_picks_pink_side_for_warm_palette(tmp_path: Path, monkeypatch):
    # Synthetic 9:16 frame: left pink dress blob, right white/dark blob
    h, w = 640, 360
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = (40, 40, 50)
    arr[80:300, 20:160] = (255, 170, 190)  # pink left
    arr[80:300, 200:340] = (245, 245, 245)  # white right
    arr[80:140, 200:340] = (20, 20, 20)  # dark hair right
    frame = tmp_path / "frame.jpg"
    Image.fromarray(arr, "RGB").save(frame)
    ref = tmp_path / "ref.png"
    Image.fromarray(np.full((64, 64, 3), (255, 182, 193), dtype=np.uint8), "RGB").save(ref)

    monkeypatch.setattr(
        "tools.drama_characters.load_characters",
        lambda slug: [{"id": "ruolin", "colors": "主色:粉#FFB6C1"}],
    )
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda cards, cid: {"id": "ruolin", "colors": "主色:粉#FFB6C1"},
    )

    box = _speaker_face_crop_box_fallback(frame, ref, slug="demo", character_id="ruolin")
    assert box is not None
    assert box[0] < 0.3  # left side


def test_fallback_picks_opposite_for_cool_palette(tmp_path: Path, monkeypatch):
    h, w = 640, 360
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :] = (40, 40, 50)
    arr[80:300, 20:160] = (255, 170, 190)
    arr[80:300, 200:340] = (245, 245, 245)
    arr[80:140, 200:340] = (20, 20, 20)
    frame = tmp_path / "frame.jpg"
    Image.fromarray(arr, "RGB").save(frame)
    ref = tmp_path / "ref.png"
    Image.fromarray(np.full((64, 64, 3), (245, 245, 245), dtype=np.uint8), "RGB").save(ref)

    monkeypatch.setattr(
        "tools.drama_characters.load_characters",
        lambda slug: [{"id": "ruoxi", "colors": "主色:白#F5F5F5, 发色:深黑#0D0D0D"}],
    )
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda cards, cid: {"id": "ruoxi", "colors": "主色:白#F5F5F5, 发色:深黑#0D0D0D"},
    )

    box = _speaker_face_crop_box_fallback(frame, ref, slug="demo", character_id="ruoxi")
    assert box is not None
    assert box[0] > 0.4  # right side


def test_layout_lock_keeps_cool_speaker_right_when_midshot_pink_flips(
    tmp_path: Path, monkeypatch
):
    """Shot7 regression: at t≈6s right becomes pinker — cool speaker must stay right."""
    h, w = 640, 360
    # Early plate: pink LEFT (correct cast framing)
    early = np.zeros((h, w, 3), dtype=np.uint8)
    early[:, :] = (40, 40, 50)
    early[80:300, 20:160] = (255, 170, 190)
    early[80:300, 200:340] = (245, 245, 245)
    early[80:140, 200:340] = (20, 20, 20)
    Image.fromarray(early, "RGB").save(tmp_path / "layout_lock.jpg")

    cards = {
        "ruolin": {"id": "ruolin", "colors": "主色:粉#FFB6C1"},
        "ruoxi": {"id": "ruoxi", "colors": "主色:白#F5F5F5, 发色:深黑#0D0D0D"},
    }
    monkeypatch.setattr("tools.drama_characters.load_characters", lambda slug: list(cards.values()))
    monkeypatch.setattr(
        "tools.drama_characters.find_character",
        lambda c, cid: cards.get(cid),
    )

    # Avoid ffmpeg: pretender that sample already wrote layout_lock.jpg
    def _fake_sample(video, t, dest):
        dest.write_bytes((tmp_path / "layout_lock.jpg").read_bytes())
        return True

    monkeypatch.setattr("tools.drama_lip._sample_frame", _fake_sample)
    monkeypatch.setattr(
        "tools.drama_lip._resolve_turn_face",
        lambda slug, turn: (str(turn.get("character_id") or ""), ""),
    )

    turns = [
        {"character_id": "ruolin", "start": 0.0, "end": 6.0},
        {"character_id": "ruoxi", "start": 6.0, "end": 9.0},
    ]
    layout = _lock_dual_speaker_layout("demo", tmp_path / "dummy.mp4", turns, tmp=tmp_path)
    assert layout["ruolin"][0] < 0.3
    assert layout["ruoxi"][0] > 0.4
