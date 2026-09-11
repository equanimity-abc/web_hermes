"""Built-in demo tools for verifying the agent loop (P2)."""

from __future__ import annotations

import ast
import operator
from datetime import datetime, timezone

from tools.registry import register

# Safe arithmetic for calculator
_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.operand))
    raise ValueError("仅支持数字与 + - * / // % ** 运算")


def _calculator(args: dict) -> str:
    expr = str(args.get("expression", "")).strip()
    if not expr:
        return '{"error": "expression 不能为空"}'
    try:
        tree = ast.parse(expr, mode="eval")
        value = _eval_node(tree)
        # Prefer int display when exact
        if abs(value - round(value)) < 1e-12:
            value = int(round(value))
        return f'{{"expression": "{expr}", "result": {value}}}'
    except Exception as e:
        return f'{{"error": "{e}", "expression": "{expr}"}}'


def _now(_args: dict) -> str:
    now = datetime.now(timezone.utc).astimezone()
    return (
        f'{{"iso": "{now.isoformat()}", '
        f'"local": "{now.strftime("%Y-%m-%d %H:%M:%S %Z")}"}}'
    )


def register_builtin_tools() -> None:
    register(
        "calculator",
        description="计算数学表达式，例如 2+3*4、(1+2)/3。仅支持四则运算与幂运算。",
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "要计算的数学表达式",
                }
            },
            "required": ["expression"],
        },
        handler=_calculator,
    )
    register(
        "get_current_time",
        description="获取当前本地日期与时间。",
        parameters={"type": "object", "properties": {}},
        handler=_now,
    )


# Register on import
register_builtin_tools()
