"""Measure or replay the opened and earlier Phase 6 development inputs."""

import argparse
from pathlib import Path
import subprocess
import sys

PHASE = Path(__file__).resolve().parent
sys.path.insert(0, str(PHASE.parent / "phase05"))

from holdout import stage_inputs
from baseline import GPU_QUERY, evaluate, server_command, settings
from sec_holdout_runner import digest, local_model, read_json, restrict_runner, runtime_hashes, write_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort", choices=("opened", "earlier"))
    parser.add_argument("work", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--model", type=Path)
    mode.add_argument("--live", type=Path)
    args = parser.parse_args()

    snapshot = PHASE.parents[1]
    data = snapshot
    historical_path = (PHASE.parent / "phase05/holdout-freeze.json" if args.cohort == "opened"
                       else PHASE / "earlier-freeze.json")
    historical = read_json(historical_path)
    config = settings(snapshot if args.cohort == "earlier" else None)
    for field in ("python", "dependencies", "model", "weights_sha256", "retrieval"):
        if config[field] != historical[field]:
            parser.error(f"{field} differs from the frozen baseline")
    if args.cohort == "earlier" and config["inputs_sha256"] != historical["inputs_sha256"]:
        parser.error("Earlier inputs differ from the frozen baseline")
    if args.model and (digest(args.model / "model.gguf") != historical["weights_sha256"]
                       or runtime_hashes(args.model) != historical["runtime_files"]):
        parser.error("Model weights or runtime differ from the frozen baseline")

    local_model.PORT = historical["port"]
    processes = ()
    if args.model:
        processes = tuple(map(subprocess.list2cmdline, (
            server_command(args.model, local_model.PORT),
            ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
        )))
    restrict_runner(replay=args.live is not None, allowed_processes=processes)
    args.work.mkdir()
    freeze = {**config, "baseline_freeze_sha256": digest(historical_path),
              "runtime_files": historical["runtime_files"], "port": local_model.PORT,
              "runner_sha256": digest(Path(__file__))}
    if args.cohort == "opened":
        data = args.work / "inputs"
        freeze["manifest_sha256"] = stage_inputs(snapshot / "opened-inputs.zip", data, historical["receipt"])
        freeze["inputs_sha256"] = historical["receipt"]["runner_bundle"]["sha256"]

    previous = read_json(args.live) if args.live else None
    report = evaluate(data, args.work / "run", freeze, args.model, previous)
    if args.live:
        report["live_sha256"] = digest(args.live)
    write_json(args.work / "report.json", report)
    if args.live:
        matches = sum(row[mode]["status"] == "matched" for row in report["cases"] for mode in ("cold", "warm"))
        total = 2 * len(report["cases"])
        print(f"{args.cohort}: {matches}/{total} cold and warm results and citations matched")
        return int(matches != total)
    print(f"{args.cohort}: measured {len(report['cases'])} cases, cold and warm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
