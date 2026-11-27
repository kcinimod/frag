"""Run the offline rules baseline, then score it in reviewer custody."""

import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any
from uuid import uuid4
from zipfile import ZipFile

PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from frag.revenue_selection import filing_inventory, run_rules
from frag.store import SourceMetadata


def read_sealed(path: Path, kind: str) -> bytes:
    receipt = json.loads((PHASE / "continuation-holdout-receipt.json").read_bytes())
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != receipt[f"{kind}_bundle"]["sha256"]:
        raise ValueError(f"The {kind} archive differs from its #54 seal.")
    return payload


def json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def elapsed(start: float) -> float:
    return round((perf_counter() - start) * 1000, 3)


def peak_working_set_bytes() -> int | None:
    if sys.platform != "win32":
        return None

    from ctypes import POINTER, Structure, WinDLL, byref, c_size_t, sizeof
    from ctypes.wintypes import BOOL, DWORD, HANDLE

    class ProcessMemoryCounters(Structure):
        _fields_ = [
            ("size", DWORD), ("page_faults", DWORD),
            ("peak_working_set", c_size_t), ("working_set", c_size_t),
            ("quota_peak_paged_pool", c_size_t), ("quota_paged_pool", c_size_t),
            ("quota_peak_nonpaged_pool", c_size_t), ("quota_nonpaged_pool", c_size_t),
            ("pagefile_usage", c_size_t), ("peak_pagefile_usage", c_size_t),
        ]

    process = WinDLL("kernel32").GetCurrentProcess
    process.restype = HANDLE
    memory = WinDLL("psapi").GetProcessMemoryInfo
    memory.argtypes = [HANDLE, POINTER(ProcessMemoryCounters), DWORD]
    memory.restype = BOOL
    counters = ProcessMemoryCounters()
    counters.size = sizeof(counters)
    return int(counters.peak_working_set) if memory(process(), byref(counters), counters.size) else None


def run(runner_path: Path, output: Path) -> None:
    runner_payload = read_sealed(runner_path, "runner")
    if output.exists():
        raise FileExistsError(output)
    staging = output.with_name(f"{output.name}.incomplete-{uuid4()}")
    write_run(runner_payload, staging)
    staging.rename(output)


