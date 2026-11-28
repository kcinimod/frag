"""Replay rules-only extraction on the opened #54 and #59 cohorts."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile

from fresh_score import audit_observations
from revenue_selection_baseline import PHASE, block_sockets, json_bytes, read_sealed
from revenue_selection_holdout import sealed
from revenue_selection_model import filing_source

from frag.revenue_selection import filing_inventory, run_rules


def replay(runner_payload: bytes, scorer_payload: bytes) -> dict[str, Any]:
    with ZipFile(BytesIO(runner_payload)) as runner, ZipFile(BytesIO(scorer_payload)) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        reviews = json.loads(scorer.read("expected.json"))["sources"]
        cases = {}
        for filing in manifest["sources"] + manifest.get("synthetic_inputs", []):
            source_id = filing["source_id"]
            original = runner.read(filing["path"])
            if (len(original), sha256(original).hexdigest()) != (filing["byte_length"], filing["sha256"]):
                raise ValueError(f"Original differs from the sealed manifest for {source_id}.")
            source = filing_source(filing) if "cik" in filing else {
                "company": None, "filing_date": None, "provenance": {"kind": "synthetic"},
            }
            result = run_rules(filing_inventory(original), source)
            review = reviews[source_id]
            observations = result["observations"]
            audited = audit_observations(original, filing, review, {"facts": observations}) if review["facts"] else []
            cases[source_id] = {
                "issuer": filing["issuer"], "selected": result["selected"], "stop": result["stop"],
                "expected_years": sorted(row["expected"]["fiscal_year"] for row in audited),
                "exact_years": sorted(row["expected"]["fiscal_year"] for row in audited if row["extraction_matched"]),
                "observations": observations, "diagnostics": result["diagnostics"],
            }
        if cases.keys() != reviews.keys():
            raise ValueError("Runner and scoring references must cover the same cases.")
        return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohort54", type=Path)
    parser.add_argument("cohort59", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    sys.addaudithook(block_sockets)
    receipt = json.loads((PHASE / "revenue-selection-holdout-receipt.json").read_bytes())
    report = {
        "54": replay(read_sealed(args.cohort54 / "runner/inputs.zip", "runner"),
                     read_sealed(args.cohort54 / "scorer/expected.zip", "scorer")),
        "59": replay(sealed(args.cohort59 / "runner/inputs.zip", receipt["runner_sha256"]),
                     sealed(args.cohort59 / "scorer/expected.zip", receipt["scorer_sha256"])),
    }
    with args.output.open("xb") as output:
        output.write(json_bytes(report))


if __name__ == "__main__":
    main()
