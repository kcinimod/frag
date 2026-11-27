"""Verify the #59 SEC extraction holdout in scorer custody."""

import argparse
from hashlib import sha256
from html import unescape
from io import BytesIO
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

PHASE = Path(__file__).resolve().parent
RECEIPT = PHASE / "revenue-selection-holdout-receipt.json"


def sealed(path: Path, digest: str) -> bytes:
    data = path.read_bytes()
    if sha256(data).hexdigest() != digest:
        raise ValueError(f"Seal mismatch for {path.name}.")
    return data


def identities(sources: list[dict[str, Any]]) -> tuple[set[str], ...]:
    ciks: set[str] = set()
    accessions: set[str] = set()
    hashes: set[str] = set()
    names: set[str] = set()
    for source in sources:
        ciks.update(str(int(cik)) for cik in [source["cik"], *source.get("related_ciks", [])])
        accessions.update(accession.replace("-", "") for accession in [
            source["accession"], *source.get("related_accessions", []),
        ])
        hashes.add(source["sha256"].lower())
        names.update("".join(ch for ch in name.casefold() if ch.isalnum()) for name in [
            source["issuer"], *source.get("aliases", []),
        ])
    return ciks, accessions, hashes, names


def checked_span(original: bytes, locator: dict[str, Any]) -> bytes:
    start, end = locator["start_byte"], locator["end_byte"]
    segment = original[start:end]
    if not 0 <= start < end <= len(original) or sha256(segment).hexdigest() != locator["sha256"]:
        raise ValueError(f"Original byte span differs at offset {start}.")
    return segment


def visible(segment: bytes) -> str:
    text = unescape(re.sub(rb"<[^>]*>", b" ", segment).decode()).replace("\u200b", "")
    return " ".join(text.split())


def inside(child: dict[str, Any], parent: dict[str, Any]) -> bool:
    return bool(parent["start_byte"] <= child["start_byte"] < child["end_byte"] <= parent["end_byte"])


def audit_observations(
    original: bytes, source: dict[str, Any], review: dict[str, Any], company_facts: dict[str, Any],
) -> None:
    locators = review["locators"]
    title = visible(checked_span(original, locators["statement_heading"])).casefold().replace("state ments", "statements")
    units = visible(checked_span(original, locators["statement_title_and_units"])).casefold()
    row = visible(checked_span(original, locators["revenue_row"]))
    if (review["statement_title"].casefold() not in title or "in millions" not in units
            or not row.startswith(review["statement_row"]) or not inside(locators["revenue_row"], locators["statement"])):
        raise ValueError(f"Statement evidence differs for {source['source_id']}.")
    if str(int(company_facts["cik"])) != str(int(source["cik"])):
        raise ValueError("SEC Company Facts must belong to the filing registrant.")
    for year, fact in review["facts"].items():
        spans = fact["locators"]
        snippets = {key: checked_span(original, locator) for key, locator in spans.items()}
        amount = int(fact["raw_amount"].replace(",", "")) * fact["scale"]
        start, end = fact["period_start"], fact["period_end"]
        context = visible(snippets["context"]).split()
        inline_tag = snippets["inline_fact"].partition(b">")[0]
        attrs = dict(re.findall(rb'([\w:-]+)="([^"]+)"', inline_tag))
        unit_id = attrs.get(b"unitRef", b"")
        sec_rows = company_facts["facts"]["us-gaap"][fact["concept"].split(":")[1]]["units"]["USD"]
        if (
            year != str(fact["fiscal_year"])
            or visible(snippets["period_cell"]) != year
            or not inside(spans["period_cell"], locators["period_header"])
            or not inside(spans["statement_cell"], locators["revenue_row"])
            or not inside(spans["inline_fact"], spans["statement_cell"])
            or visible(snippets["statement_cell"]) != fact["raw_amount"]
            or visible(snippets["inline_fact"]) != fact["raw_amount"]
            or len(context) != 3
            or (int(context[0]), *context[1:]) != (int(source["cik"]), start, end)
            or (fact["scope"], fact["currency"], fact["scale"]) != ("consolidated", "USD", 1_000_000)
            or visible(snippets["unit"]).casefold() != "iso4217:usd"
            or attrs.get(b"id") != fact["element_id"].encode()
            or attrs.get(b"contextRef") != fact["context_id"].encode()
            or attrs.get(b"name") != fact["concept"].encode()
            or attrs.get(b"scale") != b"6"
            or f'id="{fact["context_id"]}"'.encode() not in snippets["context"].partition(b">")[0]
            or b'id="' + unit_id + b'"' not in snippets["unit"].partition(b">")[0]
            or str(amount) != fact["normalized_amount"]
            or not any((item["accn"], item.get("start"), item["end"], item["val"]) ==
                       (source["accession"], start, end, amount) for item in sec_rows)
        ):
            raise ValueError(f"Observation evidence differs for {source['source_id']} FY{year}.")


