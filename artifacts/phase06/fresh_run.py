"""Freeze, measure, or replay the label-blind Phase 6 SEC runner."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import platform
import subprocess
import sys

PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path.insert(0, str(PHASE.with_name("phase05")))

from baseline import GPU_QUERY, evaluate, server_command, settings
from holdout import stage_inputs
from sec_holdout_runner import digest, local_model, read_json, restrict_runner, runtime_hashes, write_json

PRODUCTION = "208cca1e410a0811cba600ad93753b53b42cc43a"
GATE_PRODUCTION = "d5ea2c36af63bb64b30721ceb94cb26236dc4b0a"
SCORING_FILES = (
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
    for name in (Path(__file__), PHASE / "FRESH_PROTOCOL.md", PHASE / "acceptance.ps1", receipt_path, gate,
                 layout, historical, ROOT / "artifacts/phase05/custody.json",
                 ROOT / "artifacts/phase05/holdout.py"):
        config["files"][name.relative_to(ROOT).as_posix()] = digest(name)
    return {
        **config, "production_revision": PRODUCTION, "development_gate_revision": GATE_PRODUCTION,
        "thresholds_per_pass": {"supported_answers": 11, "grounded_abstentions": 3, "exact_replay": 15},
        "receipt": receipt, "runtime_files": baseline["runtime_files"], "port": baseline["port"],
    }


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
    report = evaluate(data, args.work / "run", frozen, args.model, previous)
    report["binding"] = binding
    if replay:
        report["live_sha256"] = digest(args.saved_run)
    write_json(args.work / "report.json", report)
    if replay:
        matches = sum(row[mode]["status"] == "matched" for row in report["cases"] for mode in ("cold", "warm"))
        print(f"{matches}/{2 * len(report['cases'])} cold and warm results and citation sets matched")
    else:
        print(f"Measured {len(report['cases'])} cases, cold and warm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
