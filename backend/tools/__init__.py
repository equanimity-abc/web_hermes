"""工具包：导入 builtin 以完成注册。"""

from tools import builtin as _builtin  # noqa: F401
from tools.registry import dispatch, list_tool_names, openai_tools

__all__ = ["dispatch", "list_tool_names", "openai_tools"]
