"""Score the frozen fresh SEC run in scorer custody."""

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import re
from statistics import median
import sys
from typing import Any
from zipfile import ZipFile

PHASE = Path(__file__).resolve().parent
ROOT = PHASE.parents[1]
sys.path[:0] = [str(PHASE), str(ROOT / "src"), str(PHASE.with_name("phase05"))]

from acceptance_score import citation_response_matches, growth_amounts_match, reason_matches, unpack_report  # type: ignore[import-not-found]
from development_score import memory_peaks, stop_details, summarize_cases  # type: ignore[import-not-found]
from holdout_score import classify, growth_presentation  # type: ignore[import-not-found]
from revenue_score import truthful_gap  # type: ignore[import-not-found]
from score import MODES, checked_span, position, visible, within  # type: ignore[import-not-found]
from sec_holdout_score import fact_matches  # type: ignore[import-not-found]
from frag.store import SourceError

UNITS = {1_000: "thousands", 1_000_000: "millions"}


def amount_citation_supported(
    lines: list[bytes], citation: dict[str, Any], excerpt: str, review: dict[str, Any], fact: dict[str, Any],
) -> bool:
    context = citation["context_locators"]
    return (
        within(position(lines, citation["locator"]), fact["locators"]["statement_cell"])
        and all(within(position(lines, context[key]), span) for key, span in (
            ("year_header", fact["locators"]["period_cell"]),
            ("metric_label", review["locators"]["revenue_row"]),
            ("unit_header", review["locators"]["statement_title_and_units"]),
        ))
        and re.search(rf"(?<![\d,]){re.escape(fact['raw_amount'])}(?![\d,])", excerpt) is not None
        and re.search(rf"\b{fact['fiscal_year']}\b", excerpt) is not None
        and f"iso4217:{fact['currency'].lower()}" in excerpt.casefold()
        and re.search(rf"\b{UNITS[fact['scale']]}\b", excerpt, re.I) is not None
    )


def period_citation_supported(lines: list[bytes], citation: dict[str, Any], review: dict[str, Any]) -> bool:
    context = citation["context_locators"]
    locators = review["locators"]
    offsets = [position(lines, locator) for key, locator in context.items() if key.startswith("year_")]
    offsets.append(position(lines, citation["locator"]))
    headers = [fact["locators"]["period_cell"] for fact in review["facts"].values()]
    return (
        len(offsets) == len(headers)
        and all(sum(within(offset, header) for offset in offsets) == 1 for header in headers)
        and all(within(position(lines, context[key]), locators[span]) for key, span in (
            ("statement_heading", "statement_title_and_units"),
            ("annual_header", "period_header"),
            ("metric_label", "revenue_row"),
        ))
    )