def audit(
    scorer: ZipFile, manifest: dict[str, Any], originals: dict[str, bytes], receipt: dict[str, Any],
) -> tuple[tuple[set[str], ...], tuple[set[str], ...]]:
    review_data = scorer.read("reviewer-audit.json")
    inventory_data = scorer.read("development-inventory.json")
    expected = json.loads(scorer.read("expected.json"))
    lineages = json.loads(scorer.read("lineages.json"))
    if (sha256(review_data).hexdigest() != receipt["reviewer_audit_sha256"]
            or sha256(inventory_data).hexdigest() != receipt["preparation_inventory_sha256"]
            or expected["cohort"] != manifest["cohort"] or expected["sources"].keys() != originals.keys()):
        raise ValueError("Scoring evidence does not bind to the receipt and inputs.")
    known = identities(json.loads(inventory_data)["sources"])
    reserved = identities(list(lineages.values()))
    if any(held & used for held, used in zip(reserved, known, strict=True)):
        raise ValueError("The preparation inventory overlaps the holdout.")
    filings = {source["source_id"]: source for source in manifest["sources"]}
    if lineages.keys() != filings.keys():
        raise ValueError("Each original filing must have a lineage record.")
    for source_id, lineage in lineages.items():
        if any(lineage[key] != filings[source_id][key] for key in ("cik", "accession", "issuer", "sha256")):
            raise ValueError("Lineage and original filing identities differ.")
    outcomes = {"target_present": 0, "absent_target": 0}
    observations = 0
    layouts = set()
    for source_id, review in expected["sources"].items():
        original = originals[source_id]
        for locator in review["locators"].values():
            checked_span(original, locator)
        for evidence in review.get("applicable_notes", []) + review.get("distractors", []):
            checked_span(original, evidence["locator"])
        outcomes[review["outcome"]] += 1
        observations += len(review["facts"])
        if review["outcome"] == "target_present":
            layouts.add(tuple(review["layout"]))
            facts = json.loads(scorer.read(review["company_facts"]))
            audit_observations(original, filings[source_id], review, facts)
        elif review["facts"] or not review["evidence_gap"]:
            raise ValueError("An absent-target control must document the gap and carry no observations.")
        elif "exhibit" in review:
            exhibit = review["exhibit"]
            exhibit_bytes = scorer.read(exhibit["path"])
            if sha256(exhibit_bytes).hexdigest() != exhibit["sha256"]:
                raise ValueError("Exhibit bytes differ from the review.")
            statement = checked_span(exhibit_bytes, exhibit["statement"])
            row = checked_span(exhibit_bytes, exhibit["revenue_row"])
            if row not in statement or not visible(row).startswith("Total revenue"):
                raise ValueError("The incorporated exhibit must contain the reviewed revenue row.")
    if (outcomes["target_present"], outcomes["absent_target"], observations, len(layouts)) != (
        receipt["reviewed_rows"], receipt["absent_targets"], receipt["observations"], receipt["statement_layouts"],
    ):
        raise ValueError("Reviewed cohort counts differ from the receipt.")
    print(f"Verified both seals, {observations} reviewed observations and {outcomes['absent_target']} absent-target controls.")
    return known, reserved


def verify(custody: Path, final_inventory: list[Path]) -> None:
    receipt = json.loads(RECEIPT.read_bytes())
    runner_bytes = sealed(custody / "runner/inputs.zip", receipt["runner_sha256"])
    scorer_bytes = sealed(custody / "scorer/expected.zip", receipt["scorer_sha256"])
    with ZipFile(BytesIO(runner_bytes)) as runner, ZipFile(BytesIO(scorer_bytes)) as scorer:
        manifest = json.loads(runner.read("manifest.json"))
        if manifest["cohort"] != receipt["cohort"]:
            raise ValueError("Runner and receipt cohort differ.")
        sources = manifest["sources"] + manifest["synthetic_inputs"]
        paths = [source["path"] for source in sources]
        if (
            sorted(runner.namelist()) != sorted(["manifest.json", *paths])
            or len(paths) != len(set(paths))
            or len(sources) != len({source["source_id"] for source in sources})
        ):
            raise ValueError("Runner archive must contain only the manifest and unique inputs.")
        originals = {}
        for source in sources:
            original = runner.read(source["path"])
            if (len(original), sha256(original).hexdigest()) != (source["byte_length"], source["sha256"]):
                raise ValueError(f"Source bytes differ from the manifest for {source['source_id']}.")
            originals[source["source_id"]] = original

        known, reserved = audit(scorer, manifest, originals, receipt)

    if final_inventory:
        final_sources = []
        for path in final_inventory:
            data = path.read_bytes()
            final_sources.extend(json.loads(data)["sources"])
            print(f"Final inventory SHA-256 {sha256(data).hexdigest()}  {path}")
        final = identities(final_sources)
        if any(not before <= after for before, after in zip(known, final, strict=True)):
            raise ValueError("The final inventory omits identities from the preparation inventory.")
        if any(held & used for held, used in zip(reserved, final, strict=True)):
            raise ValueError("The final development inventory overlaps the holdout.")
        print("Final development inventory recheck passed.")
    else:
        print("Preparation inventory verified. Final development inventory recheck remains pending.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("custody", type=Path)
    parser.add_argument("--final-inventory", type=Path, action="append", default=[])
    args = parser.parse_args()
    verify(args.custody, args.final_inventory)


if __name__ == "__main__":
    main()
