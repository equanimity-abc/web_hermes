"""可选插件目录：backend/tools/plugins/*.py 中调用 register() 即可挂载。"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

_PLUGIN_PROMPT_HINTS: list[str] = []


def add_plugin_prompt_hint(text: str) -> None:
    """Plugins may append a short system-prompt hint (loaded at import)."""
    snippet = (text or "").strip()
    if snippet and snippet not in _PLUGIN_PROMPT_HINTS:
        _PLUGIN_PROMPT_HINTS.append(snippet)


def plugin_prompt_hints() -> list[str]:
    return list(_PLUGIN_PROMPT_HINTS)


def load_plugin_tools() -> list[str]:
    """Import tools.plugins.* modules. Returns loaded module names."""
    plugins_dir = Path(__file__).resolve().parent / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    init = plugins_dir / "__init__.py"
    if not init.exists():
        init.write_text('"""User/plugin tools drop-in package."""\n', encoding="utf-8")

    src_root = plugins_dir.parent.parent
    backend_root = src_root.parent
    for path in (src_root, backend_root):
        entry = str(path)
        if entry not in sys.path:
            sys.path.insert(0, entry)

    loaded: list[str] = []
    package_name = "tools.plugins"
    try:
        package = importlib.import_module(package_name)
    except Exception:
        return loaded

    for mod in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if mod.ispkg:
            continue
        try:
            importlib.import_module(mod.name)
            loaded.append(mod.name)
        except Exception as e:
            print(f"[tools.plugins] failed to load {mod.name}: {e}")
    load_skill_hints()
    _load_providers()
    return loaded


def _load_providers() -> None:
    """Auto-register generation adapters (tools/providers/*.py)."""
    try:
        from tools.providers import registry

        registry.load_all()
    except Exception as e:
        print(f"[providers] failed to load adapters: {e}")


def _frontmatter_field(text: str, key: str) -> str:
    """Extract a scalar field from YAML frontmatter (``--- ... ---``).

    Supports plain / single-quoted / double-quoted values. Returns the
    whitespace-collapsed value, or "" when the field is absent.
    """
    import re

    m = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.S)
    if not m:
        return ""
    fm = m.group(1)
    for line in fm.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip() != key:
            continue
        val = v.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        return " ".join(val.split())
    return ""


def load_skill_hints() -> list[str]:
    """Inject skills/*/SKILL.md frontmatter ``description`` into the system prompt.

    Standard SKILL.md convention: YAML frontmatter (name/description/…) followed
    by markdown instructions. The ``description`` doubles as the standing hint.
    """
    skills_dir = Path(__file__).resolve().parent.parent / "skills"
    loaded: list[str] = []
    if not skills_dir.is_dir():
        return loaded
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hint = _frontmatter_field(text, "description")
        if hint:
            add_plugin_prompt_hint(hint)
            loaded.append(skill_md.parent.name)
    return loaded