def observed_fact(actual: dict[str, Any], expected: dict[str, Any], lines: list[bytes], source_id: str) -> bool:
    try:
        locators = actual["locators"]
        return bool(
            actual["source_id"] == source_id and fact_matches(actual, expected)
            and actual["raw_amount"] == expected["raw_amount"] and actual["scale"] == expected["scale"]
            and within(position(lines, locators["value"]), expected["locators"]["statement_cell"])
            and within(position(lines, locators["year_header"]), expected["locators"]["period_cell"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def audit_observations(
    original: bytes, filing: dict[str, Any], review: dict[str, Any], evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    source_id = f'sha256:{filing["sha256"]}'
    statement = review["locators"]
    for span in statement.values():
        checked_span(original, span)
    for note in review["applicable_notes"]:
        checked_span(original, note["locator"])
    lines = original.split(b"\n")
    rows = []
    for expected in review["facts"].values():
        for span in expected["locators"].values():
            checked_span(original, span)
        matches = [fact for fact in evidence.get("facts", []) if observed_fact(fact, expected, lines, source_id)
                   and within(position(lines, fact["locators"]["table"]), statement["statement"])
                   and within(position(lines, fact["locators"]["metric_label"]), statement["revenue_row"])
                   and within(position(lines, fact["locators"]["unit_header"]), statement["statement_title_and_units"])]
        observed = matches[0] if len(matches) == 1 else None
        rows.append({
            "source_id": filing["source_id"], "original_sha256": filing["sha256"], "expected": expected,
            "observed": observed, "extraction_matched": observed is not None,
            "reusable_verification_matched": bool(
                observed and observed["status"] == "verified" and expected["verification"] == "inline_corroborated"
                and evidence.get("verification_reference") is None
                and all(actual_key in observed["locators"]
                        and within(position(lines, observed["locators"][actual_key]), expected["locators"][expected_key])
                        for actual_key, expected_key in (("inline_context", "context"), ("currency_measure", "unit")))
            ),
        })
    return rows


def check_citations(
    original: bytes, original_hash: str, review: dict[str, Any], run: dict[str, Any],
    facts: dict[str, Any], *, absence: bool, comparison: bool,
) -> bool:
    result, opened = run["result"], run["citations"]
    citations = result.get("citations", [])
    ids = {citation["id"] for citation in citations}
    if len(ids) != len(citations) or ids != opened.keys() or not facts.keys() <= ids:
        return False
    if absence and "statement-periods" not in ids:
        return False
    lines = original.split(b"\n")
    notes = [note["locator"] for note in review["applicable_notes"]
             if facts and (comparison or not note.get("comparison_only"))]
    covered = set()
    try:
        for citation in citations:
            key = citation["id"]
            if not citation_response_matches(original, result, citation, opened[key]):
                return False
            excerpt = opened[key]["text"].partition("\n\n")[2]
            if key in facts:
                if not amount_citation_supported(lines, citation, excerpt, review, facts[key]):
                    return False
            elif key == "statement-periods" and absence:
                if not period_citation_supported(lines, citation, review):
                    return False
            else:
                locator = citation["locator"]
                start, end = (position(lines, locator[edge]) for edge in ("start", "end_exclusive"))
                matches = {index for index, note in enumerate(notes)
                           if start <= note["start_byte"] < note["end_byte"] <= end}
                if not matches:
                    return False
                covered.update(matches)
        return len(covered) == len(notes) and result.get("source_hash") == original_hash
    except (KeyError, TypeError, ValueError, SourceError):
        return False


def comparison_claims_supported(result: dict[str, Any], label: dict[str, Any], notes: str) -> bool:
    presentation = growth_presentation(label)
    caveats = result.get("scope_caveats", [])
    required = presentation["scope_caveats"]
    if caveats[:len(required)] != required or result.get("comparison_basis") != presentation["comparison_basis"]:
        return False
    notes = notes.casefold()
    for claim in caveats[len(required):]:
        terms: tuple[str, ...]
        if claim == "Both periods use the filing's continuing-operations basis after retrospective presentation of discontinued operations.":
            terms = ("continuing operations", "discontinued operations")
        elif claim == "Reported net operating revenues reflect bottling refranchising.":
            terms = ("bottling", "refranchis")
        elif match := re.fullmatch(r"(.+) results are included from the acquisition date in (\d{4})\.", claim):
            terms = (match[1].casefold(), match[2], "acqui")
        elif match := re.fullmatch(r"Reported growth includes the effect of the (.+) divestiture in (\d{4})\.", claim):
            terms = (match[1].casefold(), match[2], "divest")
        elif match := re.fullmatch(r"FY\d{4} includes (.+) revenue from the acquisition date\.", claim):
            terms = (match[1].casefold(), "revenue", "acqui")
        elif re.fullmatch(r"Supplemental pro forma results use the combination period described in Note \d+\.", claim):
            terms = ("pro forma",)
        else:
            return False
        if not all(term in notes for term in terms):
            return False
    return True


def score_case(
    run: dict[str, Any], repeated: dict[str, Any], evidence: dict[str, Any], label: dict[str, Any],
    review: dict[str, Any], original: bytes, original_hash: str,
) -> dict[str, Any]:
    result = run["result"]
    status, outcome = result.get("status", "command_failed"), label["outcome"]
    growth = label["kind"] == "growth"
    requested = dict(zip(("prior", "current") if growth else ("revenue",), label["years"], strict=True))
    present = {role: review["facts"][year] for role, year in requested.items() if year in review["facts"]}
    operands = result.get("operands", []) if growth else [result["fact"]] if result.get("fact") else []
    facts = {fact.get("role") if growth else "revenue": fact for fact in operands}
    source_id = f"sha256:{original_hash}"
    lines = original.split(b"\n")
    actual_facts = evidence.get("facts", [])
    facts_ok = len(facts) == len(operands) and all(
        role in present and present[role]["verification"] == "inline_corroborated"
        and fact["status"] == "verified" and {k: v for k, v in fact.items() if k != "role"} in actual_facts
        and observed_fact(fact, present[role], lines, source_id) for role, fact in facts.items()
    )
    year_fields = ("prior_year", "current_year") if growth else ("fiscal_year",)
    identity_ok = (result.get("source_id") == source_id and result.get("source_hash") == original_hash
                   and [result.get(key) for key in year_fields] == list(map(int, requested.values())))
    numeric = status in {"answered", "calculated", "undefined_zero_baseline"} or bool(
        result.get("percent") or result.get("absolute_change")
    )
    findings = []
    accurate = False
    if numeric:
        accurate = outcome == "answerable" and identity_ok and facts_ok and facts.keys() == requested.keys()
        if not accurate:
            findings.append("wrong_answer")
        elif growth:
            # Check arithmetic independently of the presentation checks in the inherited helper.
            prior, current = (facts[role] for role in ("prior", "current"))
            difference = Fraction(current["normalized_amount"]) - Fraction(prior["normalized_amount"])
            expected_formula = "(current revenue - prior revenue) / prior revenue \u00d7 100"
            accurate = (difference == Fraction(label["absolute_change"])
                        and result.get("formula") == expected_formula
                        and growth_amounts_match(result, {**label, "presentation": {
                            "comparison_basis": result.get("comparison_basis"),
                            "scope_caveats": result.get("scope_caveats"),
                        }}, facts, prior["normalized_amount"]))
        else:
            fact = facts["revenue"]
            accurate = status == "answered" and result.get("trace") == [{
                "operation": "lookup", "currency": fact["currency"], "fact_id": fact["fact_id"],
                "normalized_amount": fact["normalized_amount"],
            }]
        if not accurate and "wrong_answer" not in findings:
            findings.append("wrong_answer")
    absence = outcome == "absent_year" and not numeric
    comparison = (growth and numeric) or outcome == "incompatible_periods"
    cited_facts = {role: present[role] for role in facts if role in present}
    citations_ok = check_citations(original, original_hash, review, run, cited_facts,
                                  absence=absence, comparison=comparison)
    abstention = status in {"unavailable", "evidence_unavailable"} and not numeric
    reason_ok = False
    if abstention:
        if outcome in {"absent_year", "incompatible_periods"}:
            reason_ok = reason_matches(result, label, review["facts"], requested, present, {})
            partial_ok = facts_ok and set(facts) == set(present)
        else:
            reason_ok = truthful_gap(result, label, evidence)
            if outcome == "present_unverifiable":
                reason_ok = reason_ok and any(
                    fact["status"] == "provisional" and observed_fact(fact, present["revenue"], lines, source_id)
                    for fact in actual_facts
                )
            partial_ok = facts_ok and (not facts or (outcome == "answerable" and growth and len(facts) == 1))
            if facts and {issue.get("role") for issue in result.get("issues", [])} & facts.keys():
                partial_ok = False
        if not partial_ok:
            findings.append("unsupported_partial")
        if not reason_ok:
            findings.append("contradicted_abstention")
        if result.get("trace") or result.get("scope_caveats") or result.get("comparison_basis"):
            findings.append("unsupported_abstention_claim")
    if numeric or facts or result.get("citations") or run["citations"] or (abstention and absence):
        if not citations_ok:
            findings.append("unsupported_citation")
    if growth and accurate:
        notes = " ".join(visible(checked_span(original, note["locator"])) for note in review["applicable_notes"])
        if not comparison_claims_supported(result, label, notes):
            findings.append("unsupported_comparison_claim")
    if (numeric or abstention) and not identity_ok:
        findings.append("wrong_result_identity")
    replay_ok = repeated.get("status") == "matched" and all(
        key not in repeated or repeated[key] == run[key] for key in ("result", "citations")
    )
    if not replay_ok:
        findings.append("offline_replay_mismatch")
    grounded = abstention and outcome != "answerable" and reason_ok and citations_ok and not findings
    return {
        "status": status, "expected_outcome": outcome, "numeric_answer_emitted": numeric,
        "answer_accurate": accurate, "citations_supported": citations_ok,
        "grounded_abstention": grounded, "offline_replay_matched": replay_ok,
        "end_to_end_complete": (accurate or grounded) and citations_ok and not findings,
        "findings": findings,
    }


def score(
    freeze_path: Path, runner_path: Path, expected_path: Path, live_path: Path, replay_path: Path,
) -> dict[str, Any]:
    frozen = json.loads(freeze_path.read_bytes())
    receipt = frozen["receipt"]
    for kind, path in (("runner", runner_path), ("scorer", expected_path)):
        if sha256(path.read_bytes()).hexdigest() != receipt[f"{kind}_bundle"]["sha256"]:
            raise ValueError(f"{kind} archive differs from the seal.")
    scorer_files = {name: value for name, value in frozen["files"].items() if name.startswith("src/")}
    for relative, expected_hash in (scorer_files | frozen["scoring_files"]).items():
        if sha256((ROOT / relative).read_bytes()).hexdigest() != expected_hash:
            raise ValueError(f"Scoring file differs from the freeze: {relative}")
    if expected_path.resolve().is_relative_to(live_path.resolve().parent):
        raise ValueError("Independent references must remain outside the run directory.")
    with ZipFile(runner_path) as runner, ZipFile(expected_path) as scorer:
        expected = json.loads(scorer.read("expected.json"))
        manifest_bytes = runner.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        originals = {filing["source_id"]: runner.read(filing["path"]) for filing in manifest["sources"]}
    binding = {"freeze_sha256": sha256(freeze_path.read_bytes()).hexdigest(),
               "manifest_sha256": sha256(manifest_bytes).hexdigest(),
               "runner_sha256": receipt["runner_bundle"]["sha256"]}
    live_bytes, replay_bytes = (unpack_report(path.read_bytes()) for path in (live_path, replay_path))
    live, replay = json.loads(live_bytes), json.loads(replay_bytes)
    live_hash = sha256(live_bytes).hexdigest()
    if (replay.get("live_sha256") != live_hash or expected["cohort"] != manifest["cohort"]
            or expected["cases"].keys() != {row["case_id"] for row in manifest["cases"]}
            or expected["sources"].keys() != originals.keys()
            or any(report["freeze"] != frozen or report["binding"] != binding
                   or [row["case"] for row in report["cases"]] != manifest["cases"]
                   or report["sources"].keys() != originals.keys() for report in (live, replay))
            or any(source["evidence"] != replay["sources"][key]["evidence"]
                   for key, source in live["sources"].items())):
        raise ValueError("Reports differ from the frozen inputs or replayed intake.")
    observations = []
    for filing in manifest["sources"]:
        key = filing["source_id"]
        original = originals[key]
        if sha256(original).hexdigest() != filing["sha256"]:
            raise ValueError("Original filing hash differs from the sealed manifest.")
        observations.extend(audit_observations(original, filing, expected["sources"][key],
                                               live["sources"][key]["evidence"]))
    thresholds = frozen["thresholds_per_pass"]
    if (len(observations) != receipt["observation_count"]
            or Counter(row["outcome"] for row in expected["cases"].values()) != receipt["case_counts_by_outcome"]):
        raise ValueError("Case or observation counts differ from the sealed receipt.")
    report: dict[str, Any] = {
        "binding": binding, "live_sha256": live_hash, "replay_sha256": sha256(replay_bytes).hexdigest(),
        "scorer_bundle_sha256": receipt["scorer_bundle"]["sha256"], **memory_peaks(live),
        "observations": observations,
        "extraction_coverage": [sum(row["extraction_matched"] for row in observations), len(observations)],
        "reusable_verification_coverage": [sum(row["reusable_verification_matched"] for row in observations),
                                           len(observations)],
    }
    historical = json.loads((ROOT / "artifacts/phase05/holdout-score.json").read_bytes())
    report["historical_phase05"] = {
        **{key: historical[key] for key in ("accepted", "peak_working_set_mib", "peak_device_vram_mib")},
        **{mode: {key: historical[mode][key] for key in ("metrics", "latency_ms", "stages", "findings")}
           for mode in MODES},
    }
    for mode in MODES:
        cases = []
        for live_row, replay_row in zip(live["cases"], replay["cases"], strict=True):
            case, run, repeated = live_row["case"], live_row[mode], replay_row[mode]
            key = case["source_id"]
            label = expected["cases"][case["case_id"]]
            if label["source_id"] != key:
                raise ValueError("Case joins to a different original in the independent references.")
            label = {**label, "years": list(map(str, label["years"]))}
            review = expected["sources"][key]
            if label["outcome"] == "answerable" and label["kind"] == "growth":
                lengths = [review["facts"][year]["period_days"] for year in label["years"]]
                if len(set(lengths)) == 2 and all(days in {364, 371} for days in lengths):
                    label["period_weeks"] = [days // 7 for days in lengths]
            evidence = live["sources"][key]["evidence"]
            original = originals[key]
            result = score_case(run, repeated, evidence, label, review, original, sha256(original).hexdigest())
            stages = classify(run, evidence, review, original, label, result)
            if result["status"] == "ingestion_failed":
                stages["first_failure_stage"] = "ingestion"
            cases.append({**case, **result, **stages, "stop": stop_details(run, stages),
                          "elapsed_ms": run.get("elapsed_ms"), "opened_citations": len(run["citations"])})
        timed = [row for row in cases if row["elapsed_ms"] is not None]
        # An ingestion failure has no question timing and still stays in every case denominator.
        metrics = summarize_cases([{**row, "elapsed_ms": row["elapsed_ms"] or 0} for row in cases])
        if len(timed) != len(cases):
            durations = [row["elapsed_ms"] for row in timed]
            metrics["latency_ms"] = {"min": min(durations), "median": median(durations), "max": max(durations)} if durations else None
        metrics["timed_cases"] = len(timed)
        report[mode] = {"metrics": metrics, "cases": cases, "passed": (
            metrics["supported_answers"] >= thresholds["supported_answers"]
            and metrics["grounded_abstentions"] == thresholds["grounded_abstentions"]
            and metrics["offline_replay"] == [thresholds["exact_replay"], receipt["case_count"]]
            and not any(row["findings"] for row in cases)
        )}
    report["passed"] = all(report[mode]["passed"] for mode in MODES)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "inputs", "expected", "live", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    report = score(args.freeze, args.inputs, args.expected, args.live, args.replay)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    for mode in MODES:
        print(mode, report[mode]["metrics"])
    print("Acceptance passed" if report["passed"] else "Acceptance failed")
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
