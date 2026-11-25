"""Score Phase 5 filing-scoped results after offline replay."""

import argparse
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from frag.citations import citation_text
from frag.store import SourceError

from score import (
    MODES, PHASE, audit, checked_span, original_observation, reports_week_lengths,
    score_citations, score_statement_periods, visible,
)
from sec_holdout_score import matches_amount, position


def unpack_report(raw: bytes) -> bytes:
    return gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw


def audit_reference(original: bytes, filing: dict[str, Any], review: dict[str, Any]) -> None:
    if sha256(original).hexdigest() != filing["sha256"]:
        raise ValueError(f"Original hash differs for {filing['accession']}.")
    checked = {key: checked_span(original, span) for key, span in review["locators"].items()}
    if "in millions" not in visible(checked["statement_title_and_units"]).casefold():
        raise ValueError("Original statement units differ from the reference.")
    if review["statement_row"].casefold() not in visible(checked["revenue_row"]).casefold():
        raise ValueError("Original revenue row differs from the reference.")
    inline = {}
    for year, fact in review["facts"].items():
        span = fact["locators"]
        cell = checked_span(original, span["statement_cell"])
        if (fact["scope"] != "consolidated" or fact["currency"] != "USD" or fact["scale"] != 1_000_000
                or str(fact["fiscal_year"]) != year or year not in visible(checked["period_header"])
                or not re.search(rf"(?<![\d,]){re.escape(fact['raw_amount'])}(?![\d,])", visible(cell))
                or int(fact["raw_amount"].replace(",", "")) * fact["scale"] != int(fact["normalized_amount"])):
            raise ValueError(f"Original statement observation differs for FY{year}.")
        if "inline_fact" in span:
            inline[year] = fact
    audit(original, filing, {**review, "facts": inline})


def citation_response_matches(
    original: bytes, result: dict[str, Any], citation: dict[str, Any], opened: dict[str, Any],
) -> bool:
    source = result["source_id"]
    key = citation["id"]
    if "prior_year" in result:
        route = (f'/api/sources/{source}/growth/citations/{key}'
                 f'?prior={result["prior_year"]}&current={result["current_year"]}')
    else:
        route = f'/api/sources/{source}/lookup/citations/{result["fiscal_year"]}/{key}'
    if opened.get("http_status") != 200 or opened.get("path") != route:
        return False
    text = opened.get("text")
    if not isinstance(text, str):
        return False
    header, _, excerpt = text.partition("\n\n")
    expected_header, _, expected_excerpt = citation_text(
        original, result["source_hash"], citation,
    ).partition("\n\n")
    # JSON dumps sort context keys, while the route presents them in filing order.
    if "context_locators" in citation:
        return header == expected_header and sorted(excerpt.splitlines()) == sorted(expected_excerpt.splitlines())
    return header == expected_header and excerpt == expected_excerpt


def supported_citations(
    original: bytes, original_hash: str, review: dict[str, Any], run: dict[str, Any],
    facts: dict[str, Any], *, absence: bool, comparison: bool,
) -> bool:
    result = run["result"]
    citations = result.get("citations", [])
    opened = run["citations"]
    ids = {citation["id"] for citation in citations}
    if len(ids) != len(citations) or ids != opened.keys():
        return False
    lines = original.split(b"\n")
    notes = review["applicable_notes"]
    if result.get("source_hash") != original_hash or result.get("source_id") != f"sha256:{original_hash}":
        return False
    try:
        for citation in citations:
            key = citation["id"]
            if not citation_response_matches(original, result, citation, opened[key]):
                return False
            if key in facts or (key == "statement-periods" and absence):
                continue
            locator = citation["locator"]
            if not facts or "start" not in locator:
                return False
            start, end = (position(lines, locator[edge]) for edge in ("start", "end_exclusive"))
            if not any(
                start <= note["locator"]["start_byte"] < note["locator"]["end_byte"] <= end
                and (comparison or not note.get("comparison_only")) for note in notes
            ):
                return False
        if absence and not score_statement_periods(lines, review, run):
            return False
        return not facts or bool(
            score_citations(lines, original_hash, review, run, facts, comparison=comparison)["supported"]
        )
    except (KeyError, TypeError, ValueError, SourceError):
        return False


def growth_amounts_match(result: dict[str, Any], label: dict[str, Any]) -> bool:
    percent = result.get("percent") or {}
    change = result.get("absolute_change")
    subtractions = [item.get("result") for item in result.get("trace", []) if item["operation"] == "subtract"]
    weeks = label.get("period_weeks") or []
    return (
        percent.get("unit") == "percent" and matches_amount(percent.get("value"), label["percent"])
        and len(subtractions) == 1 and matches_amount(subtractions[0], label["absolute_change"])
        and (change is None or (change.get("currency") == "USD"
                                and matches_amount(change.get("value"), label["absolute_change"])))
        and (not weeks or any(reports_week_lengths(text, label["years"], weeks)
                              for text in result.get("scope_caveats", [])))
    )


