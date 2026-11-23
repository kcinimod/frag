"""Adapt replayed FinQA outcomes to the pinned upstream scorer."""

import json
import math
from collections import Counter
from contextlib import redirect_stdout
from hashlib import sha256
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from frag.finqa_program import REDUCTIONS


def _load_scorer(path: Path, expected_hash: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != expected_hash:
        raise ValueError("evaluate.py does not match the pinned SHA-256")
    scorer: dict[str, Any] = {"__name__": "pinned_finqa_evaluator"}
    try:
        # Execute the exact bytes checked above, including the upstream imports.
        exec(compile(raw, str(path), "exec"), scorer)
    except ImportError as exc:
        raise ValueError(f"Install the finqa-scoring dependency group: {exc}") from exc
    return scorer


def _prediction(outcome: dict[str, Any], table: list[list[str]]) -> list[str]:
    tokens: list[str] = []
    if outcome["status"] != "executed":
        return ["EOF"]
    for op, left, right in outcome["program"]:
        if op in REDUCTIONS:
            row = table[int(left.removeprefix("table_"))]
            left = row[0]
            # The upstream parser strips whitespace and treats these characters as syntax.
            if not left or left.strip() != left or any(char in left for char in "#|()"):
                raise ValueError(f"Upstream scorer cannot represent table row label {left!r}")
            if any(other and other[0] == left and other[1:] != row[1:] for other in table):
                raise ValueError(f"Upstream scorer cannot uniquely address table row label {left!r}")
        else:
            left, right = left.replace("−", "-"), right.replace("−", "-")
        tokens.extend((f"{op}(", left, right, ")"))
    return [*tokens, "EOF"]


def _upstream_case(
    scorer: dict[str, Any], tokens: list[str], row: dict[str, Any],
) -> dict[str, Any]:
    qa = row["qa"]
    invalid, value = scorer["eval_program"](tokens, row["table"])
    gold = scorer["program_tokenization"](qa["program"])
    execution_match = invalid == 0 and value == qa["exe_ans"]
    if isinstance(value, complex) or (isinstance(value, float) and not math.isfinite(value)):
        value = str(value)
    return {
        "invalid_flag": invalid, "value": value,
        "execution_match": execution_match,
        "program_match": bool(scorer["equal_program"](gold, tokens)),
    }


def score_cases(
    scorer_path: Path, expected_hash: str, cases: dict[str, dict[str, Any]], rows: list[dict[str, Any]],
) -> dict[str, Any]:
    scorer = _load_scorer(scorer_path, expected_hash)
    predictions = []
    comparisons = []
    statuses: Counter[str] = Counter()
    execution_matches = program_matches = 0
    for row in rows:
        case_id = row["id"]
        case = cases[case_id]
        outcome = case["outcome"]
        status = outcome["status"]
        statuses[status] += 1
        discrepancies = []
        try:
            tokens = _prediction(outcome, row["table"])
        except ValueError as exc:
            discrepancies.append(str(exc))
            tokens = ["EOF"]
        predictions.append({"id": case_id, "predicted": tokens})
        upstream = None
        try:
            with redirect_stdout(StringIO()):
                upstream = _upstream_case(scorer, tokens, row)
        except Exception as exc:
            discrepancies.append(f"Upstream case scorer failed ({type(exc).__name__}): {exc}")
        if upstream is not None:
            if tokens != ["EOF"] and (upstream["invalid_flag"] or upstream["value"] != outcome["value"]):
                discrepancies.append("Upstream execution differs from the replayed result")
            if upstream["execution_match"] != case["internal_answer_match"]:
                discrepancies.append("Upstream execution match differs from the internal answer match")
            execution_matches += upstream["execution_match"]
            program_matches += upstream["program_match"]
        comparisons.append({
            "id": case_id, "status": status, "outcome": outcome, "reference": case["reference"],
            "upstream": upstream, "discrepancies": discrepancies,
        })

    log = StringIO()
    discrepancies = []
    execution_accuracy = program_accuracy = None
    with TemporaryDirectory(prefix="frag-finqa-score-") as directory:
        predictions_path = Path(directory) / "predictions.json"
        references_path = Path(directory) / "references.json"
        predictions_path.write_text(json.dumps(predictions), encoding="utf-8")
        references_path.write_text(json.dumps(rows), encoding="utf-8")
        try:
            with redirect_stdout(log):
                execution_accuracy, program_accuracy = scorer["evaluate_result"](predictions_path, references_path)
        except Exception as exc:
            discrepancies.append(f"Upstream cohort scorer failed ({type(exc).__name__}): {exc}")
        else:
            if (execution_accuracy, program_accuracy) != (execution_matches / len(rows), program_matches / len(rows)):
                discrepancies.append("Upstream aggregate scores differ from the per-case totals")
    parity = "unresolved" if discrepancies or any(case["discrepancies"] for case in comparisons) else "verified"
    return {
        "summary": {
            "score_label": "internal", "parity": parity, "denominator": len(rows),
            "statuses": dict(statuses), "execution_matches": execution_matches, "program_matches": program_matches,
            "upstream_execution_accuracy": execution_accuracy, "upstream_program_accuracy": program_accuracy,
        },
        "predictions": predictions, "cases": comparisons, "discrepancies": discrepancies,
        "upstream_log": log.getvalue(),
    }
