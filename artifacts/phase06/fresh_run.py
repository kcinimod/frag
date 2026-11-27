"""Freeze, measure, or replay the label-blind Phase 6 SEC runner."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path.insert(0, str(PHASE.with_name("phase05")))

from baseline import GPU_QUERY, evaluate, server_command, settings
from exact_replay import PAYLOADS, differing_payloads
from holdout import stage_inputs
from sec_holdout_runner import (
    ask_case, command, digest, local_model, open_citations, read_json, restrict_runner, runtime_hashes, write_json,
)
from frag.lookup import resolve_request

GATE_PRODUCTION = "d5ea2c36af63bb64b30721ceb94cb26236dc4b0a"
SCORING_FILES = (
    "artifacts/phase06/fresh_score_v2.py", "artifacts/phase06/exact_replay.py",
    "artifacts/phase06/fresh_score.py", "artifacts/phase06/development_score.py",
    "artifacts/phase06/revenue_score.py", "artifacts/phase06/observations.py",
    "artifacts/phase05/acceptance_score.py", "artifacts/phase05/holdout_score.py",
    "artifacts/phase05/score.py", "artifacts/phase05/holdout-score.json", "artifacts/phase04/sec_holdout_score.py",
)


def configuration() -> dict:
    config = settings(None)
    receipt_path = PHASE / "sec-holdout-receipt.json"
    receipt = read_json(receipt_path)
    gate = PHASE / "gate-score.json"
    layout = PHASE / "DEVELOPMENT_LAYOUTS.md"
    if (digest(gate) != receipt["development_gate_record_sha256"] or not read_json(gate)["passed"]
            or digest(layout) != receipt["development_layout_inventory_sha256"]):
        raise ValueError("The required development gate or layout inventory differs from the custody receipt.")
    historical = ROOT / "artifacts/phase05/holdout-freeze.json"
    baseline = read_json(historical)
    for field in ("python", "dependencies", "model", "weights_sha256", "retrieval"):
        if config[field] != baseline[field]:
            raise ValueError(f"{field} differs from the development gate baseline.")
    for name in (Path(__file__), PHASE / "exact_replay.py", PHASE / "EXACT_REPLAY.md",
                 PHASE / "acceptance.ps1", receipt_path, gate, layout, historical, ROOT / "artifacts/phase05/custody.json",
                 ROOT / "artifacts/phase05/holdout.py"):
        config["files"][name.relative_to(ROOT).as_posix()] = digest(name)
    return {
        **config, "replay_protocol": "complete-payloads", "development_gate_revision": GATE_PRODUCTION,
        "thresholds_per_pass": {"supported_answers": 11, "grounded_abstentions": 3, "exact_replay": 15},
        "receipt": receipt, "runtime_files": baseline["runtime_files"], "port": baseline["port"],
    }


def block_socket_creation(event: str, args: tuple[Any, ...]) -> None:
    if event == "socket.__new__":
        raise PermissionError("Sockets are blocked during offline replay.")


def replay_question(
    store: Path, case: dict[str, Any], source: dict[str, Any], saved: dict[str, Any],
) -> dict[str, Any]:
    record_path = store.parent / f'{case["case_id"]}.json'
    record = saved.get("record")
    expected = saved.get("result")
    if ("command_error" in source or resolve_request(case["question"]) is None
            or (record is None and isinstance(expected, dict) and "command_error" in expected)):
        outcome = ask_case(store, case, source, record_path)
        payloads = {field: outcome[field] for field in PAYLOADS}
    elif isinstance(record, dict) and record.get("question") == case["question"]:
        write_json(record_path, record)
        result = command("replay-ask", str(record_path), "--store", str(store))
        payloads = {"result": result, "citations": open_citations(store, result)}
    else:
        return {"status": "mismatch", "replay_error": "No validation record for the manifest question."}
    differences = differing_payloads(saved, payloads)
    if differences:
        return {"status": "mismatch", **payloads, "differing_payloads": differences}
    return {"status": "matched", **payloads}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "live", "replay"))
    parser.add_argument("freeze", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--scoring", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--saved-run", type=Path)
    args = parser.parse_args()
    replay = args.mode == "replay"
    if replay == bool(args.model):
        parser.error("Freeze and live require the pinned model. Replay runs offline.")
    config = configuration()
    if args.model and (digest(args.model / "model.gguf") != config["weights_sha256"]
                       or runtime_hashes(args.model) != config["runtime_files"]):
        parser.error("Weights or runtime differ from the development gate baseline.")
    if args.mode == "freeze":
        if args.scoring is None or args.scoring.resolve().is_relative_to(ROOT):
            parser.error("Freeze requires the scorer in a separate workspace.")
        if any(digest(args.scoring / name) != config["files"][name]
               for name in config["files"] if name.startswith("src/")):
            parser.error("Scorer's production utilities differ from the runner snapshot.")
        write_json(args.freeze, {
            **config, "scoring_files": {name: digest(args.scoring / name) for name in SCORING_FILES},
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(), "cpu": platform.processor(),
            "gpu_sampler": subprocess.check_output(["where.exe", "nvidia-smi.exe"], text=True).splitlines()[0],
        })
        return 0
    if args.inputs is None or args.work is None or replay != bool(args.saved_run):
        parser.error("Run and replay require sealed inputs and fresh work. Replay requires the live report.")
    frozen = read_json(args.freeze)
    if any(frozen.get(key) != value for key, value in config.items()):
        parser.error("Code, settings, dependencies or runtime differ from the freeze.")
    local_model.PORT = frozen["port"]
    processes = () if replay else tuple(map(subprocess.list2cmdline, (
        server_command(args.model, local_model.PORT),
        ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
    )))
    restrict_runner(replay=replay, allowed_processes=processes)
    if replay:
        sys.addaudithook(block_socket_creation)
    args.work.mkdir()
    data = args.work / "inputs"
    binding = {
        "freeze_sha256": digest(args.freeze),
        "manifest_sha256": stage_inputs(args.inputs, data, frozen["receipt"]),
        "runner_sha256": digest(args.inputs),
    }
    previous = read_json(args.saved_run) if replay else None
    if previous is not None and previous["binding"] != binding:
        parser.error("Saved run and frozen inputs differ.")
    report = evaluate(data, args.work / "run", frozen, args.model, previous,
                      replay_question=replay_question, require_equal_intake=False)
    report["binding"] = binding
    if previous is not None:
        report["live_sha256"] = digest(args.saved_run)
    write_json(args.work / "report.json", report)
    if replay:
        matches = sum(row[mode]["status"] == "matched" for row in report["cases"] for mode in ("cold", "warm"))
        total = 2 * len(report["cases"])
        print(f"{matches}/{total} cold and warm results and citation sets matched")
        if report["differing_intake_sources"]:
            print("Reingested evidence differs for " + ", ".join(report["differing_intake_sources"]))
        return 0 if matches == total and not report["differing_intake_sources"] else 2
    else:
        print(f"Measured {len(report['cases'])} cases, cold and warm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
