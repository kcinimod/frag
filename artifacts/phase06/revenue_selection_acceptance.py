"""Freeze, run, and replay the issuer-disjoint #60 extraction comparison."""

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter, sleep
from typing import Any, Iterator
from uuid import uuid4
from zipfile import ZipFile

from revenue_selection_baseline import PHASE, ROOT, block_sockets, elapsed, json_bytes, peak_working_set_bytes
import revenue_selection_holdout as holdout
from revenue_selection_model import (
    CONTEXT_SIZE, MAX_RESPONSE_TOKENS, PROMPT_BYTE_LIMIT, ROW_FRAGMENT_BYTES, ROW_ID_GRAMMAR,
    RUNTIME_FINGERPRINT, STRATEGIES, SYSTEM_PROMPT, TABLE_CONTEXT_BYTES, TIMEOUT_SECONDS, WEIGHTS,
    LocalSelector, digest, filing_source, model_peak_working_set, select_revenue,
)
from revenue_selection_model_score import paired_outcomes, replay, submitted_rows

from frag.revenue_selection import filing_inventory
from frag.store import SourceMetadata

DEVELOPMENT_REVISION = "24fad0d5af1cfb8501c6b7caf06a407330f39046"
SETTINGS = {
    "context_tokens": CONTEXT_SIZE, "threads": 4, "batch_threads": 4, "parallel": 1,
    "gpu_layers": 99, "device": "Vulkan1", "port": 18160, "offline": True,
    "runtime_fingerprint": RUNTIME_FINGERPRINT, "timeout_seconds": TIMEOUT_SECONDS,
    "temperature": 0, "seed": 0, "max_response_tokens": MAX_RESPONSE_TOKENS,
    "grammar": ROW_ID_GRAMMAR, "grammar_choices": "null and stable row IDs in each batch",
    "prompt": SYSTEM_PROMPT, "prompt_byte_limit": PROMPT_BYTE_LIMIT,
    "row_fragment_bytes": ROW_FRAGMENT_BYTES, "table_context_bytes": TABLE_CONTEXT_BYTES,
    "gpu_sample_interval_ms": 50,
}
GATE = {
    "require_strict_overall_improvement": True, "minimum_improved_issuer_families": 2,
    "maximum_incorrect_accepted": 0, "require_all_absent_target_abstentions": True,
    "exact": "reviewed statement, row, value, fiscal header, units, amount, full period, currency, scale and scope",
    "accepted": "every retained observation, including provisional; any non-exact or duplicate is penalized",
    "abstention": "no selected row, no observation, and a candidate or model abstention stop",
}
ABSTENTIONS = {"no_candidate", "ambiguous_candidates", "model_abstained"}


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def code_hashes(revision: str) -> dict[str, str]:
    paths = git("ls-tree", "-r", "--name-only", revision, "src/frag", "artifacts/phase04",
                "artifacts/phase05", "artifacts/phase06", "pyproject.toml", "uv.lock").decode().splitlines()
    paths = [path for path in paths if path.endswith((".py", ".toml", ".lock")) or path.startswith("src/frag/")]
    hashes = {}
    for path in paths:
        if path == "src/frag/local_model.py":
            # The workbench model adapter is outside this standalone experiment.
            continue
        data = git("show", f"{revision}:{path}").replace(b"\r\n", b"\n")
        if data != (ROOT / path).read_bytes().replace(b"\r\n", b"\n"):
            raise ValueError(f"Frozen code differs from the working copy: {path}")
        hashes[path] = sha256(data).hexdigest()
    return hashes


def gpu_identity() -> list[str]:
    return subprocess.check_output([
        "nvidia-smi", "--query-gpu=uuid,name,driver_version", "--format=csv,noheader",
    ], text=True, creationflags=subprocess.CREATE_NO_WINDOW).splitlines()


