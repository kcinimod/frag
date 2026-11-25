"""Audit unique statement observations after the frozen scorers verify custody."""

import argparse
import gzip
import json
from pathlib import Path
import sys
from typing import Any
from zipfile import ZipFile


def measure(
    filings: list[tuple[dict[str, Any], bytes]],
    references: dict[str, Any],
    sources: dict[str, Any],
) -> dict[str, Any]:
    # The PowerShell runner makes the frozen Phase 5 scoring module available.
    from acceptance_score import observation_matches

    rows = []
    for filing, original in filings:
        source_id = filing["source_id"]
        review = references[source_id]
        expected = list(review["facts"].values())
        if "provisional_observation" in review:
            expected.append(review["provisional_observation"])
        lines = original.split(b"\n")
        facts = sources[source_id]["evidence"]["facts"]
        observations = []
        for reference in expected:
            matches = [fact for fact in facts if observation_matches(fact, reference, lines)]
            observations.append({
                "fiscal_year": reference["fiscal_year"],
                "extraction_matched": bool(matches),
                "verified": any(fact["status"] == "verified" for fact in matches),
            })
        rows.append({
            "accession": source_id,
            "cik": filing["cik"],
            "original": filing["original_filename"],
            "sha256": filing["sha256"],
            "observations": observations,
        })
    observations = [observation for row in rows for observation in row["observations"]]
    return {
        "reviewed_observations": len(observations),
        "extraction_matches": sum(row["extraction_matched"] for row in observations),
        "verified_facts": sum(row["verified"] for row in observations),
        "originals": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot", "earlier_live", "opened_live", "opened_reference"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    scoring = args.snapshot / "scoring"
    phase = scoring / "artifacts/phase05"
    sys.path.insert(0, str(phase))
    earlier = json.loads((phase / "inputs.json").read_bytes())
    earlier_reference = json.loads((phase / "expected.json").read_bytes())
    earlier_sources = json.loads(args.earlier_live.read_bytes())["sources"]
    opened_sources = json.loads(args.opened_live.read_bytes())["sources"]
    with (
        ZipFile(args.snapshot / "opened-inputs.zip") as runner,
        ZipFile(args.opened_reference) as scorer,
    ):
        opened = json.loads(runner.read("manifest.json"))
        opened_reference = json.loads(scorer.read("expected.json"))
        report = {
            "opened": measure(
                [(filing, runner.read(filing["path"])) for filing in opened["sources"]],
                opened_reference["sources"], opened_sources,
            ),
            "earlier": measure(
                [(filing, gzip.decompress((scoring / filing["archive"]).read_bytes()))
                 for filing in earlier["sources"]],
                earlier_reference["sources"], earlier_sources,
            ),
        }
    with (args.snapshot / "observations.json").open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
