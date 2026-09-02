"""Cross-session memory file (simple Hermes-style notes).

Persists under MEMORY_DIR/MEMORY.md so every new session can inject facts.
"""

from __future__ import annotations

from pathlib import Path

from config import config

_MAX_CHARS = 12_000


def memory_path() -> Path:
    root = Path(config.MEMORY_DIR).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root / "MEMORY.md"


def read_memory() -> str:
    path = memory_path()
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def write_memory(content: str, *, append: bool = False) -> str:
    """Write memory file. Returns the stored text (possibly truncated)."""
    text = str(content or "")
    path = memory_path()
    if append:
        existing = read_memory().rstrip()
        if existing and text.strip():
            text = existing + "\n" + text.strip() + "\n"
        elif existing:
            text = existing + "\n"
        else:
            text = text.strip() + ("\n" if text.strip() else "")
    else:
        text = text.strip() + ("\n" if text.strip() else "")

    if len(text) > _MAX_CHARS:
        text = text[: _MAX_CHARS - 20] + "\n…(truncated)\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return text


def scrub_memory_terms(*terms: str) -> str:
    """Drop MEMORY.md lines that mention any term (e.g. deleted project slug/title).

    Preference lines without those terms are kept. Empty result clears the file.
    """
    needles = [str(t).strip().lower() for t in terms if str(t or "").strip()]
    body = read_memory()
    if not body or not needles:
        return body

    kept: list[str] = []
    for line in body.splitlines():
        low = line.lower()
        if any(n in low for n in needles):
            continue
        kept.append(line)

    # Collapse runs of blank lines left by removals.
    cleaned: list[str] = []
    blank = False
    for line in kept:
        if not line.strip():
            if blank:
                continue
            blank = True
            cleaned.append("")
        else:
            blank = False
            cleaned.append(line)

    text = "\n".join(cleaned).strip()
    return write_memory(text + ("\n" if text else ""), append=False)


def memory_block_for_prompt() -> str:
    """Snippet injected into system prompts."""
    body = read_memory().strip()
    if not body:
        return ""
    if len(body) > 4000:
        body = body[:4000] + "\n…(truncated)"
    return "## 长期记忆\n" + body