def observation_matches(actual: dict[str, Any], expected: dict[str, Any], lines: list[bytes]) -> bool:
    try:
        return original_observation(actual, expected, lines)
    except (KeyError, TypeError, ValueError):
        return False


def reason_matches(
    result: dict[str, Any], label: dict[str, Any], statement: dict[str, Any],
    requested: dict[str, str], present: dict[str, Any], extracted: dict[str, list[dict[str, Any]]],
) -> bool:
    status, issues = result.get("status"), result.get("issues", [])
    outcome = label["outcome"]
    if outcome == "absent_year":
        periods = ", ".join(f"FY{year}" for year in sorted(statement))
        expected = [
            {"code": "absent", "role": role, "fiscal_year": int(year),
             "detail": f"FY{year} is absent from the consolidated revenue statement. The statement shows {periods}."}
            for role, year in requested.items() if role not in present
        ]
        if label["kind"] == "growth":
            return bool(expected) and status == "unavailable" and issues == expected
        return (len(expected) == 1 and status == "evidence_unavailable"
                and result.get("reason") == "absent" and result.get("message") == expected[0]["detail"])
    if outcome == "incompatible_periods":
        prior, current = label["years"]
        prior_weeks, current_weeks = label["period_weeks"]
        detail = (f"FY{prior} spans {prior_weeks} weeks and FY{current} spans {current_weeks} weeks. "
                  "The reported annual amounts do not meet the requested equal-length comparison.")
        return status == "unavailable" and issues == [
            {"code": "incompatible", "role": None, "fiscal_year": None, "detail": detail},
        ]
    if outcome == "present_unverifiable" or label.get("baseline_gap") == "present_unverifiable":
        year, = requested.values()
        message = result.get("message", "")
        return (status == "evidence_unavailable" and result.get("reason") == "unverified"
                and any(fact["status"] == "provisional" for fact in extracted.get("revenue", []))
                and message.startswith(f"FY{year} revenue evidence gap. The extracted observation could not be verified.")
                and not re.search(r"\b(?:absent|missing)\b|\b(?:does not|did not)\s+(?:show|report|contain)\b",
                                  message, re.IGNORECASE))
    raise ValueError(f"Unsupported acceptance outcome {outcome!r}.")


