"""Rescore retained SEC acceptance reports with the corrected evidence policy."""

import argparse
from collections import Counter
from datetime import date, datetime
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
from holdout_score import evidence_gap, growth_presentation  # type: ignore[import-not-found]
from revenue_score import truthful_gap  # type: ignore[import-not-found]
from score import MODES, checked_span, position, visible, within  # type: ignore[import-not-found]
from fresh_score import amount_citation_supported as amount_cell_supported, observed_fact  # type: ignore[import-not-found]
from frag.income_html import is_statement_heading
from frag.store import SourceError

SCORING_REVISION = "phase06-evidence-v2"
INLINE_LOCATORS = (("inline_fact", "inline_fact"), ("inline_context", "context"), ("currency_measure", "unit"))
PRODUCTION_DEPENDENCIES = (
    "__init__.py", "citations.py", "dated_revenue.py", "growth.py", "income_html.py", "revenue.py",
    "revenue_notes.py", "store.py", "verification.py", "microsoft-revenue-reference.json",
)


def anchor_within(lines: list[bytes], locator: Any, span: dict[str, Any]) -> bool:
    try:
        return bool(within(position(lines, locator), span))
    except (KeyError, TypeError, ValueError):
        return False


def heading_supported(original: bytes, lines: list[bytes], locator: dict[str, Any], span: dict[str, Any]) -> bool:
    start = position(lines, locator)
    if within(start, span):
        return is_statement_heading(element_text(original, start))
    # A reviewed heading can start at its text, inside the element opened by the citation.
    prefix = original[start:span["start_byte"]]
    if not re.fullmatch(rb"(?:<[a-z][^<>]*>\s*)+", prefix, re.I):
        return False
    tag = re.match(rb"<([a-z][\w-]*)", prefix, re.I)
    if tag is None:
        return False
    close = re.search(rb"</" + tag[1] + rb"\s*>", original[span["start_byte"]:span["end_byte"]], re.I)
    end = span["start_byte"] + close.start() if close else span["end_byte"]
    return is_statement_heading(visible(original[start:end]))


def period_citation_supported(
    original: bytes, lines: list[bytes], citation: dict[str, Any], review: dict[str, Any],
) -> bool:
    context = citation["context_locators"]
    locators = review["locators"]
    years = sorted(review["facts"])
    if not years:
        return False
    headers = {f"year_{year}": context.get(f"year_{year}") for year in years[:-1]}
    headers[f"year_{years[-1]}"] = citation["locator"]
    required = {"statement_heading", "annual_header", "metric_label", *(f"year_{year}" for year in years[:-1])}
    extras = set(context) - required
    if not required <= context.keys() or extras - {f"date_prefix_{year}" for year in years}:
        return False
    return (
        heading_supported(original, lines, context["statement_heading"], locators["statement_title_and_units"])
        and annual_header_supported(original, lines, context["annual_header"], locators)
        and anchor_within(lines, context["metric_label"], locators["revenue_row"])
        and all(anchor_within(lines, headers[f"year_{year}"], review["facts"][year]["locators"]["period_cell"])
                for year in years)
        and all(anchor_within(lines, context[key],
                              review["facts"][key.removeprefix("date_prefix_")]["locators"].get(
                                  "date_prefix", {}))
                for key in extras)
    )


def annual_header_supported(
    original: bytes, lines: list[bytes], locator: dict[str, Any], locators: dict[str, Any],
) -> bool:
    if "annual_header" in locators:
        return anchor_within(lines, locator, locators["annual_header"])
    return anchor_within(lines, locator, locators["period_header"]) and bool(re.search(
        r"\b(?:years?|twelve months) ended\b", element_text(original, position(lines, locator)), re.I,
    ))


