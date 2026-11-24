"""Verify revenue in consolidated statements with separately dated columns."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files
from typing import Any

from frag.income_html import (
    EvidenceText, GridCell, StatementHTML, Table, UnsupportedLayout, original_span, table_grid,
)
from frag.revenue import MONTHS, REVENUE_CONCEPT, SCALES, _normalize, _value_cell, revenue_fact_id

PARSER_VERSION = "dated-annual-revenue-v1"
REFERENCE = json.loads(files("frag").joinpath("apple-revenue-reference.json").read_text(encoding="utf-8"))
EVIDENCE_VERSION: str = REFERENCE["evidence_version"]
EXTRACTION_CACHE_REVISION = "reviewed-comparison-v1"
OPERATIONS_HEADING = re.compile(r"consolidated statements? of operations", re.I)
DATE_HEADER = re.compile(r"([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})")
MONEY_PREAMBLE = re.compile(r"^\((?:dollars )?in (thousands|millions|billions)\b", re.I)


@dataclass(frozen=True)
class DatedStatement:
    table: Table
    rows: list[list[GridCell]]
    label: GridCell
    annual: GridCell
    scale: int


def is_dated_statement(table: Table) -> bool:
    return bool(table.heading and OPERATIONS_HEADING.fullmatch(table.heading.text))


def _cover(document: StatementHTML, concept: str) -> str:
    values = document.cover_facts.get(f"dei:{concept}", [])
    return values[0].text if len(values) == 1 else ""


def applies_to(document: StatementHTML) -> bool:
    return (_cover(document, "entitycentralindexkey") == REFERENCE["identity"]["cik"]
            or any(is_dated_statement(table) for table in document.tables))


def _displayed_date(text: str) -> date:
    match = DATE_HEADER.fullmatch(text)
    if match is None:
        raise UnsupportedLayout("Expected a full fiscal year-end date in the statement.")
    try:
        return date(int(match[3]), MONTHS[match[1].casefold()], int(match[2]))
    except (KeyError, ValueError) as exc:
        raise UnsupportedLayout("Invalid fiscal year-end date in the statement.") from exc


def _source_requirements(source: dict[str, Any], cik: str, company: str, end: date) -> list[str]:
    identity = REFERENCE["identity"]
    unresolved = []
    if source["provenance"]["kind"] == "synthetic":
        unresolved.append("original_filing")
    if (source["source_hash"] != identity["source_hash"] or cik != identity["cik"]
            or company != identity["company"] or end.isoformat() != identity["report_end"]):
        unresolved.append("source_identity_verification")
    supplied_company = source["company"]
    if supplied_company is not None and supplied_company.rstrip(".").casefold() != company.rstrip(".").casefold():
        unresolved.append("supplied_company_conflict")
    for field in ("form", "accession", "filing_date"):
        if source[field] not in (None, identity[field]):
            unresolved.append(f"supplied_{field}_conflict")
    if source["source_url"] not in (None, identity["source_url"], identity["reviewed_copy_url"]):
        unresolved.append("supplied_source_url_conflict")
    return unresolved


def _matches_disclosure(lines: list[str], disclosure: dict[str, Any]) -> bool:
    span = disclosure["locator"]
    try:
        excerpt = original_span(lines, span["start"], span["end_exclusive"])
    except ValueError:
        return False
    return bool(excerpt and hashlib.sha256(excerpt.encode("utf-8")).hexdigest() == disclosure["sha256"])


def _notes(lines: list[str], unresolved: list[str]) -> list[dict[str, Any]]:
    notes = []
    for note in REFERENCE["notes"]:
        if _matches_disclosure(lines, note):
            notes.append(deepcopy(note))
        else:
            unresolved.append(f'note_{note["number"]}_boundary_or_content')
    return notes


def legacy_comparison() -> dict[str, Any]:
    return {
        "status": "unresolved", "reference_status": "unresolved", "basis": None,
        "evidence": [], "scope_caveats": [], "unresolved_requirements": ["comparison_compatibility"],
    }


def _period_columns(rows: list[list[GridCell]]) -> tuple[GridCell, dict[date, GridCell]]:
    annual = _one(
        [entry for row in rows for entry in row if entry.cell.text.casefold() == "years ended"],
        "Expected one Years ended header above the revenue row.",
    )
    candidates = []
    for row in rows[annual.row:]:
        region = [entry for entry in row if entry.cell.text and entry.columns.start in annual.columns]
        if region and all(DATE_HEADER.fullmatch(entry.cell.text) for entry in region):
            candidates.append(region)
    headers = _one(candidates, "Expected one row of full dates below Years ended.")
    periods = {_displayed_date(entry.cell.text): entry for entry in headers}
    if len({end.year for end in periods}) != len(headers) or any(
        not set(entry.columns) <= set(annual.columns) for entry in headers
    ):
        raise UnsupportedLayout("The fiscal year columns are duplicated or cross the annual header.")
    return annual, periods


def _one[T](items: list[T], message: str) -> T:
    if len(items) != 1:
        raise UnsupportedLayout(message)
    return items[0]


def _inline_period(
    document: StatementHTML, inline: dict[str, str | None], cik: str,
    end: date, prior_end: date | None,
) -> tuple[date, dict[str, int]]:
    context = _one(
        document.contexts.get(inline.get("contextref") or "", []),
        "The inline XBRL period context does not resolve uniquely.",
    )
    fields = {key: field.text for key, field in context.fields.items()}
    if context.dimensioned:
        raise UnsupportedLayout("The inline XBRL context has dimensions that conflict with consolidated scope.")
    if fields.get("xbrli:identifier") != cik:
        raise UnsupportedLayout("The inline XBRL entity conflicts with the filing cover.")
    if fields.get("xbrli:enddate") != end.isoformat():
        raise UnsupportedLayout("The inline XBRL period conflicts with the displayed fiscal year-end.")
    raw_start = fields.get("xbrli:startdate", "")
    try:
        start = date.fromisoformat(raw_start)
    except ValueError as exc:
        raise UnsupportedLayout("Inline XBRL does not specify a valid annual start date.") from exc
    days = (end - start).days + 1
    if (days not in {364, 365, 366, 371}
            or (prior_end is not None and start != prior_end + timedelta(days=1))
            or (str(end.year) in REFERENCE["period_weeks"] and cik == REFERENCE["identity"]["cik"]
                and days != 7 * REFERENCE["period_weeks"][str(end.year)])):
        raise UnsupportedLayout("Inline XBRL duration conflicts with the annual statement or fiscal calendar.")
    return start, EvidenceText(context.position).locator()


def _fact(
    document: StatementHTML, statement: DatedStatement, header: GridCell, end: date,
    prior_end: date | None, cik: str, base: dict[str, Any],
) -> dict[str, Any]:
    table, rows, label, scale = statement.table, statement.rows, statement.label, statement.scale
    value = _value_cell(rows[label.row - 1], label, header)
    if value is None:
        raise UnsupportedLayout("The revenue cell is missing from the displayed fiscal year column.")
    tagged = _one(value.cell.inline_facts, "Expected one inline XBRL fact in the revenue cell.")
    inline = tagged.attrs
    if (inline.get("name") or "").casefold() != REVENUE_CONCEPT.casefold():
        raise UnsupportedLayout("The inline XBRL concept conflicts with the total revenue row.")
    start, context = _inline_period(document, inline, cik, end, prior_end)
    if inline.get("scale") != str(len(str(scale)) - 1):
        raise UnsupportedLayout("Inline XBRL scale conflicts with the visible statement scale.")
    raw = value.cell.text
    amount = _normalize(raw, scale)
    if (inline.get("format") != "ixt:num-dot-decimal" or inline.get("sign") is not None
            or amount is None or amount.startswith("-")
            or amount != _normalize(tagged.text, scale)):
        raise UnsupportedLayout("Inline XBRL amount or sign conflicts with the displayed revenue amount.")
    measure = _one(
        document.unit_measures.get(inline.get("unitref") or "", []),
        "The inline XBRL currency unit does not resolve uniquely.",
    )
    markers = [
        entry for row in rows[header.row:label.row] for entry in row
        if entry.cell.text in {"$", "US$", "USD"} and set(entry.columns) <= set(header.columns)
    ]
    if measure.text.casefold() != "iso4217:usd" or not markers:
        raise UnsupportedLayout("The USD inline XBRL unit and visible statement currency could not be reconciled.")
    assert table.heading is not None and table.preamble is not None
    return {
        **base, "fact_id": revenue_fact_id(base["source_id"], end.year),
        "metric": "reported_consolidated_revenue", "metric_label": label.cell.text,
        "raw_amount": raw, "normalized_amount": amount, "currency": "USD", "scale": scale,
        "basis": "as_reported_in_filing", "scope": "consolidated",
        "reporting_period": {"kind": "annual", "fiscal_year": end.year,
                             "start": start.isoformat(), "end": end.isoformat()},
        "inline_xbrl": {
            "fact_element_id": inline.get("id"), "concept": inline["name"],
            "context_id": inline["contextref"], "unit_id": inline["unitref"],
        },
        "locators": {
            "table": table.locator(), "statement_heading": table.heading.locator(),
            "metric_label": label.locator(table), "annual_header": statement.annual.locator(table),
            "year_header": header.locator(table), "value": value.locator(table),
            "unit_header": {"table": table.number, **table.preamble.locator()},
            "currency_symbol": markers[0].locator(table),
            "currency_measure": measure.locator(), "inline_context": context,
            "inline_fact": tagged.locator(),
        },
    }


def inspect_dated_revenue(
    document: StatementHTML, lines: list[str], source: dict[str, Any],
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    unresolved = []
    try:
        table = _one([table for table in document.tables if is_dated_statement(table)],
                      "Expected one visible consolidated statement of operations.")
        rows = [row.cells for row in table_grid(table)]
        label = _one([
            entry for row in rows for entry in row
            if entry.cell.text.casefold() in {"total net sales", "total revenue"}
        ], "Expected one total revenue row in the consolidated statement.")
        annual, periods = _period_columns(rows[:label.row - 1])
        ordered = sorted(periods)
        current = ordered[-1]
        company = _cover(document, "entityregistrantname")
        cik = _cover(document, "entitycentralindexkey")
        if (not company or not re.fullmatch(r"[0-9]{10}", cik)
                or _cover(document, "documenttype") != "10-K"
                or _displayed_date(_cover(document, "documentperiodenddate")) != current):
            raise UnsupportedLayout("The 10-K cover identity or period conflicts with the visible statement.")
        units = MONEY_PREAMBLE.match(table.preamble.text) if table.preamble else None
        if units is None:
            raise UnsupportedLayout("The monetary scale is missing from the visible consolidated statement.")
        scale = SCALES[units[1].casefold()]
        statement = DatedStatement(table, rows, label, annual, scale)
        requirements = _source_requirements(source, cik, company, current)
        notes = _notes(lines, requirements) if cik == REFERENCE["identity"]["cik"] else []
        if not notes:
            requirements.append("applicable_notes")
        unresolved.extend(requirements)
        base = {
            "source_id": source["source_id"], "company": company,
            "filing_date": source["filing_date"], "parser_version": PARSER_VERSION,
            "evidence_version": EVIDENCE_VERSION, "applicable_notes": notes,
            "status": "provisional" if requirements else "verified",
            "unresolved_requirements": requirements,
            "parent_table_id": f'{source["source_id"]}#table-{table.number}',
        }
        for index, end in enumerate(ordered):
            prior_end = ordered[index - 1] if index else None
            try:
                fact = _fact(document, statement, periods[end], end, prior_end, cik, base)
                facts.append(fact | {"comparative": end < current})
            except UnsupportedLayout as exc:
                diagnostics.append({"code": "unsupported_observation", "fiscal_year": end.year, "message": str(exc)})
    except UnsupportedLayout as exc:
        diagnostics.append({"code": "unsupported_layout", "message": str(exc)})
    if diagnostics:
        unresolved.append("extraction")
    reviewed = REFERENCE["comparison"]
    verified = {fact["reporting_period"]["fiscal_year"]: fact["fact_id"]
                for fact in facts if fact["status"] == "verified"}
    pair_years = (reviewed["prior_year"], reviewed["current_year"])
    comparison = legacy_comparison()
    if all(year in verified for year in pair_years):
        disclosure = reviewed["evidence"]
        if _matches_disclosure(lines, disclosure):
            comparison.update(
                status="compatible", reference_status="compatible", basis=reviewed["basis"],
                scope_caveats=[*reviewed["scope_caveats"], disclosure["scope_caveat"]],
                evidence=[deepcopy(disclosure)], unresolved_requirements=[],
                fact_ids=[verified[year] for year in pair_years],
            )
        else:
            comparison["unresolved_requirements"].append(disclosure["id"])
    unresolved.extend(comparison["unresolved_requirements"])
    return {
        "parser_version": PARSER_VERSION, "evidence_version": EVIDENCE_VERSION, "facts": facts,
        "diagnostics": diagnostics, "unresolved_requirements": unresolved,
        "comparison": comparison,
        "real_source_acceptance": not unresolved,
    }
