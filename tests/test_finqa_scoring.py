import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from frag import finqa


# Synthetic examples with independently worked answers. Only the evaluator is upstream.
CASES = [
    ("add", [["add", "7", "12"]], "add(12, 7)", 19, True),
    ("subtract", [["subtract", "12", "7"]], "subtract(12, 7)", 5, True),
    ("multiply", [["multiply", "25%", "12"]], "multiply(25%, 12)", 3, True),
    ("divide", [["subtract", "12", "7"], ["divide", "#0", "2"]],
     "divide(5, 2)", 2.5, False),
    ("exp", [["exp", "7", "const_2"]], "exp(7, const_2)", 49, True),
    ("greater-no", [["greater", "25%", "2"]], "greater(25%, 2)", "no", True),
    ("greater-yes", [["greater", "12", "7"]], "greater(12, 7)", "yes", True),
    ("max", [["table_max", "table_1", "none"]], "table_max(Net sales, none)", 12, True),
    ("min", [["table_min", "table_1", "none"]], "table_min(Net sales, none)", -2, True),
    ("sum", [["table_sum", "table_1", "none"]], "table_sum(Net sales, none)", 10, True),
    ("average", [["table_average", "table_1", "none"]], "table_average(Net sales, none)", 5, True),
    ("invalid", [["add", "999", "7"]], "add(12, 7)", 19, False),
    ("failure", [["divide", "12", "0"]], "divide(12, 2)", 6, False),
    ("abstained", [], "divide(12, 2)", 6, False),
]


@pytest.fixture
def diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    request: pytest.FixtureRequest,
) -> tuple[Path, Path, Path, Path]:
    rows: list[dict[str, Any]] = [{
        "id": case_id, "filename": "synthetic.pdf",
        "pre_text": ["The amounts were 12, 7 and 2. The rate was 25%. The offset was 0."],
        "post_text": [], "table": [["Year", "2025", "2024"], ["Net sales", "$12", "-2 (a)"]],
        "qa": {"question": f"Synthetic example {case_id}", "gold_inds": {"table_1": "", "text_0": ""},
               "exe_ans": answer, "program": reference},
    } for case_id, _, reference, answer, _ in CASES]
    if getattr(request, "param", None) == "ambiguous-row":
        next(row for row in rows if row["id"] == "max")["table"].append(["Net sales", "4", "1"])
    hashes = {}
    for name, data in {"train.json": [], "test.json": [], "dev.json": rows}.items():
        raw = json.dumps(data).encode()
        (tmp_path / name).write_bytes(raw)
        hashes[name] = sha256(raw).hexdigest()
    monkeypatch.setattr(finqa, "INPUT_HASHES", hashes)
    proposals = iter(json.dumps({"program": program}) for _, program, *_ in CASES)

    def planner(payload: dict[str, Any]) -> str:
        # Model boundary. The CLI still builds and validates the production benchmark prompt.
        assert "Net sales" in payload["messages"][1]["content"]
        return next(proposals)

    monkeypatch.setattr(finqa, "propose_lookup", planner)
    cohort = tmp_path / "cohort.json"
    cohort.write_text(json.dumps([row["id"] for row in rows]), encoding="utf-8")
    record = tmp_path / "run.json"
    report = tmp_path / "report.json"
    assert finqa.main(["run", str(tmp_path), str(record), "--cohort", str(cohort)]) == 0
    capsys.readouterr()
    return tmp_path, record, report, cohort


@pytest.fixture
def pinned_scorer() -> bytes:
    scorer = Path("build/finqa/evaluate.py")
    if not scorer.is_file():
        pytest.skip("Acquire the pinned evaluator using FINQA_DIAGNOSTIC.md")
    for dependency in ("numpy", "sympy", "tqdm"):
        pytest.importorskip(dependency)
    return scorer.read_bytes()