def amount_citation_supported(
    original: bytes, lines: list[bytes], citation: dict[str, Any], excerpt: str,
    review: dict[str, Any], fact: dict[str, Any],
) -> bool:
    context = citation["context_locators"]
    locators = review["locators"]
    fields = {"metric_label", "year_header", "unit_header", "statement_heading", "statement_issuer",
              "annual_header", "currency_measure", "currency_symbol", "date_prefix"}
    return (
        context.keys() <= fields
        and all(key not in context or anchor_within(lines, context[key], span) for key, span in (
            ("currency_measure", fact["locators"].get("unit", {})),
            ("annual_header", locators["period_header"]),
            ("date_prefix", fact["locators"].get("date_prefix", {})),
        ))
        and ("statement_heading" not in context or heading_supported(
            original, lines, context["statement_heading"], locators["statement_title_and_units"]))
        and ("statement_issuer" not in context or issuer_supported(original, lines, context, review))
        and ("currency_symbol" not in context or (
            anchor_within(lines, context["currency_symbol"], locators["statement"])
            and element_text(original, position(lines, context["currency_symbol"])) == "$"
        ))
        and amount_cell_supported(lines, citation, excerpt, review, fact)
    )


def element_text(original: bytes, start: int) -> str:
    tag = re.match(rb"<([a-z][\w-]*)\b[^<>]*>", original[start:], re.I)
    if not tag:
        return ""
    close = re.search(rb"</" + tag[1] + rb"\s*>", original[start + tag.end():], re.I)
    return visible(original[start:start + tag.end() + close.start()]) if close else ""


def issuer_supported(
    original: bytes, lines: list[bytes], context: dict[str, Any], review: dict[str, Any],
) -> bool:
    start = position(lines, context["statement_issuer"])
    heading = position(lines, context["statement_heading"])
    name = re.sub(r"[^a-z0-9]", "", element_text(original, start).casefold())
    issuer = re.sub(r"\b(?:inc|corp|corporation|co|company)\.?$", "", review.get("issuer", "").casefold())
    issuer = re.sub(r"[^a-z0-9]", "", issuer)
    return bool(issuer and name.startswith(issuer) and start < heading and len(visible(original[start:heading])) <= 150)


def note_bounds(lines: list[bytes], locator: dict[str, Any]) -> tuple[int, int]:
    return position(lines, locator["start"]), position(lines, locator["end_exclusive"])


def reviewed_notes_covered(
    lines: list[bytes], observations: list[dict[str, Any]], notes: list[dict[str, Any]],
) -> bool:
    try:
        bounds = [note_bounds(lines, item["locator"]) for item in observations]
    except (KeyError, TypeError, ValueError):
        return False
    return all(any(start <= note["locator"]["start_byte"] < note["locator"]["end_byte"] <= end
                   for start, end in bounds) for note in notes if not note.get("comparison_only"))


