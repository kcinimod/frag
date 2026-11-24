"""Audit the independent original locators and score a frozen development run."""

import argparse
from collections import Counter
from decimal import Decimal
import gzip
from hashlib import sha256
from html import unescape
import json
from pathlib import Path
import re
from statistics import median
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase04"))

from sec_holdout_score import fact_matches, matches_amount, position, within

PHASE = Path("artifacts/phase05")
MODES = ("cold", "warm")


def checked_span(original: bytes, span: dict[str, Any]) -> bytes:
    start, end = span["start_byte"], span["end_byte"]
    part = original[start:end]
    if not 0 <= start < end <= len(original) or sha256(part).hexdigest() != span["sha256"]:
        raise ValueError(f"Original span does not match its reference at byte {start}.")
    return part


def visible(part: bytes) -> str:
    return " ".join(unescape(re.sub(rb"<[^>]*>", b" ", part).decode()).split())


def audit(original: bytes, filing: dict[str, Any], review: dict[str, Any]) -> None:
    if sha256(original).hexdigest() != filing["sha256"]:
        raise ValueError(f"Original hash differs for {filing['accession']}.")
    spans = {key: checked_span(original, span) for key, span in review["locators"].items()}
    if review["statement_row"].casefold() not in visible(spans["revenue_row"]).casefold():
        raise ValueError(f"Statement row differs for {filing['accession']}.")
    for year, fact in review["facts"].items():
        locators = {key: checked_span(original, span) for key, span in fact["locators"].items()}
        context = f'{filing["cik"]} {fact["period_start"]} {fact["period_end"]}'
        if (year not in visible(spans["period_header"])
                or visible(locators["context"]) != context
                or visible(locators["unit"]).casefold() != "iso4217:usd"
                or fact["raw_amount"] not in visible(locators["statement_cell"])
                or visible(locators["inline_fact"]) != fact["raw_amount"]
                or f'id="{fact["element_id"]}"'.encode() not in locators["inline_fact"]
                or f'contextRef="{fact["context_id"]}"'.encode() not in locators["inline_fact"]
                or b'scale="6"' not in locators["inline_fact"]
                or int(fact["raw_amount"].replace(",", "")) * fact["scale"] != int(fact["normalized_amount"])):
            raise ValueError(f"Original observation differs for {filing['accession']} FY{year}.")
    for note in review["applicable_notes"]:
        checked_span(original, note["locator"])


def score_citations(
    lines: list[bytes], original_hash: str, review: dict[str, Any],
    run: dict[str, Any], roles: dict[str, dict[str, Any]], *, comparison: bool,
) -> dict[str, Any]:
    result = run["result"]
    citations = {item["id"]: item for item in result.get("citations", [])}
    links = {}
    for key in citations:
        opened = run["citations"].get(key, {})
        header, _, excerpt = opened.get("text", "").partition("\n\n")
        links[key] = opened.get("http_status") == 200 and original_hash in header and bool(excerpt.strip())
    cells = {}
    for role, fact in roles.items():
        citation = citations.get(role, {})
        context = citation.get("context_locators", {})
        excerpt = run["citations"].get(role, {}).get("text", "").partition("\n\n")[2]
        cells[role] = bool(
            links.get(role) and "locator" in citation
            and within(position(lines, citation["locator"]), fact["locators"]["statement_cell"])
            and all(key in context and within(position(lines, context[key]), review["locators"][span])
                    for key, span in (("metric_label", "revenue_row"), ("year_header", "period_header"),
                                      ("unit_header", "statement_title_and_units")))
            and fact["raw_amount"] in excerpt
            and str(fact["fiscal_year"]) in excerpt
            and "iso4217:usd" in excerpt.casefold()
            and "in millions" in excerpt.casefold()
        )
    notes = {}
    for note in review["applicable_notes"] if roles else ():
        if note.get("comparison_only") and not comparison:
            continue
        ref = note["locator"]
        notes[note["label"]] = any(
            links[key] and position(lines, locator["start"]) <= ref["start_byte"]
            and position(lines, locator["end_exclusive"]) >= ref["end_byte"]
            for key, citation in citations.items() if "start" in (locator := citation["locator"])
        )
    return {
        "links": links, "cells": cells, "notes": notes,
        "supported": bool(roles) and all(links.values()) and all(cells.values()) and all(notes.values()),
    }