def runtime_hashes(runtime: Path) -> dict[str, str]:
    return {path.name: digest(path) for path in [runtime, *sorted(runtime.parent.glob("*.dll"))]}


def freeze(custody: Path, output: Path, runtime: Path, weights: Path) -> None:
    revision = git("rev-parse", "HEAD").decode().strip()
    hashes = code_hashes(revision)
    receipt = json.loads(holdout.RECEIPT.read_bytes())
    scorer = holdout.sealed(custody / "scorer/expected.zip", receipt["scorer_sha256"])
    with ZipFile(BytesIO(scorer)) as archive:
        preparation = json.loads(archive.read("development-inventory.json"))
    # The unchanged development revision predates all #60 evaluation tooling.
    changed = git("diff", "--name-only", receipt["preparation_base"], DEVELOPMENT_REVISION).decode().splitlines()
    output.mkdir(parents=True, exist_ok=False)
    inventory = output / "final-development-inventory.json"
    inventory.write_bytes(json_bytes({
        "development_revision": DEVELOPMENT_REVISION, "sources": preparation["sources"],
        "paths_changed_since_preparation": changed,
    }))
    holdout.verify(custody, [inventory], DEVELOPMENT_REVISION)
    if digest(weights) != WEIGHTS["sha256"]:
        raise ValueError("Weights differ from the pinned Qwen GGUF.")
    record = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "development_revision": DEVELOPMENT_REVISION,
        "evaluation_revision": revision, "code_sha256": hashes, "holdout": receipt,
        "final_development_inventory_sha256": digest(inventory), "issuer_independence_recheck": "passed",
        "settings": SETTINGS, "strategies": STRATEGIES, "weights": WEIGHTS, "runtime_sha256": runtime_hashes(runtime),
        "python": platform.python_version(), "windows": platform.platform(), "gpus": gpu_identity(), "gate": GATE,
    }
    (output / "freeze.json").write_bytes(json_bytes(record))


