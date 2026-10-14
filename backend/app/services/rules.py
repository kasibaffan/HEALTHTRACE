"""Deterministic rule evaluation. No AI is involved in deciding a rule result."""
import operator as op
from typing import Any

_COMPARE = {
    ">=": op.ge,
    ">": op.gt,
    "<=": op.le,
    "<": op.lt,
    "==": op.eq,
    "contains": lambda actual, needle: str(needle).lower() in str(actual).lower(),
}


def evaluate(operator_symbol: str, actual: Any, threshold: Any) -> bool:
    return bool(_COMPARE[operator_symbol](actual, threshold))


def describe(operator_symbol: str, actual: Any, threshold: Any) -> str:
    def fmt(v: Any) -> str:
        return f"{v:g}" if isinstance(v, (int, float)) else f"'{v}'"

    if operator_symbol == "contains":
        return f"{fmt(threshold)} in {fmt(actual)}"
    return f"{fmt(actual)} {operator_symbol} {fmt(threshold)}"
