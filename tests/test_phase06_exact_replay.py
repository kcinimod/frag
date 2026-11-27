"""Exercise the Phase 6 acceptance entry points with a sealed synthetic cohort."""

from copy import deepcopy
import gzip
from hashlib import sha256
import json
from pathlib import Path
from shutil import copy2, copytree
import subprocess
import sys
from typing import Any
from zipfile import ZipFile

import pytest

from frag.cli import main as frag
from frag.local_model import InvalidModelResponse, ModelUnavailable
from frag.store import SourceStore

ROOT = Path(__file__).resolve().parents[1]
PHASE = Path("artifacts/phase06")

PREPARE = """
import sys
from pathlib import Path
sys.path.insert(0, str(Path("artifacts/phase06").resolve()))
from fresh_run import PHASE, ask_case, configuration, digest, read_json, settings, stage_inputs, write_json
from sec_holdout_runner import ingest

# The synthetic freeze uses the interpreter and dependencies running the test.
historical = PHASE.with_name("phase05") / "holdout-freeze.json"
baseline = read_json(historical) | settings(None)
historical.unlink()
write_json(historical, baseline)
freeze = configuration() | {"scoring_files": {}}
write_json(Path("freeze.json"), freeze)
manifest_hash = stage_inputs(Path("inputs.zip"), Path("staged"), freeze["receipt"])
manifest = read_json(Path("staged/artifacts/phase05/inputs.json"))
sources = {}
rows = []
from zipfile import ZipFile
with ZipFile("inputs.zip") as inputs:
    for filing, case in zip(manifest["sources"], manifest["cases"], strict=True):
        key = filing["source_id"]
        original = Path(filing["original_filename"])
        original.write_bytes(inputs.read(filing["path"]))
        source = ingest(Path("store"), original, filing)
        source.pop("original_path", None)
        if "provenance" in source:
            source["provenance"].pop("input_path")
            source["provenance"].pop("preserved_at")
        sources[key] = {"evidence": source}
        cold = ask_case(Path("store"), case, source, Path("cold.json"))
        warm = ask_case(Path("store"), case, source, Path("warm.json"))
        rows.append({"case": case, "cold": cold, "warm": warm,
                     "peak_working_set_mib": {"runner": 1, "planner": 1}, "peak_device_vram_mib": 0})
write_json(Path("live.json"), {
    "binding": {"freeze_sha256": digest(Path("freeze.json")), "manifest_sha256": manifest_hash,
                "runner_sha256": digest(Path("inputs.zip"))},
    "freeze": freeze, "sources": sources, "cases": rows,
})
"""


