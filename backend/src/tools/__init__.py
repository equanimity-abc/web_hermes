"""工具包：builtin + workspace + 可选 plugins。"""

from tools import builtin as _builtin  # noqa: F401
from tools import memory as _memory  # noqa: F401
from tools import workspace as _workspace  # noqa: F401
from tools.loader import load_plugin_tools
from tools.registry import dispatch, list_tool_names, openai_tools, tool_requires_approval

_loaded_plugins = load_plugin_tools()

__all__ = [
    "dispatch",
    "list_tool_names",
    "openai_tools",
    "tool_requires_approval",
    "_loaded_plugins",
]
