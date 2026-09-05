"""多人脸画面按定妆嵌入选脸，避免拿错成配角。"""

from __future__ import annotations

from tools.drama_qc import _cosine


def test_best_face_match_prefers_subject(monkeypatch, tmp_path):
    from tools import drama_qc as qc

    class _Face:
        def __init__(self, emb, bbox):
            self.normed_embedding = emb
            self.embedding = emb
            self.bbox = bbox

    def _vec(ones_at: int) -> list[float]:
        v = [0.0] * 16
        v[ones_at] = 1.0
        return v

    class _App:
        def get(self, img):
            # 大脸=配角，小脸=主体；旧逻辑 faces[0]/最大脸会拿错。
            return [
                _Face(_vec(0), [0, 0, 200, 200]),
                _Face(_vec(1), [0, 0, 40, 40]),
            ]

    monkeypatch.setattr(qc, "_arcface_singleton", lambda: _App())
    monkeypatch.setattr(qc, "_arcface_ready", lambda: True)

    from PIL import Image

    path = tmp_path / "scene.png"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(path)

    subject = _vec(1)
    emb, method = qc._arcface_embedding(path, match_to=subject)
    assert method == "arcface"
    assert emb is not None
    assert _cosine(emb, subject) > 0.99

    largest, method2 = qc._arcface_embedding(path)
    assert method2 == "arcface"
    assert largest is not None
    assert _cosine(largest, _vec(0)) > 0.99