@pytest.fixture
def cohort(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    snapshot = tmp_path / "runner"
    copytree(ROOT / "src/frag", snapshot / "src/frag", ignore=lambda *_: ["__pycache__"])
    files = [
        "pyproject.toml", "uv.lock", "scripts/start-local-model.ps1", "scripts/setup-local-model.ps1",
        "artifacts/phase04/SEC_ACCEPTANCE_PROTOCOL.md",
        "artifacts/phase04/sec-holdout-receipt.json",
        "artifacts/phase04/sec_holdout_runner.py", "artifacts/phase04/sec_holdout_score.py",
        "artifacts/phase05/baseline.py", "artifacts/phase05/holdout.py", "artifacts/phase05/score.py",
        "artifacts/phase05/custody.json", "artifacts/phase05/holdout-freeze.json",
        *(str(PHASE / name) for name in ("fresh_run.py", "exact_replay.py", "EXACT_REPLAY.md",
                                         "DEVELOPMENT_LAYOUTS.md", "gate-score.json")),
    ]
    for name in files:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        copy2(ROOT / name, target)

    manifest: dict[str, Any] = {"cohort": "synthetic-exact-replay", "sources": [], "cases": []}
    expected: dict[str, Any] = {"cohort": manifest["cohort"], "sources": {}, "cases": {}}
    with ZipFile(snapshot / "inputs.zip", "w") as inputs:
        for cik, original in [(1, b""), (2, b"<html><body>Synthetic clarification control</body></html>")]:
            accession = f"{cik:010}-24-000001"
            filename = f"synthetic-{cik}.html"
            manifest["sources"].append({
                "cik": cik, "source_id": accession, "accession": accession, "form": "10-K",
                "original_filename": filename, "path": filename, "issuer": f"Synthetic {cik}",
                "filing_date": "2024-01-01", "source_url": f"https://www.sec.gov/Archives/{filename}",
                "sha256": sha256(original).hexdigest(), "byte_length": len(original),
            })
            case_id = f"synthetic-{cik}"
            manifest["cases"].append({"case_id": case_id, "source_id": accession, "question": "What was revenue?"})
            expected["sources"][accession] = {"locators": {}, "facts": {}, "applicable_notes": []}
            expected["cases"][case_id] = {
                "source_id": accession, "kind": "lookup", "years": [2024], "outcome": "answerable",
            }
            inputs.writestr(filename, original)
        inputs.writestr("manifest.json", json.dumps(manifest))
    expected_path = tmp_path / "expected.zip"
    with ZipFile(expected_path, "w") as archive:
        archive.writestr("expected.json", json.dumps(expected))
    receipt = {
        "cohort": manifest["cohort"], "case_count": 2, "original_count": 2, "issuer_count": 2,
        "observation_count": 0, "case_counts_by_outcome": {"answerable": 2},
        "runner_bundle": {"sha256": sha256((snapshot / "inputs.zip").read_bytes()).hexdigest()},
        "scorer_bundle": {"sha256": sha256(expected_path.read_bytes()).hexdigest()},
        "development_gate_record_sha256": sha256((snapshot / PHASE / "gate-score.json").read_bytes()).hexdigest(),
        "development_layout_inventory_sha256": sha256(
            (snapshot / PHASE / "DEVELOPMENT_LAYOUTS.md").read_bytes(),
        ).hexdigest(),
    }
    (snapshot / PHASE / "sec-holdout-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    prepared = subprocess.run([sys.executable, "-c", PREPARE], cwd=snapshot, capture_output=True, text=True)
    assert prepared.returncode == 0, prepared.stderr
    return snapshot, expected_path, json.loads((snapshot / "live.json").read_bytes())


@pytest.mark.parametrize(
    ("fault", "changed_payload"),
    [(None, None), ("add_failure_field", "result"), ("change_failure_field", "result"),
     ("open_extra_citation", "citations")],
)
def test_acceptance_replay_and_score_require_complete_payload_equality(
    cohort: tuple[Path, Path, dict[str, Any]], fault: str | None, changed_payload: str | None,
) -> None:
    snapshot, expected, live = cohort
    failure, clarification = live["cases"]
    assert failure["cold"]["result"] == {"status": "ingestion_failed"}
    assert clarification["warm"]["result"]["status"] == "clarify"
    expected_failure = deepcopy(failure["cold"])
    if fault == "add_failure_field":
        failure["cold"]["result"]["detail"] = "Synthetic changed failure detail"
    elif fault == "change_failure_field":
        failure["cold"]["result"]["status"] = "other_failure"
    elif fault == "open_extra_citation":
        failure["cold"]["citations"]["extra"] = {"http_status": 200, "path": "/synthetic", "text": "synthetic"}
    (snapshot / "live.json").write_text(json.dumps(live), encoding="utf-8")
    runner = subprocess.run(
        [sys.executable, str(PHASE / "fresh_run.py"), "replay", "freeze.json", "--inputs", "inputs.zip",
         "--saved-run", "live.json", "--work", "replay"], cwd=snapshot, capture_output=True, text=True,
    )
    exit_code = 2 if fault else 0
    assert runner.returncode == exit_code, runner.stderr
    assert ("3/4" if fault else "4/4") in runner.stdout
    replay_file = snapshot / "replay/report.json"
    replay = json.loads(replay_file.read_bytes())
    for index, row in enumerate(replay["cases"]):
        for mode in ("cold", "warm"):
            repeated = row[mode]
            changed = changed_payload is not None and index == 0 and mode == "cold"
            original = expected_failure if changed else live["cases"][index][mode]
            assert repeated["result"] == original["result"]
            assert repeated["citations"] == original["citations"]
            assert repeated["status"] == ("mismatch" if changed else "matched")
            if changed:
                assert repeated["differing_payloads"] == [changed_payload]

    # Isolate the replay requirement in the synthetic score. The runner above
    # uses its normal freeze, while these counters require only exact replay.
    freeze_path = snapshot / "score-freeze.json"
    live["freeze"]["thresholds_per_pass"] = {"supported_answers": 0, "grounded_abstentions": 0, "exact_replay": 2}
    freeze_path.write_text(json.dumps(live["freeze"]), encoding="utf-8")
    live["binding"]["freeze_sha256"] = sha256(freeze_path.read_bytes()).hexdigest()
    live_path = snapshot / "live.json"
    live_path.write_text(json.dumps(live), encoding="utf-8")
    replay.update(freeze=live["freeze"], binding=live["binding"], live_sha256=sha256(live_path.read_bytes()).hexdigest())
    if fault:
        # A forged status still cannot turn unequal payloads into score credit.
        replay["cases"][0]["cold"]["status"] = "matched"
    replay_file.write_text(json.dumps(replay), encoding="utf-8")
    score_path = snapshot / "score.json"
    scored = subprocess.run(
        [sys.executable, str(ROOT / PHASE / "fresh_score_v2.py"), str(freeze_path),
         str(snapshot / "inputs.zip"), str(expected), str(live_path), str(replay_file), str(score_path)],
        cwd=snapshot, capture_output=True, text=True,
    )
    assert scored.returncode == exit_code, scored.stderr
    score = json.loads(score_path.read_bytes())
    assert score["passed"] is (fault is None)
    assert score["cold"]["metrics"]["offline_replay"] == ([1, 2] if fault else [2, 2])
    assert score["warm"]["metrics"]["offline_replay"] == [2, 2]
    assert ("offline_replay_mismatch" in score["cold"]["cases"][0]["findings"]) is (fault is not None)


@pytest.mark.parametrize(
    ("error", "status"),
    [(ModelUnavailable(), "model_unavailable"), (TimeoutError(), "model_timeout"),
     (InvalidModelResponse(), "invalid_plan")],
)
def test_recorded_planner_failure_replays_without_opening_a_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    error: Exception, status: str,
) -> None:
    def fail_planner(payload: dict[str, Any]) -> str:
        raise error

    def deny_socket(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Replay attempted to create a socket.")

    store = SourceStore(tmp_path / "store")
    archive = ROOT / "artifacts/phase01/originals/msft-20230630.htm.gz"
    source = store.ingest_bytes(gzip.decompress(archive.read_bytes()), provenance="local_original")
    saved = str(tmp_path / "record.json")
    monkeypatch.setattr("frag.cli.propose_lookup", fail_planner)
    assert frag(["ask", source["source_id"], "What was revenue in FY2023?",
                 "--store", str(store.root), "--record", saved]) == 0
    live = json.loads(capsys.readouterr().out)
    assert live["status"] == status

    monkeypatch.setattr("socket.socket", deny_socket)
    assert frag(["replay-ask", saved, "--store", str(store.root)]) == 0
    assert json.loads(capsys.readouterr().out) == live
