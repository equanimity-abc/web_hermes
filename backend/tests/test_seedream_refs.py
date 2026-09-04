"""Seedream 参考图 payload + look 扩写启发式。"""

from __future__ import annotations

from tools.drama_characters import look_needs_expand
from tools.providers import ark_providers


def test_look_needs_expand_detects_template():
    thin = "嫦娥，抖音竖屏漫剧主角/配角，五官清晰，发型与服装符合剧情气质，高质量二次元"
    assert look_needs_expand(thin) is True
    rich = (
        "嫦娥，鹅蛋脸细眉杏眼，银白长发高挽玉簪，月白广袖仙裙配淡金披帛，"
        "赤足踏云，清冷仙气，古风二次元立绘"
    )
    assert look_needs_expand(rich) is False


def test_prompt_with_identity_refs():
    one = ark_providers._prompt_with_identity_refs("竖屏近景嫦娥", ref_count=1)
    assert "定妆" in one and "全新构图" in one
    two = ark_providers._prompt_with_identity_refs("双人镜", ref_count=2)
    assert "图1" in two and "图2" in two
    none = ark_providers._prompt_with_identity_refs("空镜", ref_count=0)
    assert none == "空镜"


def test_seedream_image_payload_single_and_multi(tmp_path, monkeypatch):
    from PIL import Image

    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (64, 64), (20, 40, 60)).save(a)
    Image.new("RGB", (64, 64), (200, 100, 50)).save(b)

    monkeypatch.setattr(
        ark_providers,
        "_local_ref_to_data_uri",
        lambda rel, max_side=1536: f"data:image/jpeg;base64,{rel}",
    )
    single = ark_providers._seedream_image_payload(("ref-a",))
    assert single == "data:image/jpeg;base64,ref-a"
    multi = ark_providers._seedream_image_payload(("ref-a", "ref-b", "ref-c", "ref-d"))
    assert isinstance(multi, list)
    assert len(multi) == 3  # capped
