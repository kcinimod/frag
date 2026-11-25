"""Phase 5 acceptance controls using retained development records."""

import gzip
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import pytest

PHASE = Path("artifacts/phase05")
ROOT = Path(__file__).resolve().parents[1]


def retained(name: str) -> dict[str, Any]:
    report: dict[str, Any] = json.loads(gzip.decompress((ROOT / PHASE / f"{name}.json.gz").read_bytes()))
    return report


@pytest.mark.parametrize(
    ("case_id", "fault", "finding"),
    [
        ("aapl-lookup", "amount", "wrong_answer"),
        ("aapl-lookup", "currency", "wrong_answer"),
        ("aapl-lookup", "scale", "wrong_answer"),
        ("aapl-lookup", "period", "wrong_answer"),
        ("aapl-growth", "percent", "wrong_answer"),
        ("aapl-growth", "percent_unit", "wrong_answer"),
        ("aapl-growth", "trace", "wrong_answer"),
        ("aapl-growth", "growth_basis", "wrong_answer"),
        ("aapl-absent", "partial_amount", "unsupported_partial"),
        ("aapl-absent", "partial_note", "unsupported_citation"),
        ("aapl-absent", "unopened_periods", "unsupported_citation"),
        ("aapl-absent", "extra_link", "unsupported_citation"),
        ("intc-incompatible", "missing_year", "contradicted_abstention"),
        ("intc-incompatible", "abstention_text", "contradicted_abstention"),
        ("aapl-2024-present", "lookup_missing_year", "contradicted_abstention"),
        ("aapl-2024-present", "lookup_altered_reason", "contradicted_abstention"),
        ("aapl-lookup", "replay_result", "offline_replay_mismatch"),
        ("aapl-lookup", "replay_citation", "offline_replay_mismatch"),
    ],
)
def test_acceptance_controls(tmp_path: Path, case_id: str, fault: str, finding: str) -> None:
    live = retained("evidence-gap-live")
    replay = retained("evidence-gap-replay")
    saved = next(item for item in live["cases"] if item["case"]["case_id"] == case_id)
    row = saved["cold"]
    source_id = saved["case"]["source_id"]
    original_replay = next(item for item in replay["cases"] if item["case"]["case_id"] == case_id)
    result = row["result"]
    if fault == "amount":
        result["fact"]["normalized_amount"] = "383286000000"
    elif fault == "currency":
        result["fact"]["currency"] = "CAD"
    elif fault == "scale":
        result["fact"]["scale"] = 1_000
    elif fault == "period":
        result["fact"]["reporting_period"]["end"] = "2023-10-01"
    elif fault == "percent":
        result["percent"]["value"] = "-2.81"
    elif fault == "percent_unit":
        result["percent"]["unit"] = "USD"
    elif fault == "trace":
        result["trace"][1]["result"] = "999"
    elif fault == "growth_basis":
        claim = " The comparison uses constant-currency amounts."
        result["scope_caveats"][0] += claim
        for payload in (live, replay):
            payload["sources"][source_id]["evidence"]["comparison"]["scope_caveats"][0] += claim
    elif fault == "partial_amount":
        result["operands"][0]["raw_amount"] = "383,286"
    elif fault == "partial_note":
        row["citations"]["note-2"]["text"] += "Unsupported disclosure.\n"
    elif fault == "unopened_periods":
        row["citations"]["statement-periods"]["http_status"] = 404
    elif fault == "extra_link":
        extraneous = {**result["citations"][0], "id": "other"}
        result["citations"].append(extraneous)
        row["citations"]["other"] = {**row["citations"]["current"]}
        row["citations"]["other"]["path"] = row["citations"]["other"]["path"].replace("current?", "other?")
    elif fault == "missing_year":
        result["issues"].append({"code": "missing", "role": "prior", "fiscal_year": 2022,
                                 "detail": "FY2022 is missing."})
    elif fault == "abstention_text":
        result["issues"][0]["detail"] += " FY2022 is missing from the filing."
    elif fault == "lookup_missing_year":
        result["reason"] = "absent"
        result["message"] = "FY2024 is absent from the consolidated revenue statement."
    elif fault == "lookup_altered_reason":
        claim = "The statement lists only FY2021 through FY2023."
        result["message"] += f" {claim}"
        for payload in (live, replay):
            payload["sources"][source_id]["evidence"]["diagnostics"].append({"fiscal_year": 2024, "message": claim})
    else:
        key = "result" if fault == "replay_result" else "citations"
        original_replay["cold"] = {"status": "mismatch", key: {}}

    live_path, replay_path, report = (tmp_path / name for name in ("live.json", "replay.json", "score.json"))
    live_bytes = json.dumps(live).encode("utf-8")
    live_path.write_bytes(live_bytes)
    replay["live_sha256"] = sha256(live_bytes).hexdigest()
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    process = subprocess.run(
        [sys.executable, str(PHASE / "acceptance_score.py"), str(ROOT), str(live_path),
         str(replay_path), str(report)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert process.returncode == 1, process.stderr
    scored = json.loads(report.read_bytes())
    cold, warm = scored["cold"], scored["warm"]
    assert cold["metrics"]["end_to_end"] == [13 if case_id == "aapl-2024-present" else 12, 15]
    assert warm["metrics"]["end_to_end"] == [13, 15]
    selected = next(item for item in cold["cases"] if item["case_id"] == case_id)
    assert finding in selected["findings"]
    assert not selected["end_to_end_complete"]


@pytest.mark.parametrize("digest", [None, "0" * 64])
def test_replay_must_identify_the_saved_run(tmp_path: Path, digest: str | None) -> None:
    replay = retained("evidence-gap-replay")
    if digest is not None:
        replay["live_sha256"] = digest
    replay_path = tmp_path / "unbound-replay.json"
    replay_path.write_text(json.dumps(replay), encoding="utf-8")
    report = tmp_path / "score.json"
    process = subprocess.run(
        [sys.executable, str(PHASE / "acceptance_score.py"), str(ROOT),
         str(PHASE / "evidence-gap-live.json.gz"), str(replay_path), str(report)],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert process.returncode == 2
    assert "differ from the freeze" in process.stderr
    assert not report.exists()