def test_pinned_evaluator_scores_all_benchmark_operations_and_counts_failures(
    diagnostic: tuple[Path, Path, Path, Path], pinned_scorer: bytes,
) -> None:
    cache, record, report, cohort = diagnostic
    (cache / "evaluate.py").write_bytes(pinned_scorer)
    assert finqa.main(["score", str(cache), str(record), str(report), "--cohort", str(cohort)]) == 0
    result = json.loads(report.read_bytes())
    assert result["summary"] == {
        "score_label": "internal", "parity": "verified", "denominator": 14,
        "execution_matches": 11, "program_matches": 10,
        "upstream_execution_accuracy": 11 / 14, "upstream_program_accuracy": 10 / 14,
        "statuses": {"executed": 11, "invalid_plan": 1, "execution_failure": 1, "abstained": 1},
    }
    for case, prediction, (case_id, _, _, value, program_match) in zip(
        result["cases"], result["predictions"], CASES, strict=True,
    ):
        assert case["id"] == prediction["id"] == case_id
        assert case["upstream"]["program_match"] is program_match
        if case_id in {"invalid", "failure", "abstained"}:
            assert prediction["predicted"] == ["EOF"]
            assert case["upstream"]["execution_match"] is False
        else:
            assert case["upstream"]["value"] == value
            assert case["upstream"]["execution_match"] is True
        assert case["discrepancies"] == []
    assert result["predictions"][2]["predicted"] == ["multiply(", "25%", "12", ")", "EOF"]
    assert result["predictions"][7]["predicted"] == ["table_max(", "Net sales", "none", ")", "EOF"]


@pytest.mark.parametrize("diagnostic", ["ambiguous-row"], indirect=True)
def test_ambiguous_upstream_table_label_is_recorded_as_a_parity_discrepancy(
    diagnostic: tuple[Path, Path, Path, Path], pinned_scorer: bytes,
) -> None:
    cache, record, report, cohort = diagnostic
    (cache / "evaluate.py").write_bytes(pinned_scorer)
    assert finqa.main(["score", str(cache), str(record), str(report), "--cohort", str(cohort)]) == 0
    result = json.loads(report.read_bytes())
    assert result["summary"]["parity"] == "unresolved"
    assert result["summary"]["score_label"] == "internal"
    assert result["summary"]["denominator"] == 14
    assert result["summary"]["execution_matches"] == 10
    case = next(case for case in result["cases"] if case["id"] == "max")
    assert case["status"] == "executed"
    assert case["outcome"]["value"] == 12
    assert not case["upstream"]["execution_match"]
    assert any("cannot uniquely address" in reason for reason in case["discrepancies"])


def test_score_rejects_an_evaluator_whose_hash_differs(
    diagnostic: tuple[Path, Path, Path, Path], capsys: pytest.CaptureFixture[str],
) -> None:
    cache, record, report, cohort = diagnostic
    (cache / "evaluate.py").write_text('raise RuntimeError("Unexpected evaluator execution")', encoding="utf-8")
    assert finqa.main(["score", str(cache), str(record), str(report), "--cohort", str(cohort)]) == 1
    assert "evaluate.py does not match the pinned SHA-256" in capsys.readouterr().err
    assert not report.exists()


@pytest.mark.parametrize(("tamper", "error"), [
    ("missing", "missing IDs"),
    ("unexpected", "unexpected IDs ['abstained']"),
    ("duplicate-outcome", "duplicate outcome IDs"),
    ("duplicate-cohort", "unique question IDs"),
])
def test_score_checks_cohort_against_outcomes_before_invoking_scorer(
    diagnostic: tuple[Path, Path, Path, Path], capsys: pytest.CaptureFixture[str],
    tamper: str, error: str,
) -> None:
    cache, record, report, cohort = diagnostic
    saved = json.loads(record.read_bytes())
    if tamper == "missing":
        saved["cases"].pop()
        saved["cohort_ids"].pop()
    elif tamper == "duplicate-outcome":
        saved["cases"].append(saved["cases"][0])
    elif tamper == "unexpected":
        cohort.write_text(json.dumps(saved["cohort_ids"][:-1]), encoding="utf-8")
    else:
        cohort.write_text('["add", "add"]', encoding="utf-8")
    record.write_text(json.dumps(saved), encoding="utf-8")
    assert finqa.main(["score", str(cache), str(record), str(report), "--cohort", str(cohort)]) == 1
    assert error in capsys.readouterr().err
    assert not report.exists()