def original_observation(actual: dict[str, Any], expected: dict[str, Any], lines: list[bytes]) -> bool:
    value = actual.get("locators", {}).get("value")
    return bool(value and fact_matches(actual, expected)
                and actual.get("raw_amount") == expected["raw_amount"]
                and actual.get("scale") == expected["scale"]
                and within(position(lines, value), expected["locators"]["statement_cell"]))


def reports_week_lengths(text: str, years: list[str], weeks: list[int]) -> bool:
    pairs = re.findall(
        r"\b(?:FY\s*)?(\d{4})\b(?:(?!\b(?:FY\s*)?\d{4}\b)[^.;])*?\b(\d+)[ -]weeks?\b",
        text, flags=re.IGNORECASE,
    )
    return set(zip(years, map(str, weeks), strict=True)) <= set(pairs)


def score_case(
    row: dict[str, Any], source: dict[str, Any], filing: dict[str, Any], label: dict[str, Any],
    review: dict[str, Any], original: bytes, mode: str,
) -> dict[str, Any]:
    run = row[mode]
    record = run.get("record") or {}
    result = run["result"]
    status = result.get("status", "command_failed")
    growth = label["kind"] == "growth"
    roles = dict(zip(("prior", "current") if growth else ("revenue",), label["years"], strict=True))
    wanted = {role: review["facts"][year] for role, year in roles.items() if year in review["facts"]}
    lines = original.split(b"\n")
    matched = {
        role: [fact for fact in source.get("facts", []) if original_observation(fact, expected, lines)]
        for role, expected in wanted.items()
    }
    extracted = {role: bool(facts) for role, facts in matched.items()}
    verified = {role: any(fact["status"] == "verified" for fact in facts) for role, facts in matched.items()}
    actual = (
        {fact["role"]: fact for fact in result.get("operands", []) if fact["status"] == "verified"}
        if growth else ({"revenue": result["fact"]} if result.get("fact") else {})
    )
    numeric = status in {"answered", "calculated"}
    answerable = label["outcome"] == "answerable"
    cited = wanted if numeric else {role: expected for role, expected in wanted.items() if role in actual}
    citations = score_citations(lines, filing["sha256"], review, run, cited, comparison=status == "calculated")
    correct_facts = all(role in wanted and original_observation(fact, wanted[role], lines)
                        for role, fact in actual.items())
    weeks = label.get("period_weeks") or []
    caveat = not weeks or any(reports_week_lengths(text, label["years"], weeks)
                             for text in result.get("scope_caveats", []))
    accurate = None
    grounded = None
    issues = result.get("issues", [])
    missing_years = [issue["fiscal_year"] for issue in issues if issue["code"] == "missing"]
    if answerable:
        accurate = numeric and set(actual) == set(wanted) and correct_facts
        if accurate and growth:
            pct = result.get("percent") or {}
            change = result.get("absolute_change")
            subtraction = [item["result"] for item in result.get("trace", []) if item["operation"] == "subtract"]
            accurate = (pct.get("unit") == "percent" and matches_amount(pct.get("value"), label["percent"])
                        and len(subtraction) == 1 and matches_amount(subtraction[0], label["absolute_change"])
                        and (change is None or (change.get("currency") == "USD"
                                                and matches_amount(change.get("value"), label["absolute_change"]))))
    else:
        withheld = status == "unavailable" and not any(result.get(key) for key in ("percent", "absolute_change", "trace"))
        verified_roles = {role for role, passed in verified.items() if passed}
        partial_supported = (
            verified_roles <= actual.keys() and correct_facts
            and (citations["supported"] if actual else not citations["links"])
        )
        if label["outcome"] == "absent_year":
            reason_supported = missing_years == [int(year) for year in roles.values() if year not in review["facts"]]
        else:
            reason_supported = not missing_years and any(
                issue["code"] == "incompatible"
                and reports_week_lengths(issue.get("detail", ""), label["years"], weeks)
                for issue in issues
            )
        grounded = withheld and reason_supported and partial_supported
    evidence = record.get("evidence", [])
    retrieved_ids = {item["fact_id"] for item in evidence}
    extracted_ids = {fact["fact_id"] for facts in matched.values() for fact in facts if fact["status"] == "verified"}
    complete = bool(accurate and caveat and citations["supported"] or grounded)
    return {
        "case_id": row["case"]["case_id"], "expected_outcome": label["outcome"], "kind": label["kind"],
        "baseline_gap": label.get("baseline_gap"),
        "present_unverifiable_reported": (
            all(extracted.values()) and not all(verified.values()) and status == "evidence_unavailable"
            and "evidence gap" in result.get("message", "").casefold() and not missing_years
            if label.get("baseline_gap") == "present_unverifiable" else None
        ),
        "stages": {
            "extraction": extracted, "verification": verified,
            "retrieval": {"eligible_fact_ids": sorted(retrieved_ids), "matched_fact_ids": sorted(retrieved_ids & extracted_ids)},
            "context_assembly": {"assembled": "evidence" in record,
                                 "model_request_recorded": record.get("model_request") is not None,
                                 "resolved_request": record.get("resolved_request")},
            "planning": {"proposal_recorded": record.get("proposed_plan") is not None},
            "execution": {"trace_operations": [item["operation"] for item in result.get("trace", [])],
                          "validation_status": record.get("validation_status")},
            "presentation": status,
        },
        "numeric_answer_emitted": numeric, "answer_accurate": accurate, "grounded_abstention": grounded,
        "contradicted_missing_years": sorted(set(missing_years) & {int(year) for year in review["facts"]}),
        "citations": citations, "required_period_caveat_present": caveat if weeks and answerable else None,
        "uses_reviewed_reference": any(verified.values()) and filing["role"] == "control",
        "end_to_end_complete": complete,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "live", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    inputs = (args.data / PHASE / "inputs.json").read_bytes()
    gold = (args.data / PHASE / "expected.json").read_bytes()
    manifest, labels = json.loads(inputs), json.loads(gold)
    live_bytes, replay_bytes = args.live.read_bytes(), args.replay.read_bytes()
    live, replay = json.loads(live_bytes), json.loads(replay_bytes)
    frozen = live["freeze"]
    if (frozen != replay["freeze"] or frozen["inputs_sha256"] != sha256(inputs).hexdigest()
            or frozen["reference_sha256"] != sha256(gold).hexdigest()
            or frozen["files"]["artifacts/phase05/score.py"] != sha256(Path(__file__).read_bytes()).hexdigest()
            or any([row["case"] for row in report["cases"]] != manifest["cases"] for report in (live, replay))):
        parser.error("Reports and references differ from the freeze.")
    originals = {}
    filings = {filing["source_id"]: filing for filing in manifest["sources"]}
    for key, filing in filings.items():
        original = gzip.decompress((args.data / filing["archive"]).read_bytes())
        audit(original, filing, labels["sources"][key])
        originals[key] = original
    scored: dict[str, Any] = {}
    for mode in MODES:
        rows = []
        for row, repeated in zip(live["cases"], replay["cases"], strict=True):
            case = row["case"]
            key = case["source_id"]
            outcome = score_case(row, live["sources"][key]["evidence"], filings[key],
                                 labels["cases"][case["case_id"]], labels["sources"][key], originals[key], mode)
            outcome["offline_replay"] = repeated[mode]["status"]
            rows.append(outcome)
        answerable = [row for row in rows if row["answer_accurate"] is not None]
        emitted = [row for row in rows if row["numeric_answer_emitted"]]
        latency = [row[mode]["elapsed_ms"] for row in live["cases"] if "elapsed_ms" in row[mode]]
        scored[mode] = {
            "metrics": {
                "accuracy": [sum(row["answer_accurate"] for row in answerable), len(answerable)],
                "citation_support_answerable": [sum(row["citations"]["supported"] for row in answerable), len(answerable)],
                "citation_support_emitted": [sum(row["citations"]["supported"] for row in emitted), len(emitted)],
                "coverage": [len(emitted), len(rows)],
                "grounded_abstention": [sum(row["grounded_abstention"] is True for row in rows), len(rows) - len(answerable)],
                "end_to_end": [sum(row["end_to_end_complete"] for row in rows), len(rows)],
                "offline_replay": [sum(row["offline_replay"] == "matched" for row in rows), len(rows)],
            },
            "latency_ms": {"min": min(latency), "median": median(latency), "max": max(latency)},
            "statuses": dict(Counter(row["stages"]["presentation"] for row in rows)),
            "cases": rows,
        }
    report = {
        "live_sha256": sha256(live_bytes).hexdigest(), "replay_sha256": sha256(replay_bytes).hexdigest(),
        "audited_originals": len(originals),
        "peak_working_set_mib": {
            key: max(row["peak_working_set_mib"][key] for row in live["cases"]) for key in ("planner", "runner")
        },
        "peak_device_vram_mib": max(row["peak_device_vram_mib"] for row in live["cases"]),
        **scored,
    }
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({mode: report[mode]["metrics"] for mode in MODES}))


if __name__ == "__main__":
    main()
