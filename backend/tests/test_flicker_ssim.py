"""闪烁 SSIM：mean/median 稳健过闸。"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def test_score_ssim_uses_max_of_mean_median(tmp_path: Path):
    from tools.drama_qc import score_ssim_paths

    paths = []
    # 多数帧几乎相同，一对突变 → mean 会被拉低，median 仍高
    for i in range(6):
        p = tmp_path / f"f{i}.png"
        if i == 3:
            Image.new("L", (48, 48), 200).save(p)
        else:
            Image.new("L", (48, 48), 40).save(p)
        paths.append(p)
    scored = score_ssim_paths(paths)
    assert scored["status"] == "ok"
    assert scored["ssim"] == max(scored["ssim_mean"], scored["ssim_median"])
    assert scored["ssim_median"] >= scored["ssim_mean"]