def cases(payload: bytes) -> Iterator[tuple[dict[str, Any], bytes, dict[str, Any]]]:
    with ZipFile(BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        for filing in manifest["sources"] + manifest["synthetic_inputs"]:
            original = archive.read(filing["path"])
            if (len(original), sha256(original).hexdigest()) != (filing["byte_length"], filing["sha256"]):
                raise ValueError("Original bytes differ from the sealed manifest.")
            source = filing_source(filing) if "cik" in filing else {
                **asdict(SourceMetadata(company=filing["issuer"])), "provenance": {"kind": "synthetic"},
            }
            yield filing, original, source


def worker(frozen: dict[str, Any], runner: Path, output: Path, strategy: str, runtime: Path, weights: Path) -> None:
    payload = holdout.sealed(runner, frozen["holdout"]["runner_sha256"])
    if strategy == "rules_alone":
        data = select_cases(payload, strategy, LocalSelector(SETTINGS["port"], "unused"))
    else:
        opts = frozen["settings"]
        alias = f"{WEIGHTS['alias']}-{uuid4().hex}"
        args = [
            "--offline", "--host", "127.0.0.1", "--port", str(opts["port"]), "--model", str(weights.resolve()),
            "--alias", alias, "--ctx-size", str(opts["context_tokens"]), "--threads", str(opts["threads"]),
            "--threads-batch", str(opts["batch_threads"]), "--n-gpu-layers", str(opts["gpu_layers"]),
            "--parallel", str(opts["parallel"]), "--device", opts["device"],
        ]
        with output.with_suffix(".log").open("xb") as log:
            start = perf_counter()
            process = subprocess.Popen([str(runtime.resolve()), *args], cwd=runtime.resolve().parent,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                selector = LocalSelector(opts["port"], alias)
                selector.wait_ready(process)
                startup = elapsed(start)
                data = select_cases(payload, strategy, selector)
                data.update(startup_ms=startup, model_peak_working_set_bytes=model_peak_working_set(process.pid))
            finally:
                process.terminate()
                process.wait(timeout=15)
    data["python_peak_working_set_bytes"] = peak_working_set_bytes()
    output.write_bytes(json_bytes(data))


def select_cases(payload: bytes, strategy: str, selector: LocalSelector) -> dict[str, Any]:
    records = {}
    for filing, original, source in cases(payload):
        start = perf_counter()
        inventory = filing_inventory(original)
        inventory_ms = elapsed(start)
        inventory_hash = digest_inventory(inventory.record())
        start = perf_counter()
        record = select_revenue(strategy, inventory, source, selector.propose)
        records[filing["source_id"]] = {
            **record, "original_sha256": inventory.original_sha256, "inventory_sha256": inventory_hash,
            "inventory_ms": inventory_ms, "selection_and_validation_ms": elapsed(start),
        }
        print(f"{strategy} {filing['source_id']}: {record['stop']}, {record['selected']}", flush=True)
    return {"cases": records}


def digest_inventory(tables: list[dict[str, Any]]) -> str:
    return sha256(json_bytes(tables)).hexdigest()


def measured_worker(
    freeze_path: Path, runner: Path, output: Path, strategy: str, runtime: Path, weights: Path,
) -> dict[str, Any]:
    raw_samples = output.with_suffix(".gpu.csv")
    with raw_samples.open("xb") as samples:
        sampler = subprocess.Popen([
            "nvidia-smi", "--query-gpu=timestamp,uuid,memory.used", "--format=csv,noheader,nounits",
            "--loop-ms", str(SETTINGS["gpu_sample_interval_ms"]),
        ], stdout=samples, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            for _ in range(100):
                if raw_samples.stat().st_size or sampler.poll() is not None:
                    break
                sleep(0.05)
            if not raw_samples.stat().st_size or sampler.poll() is not None:
                raise RuntimeError("NVIDIA device memory sampler did not start.")
            start = perf_counter()
            subprocess.run([sys.executable, __file__, "worker", str(freeze_path), str(runner), str(output),
                            strategy, str(runtime), str(weights)], check=True)
            wall = elapsed(start)
        finally:
            sampler.terminate()
            sampler.communicate(timeout=10)
    peaks: dict[str, list[int]] = {}
    for line in raw_samples.read_text().splitlines():
        _, uuid, used = line.split(", ")
        peaks.setdefault(uuid, []).append(int(used))
    data = json.loads(output.read_bytes())
    return {**data, "worker_wall_ms": wall, "gpu_sample_sha256": digest(raw_samples), "gpu_memory": {
        uuid: {"first_mib": values[0], "sampled_peak_mib": max(values), "samples": len(values)}
        for uuid, values in peaks.items()
    }}


def run(freeze_path: Path, runner: Path, output: Path, runtime: Path, weights: Path) -> None:
    frozen = json.loads(freeze_path.read_bytes())
    if (code_hashes(frozen["evaluation_revision"]) != frozen["code_sha256"]
            or frozen["settings"] != SETTINGS or frozen["weights"] != WEIGHTS
            or runtime_hashes(runtime) != frozen["runtime_sha256"] or digest(weights) != WEIGHTS["sha256"]
            or platform.python_version() != frozen["python"] or platform.platform() != frozen["windows"]
            or gpu_identity() != frozen["gpus"]):
        raise ValueError("Runner configuration differs from the freeze.")
    output.mkdir(parents=True, exist_ok=False)
    results = {strategy: measured_worker(freeze_path, runner, output / f"{strategy}.json", strategy, runtime, weights)
               for strategy in STRATEGIES}
    (output / "run.json.gz").write_bytes(gzip.compress(json_bytes({
        "freeze_sha256": digest(freeze_path), "runner_sha256": digest(runner), "strategies": results,
    }), mtime=0))


def score(freeze_path: Path, runner_path: Path, scorer_path: Path, run_path: Path) -> dict[str, Any]:
    from fresh_score import audit_observations
    from sec_holdout_score import position, within

    frozen = json.loads(freeze_path.read_bytes())
    report = json.loads(gzip.decompress(run_path.read_bytes()))
    receipt = frozen["holdout"]
    if (report["freeze_sha256"] != digest(freeze_path) or report["runner_sha256"] != receipt["runner_sha256"]
            or report["strategies"].keys() != set(STRATEGIES) or frozen["gate"] != GATE
            or code_hashes(frozen["evaluation_revision"]) != frozen["code_sha256"]):
        raise ValueError("Run or scorer differs from the freeze.")
    runner = holdout.sealed(runner_path, receipt["runner_sha256"])
    scorer = holdout.sealed(scorer_path, receipt["scorer_sha256"])
    with ZipFile(BytesIO(scorer)) as archive:
        reviews = json.loads(archive.read("expected.json"))["sources"]
        lineages = json.loads(archive.read("lineages.json"))
    results = {}
    for filing, original, source in cases(runner):
        source_id = filing["source_id"]
        review = reviews[source_id]
        inventory = filing_inventory(original)
        tables = inventory.record()
        inventory_hash = digest_inventory(tables)
        lines = original.split(b"\n")
        target = None
        if review["outcome"] == "target_present":
            spans = review["locators"]
            matches = [
                {"table_id": table["table_id"], "row_id": row["row_id"]}
                for table in tables if within(position(lines, table["locator"]), spans["statement"])
                for row in table["rows"] if within(position(lines, row["locator"]), spans["revenue_row"])
            ]
            if len(matches) > 1:
                raise ValueError(f"The independent review resolves multiple inventory rows for {source_id}.")
            if len(matches) == 1:
                target = matches[0]
        records = {strategy: report["strategies"][strategy]["cases"][source_id] for strategy in STRATEGIES}
        full_rows = submitted_rows(records["model_alone"])
        outcomes = {}
        for strategy, record in records.items():
            if record["inventory_sha256"] != inventory_hash:
                raise ValueError(f"Parsed candidate inventory differs for {source_id}.")
            replay(inventory, source, record, strategy)
            observations = record["observations"]
            audited = audit_observations(original, filing, review, {"facts": observations}) if review["facts"] else []
            exact = sorted(row["expected"]["fiscal_year"] for row in audited if row["extraction_matched"] and target)
            years = sorted(row["expected"]["fiscal_year"] for row in audited)
            outcome = paired_outcomes(strategy, record, target, years, exact, full_model_rows=full_rows)
            outcomes[strategy] = {
                **outcome,
                "candidate_available": (target is not None and (
                    outcome["reviewed_target_shortlisted"] if strategy == "rules_alone"
                    else outcome["reviewed_target_submitted"]
                )) if years else None,
                "pre_validation_selection_error": record["selected"] is not None and record["selected"] != target,
                "incorrect_accepted": len(observations) - len(exact),
                "absent_target_abstained": (
                    record["selected"] is None and not observations and record["stop"] in ABSTENTIONS
                ) if not years else None,
            }
            if years and target is None:
                outcomes[strategy].update(selection_outcome="target_missing_from_inventory",
                                          miss_cause="candidate_representation")
        results[source_id] = {
            "issuer": filing["issuer"], "issuer_family": lineages.get(source_id, {}).get("cik"),
            "review_outcome": review["outcome"], "evidence_gap": review["evidence_gap"],
            "reviewed_target": target, "strategies": outcomes,
        }
    if (results.keys() != reviews.keys()
            or any(data["cases"].keys() != results.keys() for data in report["strategies"].values())):
        raise ValueError("The review and each strategy must cover every sealed case exactly.")
    totals = {strategy: summarize(strategy, results, report["strategies"][strategy]) for strategy in STRATEGIES}
    baseline = totals["rules_alone"]
    for strategy in STRATEGIES[1:]:
        totals[strategy]["adoption"] = adoption(baseline, totals[strategy])
    return {
        "freeze_sha256": digest(freeze_path), "run_sha256": digest(run_path), "scorer_sha256": digest(scorer_path),
        "replayed_cases": len(results), "cases": results, "strategies": totals,
        "qualifying_strategies": [strategy for strategy in STRATEGIES[1:] if totals[strategy]["adoption"]["qualifies"]],
    }


def summarize(strategy: str, results: dict[str, Any], run_data: dict[str, Any]) -> dict[str, Any]:
    metrics = {"reviewed": 0, "exact": 0, "candidate_available": 0, "target_present": 0,
               "pre_validation_selection_errors": 0, "incorrect_accepted": 0, "absent": 0, "abstained": 0}
    total = dict(metrics)
    families = {}
    for case in results.values():
        row = case["strategies"][strategy]
        counts = {
            "reviewed": len(row["extraction"]["expected_fiscal_years"]),
            "exact": len(row["extraction"]["exact_fiscal_years"]),
            "candidate_available": int(row["candidate_available"] is True),
            "target_present": int(case["review_outcome"] == "target_present"),
            "pre_validation_selection_errors": int(row["pre_validation_selection_error"]),
            "incorrect_accepted": row["incorrect_accepted"],
            "absent": int(case["review_outcome"] == "absent_target"),
            "abstained": int(row["absent_target_abstained"] is True),
        }
        family = case["issuer_family"]
        if family is not None:
            family_totals = families.setdefault(family, {"issuer": case["issuer"], **metrics})
            for field, value in counts.items():
                family_totals[field] += value
        for field, value in counts.items():
            total[field] += value
    records = list(run_data["cases"].values())
    return {
        **total, "issuer_families": families, "inventory_ms": round(sum(r["inventory_ms"] for r in records), 3),
        "selection_and_validation_ms": round(sum(r["selection_and_validation_ms"] for r in records), 3),
        "model_calls": sum(len(r.get("batches", [])) for r in records),
        **{key: value for key, value in run_data.items() if key != "cases"},
    }


def adoption(baseline: dict[str, Any], alternative: dict[str, Any]) -> dict[str, Any]:
    improved = [
        family for family, outcome in alternative["issuer_families"].items()
        if outcome["exact"] > baseline["issuer_families"][family]["exact"]
    ]
    checks = {
        "overall_improvement": alternative["exact"] > baseline["exact"],
        "issuer_family_improvement": len(improved) >= GATE["minimum_improved_issuer_families"],
        "no_incorrect_accepted": alternative["incorrect_accepted"] <= GATE["maximum_incorrect_accepted"],
        "all_absent_targets_abstained": alternative["absent"] == alternative["abstained"],
    }
    return {"qualifies": all(checks.values()), "checks": checks, "improved_issuer_families": improved}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action, arguments in {
        "freeze": ("custody", "output", "runtime", "weights"),
        "run": ("freeze", "runner", "output", "runtime", "weights"),
        "worker": ("freeze", "runner", "output", "strategy", "runtime", "weights"),
        "score": ("freeze", "runner", "scorer", "run", "output"),
    }.items():
        command = commands.add_parser(action)
        for arg in arguments:
            if arg == "strategy":
                command.add_argument(arg, choices=STRATEGIES)
            else:
                command.add_argument(arg, type=Path)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.custody, args.output, args.runtime, args.weights)
    elif args.action == "run":
        run(args.freeze, args.runner, args.output, args.runtime, args.weights)
    elif args.action == "worker":
        worker(json.loads(args.freeze.read_bytes()), args.runner, args.output, args.strategy, args.runtime, args.weights)
    else:
        sys.addaudithook(block_sockets)
        result = score(args.freeze, args.runner, args.scorer, args.run)
        with args.output.open("xb") as output:
            output.write(json_bytes(result))


if __name__ == "__main__":
    main()
