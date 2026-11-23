import json
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from frag import finqa


@pytest.fixture
def synthetic_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    row = {
        "id": "synthetic-dev",
        "filename": "synthetic.pdf",
        "pre_text": ["Sales reached 12 and costs reached 7. The rate was 6.4 %.", "Distractor 999."],
        "post_text": ["The adjustment was 0."],
        "table": [["year", "2024", "2023"], ["sales", "12", "-13 ( 13 )"]],
        "qa": {
            "question": "How much did sales exceed costs?",
            "gold_inds": {
                "text_0": "ANNOTATION VALUE", "table_1": "ANNOTATION VALUE",
                "table_0": "ANNOTATION VALUE", "text_2": "ANNOTATION VALUE",
            },
            "exe_ans": 5.0, "answer": "REFERENCE ANSWER", "program": "REFERENCE PROGRAM",
            "model_input": "UPSTREAM MODEL INPUT",
        },
    }
    # The files are synthetic substitutes for the pinned inputs.
    for name, contents in {"train.json": [], "dev.json": [row], "test.json": []}.items():
        (tmp_path / name).write_text(json.dumps(contents), encoding="utf-8")
    monkeypatch.setattr(finqa, "INPUT_HASHES", {
        name: sha256((tmp_path / name).read_bytes()).hexdigest()
        for name in ("train.json", "dev.json", "test.json")
    })
    return tmp_path


def test_synthetic_diagnostic_delivers_only_annotated_source_and_replays(
    synthetic_cache: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    delivered: list[dict[str, Any]] = []

    def planner(payload: dict[str, Any]) -> str:
        delivered.append(payload)
        return '{"program":[["subtract","12","7"]]}'

    monkeypatch.setattr(finqa, "propose_lookup", planner)
    output = synthetic_cache / "run.json"
    assert finqa.main(["run", str(synthetic_cache), str(output), "--id", "synthetic-dev"]) == 0
    capsys.readouterr()
    record = json.loads(output.read_bytes())
    case = record["cases"][0]
    assert delivered == [case["planner_input"]]
    prompt = json.dumps(delivered)
    assert "Sales reached 12" in prompt
    assert "The adjustment was 0" in prompt
    context = json.loads(delivered[0]["messages"][1]["content"])
    assert [item["id"] for item in context["excerpts"]] == ["table_0", "text_0", "table_1", "text_2"]
    for excluded in ("999", "ANNOTATION VALUE", "REFERENCE", "UPSTREAM MODEL INPUT"):
        assert excluded not in prompt
    assert case["outcome"]["status"] == "executed"
    assert case["outcome"]["value"] == 5.0

    def unavailable(payload: dict[str, Any]) -> str:
        raise AssertionError("Replay called the model")

    monkeypatch.setattr(finqa, "propose_lookup", unavailable)
    assert finqa.main(["replay", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["replayed"] == 1

    record["upstream"]["split_sha256"]["dev.json"] = "changed"
    output.write_text(json.dumps(record), encoding="utf-8")
    assert finqa.main(["replay", str(output)]) == 1
    assert "pinned provenance" in capsys.readouterr().err


@pytest.mark.parametrize(("proposal", "status"), [
    ('{"program":[["subtract","999","7"]]}', "invalid_plan"),
    ('{"program":[["subtract","12.00000000000000001","7"]]}', "invalid_plan"),
    ('{"program":[],"program":[["subtract","12","7"]]}', "invalid_plan"),
    ('{"program":[["add","13","7"]]}', "invalid_plan"),
    ('{"program":[["add","6.4","7"]]}', "invalid_plan"),
    ('{"program":[["subtract","12","7"],["divide","#0","0"]]}', "execution_failure"),
    ('{"program":[]}', "abstained"),
])
def test_synthetic_diagnostic_keeps_plan_failures_in_the_replayed_cohort(
    synthetic_cache: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    proposal: str, status: str,
) -> None:
    monkeypatch.setattr(finqa, "propose_lookup", lambda payload: proposal)
    output = synthetic_cache / "run.json"
    assert finqa.main(["run", str(synthetic_cache), str(output), "--id", "synthetic-dev"]) == 0
    capsys.readouterr()
    record = json.loads(output.read_bytes())
    outcome = record["cases"][0]["outcome"]
    assert outcome["status"] == status
    if status == "execution_failure":
        assert outcome["trace"][0]["result"] == 5.0
        assert outcome["step"] == 1
    assert finqa.main(["replay", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)["summary"]
    assert summary == {"cases": 1, "score_label": "internal", "statuses": {status: 1}, "answer_matches": 0}