def write_run(runner_payload: bytes, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    with ZipFile(BytesIO(runner_payload)) as runner:
        manifest = json.loads(runner.read("manifest.json"))
        for filing in manifest["sources"]:
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            if len(original) != filing["byte_length"] or sha256(original).hexdigest() != filing["sha256"]:
                raise ValueError(f"Original differs from the #54 manifest for {source_id}.")
            metadata = SourceMetadata(
                company=filing["issuer"], accession=filing["accession"], form=filing["form"],
                filing_date=filing["filing_date"], source_url=filing["source_url"],
            )
            source = {
                **asdict(metadata), "provenance": {"kind": "local_original"},
            }
            start = perf_counter()
            inventory = filing_inventory(original)
            inventory_ms = elapsed(start)
            start = perf_counter()
            tables = inventory.record()
            inventory_name = f"{source_id}-inventory.json.gz"
            payload = gzip.compress(json_bytes({
                "source_id": source_id, "original_sha256": inventory.original_sha256, "tables": tables,
                "inline_xbrl": inventory.inline_definitions(),
            }), mtime=0)
            (output / inventory_name).write_bytes(payload)
            inventory_inspection_ms = elapsed(start)
            start = perf_counter()
            result = run_rules(inventory, source)
            selection_and_validation_ms = elapsed(start)
            results[source_id] = {
                **result, "issuer": filing["issuer"], "original_sha256": inventory.original_sha256,
                "visible_table_count": len(tables), "inventory_file": inventory_name,
                "inventory_sha256": sha256(payload).hexdigest(),
                "inventory_ms": inventory_ms, "inventory_inspection_ms": inventory_inspection_ms,
                "selection_and_validation_ms": selection_and_validation_ms,
                "process_peak_working_set_bytes": peak_working_set_bytes(),
            }
            del tables, inventory

    dependencies = (
        "artifacts/phase06/revenue_selection_baseline.py", "src/frag/revenue_selection.py",
        "src/frag/income_html.py", "src/frag/dated_revenue.py", "src/frag/revenue.py",
        "src/frag/revenue_notes.py", "src/frag/apple-revenue-reference.json", "src/frag/store.py",
        "artifacts/phase06/fresh_score.py", "artifacts/phase04/sec_holdout_score.py", "uv.lock",
    )
    (output / "run.json").write_bytes(json_bytes({
        "strategy": "rules_alone", "cohort": manifest["cohort"],
        "runner_sha256": sha256(runner_payload).hexdigest(),
        "python": ".".join(map(str, sys.version_info[:3])), "platform": sys.platform,
        "device_vram_measured": False, "model_calls": 0,
        "code_and_dependency_sha256": {
            name: sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in dependencies
        },
        "filings": results,
    }))


def score(runner_path: Path, expected_path: Path, output: Path) -> None:
    from fresh_score import audit_observations, checked_span, position, within

    runner_payload = read_sealed(runner_path, "runner")
    expected_payload = read_sealed(expected_path, "scorer")
    run_payload = (output / "run.json").read_bytes()
    report = json.loads(run_payload)
    if report["runner_sha256"] != sha256(runner_payload).hexdigest() or report["strategy"] != "rules_alone":
        raise ValueError("The run does not bind to the rules strategy and sealed runner input.")
    results = {}
    with ZipFile(BytesIO(runner_payload)) as runner, ZipFile(BytesIO(expected_payload)) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        expected = json.loads(scorer.read("expected.json"))
        if not report["cohort"] == expected["cohort"] == manifest["cohort"]:
            raise ValueError("The run, runner archive, and review cohorts differ.")
        for filing in manifest["sources"]:
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            record = report["filings"][source_id]
            if sha256(original).hexdigest() != record["original_sha256"]:
                raise ValueError(f"The run original does not match the manifest for {source_id}.")
            compressed = (output / f"{source_id}-inventory.json.gz").read_bytes()
            if sha256(compressed).hexdigest() != record["inventory_sha256"]:
                raise ValueError(f"The inventory differs from the run for {source_id}.")
            tables = json.loads(gzip.decompress(compressed))["tables"]
            review = expected["sources"][source_id]
            statement_span = review["locators"]["statement"]
            row_span = review["locators"]["revenue_row"]
            for span in (statement_span, row_span):
                checked_span(original, span)
            lines = original.split(b"\n")
            targets = [
                {"table_id": table["table_id"], "row_id": row["row_id"]}
                for table in tables if within(position(lines, table["locator"]), statement_span)
                for row in table["rows"] if within(position(lines, row["locator"]), row_span)
            ]
            target = targets[0] if len(targets) == 1 else None
            observations = audit_observations(original, filing, review, {"facts": record["observations"]})
            matched = {
                row["expected"]["fiscal_year"]: row["observed"]
                for row in observations if row["extraction_matched"]
            }
            verified = [row["observed"] for row in observations if row["reusable_verification_matched"]]
            results[source_id] = {
                "issuer": filing["issuer"], "reviewed_target": target,
                "reviewed_target_inventory_matches": targets,
                "target_shortlisted": target in record["candidates"],
                "target_selected": target is not None and target == record["selected"],
                "expected_fiscal_years": sorted(int(year) for year in review["facts"]),
                "exact_fiscal_years": sorted(matched),
                "verified_exact_fiscal_years": sorted(fact["reporting_period"]["fiscal_year"] for fact in verified),
                "incorrect_verified_fiscal_years": sorted(
                    fact["reporting_period"]["fiscal_year"] for fact in record["observations"]
                    if fact["status"] == "verified" and fact not in verified
                ),
            }
    (output / "score.json").write_bytes(json_bytes({
        "run_sha256": sha256(run_payload).hexdigest(),
        "independent_review_sha256": sha256(expected_payload).hexdigest(),
        "target_shortlisted": sum(result["target_shortlisted"] for result in results.values()),
        "target_selected": sum(result["target_selected"] for result in results.values()),
        "filings_reviewed": len(results),
        "exact_observations": sum(len(result["exact_fiscal_years"]) for result in results.values()),
        "observations_reviewed": sum(len(result["expected_fiscal_years"]) for result in results.values()),
        "verified_exact_observations": sum(len(result["verified_exact_fiscal_years"]) for result in results.values()),
        "incorrect_verified_observations": sum(len(result["incorrect_verified_fiscal_years"]) for result in results.values()),
        "filings": results,
    }))


def block_sockets(event: str, args: tuple[Any, ...]) -> None:
    if event.startswith("socket."):
        raise RuntimeError("The selection experiment is offline.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "score"):
        command = commands.add_parser(name)
        command.add_argument("runner", type=Path)
        if name == "score":
            command.add_argument("expected", type=Path)
        command.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.addaudithook(block_sockets)
    if args.command == "run":
        run(args.runner, args.output)
    else:
        score(args.runner, args.expected, args.output)


if __name__ == "__main__":
    main()
