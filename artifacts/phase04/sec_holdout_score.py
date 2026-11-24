"""Score a fixed SEC holdout run against the independent custody archive."""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile


def position(lines: list[bytes], locator: dict[str, int]) -> int:
    line, character = locator["line"], locator["character"]
    if not 1 <= line <= len(lines):
        raise ValueError("Invalid original line.")
    raw_line = lines[line - 1]
    decoded = raw_line.decode("utf-8-sig" if line == 1 else "utf-8")
    if not 1 <= character <= len(decoded) + 1:
        raise ValueError("Invalid original character.")
    bom = 3 if line == 1 and raw_line.startswith(b"\xef\xbb\xbf") else 0
    return sum(len(item) + 1 for item in lines[:line - 1]) + bom + len(decoded[:character - 1].encode("utf-8"))


def within(offset: int, span: dict[str, int]) -> bool:
    return span["start_byte"] <= offset < span["end_byte"]


def matches_amount(value: Any, expected: Any) -> bool:
    try:
        return Decimal(str(value)) == Decimal(str(expected))
    except InvalidOperation:
        return False


def fact_matches(fact: dict[str, Any], expected: dict[str, Any]) -> bool:
    return (
        matches_amount(fact.get("normalized_amount"), expected["normalized_amount"])
        and fact.get("currency") == expected["currency"]
        and fact.get("scope") == expected["scope"]
        and fact.get("metric") == "reported_consolidated_revenue"
        and fact.get("reporting_period") == {
            "kind": "annual", "fiscal_year": expected["fiscal_year"],
            "start": expected["period_start"], "end": expected["period_end"],
        }
    )


