"""可选插件目录：backend/tools/plugins/*.py 中调用 register() 即可挂载。"""

from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path


def load_plugin_tools() -> list[str]:
    """Import tools.plugins.* modules. Returns loaded module names."""
    plugins_dir = Path(__file__).resolve().parent / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    init = plugins_dir / "__init__.py"
    if not init.exists():
        init.write_text('"""User/plugin tools drop-in package."""\n', encoding="utf-8")

    backend_root = str(plugins_dir.parent.parent)
    if backend_root not in sys.path:
        sys.path.insert(0, backend_root)

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
    return loaded
