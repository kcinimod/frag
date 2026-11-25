"""Freeze, measure, and replay the sealed Phase 5 cohort on Windows."""

import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import platform
import re
import subprocess
from typing import Any
from zipfile import ZipFile

from baseline import GPU_QUERY, PHASE, evaluate, server_command, settings
from sec_holdout_runner import (
    ROOT, WEIGHTS_SHA256, digest, local_model, read_json, restrict_runner, runtime_hashes, write_json,
)

RECEIPT = ROOT / PHASE / "sec-holdout-receipt.json"
THRESHOLDS = {"supported_answers": 11, "grounded_abstentions": 3}
PRODUCTION = "67dce6d2232045542c91e42b3239bc6a868534d8"
SCORING_FILES = ("acceptance_score.py", "holdout_score.py")


def configuration(model: Path | None) -> dict[str, Any]:
    config = settings(None)
    for name in ("holdout.py", "HOLDOUT_PROTOCOL.md", "sec-holdout-receipt.json", "custody.json"):
        relative = PHASE / name
        config["files"][relative.as_posix()] = digest(ROOT / relative)
    if model is not None:
        if digest(model / "model.gguf") != WEIGHTS_SHA256:
            raise ValueError("Weights do not match the pinned development model.")
        config["runtime_files"] = runtime_hashes(model)
        config["gpu_sampler"] = str(Path(subprocess.check_output(
            ["where.exe", "nvidia-smi.exe"], text=True,
        ).splitlines()[0]).resolve())
    return {
        **config, "production_revision": PRODUCTION, "thresholds_per_pass": THRESHOLDS,
        "receipt": read_json(RECEIPT),
    }


def load_manifest(bundle: ZipFile, receipt: dict[str, Any]) -> dict[str, Any]:
    manifest = json.loads(bundle.read("manifest.json"))
    sources, cases = manifest["sources"], manifest["cases"]
    source_ids = {item["source_id"] for item in sources}
    cik_set = {int(item["cik"]) for item in sources}
    filenames = {item["path"] for item in sources}
    excluded = {int(cik) for cik in read_json(ROOT / PHASE / "custody.json")["development_ciks"]}
    references = [
        read_json(path)["identity"] for path in (ROOT / "src/frag").glob("*-reference.json")
    ]
    if (manifest["cohort"] != receipt["cohort"]
            or len(cases) != receipt["case_count"]
            or len({case["case_id"] for case in cases}) != len(cases)
            or len(sources) != len(source_ids) or len(sources) != len(filenames)
            or len(sources) != receipt["original_count"] or len(cik_set) != receipt["issuer_count"]
            or cik_set & excluded or {case["source_id"] for case in cases} != source_ids
            or sorted(bundle.namelist()) != sorted(["manifest.json", *filenames])):
        raise ValueError("Sealed manifest source or case coverage differs from its receipt.")
    if any(set(case) != {"case_id", "source_id", "question"}
           or re.fullmatch(r"[\w.-]+", case["case_id"], re.ASCII) is None
           or case["case_id"] in {".", ".."} for case in cases):
        raise ValueError("Unexpected case identifier or scorer material.")
    for filing in sources:
        if (filing["form"] != "10-K" or filing["source_id"] != filing["accession"]
                or re.fullmatch(r"\d{10}-\d{2}-\d{6}", filing["source_id"]) is None
                or re.fullmatch(r"[\w.-]+\.html?", filing["original_filename"], re.ASCII) is None
                or any(int(filing["cik"]) == int(ref["cik"]) or filing["accession"] == ref["accession"]
                       or filing["sha256"] == ref["source_hash"] for ref in references)):
            raise ValueError("Unexpected filing identity or issuer-specific reviewed reference.")
    return manifest


def stage_inputs(inputs: Path, data: Path, receipt: dict[str, Any]) -> str:
    if digest(inputs) != receipt["runner_bundle"]["sha256"]:
        raise ValueError("Runner archive does not match the custody receipt.")
    with ZipFile(inputs) as bundle:
        manifest = load_manifest(bundle, receipt)
        manifest_hash = sha256(bundle.read("manifest.json")).hexdigest()
        (data / PHASE).mkdir(parents=True)
        for filing in manifest["sources"]:
            original = bundle.read(filing["path"])
            if sha256(original).hexdigest() != filing["sha256"] or len(original) != filing["byte_length"]:
                raise ValueError("Original bytes differ from the sealed manifest.")
            archive = PHASE / f'{filing["source_id"]}.htm.gz'
            compressed = gzip.compress(original, mtime=0)
            (data / archive).write_bytes(compressed)
            filing.update(archive=archive.as_posix(), archive_sha256=sha256(compressed).hexdigest())
        write_json(data / PHASE / "inputs.json", manifest)
    return manifest_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "live", "replay"))
    parser.add_argument("freeze", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--port", type=int, default=18089)
    parser.add_argument("--scoring", type=Path)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--saved-run", type=Path)
    args = parser.parse_args()
    replay = args.mode == "replay"
    if replay == bool(args.model):
        parser.error("Freeze and live modes require the pinned model. Replay runs offline.")
    config = configuration(args.model)
    if args.mode == "freeze":
        if args.scoring is None or not 1 <= args.port <= 65535:
            parser.error("Freeze requires scorer code and a dedicated planner port.")
        write_json(args.freeze, {
            **config, "port": args.port,
            "scoring_files": {name: digest(args.scoring / name) for name in SCORING_FILES},
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "platform": platform.platform(), "cpu": platform.processor(),
        })
        return 0
    if args.inputs is None or args.work is None or replay != bool(args.saved_run):
        parser.error("Run and replay require sealed inputs and fresh work. Replay requires the saved live report.")
    frozen = read_json(args.freeze)
    if any(frozen.get(key) != value for key, value in config.items()):
        parser.error("Code, settings, dependencies or model differ from the freeze.")
    local_model.PORT = frozen["port"]
    processes = ()
    if not replay:
        processes = tuple(map(subprocess.list2cmdline, (
            server_command(args.model, local_model.PORT),
            ["nvidia-smi", f"--query-gpu={GPU_QUERY}", "--format=csv,noheader,nounits"],
        )))
    restrict_runner(replay=replay, allowed_processes=processes)
    args.work.mkdir()
    data = args.work / "inputs"
    manifest_hash = stage_inputs(args.inputs, data, frozen["receipt"])
    binding = {
        "freeze_sha256": digest(args.freeze), "manifest_sha256": manifest_hash,
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
        total = 2 * len(report["cases"])
        print(f"{matches}/{total} cold and warm results and citations matched")
        return int(matches != total)
    print(f"Measured {len(report['cases'])} cases, cold and warm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