def score_case(
    run: dict[str, Any], repeated: dict[str, Any], evidence: dict[str, Any],
    label: dict[str, Any], review: dict[str, Any], original: bytes, original_hash: str,
) -> dict[str, Any]:
    result = run["result"]
    status = result.get("status", "command_failed")
    growth = label["kind"] == "growth"
    requested = dict(zip(("prior", "current") if growth else ("revenue",), label["years"], strict=True))
    statement = review["facts"]
    present = {role: statement[year] for role, year in requested.items() if year in statement}
    lines = original.split(b"\n")
    extracted = {
        role: [fact for fact in evidence.get("facts", []) if observation_matches(fact, expected, lines)]
        for role, expected in present.items()
    }
    result_years = ({"prior": result.get("prior_year"), "current": result.get("current_year")}
                    if growth else {"revenue": result.get("fiscal_year")})
    operands = result.get("operands", []) if growth else [result["fact"]] if result.get("fact") else []
    facts = {item.get("role") if growth else "revenue": item for item in operands}
    facts_correct = len(facts) == len(operands) and all(
        role in present and fact.get("status") == "verified" and fact.get("source_id") == f"sha256:{original_hash}"
        and observation_matches(fact, present[role], lines) for role, fact in facts.items()
    )
    identity_ok = (result_years == {role: int(year) for role, year in requested.items()}
                   and result.get("source_hash") == original_hash
                   and result.get("source_id") == f"sha256:{original_hash}")
    numeric = status in {"answered", "calculated"} or bool(result.get("percent") or result.get("absolute_change"))
    answerable = label["outcome"] == "answerable"
    accurate = (answerable and status == ("calculated" if growth else "answered") and facts_correct
                and identity_ok and facts.keys() == requested.keys()
                and (not growth or growth_amounts_match(result, label)))
    absence = label["outcome"] == "absent_year" and not numeric
    comparison = status == "calculated" or label["outcome"] == "incompatible_periods"
    citations_ok = supported_citations(
        original, original_hash, review, run,
        present if numeric else {role: present[role] for role in facts if role in present},
        absence=absence, comparison=comparison,
    )
    findings = []
    if numeric and not accurate:
        findings.append("wrong_answer")
    if not citations_ok and (numeric or facts or result.get("citations") or run["citations"] or absence):
        findings.append("unsupported_citation")
    grounded = False
    if not numeric and status in {"unavailable", "evidence_unavailable"}:
        known_gap = not answerable or label.get("baseline_gap") == "present_unverifiable"
        if known_gap:
            reason_ok = reason_matches(result, label, statement, requested, present, extracted)
        else:
            reason_ok = False
        required = set(present) if absence or comparison else set()
        partial_ok = facts_correct and required == facts.keys()
        if (known_gap or facts) and not partial_ok:
            findings.append("unsupported_partial")
        if not reason_ok:
            findings.append("contradicted_abstention")
        if result.get("trace"):
            findings.append("unsupported_abstention_trace")
        grounded = not answerable and reason_ok and partial_ok and citations_ok and not result.get("trace")
    replay_ok = repeated.get("status") == "matched" and all(
        key not in repeated or repeated[key] == run[key] for key in ("result", "citations")
    )
    if not replay_ok:
        findings.append("offline_replay_mismatch")
    if (numeric or status in {"unavailable", "evidence_unavailable"}) and not identity_ok:
        findings.append("wrong_result_identity")
    return {
        "status": status, "expected_outcome": label["outcome"], "numeric_answer_emitted": numeric,
        "answer_accurate": accurate, "citations_supported": citations_ok,
        "grounded_abstention": grounded, "offline_replay_matched": replay_ok,
        "end_to_end_complete": (accurate or grounded) and citations_ok and not findings,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "live", "replay", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    inputs = (args.data / PHASE / "inputs.json").read_bytes()
    reference = (args.data / PHASE / "expected.json").read_bytes()
    manifest, labels = json.loads(inputs), json.loads(reference)
    live_bytes, replay_bytes = args.live.read_bytes(), args.replay.read_bytes()
    live_json = unpack_report(live_bytes)
    live, replay = json.loads(live_json), json.loads(unpack_report(replay_bytes))
    frozen = live["freeze"]
    live_json_hash = sha256(live_json).hexdigest()
    if (replay["freeze"] != frozen or frozen["inputs_sha256"] != sha256(inputs).hexdigest()
            or frozen["reference_sha256"] != sha256(reference).hexdigest()
            or ("live_sha256" in replay and replay["live_sha256"] != live_json_hash)
            or any([row["case"] for row in report["cases"]] != manifest["cases"] for report in (live, replay))
            or live["sources"].keys() != replay["sources"].keys()
            or live["sources"].keys() != {filing["source_id"] for filing in manifest["sources"]}
            or any(source["evidence"] != replay["sources"][key]["evidence"]
                   for key, source in live["sources"].items())):
        parser.error("Reports, reingested evidence or references differ from the freeze.")
    originals = {}
    for filing in manifest["sources"]:
        key = filing["source_id"]
        original = gzip.decompress((args.data / filing["archive"]).read_bytes())
        audit_reference(original, filing, labels["sources"][key])
        originals[key] = (original, filing["sha256"])
    report: dict[str, Any] = {
        "live_sha256": sha256(live_bytes).hexdigest(),
        "replay_sha256": sha256(replay_bytes).hexdigest(),
        "replay_bound_to_live": "live_sha256" in replay,
        "reference_sha256": sha256(reference).hexdigest(),
        "scorer_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "audited_originals": len(originals),
    }
    for mode in MODES:
        rows = []
        for row, repeated in zip(live["cases"], replay["cases"], strict=True):
            case = row["case"]
            key, case_id = case["source_id"], case["case_id"]
            scored = score_case(row[mode], repeated[mode], live["sources"][key]["evidence"],
                                labels["cases"][case_id], labels["sources"][key], *originals[key])
            rows.append({"case_id": case_id, **scored})
        answerable = [row for row in rows if row["expected_outcome"] == "answerable"]
        emitted = [row for row in rows if row["numeric_answer_emitted"]]
        metrics = {
            "accuracy": [sum(row["answer_accurate"] for row in rows), len(answerable)],
            "grounded_abstention": [sum(row["grounded_abstention"] for row in rows), len(rows) - len(answerable)],
            "citation_support_emitted": [sum(row["citations_supported"] for row in emitted), len(emitted)],
            "coverage": [len(emitted), len(rows)],
            "end_to_end": [sum(row["end_to_end_complete"] for row in rows), len(rows)],
            "offline_replay": [sum(row["offline_replay_matched"] for row in rows), len(rows)],
        }
        report[mode] = {"metrics": metrics, "cases": rows}
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({mode: report[mode]["metrics"] for mode in MODES}))
    return int(any(row["findings"] for mode in MODES for row in report[mode]["cases"]))


if __name__ == "__main__":
    raise SystemExit(main())