def citation_checks(
    original: bytes, evidence: dict[str, Any], row: dict[str, Any], facts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    result, opened = row["result"], row["citations"]
    citations = {item["id"]: item for item in result.get("citations", [])}
    original_hash = sha256(original).hexdigest()
    lines = original.split(b"\n")
    reopened = {
        key: (key in opened and opened[key]["http_status"] == 200
              and f"Source SHA-256 · {original_hash}" in opened[key]["text"]
              and bool(opened[key]["text"].split("\n\n", 1)[-1].strip()))
        for key in citations
    }
    report: dict[str, Any] = {"links": reopened, "cells": {}, "notes": {}}
    for role, fact in facts.items():
        citation = citations.get(role)
        valid = False
        if citation and reopened[role] and "context_locators" in citation:
            context = citation["context_locators"]
            value = position(lines, citation["locator"])
            locators = evidence["locators"]
            valid = (
                within(value, fact["locators"]["statement_cell"])
                and all(key in context and within(position(lines, context[key]), locators[locator])
                        for key, locator in (("metric_label", "revenue_row"), ("year_header", "period_header"),
                                             ("unit_header", "statement_title_and_units")))
                and fact["raw_amount"] in opened[role]["text"]
                and str(fact["fiscal_year"]) in opened[role]["text"]
                and "iso4217:usd" in opened[role]["text"].casefold()
            )
        report["cells"][role] = valid
    if facts:
        for note in evidence["applicable_notes"]:
            reference = note["locator"]
            supported = False
            for key, citation in citations.items():
                span = citation["locator"]
                if reopened[key] and "start" in span and "end_exclusive" in span:
                    start, end = (position(lines, span[field]) for field in ("start", "end_exclusive"))
                    if start <= reference["start_byte"] and end >= reference["end_byte"]:
                        supported = True
                        break
            report["notes"][note["label"]] = supported
    report["supported"] = (
        bool(facts) and all(reopened.values()) and all(report["cells"].values())
        and all(report["notes"].values())
    )
    return report


def score_case(
    row: dict[str, Any], label: dict[str, Any], evidence: dict[str, Any], original: bytes,
) -> dict[str, Any]:
    result = row["result"]
    status = result.get("status", "command_failed")
    witness = {fact["fact_id"]: fact for fact in evidence["facts"]}
    statuses = {"lookup": "answered", "growth": "calculated"}
    answerable = label["outcome"] == "answerable"
    numeric = status in statuses.values()
    withheld = (
        not numeric and not result.get("fact") and result.get("percent") is None
        and result.get("absolute_change") is None and not result.get("trace")
    )
    gap = withheld and status in {"evidence_unavailable", "unavailable"}
    abstention = None
    accuracy = None
    caveat = None
    citations = None
    if answerable:
        accuracy = status == statuses[label["kind"]]
        if label["kind"] == "lookup":
            expected = {"revenue": witness[label["fact_ids"][0]]}
            accuracy = accuracy and fact_matches(result["fact"], expected["revenue"])
        else:
            expected = {role: witness[label[f"{role}_fact_id"]] for role in ("prior", "current")}
            actual = {fact["role"]: fact for fact in result.get("operands", [])}
            caveat = not label["period_caveat_required"] or any(
                "weeks" in message.lower() and len(set(re.findall(r"\b\d+\b", message))) >= 2
                for message in result.get("scope_caveats", [])
            )
            accuracy = accuracy and all(fact_matches(actual.get(role, {}), ref) for role, ref in expected.items())
            if accuracy:
                percent = result["percent"]
                change = result.get("absolute_change")
                accuracy = (
                    percent["unit"] == "percent" and matches_amount(percent["value"], label["percent_rounded_2dp"])
                    and (change is None or (
                        change["currency"] == "USD" and matches_amount(change["value"], label["absolute_change_usd"])
                    ))
                )
        citations = citation_checks(original, evidence, row, expected)
        completed = bool(accuracy and citations["supported"] and caveat is not False)
    else:
        year = label["missing_fiscal_year"]
        gap_message = result.get("message", "")
        missing = any(
            issue.get("code") == "missing" and issue.get("fiscal_year") == year
            for issue in result.get("issues", [])
        ) or (
            f"FY{year}" in gap_message and "annual revenue observation" in gap_message.lower()
            and "no unique" in gap_message.lower()
        )
        partial = {fact["role"]: fact for fact in result.get("operands", []) if fact["status"] == "verified"}
        partial_supported = True
        if partial:
            by_year = {witness[key]["fiscal_year"]: witness[key] for key in label["supporting_fact_ids"]}
            expected = {role: by_year.get(fact["reporting_period"]["fiscal_year"], {})
                        for role, fact in partial.items()}
            partial_supported = all(ref and fact_matches(partial[role], ref) for role, ref in expected.items())
            if partial_supported:
                citations = citation_checks(original, evidence, row, expected)
                partial_supported = citations["supported"]
        abstention = bool(gap and missing and partial_supported)
        completed = abstention
    if completed:
        outcome = "supported_answer" if answerable else "grounded_abstention"
    elif gap and answerable:
        outcome = "withheld_on_answerable_case"
    else:
        outcome = "insufficient_support"
    return {
        "case_id": label["case_id"], "source_id": label["source_id"], "expected_outcome": label["outcome"],
        "kind": label["kind"], "workflow_status": status, "answer_accurate": accuracy,
        "citations": citations, "required_period_caveat_present": caveat,
        "grounded_abstention": abstention, "end_to_end_complete": completed, "outcome": outcome,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("runner", "scorer", "freeze", "run", "replay", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    receipt = json.loads(Path(__file__).with_name("sec-holdout-receipt.json").read_bytes())
    runner_hash = sha256(args.runner.read_bytes()).hexdigest()
    scorer_hash = sha256(args.scorer.read_bytes()).hexdigest()
    if runner_hash != receipt["runner_bundle"]["sha256"] or scorer_hash != receipt["scorer_bundle"]["sha256"]:
        parser.error("Custody archive hash mismatch.")
    frozen = json.loads(args.freeze.read_bytes())
    score_path = Path(__file__)
    if sha256(score_path.read_bytes()).hexdigest() != frozen["files"][f"artifacts/phase04/{score_path.name}"]:
        parser.error("Scoring code differs from the freeze.")
    run_bytes, replay_bytes = args.run.read_bytes(), args.replay.read_bytes()
    run, replay = json.loads(run_bytes), json.loads(replay_bytes)
    with ZipFile(args.runner) as runner, ZipFile(args.scorer) as scorer:
        namespace: dict[str, Any] = {"__name__": "custody_verifier"}
        exec(compile(scorer.read("verify.py"), "verify.py", "exec"), namespace)
        namespace["audit"](args.runner, args.scorer)
        manifest_bytes = runner.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        expected = json.loads(scorer.read("expected.json"))
        header = {
            "cohort": receipt["cohort"], "manifest_sha256": sha256(manifest_bytes).hexdigest(),
            "runner_zip_sha256": runner_hash, "freeze_sha256": sha256(args.freeze.read_bytes()).hexdigest(),
        }
        for report, mode in ((run, "run"), (replay, "replay")):
            if (any(report.get(key) != value for key, value in header.items())
                    or report["mode"] != mode
                    or [row["case"] for row in report["cases"]] != manifest["cases"]):
                parser.error(f"{mode} report does not conform to the frozen inputs.")
        filers = {item["source_id"]: item for item in manifest["sources"]}
        labels = {item["case_id"]: item for item in expected["cases"]}
        results = []
        for row, repeated in zip(run["cases"], replay["cases"], strict=True):
            case = row["case"]
            label = labels[case["case_id"]]
            source_id = case["source_id"]
            original = runner.read(filers[source_id]["path"])
            score = score_case(row, label, expected["sources"][source_id], original)
            score["offline_replay_status"] = repeated["status"]
            results.append(score)
    counts = {
        "answer_accuracy": [sum(row["answer_accurate"] is True for row in results),
                            sum(row["answer_accurate"] is not None for row in results)],
        "citation_support_answerable": [
            sum(row["expected_outcome"] == "answerable" and row["citations"]["supported"] for row in results),
            sum(row["expected_outcome"] == "answerable" for row in results),
        ],
        "citation_support_emitted_answers": [
            sum(row["workflow_status"] in {"answered", "calculated"} and bool((row["citations"] or {}).get("supported"))
                for row in results),
            sum(row["workflow_status"] in {"answered", "calculated"} for row in results),
        ],
        "grounded_abstention": [sum(row["grounded_abstention"] is True for row in results),
                                sum(row["grounded_abstention"] is not None for row in results)],
        "end_to_end_completion": [sum(row["end_to_end_complete"] for row in results), len(results)],
        "offline_replay": [sum(row["offline_replay_status"] == "matched" for row in results), len(results)],
    }
    report = {
        **header, "scorer_zip_sha256": scorer_hash, "run_report_sha256": sha256(run_bytes).hexdigest(),
        "replay_report_sha256": sha256(replay_bytes).hexdigest(), "metrics": counts,
        "outcomes": dict(Counter(row["outcome"] for row in results)), "cases": results,
    }
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(counts, sort_keys=True))


if __name__ == "__main__":
    main()