def audit_observations(
    original: bytes, filing: dict[str, Any], review: dict[str, Any], evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    source_id = f'sha256:{filing["sha256"]}'
    statement = review["locators"]
    for span in statement.values():
        checked_span(original, span)
    for note in review["applicable_notes"]:
        checked_span(original, note["locator"])
        if "citation_locator" in note:
            envelope = note["citation_locator"]
            checked_span(original, envelope)
            span = note["locator"]
            if not envelope["start_byte"] <= span["start_byte"] < span["end_byte"] <= envelope["end_byte"]:
                raise ValueError("Reviewed citation range does not enclose its disclosure.")
    lines = original.split(b"\n")
    rows = []
    for expected in review["facts"].values():
        for span in expected["locators"].values():
            checked_span(original, span)
        matches = [
            fact for fact in evidence.get("facts", []) if observed_fact(fact, expected, lines, source_id)
            and all(anchor_within(lines, fact["locators"].get(key), statement[reference])
                    for key, reference in (("table", "statement"), ("metric_label", "revenue_row"),
                                           ("unit_header", "statement_title_and_units")))
        ]
        observed = matches[0] if len(matches) == 1 else None
        inline = (observed.get("inline_xbrl") or {}) if observed else {}
        rows.append({
            "source_id": filing["source_id"], "original_sha256": filing["sha256"], "expected": expected,
            "observed": observed, "extraction_matched": observed is not None,
            "reusable_verification_matched": bool(
                observed and observed["status"] == "verified" and expected["verification"] == "inline_corroborated"
                and evidence.get("verification_reference") is None
                and inline.get("concept", "").casefold() == expected["concept"].casefold()
                and inline.get("fact_element_id") == expected["element_id"]
                and inline.get("context_id") == expected["context_id"]
                and all(anchor_within(lines, observed["locators"].get(actual), expected["locators"][reference])
                        for actual, reference in INLINE_LOCATORS)
                and reviewed_notes_covered(lines, observed.get("applicable_notes", []), review["applicable_notes"])
            ),
        })
    return rows


def audit_citations(
    original: bytes, original_hash: str, review: dict[str, Any], run: dict[str, Any],
    facts: dict[str, Any], *, absence: bool, comparison: bool,
) -> tuple[list[str], bool, list[str], list[dict[str, Any]]]:
    result, opened = run["result"], run["citations"]
    citations = result.get("citations", [])
    ids = [citation["id"] for citation in citations]
    unsupported = len(set(ids)) != len(ids) or set(ids) != opened.keys()
    lines = original.split(b"\n")
    notes = [note for note in review["applicable_notes"]
             if (facts or comparison) and (comparison or not note.get("comparison_only"))]
    supported = []
    covered = set()
    for citation in citations:
        key = citation["id"]
        try:
            if (result.get("source_hash") != original_hash or result.get("source_id") != f"sha256:{original_hash}"
                    or not citation_response_matches(original, result, citation, opened[key])):
                unsupported = True
                continue
            excerpt = opened[key]["text"].partition("\n\n")[2]
            if key in facts:
                valid = amount_citation_supported(original, lines, citation, excerpt, review, facts[key])
            elif key == "statement-periods" and absence:
                valid = period_citation_supported(original, lines, citation, review)
            elif key == "fiscal-calendar" and comparison:
                contexts = citation["period_contexts"]
                valid = bool(facts) and contexts.keys() == {f'FY{fact["fiscal_year"]}' for fact in facts.values()} and all(
                    anchor_within(lines, contexts[f'FY{fact["fiscal_year"]}'], fact["locators"]["context"])
                    for fact in facts.values()
                )
            else:
                start, end = note_bounds(lines, citation["locator"])
                matches = {
                    index for index, note in enumerate(notes)
                    if start <= note["locator"]["start_byte"] < note["locator"]["end_byte"] <= end
                }
                # Extra visible text needs an independently reviewed enclosing disclosure range.
                spans = sorted((notes[index].get("citation_locator", notes[index]["locator"]) for index in matches),
                               key=lambda span: span["start_byte"])
                cursor = start
                valid = bool(spans)
                for span in spans:
                    valid = valid and not visible(original[cursor:max(cursor, span["start_byte"])])
                    cursor = max(cursor, span["end_byte"])
                valid = valid and not visible(original[cursor:end])
                if valid:
                    covered.update(matches)
            if valid:
                supported.append(key)
            else:
                unsupported = True
        except (KeyError, TypeError, ValueError, SourceError):
            unsupported = True
    missing = set(facts) - set(ids)
    if absence and "statement-periods" not in ids:
        missing.add("statement-periods")
    missing_notes = [note["label"] for index, note in enumerate(notes) if index not in covered]
    return sorted(set(supported)), unsupported, sorted(missing) + missing_notes, [notes[i] for i in sorted(covered)]


def comparison_claims_supported(
    result: dict[str, Any], label: dict[str, Any], original: bytes, cited_notes: list[dict[str, Any]],
    facts: dict[str, Any],
) -> bool:
    presentation = growth_presentation(label)
    caveats = result.get("scope_caveats", [])
    required = presentation["scope_caveats"]
    if not isinstance(caveats, list) or caveats[:len(required)] != required:
        return False
    if result.get("comparison_basis") != presentation["comparison_basis"]:
        return False
    notes = [(note["label"].casefold(), visible(checked_span(original, note["locator"])).casefold())
             for note in cited_notes]
    for claim in caveats[len(required):]:
        if not isinstance(claim, str):
            return False
        if claim == "Both periods use the filing's continuing-operations basis after retrospective presentation of discontinued operations.":
            supported = any("continuing operations" in text and "discontinued operations" in text for _, text in notes)
        elif claim == "Reported net operating revenues reflect bottling refranchising.":
            supported = any("bottling" in text and "refranchis" in text for _, text in notes)
        elif match := re.fullmatch(r"Supplemental pro forma results use the combination period described in Note (\d+)\.", claim):
            note_number = rf"\bnote\s+{match[1]}\b"
            supported = any(re.match(note_number, title) and "pro forma" in text and re.search(
                r"\b(?:combination period|as (?:though|if)|beginning of|since the date)\b", text
            ) for title, text in notes)
        else:
            supported = dated_comparison_claim_supported(claim, facts, [text for _, text in notes])
        if not supported:
            return False
    return True


def dated_comparison_claim_supported(claim: str, facts: dict[str, Any], notes: list[str]) -> bool:
    fiscal_year = False
    if match := re.fullmatch(r"FY(\d{4}) includes (.+) revenue from the acquisition date\.", claim):
        year, business, event = match[1], match[2], r"acquired|acquisition"
        fiscal_year = True
    elif match := re.fullmatch(r"(.+) results are included from the acquisition date in (\d{4})\.", claim):
        year, business, event = match[2], match[1], r"acquired|acquisition"
    elif match := re.fullmatch(r"Reported growth includes the effect of the (.+) divestiture in (\d{4})\.", claim):
        year, business, event = match[2], match[1], r"divested|divestiture|sold"
    else:
        return False
    if year not in facts:
        return False
    company = re.escape(business.casefold())
    event_phrase = rf"(?:\b(?:{event})\b (?:of |the )?{company}\b|\b{company}\b (?:was |were )?(?:{event})\b)"
    month = "january|february|march|april|may|june|july|august|september|october|november|december"
    date_pattern = rf"(?:{month}) \d{{1,2}}, \d{{4}}"
    dated_event = re.compile(rf"\bon ({date_pattern}),? [^,.;]{{0,70}}{event_phrase}|{event_phrase} on ({date_pattern})")
    for text in notes:
        if fiscal_year and re.search(
            rf"\bfiscal\s+{year}\b[^.]*\bincludes?\b[^.]*\brevenue\b[^.]*\b{company}\b"
            r"[^.]*\b(?:from|since) the (?:acquisition date|date of acquisition)\b", text
        ):
            return True
        if "acqui" in event and not (
            re.search(r"\b(?:revenue|results)\b[^.]*\bincluded\b[^.]*\b(?:acquisition date|date of acquisition)\b", text)
        ):
            continue
        if not fiscal_year and re.search(rf"{event_phrase} in {year}\b", text):
            return True
        if fiscal_year and re.search(rf"{event_phrase} in (?:fiscal |fy\s*){year}\b", text):
            return True
        for match in dated_event.finditer(text):
            try:
                event_date = datetime.strptime(match[1] or match[2], "%B %d, %Y").date()
            except ValueError:
                continue
            if fiscal_year:
                fact = facts[year]
                if date.fromisoformat(fact["period_start"]) <= event_date <= date.fromisoformat(fact["period_end"]):
                    return True
            elif event_date.year == int(year):
                return True
    return False


def disclosed_verification_gap(result: dict[str, Any], label: dict[str, Any], observation: dict[str, Any]) -> bool:
    fact = observation.get("observed") or {}
    year = label["years"][0]
    expected_reason = label["reason"].casefold()
    return (
        "no matching inline xbrl fact, context, and unit" in expected_reason
        and observation["expected"]["verification"] == "provisional" and fact.get("status") == "provisional"
        and fact.get("inline_xbrl") is None
        and result.get("message", "").replace(" Source identity verification.", "") == (
            f"FY{year} revenue evidence gap. The extracted observation could not be verified. "
            "The consolidated statement displays revenue for this year, "
            "but the original lacks the inline XBRL fact, context, and unit needed for verification. "
            "Inline xbrl verification."
        )
    )


def workflow_gap(result: dict[str, Any], label: dict[str, Any], evidence: dict[str, Any], review: dict[str, Any]) -> bool:
    if not truthful_gap(result, label, evidence):
        return False
    if label["kind"] == "lookup":
        gaps = [(label["years"][0], result["message"])]
    else:
        gaps = [(str(issue["fiscal_year"]), issue["detail"]) for issue in result["issues"]]
    return all(evidence_gap(text.removesuffix(" Expected one Years ended header above the revenue row."),
                            year, review["facts"], evidence) for year, text in gaps)


def audit_abstention(
    result: dict[str, Any], label: dict[str, Any], evidence: dict[str, Any], review: dict[str, Any],
    requested: dict[str, str], present: dict[str, Any], observations: dict[str, Any],
) -> tuple[bool, list[str], list[str]]:
    outcome = label["outcome"]
    if outcome == "present_unverifiable":
        observation = observations.get(label["years"][0], {})
        text = result.get("message", "").casefold()
        if result.get("reason") == "unverified":
            if observation and disclosed_verification_gap(result, label, observation):
                return True, [], []
            prefix = f"fy{label['years'][0]} revenue evidence gap."
            if workflow_gap(result, label, evidence, review) or text in {prefix, f"{prefix} verification is pending."}:
                return False, ["missing_required_verification_reason"], []
        if result.get("reason") == "absent" or re.search(
            r"\b(?:original|filing) (?:has|shows|reports) (?:mismatched|conflicting) (?:units|periods|amounts)\b",
            text,
        ):
            return False, [], ["contradicted_abstention"]
        return False, [], ["unsupported_abstention_claim"]
    reason_result = result
    if outcome == "absent_year" and label["kind"] == "growth":
        issues = result.get("issues", [])
        reason_result = {**result, "issues": [issue for issue in issues if issue.get("code") == "absent"]}
        extras = [issue for issue in issues if issue.get("code") != "absent"]
        if extras and (any(issue.get("role") not in present for issue in extras)
                       or not workflow_gap({**result, "issues": extras}, label, evidence, review)):
            return False, [], ["unsupported_abstention_claim"]
    if outcome in {"absent_year", "incompatible_periods"}:
        if reason_matches(reason_result, label, review["facts"], requested, present, {}):
            return True, [], []
        if workflow_gap(result, label, evidence, review):
            return False, ["missing_required_abstention_reason"], []
        if not result.get("issues") and not result.get("reason") and not result.get("message"):
            return False, ["missing_required_abstention_reason"], []
        if outcome == "incompatible_periods":
            issues = reason_result.get("issues", [])
            expected_weeks = dict(zip(label["years"], label["period_weeks"], strict=True))
            disclosed_weeks = [
                (year, int(weeks)) for issue in issues if issue.get("code") == "incompatible"
                for year, weeks in re.findall(r"\bFY(\d{4}) spans (\d+) weeks\b", issue.get("detail", ""))
            ]
            if not any(expected_weeks.get(year) != weeks for year, weeks in disclosed_weeks):
                if disclosed_weeks:
                    return False, ["missing_required_abstention_reason"], []
                return False, [], ["unsupported_abstention_claim"]
        return False, [], ["contradicted_abstention"]
    if workflow_gap(result, label, evidence, review):
        return False, ["missing_required_answer"], []
    if result.get("reason") == "absent" or any(
        issue.get("code") in {"absent", "incompatible"} for issue in result.get("issues", [])
    ):
        return False, [], ["contradicted_abstention"]
    return False, [], ["unsupported_abstention_claim"]


def score_case(
    run: dict[str, Any], repeated: dict[str, Any], evidence: dict[str, Any], label: dict[str, Any],
    review: dict[str, Any], original: bytes, original_hash: str,
    *, observations: list[dict[str, Any]],
) -> dict[str, Any]:
    result = run["result"]
    status, outcome = result.get("status", "command_failed"), label["outcome"]
    growth = label["kind"] == "growth"
    requested = dict(zip(("prior", "current") if growth else ("revenue",), label["years"], strict=True))
    present = {role: review["facts"][year] for role, year in requested.items() if year in review["facts"]}
    operands = result.get("operands", []) if growth else [result["fact"]] if result.get("fact") else []
    facts = {fact.get("role") if growth else "revenue": fact for fact in operands}
    source_id = f"sha256:{original_hash}"
    by_year = {str(row["expected"]["fiscal_year"]): row for row in observations}
    verified_roles = {
        role for role, fact in facts.items() if role in present
        and (observation := by_year.get(requested[role]))
        and observation["reusable_verification_matched"]
        and {key: value for key, value in fact.items() if key != "role"} == observation["observed"]
    }
    facts_ok = len(facts) == len(operands) and verified_roles == facts.keys()
    year_fields = ("prior_year", "current_year") if growth else ("fiscal_year",)
    identity_ok = (result.get("source_id") == source_id and result.get("source_hash") == original_hash
                   and [result.get(key) for key in year_fields] == list(map(int, requested.values())))
    numeric = status in {"answered", "calculated", "undefined_zero_baseline"} or any(
        result.get(key) is not None for key in ("percent", "absolute_change")
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
    abstention = status in {"unavailable", "evidence_unavailable"} and not numeric
    incomplete = []
    reason_ok = False
    if abstention:
        reason_ok, gaps, blocking = audit_abstention(result, label, evidence, review, requested, present, by_year)
        incomplete.extend(gaps)
        findings.extend(blocking)
        required_years = set(map(str, label.get("partial_years", [])))
        required_roles = {role for role, year in requested.items() if year in required_years}
        if required_roles - facts.keys():
            incomplete.append("missing_required_companion")
        if (not facts_ok or (outcome != "answerable" and facts.keys() - required_roles)
                or any(issue.get("role") in facts for issue in result.get("issues", []))):
            findings.append("unsupported_partial")
        if result.get("trace") or result.get("scope_caveats") or result.get("comparison_basis"):
            findings.append("unsupported_abstention_claim")
    elif facts and not numeric:
        findings.append("unsupported_partial")
    if numeric or abstention or facts or result.get("citations") or run["citations"]:
        cited_facts = present if numeric else {role: present[role] for role in facts if role in present}
        supported, unsupported, missing, cited_notes = audit_citations(
            original, original_hash, review, run, cited_facts, absence=absence, comparison=comparison,
        )
    else:
        supported, unsupported, missing, cited_notes = [], False, [], []
    if unsupported:
        findings.append("unsupported_citation")
    if missing:
        incomplete.append("missing_required_citation")
    if growth and numeric and not comparison_claims_supported(result, label, original, cited_notes, {
        year: review["facts"][year] for year in requested.values() if year in review["facts"]
    }):
        findings.append("unsupported_comparison_claim")
    if (numeric or abstention) and not identity_ok:
        findings.append("wrong_result_identity")
    # Version 1 reports store a replay status for equal payloads and the differing payload on mismatch.
    replay_ok = repeated.get("status") == "matched" and all(
        key not in repeated or repeated[key] == run[key] for key in ("result", "citations")
    )
    if not replay_ok:
        findings.append("offline_replay_mismatch")
    grounded = abstention and outcome != "answerable" and reason_ok and not findings and not incomplete
    return {
        "status": status, "expected_outcome": outcome, "numeric_answer_emitted": numeric,
        "answer_accurate": accurate, "citations_supported": bool(supported) and not unsupported,
        "supported_citation_ids": supported, "missing_citations": missing,
        "supported_companions": sorted(verified_roles.intersection(supported)) if abstention and identity_ok else [],
        "grounded_abstention": grounded, "offline_replay_matched": replay_ok,
        "end_to_end_complete": (accurate or grounded) and not findings and not incomplete,
        "findings": list(dict.fromkeys(findings)), "incomplete": bool(incomplete),
        "incomplete_findings": incomplete,
    }


def classify(
    run: dict[str, Any], evidence: dict[str, Any], label: dict[str, Any],
    scored: dict[str, Any], observations: list[dict[str, Any]],
) -> dict[str, Any]:
    record = run.get("record") or {}
    requested = {
        str(row["expected"]["fiscal_year"]): row for row in observations
        if str(row["expected"]["fiscal_year"]) in label["years"]
    }
    extracted = {year: row["extraction_matched"] for year, row in requested.items()}
    verified = {year: row["reusable_verification_matched"] for year, row in requested.items()}
    eligible = [fact["fact_id"] for fact in record.get("evidence", [])]
    model_request = record.get("model_request") is not None
    proposal = record.get("proposed_plan") is not None
    status, findings = scored["status"], scored["findings"]
    if scored["end_to_end_complete"]:
        stage = "complete"
    elif status in {"ingestion_failed", "clarify"}:
        stage = {"ingestion_failed": "ingestion", "clarify": "request_resolution"}[status]
    elif not all(extracted.values()):
        stage = "extraction"
    elif not all(verified.values()):
        stage = "verification"
    elif findings == ["offline_replay_mismatch"] and not scored["incomplete"]:
        stage = "offline_replay"
    elif scored["numeric_answer_emitted"]:
        stage = "execution" if "wrong_answer" in findings else "presentation"
    elif label["outcome"] in {"absent_year", "incompatible_periods"}:
        stage = "statement_period_inventory" if label["outcome"] == "absent_year" else "comparison_compatibility"
    elif any(row["observed"]["fact_id"] not in eligible for row in requested.values()):
        stage = "retrieval"
    elif model_request:
        stage = "execution" if proposal and status != "invalid_plan" else "planning"
    else:
        stage = "context_assembly"
    return {
        "first_failure_stage": stage, "observations_extracted": extracted, "observations_verified": verified,
        "eligible_fact_ids": eligible, "model_request_sent": model_request, "proposal_returned": proposal,
        "validation_status": record.get("validation_status"),
        "intake_diagnostics": [item["code"] for item in evidence.get("diagnostics", [])],
        "open_requirements": evidence.get("unresolved_requirements", []),
    }


def score(
    freeze_path: Path, runner_path: Path, expected_path: Path, live_path: Path, replay_path: Path,
) -> dict[str, Any]:
    frozen = json.loads(freeze_path.read_bytes())
    receipt = frozen["receipt"]
    for kind, path in (("runner", runner_path), ("scorer", expected_path)):
        if sha256(path.read_bytes()).hexdigest() != receipt[f"{kind}_bundle"]["sha256"]:
            raise ValueError(f"{kind} archive differs from the seal.")
    # The historical freeze binds the reports and custody archives. Record the checkout files
    # that influence the corrected score separately from the historical production freeze.
    dependencies = {
        *(ROOT / relative for relative in frozen["scoring_files"]),
        Path(__file__).resolve(),
        *(ROOT / "src/frag" / name for name in PRODUCTION_DEPENDENCIES),
    }
    scoring_files = {
        path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(dependencies)
    }
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
    by_source = {}
    for filing in manifest["sources"]:
        key = filing["source_id"]
        original = originals[key]
        if sha256(original).hexdigest() != filing["sha256"]:
            raise ValueError("Original filing hash differs from the sealed manifest.")
        by_source[key] = audit_observations(original, filing, expected["sources"][key],
                                            live["sources"][key]["evidence"])
    observations = [row for rows in by_source.values() for row in rows]
    issuers = {filing["source_id"]: filing["issuer"] for filing in manifest["sources"]}
    thresholds = frozen["thresholds_per_pass"]
    if (len(observations) != receipt["observation_count"]
            or Counter(row["outcome"] for row in expected["cases"].values()) != receipt["case_counts_by_outcome"]):
        raise ValueError("Case or observation counts differ from the sealed receipt.")
    report: dict[str, Any] = {
        "scoring_revision": SCORING_REVISION, "scoring_files": scoring_files,
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
            review = {**expected["sources"][key], "issuer": issuers[key]}
            if label["outcome"] == "answerable" and label["kind"] == "growth":
                lengths = [review["facts"][year]["period_days"] for year in label["years"]]
                if len(set(lengths)) == 2 and all(days in {364, 371} for days in lengths):
                    label["period_weeks"] = [days // 7 for days in lengths]
            evidence = live["sources"][key]["evidence"]
            original = originals[key]
            result = score_case(run, repeated, evidence, label, review, original, sha256(original).hexdigest(),
                                observations=by_source[key])
            stages = classify(run, evidence, label, result, by_source[key])
            cases.append({**case, **result, **stages, "stop": stop_details(run, stages),
                          "elapsed_ms": run.get("elapsed_ms"), "opened_citations": len(run["citations"])})
        timed = [row for row in cases if row["elapsed_ms"] is not None]
        # An ingestion failure has no question timing and still stays in every case denominator.
        metrics = summarize_cases([{**row, "elapsed_ms": row["elapsed_ms"] or 0} for row in cases])
        if len(timed) != len(cases):
            durations = [row["elapsed_ms"] for row in timed]
            metrics["latency_ms"] = {"min": min(durations), "median": median(durations), "max": max(durations)} if durations else None
        metrics["timed_cases"] = len(timed)
        metrics["supported_citations"] = sum(len(row["supported_citation_ids"]) for row in cases)
        metrics["supported_companions"] = sum(len(row["supported_companions"]) for row in cases)
        metrics["incomplete_cases"] = sum(row["incomplete"] for row in cases)
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
