"""Validate and execute FinQA programs against the excerpts given to the planner."""

import json
import math
import operator
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable


@dataclass(frozen=True)
class Excerpt:
    id: str
    source: str | tuple[str, ...]


ARITHMETIC: dict[str, Callable[[float, float], float]] = {
    "add": operator.add, "subtract": operator.sub, "multiply": operator.mul,
    "divide": operator.truediv, "exp": operator.pow,
}
REDUCTIONS: dict[str, Callable[[list[float]], float]] = {
    "table_max": max, "table_min": min, "table_sum": sum,
    "table_average": lambda values: sum(values) / len(values),
}
CONSTANTS = {f"const_{n}": float(n) for n in (
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 1000000000
)}
CONSTANTS["const_m1"] = -1.0
NUMBER = r"[+\-−]?(?:(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?|\.[0-9]+)(?: *%)?"
SOURCE_NUMBER = re.compile(rf"(?<![\w.])(?:{NUMBER})(?!\w|\.[0-9])")
STEP_REF = re.compile(r"#(0|[1-9][0-9]?)")
MAX_STEPS = 11


class InvalidPlan(ValueError):
    pass


def _number(token: str) -> Decimal:
    if re.fullmatch(NUMBER, token) is None:
        raise ValueError(f"Invalid number {token!r}")
    digits = token.rstrip("%").strip().replace(",", "").replace("−", "-")
    return Decimal(digits + "e-2" if token.endswith("%") else digits)


def _table_number(cell: str) -> Decimal:
    return _number(cell.replace("$", "").split("(")[0].strip())


def _excerpt_numbers(excerpt: Excerpt) -> list[Decimal]:
    if isinstance(excerpt.source, str):
        return [_number(match[0]) for match in SOURCE_NUMBER.finditer(excerpt.source)]
    values = []
    for index, cell in enumerate(excerpt.source):
        if index:
            try:
                values.append(_table_number(cell))
                continue
            except ValueError:
                pass
        values.extend(_number(match[0]) for match in SOURCE_NUMBER.finditer(cell))
    return values


def _source_numbers(question: str, excerpts: list[Excerpt]) -> dict[Decimal, list[str]]:
    numbers: dict[Decimal, list[str]] = {}
    for excerpt in [Excerpt("question", question), *excerpts]:
        for value in _excerpt_numbers(excerpt):
            locations = numbers.setdefault(value, [])
            if excerpt.id not in locations:
                locations.append(excerpt.id)
    return numbers


def _operand_source(token: str, index: int, sources: dict[Decimal, list[str]]) -> list[str]:
    if token in CONSTANTS:
        return ["benchmark_constant"]
    reference = STEP_REF.fullmatch(token)
    if reference and int(reference[1]) < index:
        return [token]
    try:
        return sources[_number(token)]
    except (ValueError, KeyError) as exc:
        raise InvalidPlan(f"Step {index} has an unsupported operand {token!r}") from exc


def _unique_fields(fields: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(fields)
    if len(result) != len(fields):
        raise InvalidPlan("Duplicate fields in plan JSON")
    return result


def _validated_program(
    proposal: str, sources: dict[Decimal, list[str]], rows: dict[str, tuple[str, ...]],
) -> tuple[list[list[str]], list[list[list[str]]]]:
    plan = json.loads(proposal, object_pairs_hook=_unique_fields)
    if not isinstance(plan, dict) or set(plan) != {"program"}:
        raise InvalidPlan("Expected a JSON object with only a program field")
    program = plan["program"]
    if not isinstance(program, list) or len(program) > MAX_STEPS:
        raise InvalidPlan(f"Expected a program with at most {MAX_STEPS} steps")
    locations: list[list[list[str]]] = []
    for index, step in enumerate(program):
        if not isinstance(step, list) or len(step) != 3 or not all(isinstance(item, str) for item in step):
            raise InvalidPlan(f"Step {index} must contain three strings")
        op, left, right = step
        if op in REDUCTIONS:
            if left not in rows or left == "table_0" or right != "none":
                raise InvalidPlan(f"Step {index} requires a selected data row ID and none")
            locations.append([[left], []])
        elif op in ARITHMETIC or op == "greater":
            locations.append([_operand_source(left, index, sources), _operand_source(right, index, sources)])
        else:
            raise InvalidPlan(f"Step {index} has an unknown operation {op!r}")
    return program, locations


def _resolve(token: str, results: list[float | str]) -> float:
    if token.startswith("#"):
        value = results[int(token[1:])]
        if isinstance(value, str):
            raise ValueError("A comparison result cannot be used as a number")
        return value
    if token in CONSTANTS:
        return CONSTANTS[token]
    return _finite_float(_number(token))


def _finite_float(value: Decimal) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Numeric operands must be finite")
    return result


def _execute_step(
    step: list[str], results: list[float | str], rows: dict[str, tuple[str, ...]],
) -> tuple[list[float], float | str]:
    op, left, right = step
    if op in REDUCTIONS:
        operands = [_finite_float(_table_number(cell)) for cell in rows[left][1:]]
        if not operands:
            raise ValueError("The selected row has no numeric data cells")
        result: float | str = REDUCTIONS[op](operands)
    else:
        a, b = _resolve(left, results), _resolve(right, results)
        operands = [a, b]
        if op == "greater":
            result = "yes" if a > b else "no"
        else:
            result = ARITHMETIC[op](a, b)
    if not isinstance(result, str) and (not isinstance(result, (int, float)) or not math.isfinite(result)):
        raise ValueError("The result must be real and finite")
    return operands, result


def evaluate_proposal(proposal: str, question: str, excerpts: list[Excerpt]) -> dict[str, Any]:
    rows = {e.id: e.source for e in excerpts if isinstance(e.source, tuple)}
    try:
        program, locations = _validated_program(proposal, _source_numbers(question, excerpts), rows)
    except (ValueError, RecursionError) as exc:
        return {"status": "invalid_plan", "reason": str(exc), "trace": []}
    if not program:
        return {"status": "abstained", "program": [], "trace": []}
    results: list[float | str] = []
    trace: list[dict[str, Any]] = []
    for index, step in enumerate(program):
        try:
            operands, result = _execute_step(step, results, rows)
        except (ValueError, ArithmeticError) as exc:
            return {"status": "execution_failure", "program": program, "step": index,
                    "reason": str(exc), "trace": trace}
        results.append(result)
        trace.append({"step": index, "instruction": step, "sources": locations[index],
                      "operands": operands, "result": result})
    value = results[-1]
    return {"status": "executed", "program": program, "trace": trace,
            "value": round(value, 5) if isinstance(value, float) else value}
