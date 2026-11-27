"""Replay model selections offline and score them against the independent #54 review."""

import argparse
from dataclasses import asdict
import gzip
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile

from revenue_selection_baseline import ROOT, block_sockets, json_bytes, read_sealed
from revenue_selection_model import CONTROLS, filing_source

from frag.revenue_model_selection import SYSTEM_PROMPT, InvalidModelResponse, ModelUnavailable, run_model_selection
from frag.revenue_selection import FilingInventory, filing_inventory
from frag.store import SourceMetadata


def replay(inventory: FilingInventory, source: dict[str, Any], saved: dict[str, Any]) -> None:
    if inventory.original_sha256 != saved["original_sha256"]:
        raise ValueError("The original changed since the model run.")
    pending = iter(saved["batches"])

    def recorded_model(prompt: str, row_ids: tuple[str, ...]) -> str:
        batch = next(pending, None)
        if (batch is None or sha256(prompt.encode()).hexdigest() != batch["prompt_sha256"]
                or list(row_ids) != batch["row_ids"]):
            raise RuntimeError("A replay prompt differs from the recorded batch.")
        if "response" in batch:
            return str(batch["response"])
        if batch["outcome"] == "invalid_response":
            raise InvalidModelResponse(batch["error"])
        raise ModelUnavailable(batch["error"])

    result = run_model_selection(inventory, source, recorded_model)
    if next(pending, None) is not None:
        raise ValueError("The replay did not consume every model batch.")
    for key, value in result.items():
        expected = saved[key]
        if key == "batches":
            for batches in (value, expected):
                for batch in batches:
                    batch.pop("elapsed_ms", None)
        if value != expected:
            raise ValueError(f"Model selection replay differs in {key} for {inventory.original_sha256}.")


def score(runner_path: Path, expected_path: Path, run_path: Path) -> dict[str, Any]:
    from fresh_score import audit_observations
    from sec_holdout_score import position, within

    runner_payload = read_sealed(runner_path, "runner")
    expected_payload = read_sealed(expected_path, "scorer")
    run_payload = run_path.read_bytes()
    report = json.loads(gzip.decompress(run_payload))
    if report["strategy"] != "model_alone" or report["runner_sha256"] != sha256(runner_payload).hexdigest():
        raise ValueError("The run must bind the model-only strategy to the sealed runner.")
    if report["batching"]["system_prompt"] != SYSTEM_PROMPT or report["controls"].keys() != CONTROLS.keys():
        raise ValueError("The model run must preserve the system prompt and both synthetic controls.")
    controls = {}
    for label, record in report["controls"].items():
        original = (ROOT / "tests" / "fixtures" / f"revenue-selection-{label}.html").read_bytes()
        source = {**asdict(SourceMetadata(company="Example Corporation")), "provenance": {"kind": "synthetic"}}
        replay(filing_inventory(original), source, record)
        controls[label] = {
            "stop": record["stop"], "selected": record["selected"], "observation_count": len(record["observations"]),
            "expected_row_id": CONTROLS[label],
        }
    results = {}
    with ZipFile(BytesIO(runner_payload)) as runner, ZipFile(BytesIO(expected_payload)) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        expected = json.loads(scorer.read("expected.json"))
        if not report["cohort"] == expected["cohort"] == manifest["cohort"]:
            raise ValueError("The run, runner archive, and review cohorts differ.")
        for filing in manifest["sources"]:
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            review = expected["sources"][source_id]
            record = report["filings"][source_id]
            inventory = filing_inventory(original)
            if inventory.original_sha256 != filing["sha256"]:
                raise ValueError(f"The original differs from the sealed manifest for {source_id}.")
            replay(inventory, filing_source(filing), record)
            audited = audit_observations(original, filing, review, {"facts": record["observations"]})
            lines = original.split(b"\n")
            locators = review["locators"]
            targets = [
                {"table_id": table["table_id"], "row_id": row["row_id"]}
                for table in inventory.record()
                if within(position(lines, table["locator"]), locators["statement"])
                for row in table["rows"]
                if within(position(lines, row["locator"]), locators["revenue_row"])
            ]
            target = targets[0] if len(targets) == 1 else None
            inventory_batches = [batch for batch in record["batches"] if batch["stage"] == "inventory"]
            verified = [row["observed"] for row in audited if row["reusable_verification_matched"]]
            results[source_id] = {
                "issuer": filing["issuer"], "stop": record["stop"], "selected": record["selected"],
                "reviewed_target": target,
                "reviewed_target_covered": target is not None and any(
                    target["row_id"] in batch["row_ids"] for batch in inventory_batches
                ),
                "reviewed_target_nominated": target is not None and any(
                    target == batch.get("selected") for batch in inventory_batches
                ),
                "reviewed_target_selected": target is not None and target == record["selected"],
                "observations_reviewed": len(audited),
                "exact_fiscal_years": sorted(row["expected"]["fiscal_year"] for row in audited if row["extraction_matched"]),
                "verified_exact_fiscal_years": sorted(fact["reporting_period"]["fiscal_year"] for fact in verified),
                "incorrect_verified_fiscal_years": sorted(
                    fact["reporting_period"]["fiscal_year"] for fact in record["observations"]
                    if fact["status"] == "verified" and fact not in verified
                ),
            }
    return {
        "run_sha256": sha256(run_payload).hexdigest(),
        "independent_review_sha256": sha256(expected_payload).hexdigest(),
        "replayed_cases": len(results) + len(controls),
        "observations_reviewed": sum(row["observations_reviewed"] for row in results.values()),
        "exact_observations": sum(len(row["exact_fiscal_years"]) for row in results.values()),
        "verified_exact_observations": sum(len(row["verified_exact_fiscal_years"]) for row in results.values()),
        "incorrect_verified_observations": sum(len(row["incorrect_verified_fiscal_years"]) for row in results.values()),
        "filings": results, "controls": controls,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runner", type=Path)
    parser.add_argument("expected", type=Path)
    parser.add_argument("run_record", type=Path)
    parser.add_argument("score_record", type=Path)
    args = parser.parse_args()
    sys.addaudithook(block_sockets)
    result = score(args.runner, args.expected, args.run_record)
    args.score_record.parent.mkdir(parents=True, exist_ok=True)
    with args.score_record.open("xb") as output:
        output.write(json_bytes(result))
    print(f"Replayed {result['replayed_cases']} cases. Exact observations {result['exact_observations']}/"
          f"{result['observations_reviewed']}.")


if __name__ == "__main__":
    main()
