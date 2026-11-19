"""Extract provisional annual revenue from the selected filing's statement layout."""

import hashlib
import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

from frag.income_html import (
    EvidenceText, GridCell, GridRow, StatementHTML, Table, UnsupportedLayout,
    is_statement_heading, table_grid,
)

PARSER_VERSION = "annual-revenue-v4"
ACCESSION = "0000950170-23-035122"
MICROSOFT_CIK = "0000789019"
TARGET_YEARS = (2022, 2023)
ANNUAL_HEADER = re.compile(r"Year Ended ([A-Za-z]+) ([0-9]{1,2}),?", re.IGNORECASE)
YEAR = re.compile(r"(?:19|20)[0-9]{2}")
SCALE = re.compile(r"\bin\s+(?:(?:USD|U\.S\. dollars)\s+)?(thousands|millions|billions)\b", re.IGNORECASE)
SCALES = {"thousands": 1_000, "millions": 1_000_000, "billions": 1_000_000_000}
USD = re.compile(r"\b(?:USD|U\.S\. dollars)\b", re.IGNORECASE)
CURRENCY_MARKERS = {"$", "USD", "US$"}
NUMBER = re.compile(r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?")
REVENUE_CONCEPT = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


@dataclass(frozen=True)
class StatementEvidence:
    table: Table
    annual_header: GridCell
    metric_label: GridCell
    unit_header: GridCell | None


def extract_revenue(original: bytes, source: dict[str, Any]) -> dict[str, Any]:
    """Produce versioned facts or an actionable diagnostic for the preserved source."""
    result: dict[str, Any] = {
        "parser_version": PARSER_VERSION, "facts": [], "diagnostics": [],
        "unresolved_requirements": [
            "source_identity_verification", "extraction", "evidence_verification",
        ],
    }
    try:
        document = StatementHTML()
        document.feed(original.decode("utf-8-sig"))
        document.close()
        if source["provenance"]["kind"] == "local_original":
            _check_document(document, source)
        if len(document.tables) != 1:
            raise UnsupportedLayout("Expected exactly one table headed Income Statements.")
        facts, diagnostics = _extract_table(document, document.tables[0], source)
    except (UnsupportedLayout, UnicodeDecodeError) as exc:
        result["diagnostics"] = [{"code": "unsupported_layout", "message": str(exc)}]
        return result
    result.update(facts=facts, diagnostics=diagnostics)
    if not diagnostics:
        result["unresolved_requirements"].remove("extraction")
    return result


def _check_document(document: StatementHTML, source: dict[str, Any]) -> None:
    expected = {
        "dei:documenttype": ["10-K"],
        "dei:documentperiodenddate": ["June 30, 2023"],
        "dei:entitycentralindexkey": [MICROSOFT_CIK],
    }
    actual = {key: [item.text for item in items] for key, items in document.cover_facts.items()}
    if actual != expected:
        raise UnsupportedLayout("Expected inline cover fields for Microsoft's FY2023 Form 10-K.")
    if not matches_microsoft_company(source["company"]):
        raise UnsupportedLayout("The supplied company conflicts with the Microsoft inline cover fields.")
    if source["accession"] not in (None, ACCESSION) or source["form"] not in (None, "10-K"):
        raise UnsupportedLayout(f"Supplied metadata conflicts with Form 10-K accession {ACCESSION}.")


def matches_microsoft_company(company: str | None) -> bool:
    return company is None or " ".join(company.casefold().replace(".", "").split()) in {
        "microsoft corp", "microsoft corporation",
    }


def _extract_table(
    document: StatementHTML, table: Table, source: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = table_grid(table)
    labels = [
        entry for row in rows for entry in row.cells
        if entry.cell.text.casefold() == "total revenue"
    ]
    if len(labels) != 1:
        raise UnsupportedLayout("Expected one Total revenue row in the income statement.")
    label = labels[0]
    header_rows = rows[:label.row - 1]
    annual_headers = [
        entry for row in header_rows for entry in row.cells if ANNUAL_HEADER.fullmatch(entry.cell.text)
    ]
    if len(annual_headers) != 1:
        raise UnsupportedLayout("Expected one annual period header above Total revenue.")
    annual = annual_headers[0]
    year_cells = _year_headers(header_rows, annual)
    value_row = rows[label.row - 1]
    # Unit disclosures may appear in a distinct row or in a merged header.
    unit_cells = [entry for row in header_rows for entry in row.cells if SCALE.search(entry.cell.text)]
    if len(unit_cells) > 1:
        raise UnsupportedLayout("Multiple statement scale declarations require review.")
    units = unit_cells[0] if unit_cells else None
    evidence = StatementEvidence(table, annual, label, units)
    facts = []
    diagnostics = []
    for year in TARGET_YEARS:
        header = year_cells[year]
        if value_row.width != rows[header.row - 1].width:
            raise UnsupportedLayout("The Total revenue row width differs from the year header row.")
        try:
            value = _value_cell(value_row.cells, label, header)
            fact = _revenue_fact(document, source, evidence, header, value, year)
        except UnsupportedLayout as exc:
            diagnostics.append({
                "code": "unsupported_observation", "fiscal_year": year, "message": str(exc),
            })
            continue
        facts.append(fact)
        for field in ("normalized_amount", "currency", "scale"):
            if fact[field] is None:
                diagnostics.append({
                    "code": f"unknown_{field}", "fiscal_year": year,
                    "message": f"FY{year} revenue has unknown {field.replace('_', ' ')}.",
                })
    if not facts and diagnostics:
        raise UnsupportedLayout(diagnostics[0]["message"])
    return facts, diagnostics


def _year_headers(rows: list[GridRow], annual: GridCell) -> dict[int, GridCell]:
    candidates: list[dict[int, GridCell]] = []
    for grid_row in rows[annual.row - 1:]:
        row = grid_row.cells
        if len(annual.columns) == 1 or annual in row:
            region = [entry for entry in row if entry.columns.start >= annual.columns.stop]
        else:
            region = [entry for entry in row if set(entry.columns) <= set(annual.columns)]
        filled = [entry for entry in region if entry.cell.text]
        if not filled or not all(YEAR.fullmatch(entry.cell.text) for entry in filled):
            continue
        years = {int(entry.cell.text): entry for entry in filled}
        if len(years) != len(filled) or not all(year in years for year in TARGET_YEARS):
            continue
        if len(annual.columns) > 1 and annual not in row:
            if set(annual.columns) != {column for entry in filled for column in entry.columns}:
                raise UnsupportedLayout("Year headers do not cover the merged annual period header.")
        candidates.append(years)
    if len(candidates) != 1:
        raise UnsupportedLayout("Annual header columns do not uniquely identify FY2022 and FY2023.")
    return candidates[0]


def _value_cell(row: list[GridCell], label: GridCell, header: GridCell) -> GridCell | None:
    columns = set(header.columns)
    candidates = [
        entry for entry in row
        if entry is not label and entry.cell.text.upper() not in CURRENCY_MARKERS
        and columns.intersection(entry.columns)
    ]
    if any(not set(entry.columns) <= columns for entry in candidates):
        raise UnsupportedLayout(f"A revenue cell crosses the FY{header.cell.text} header boundary.")
    filled = [entry for entry in candidates if entry.cell.text]
    if len(filled) > 1:
        raise UnsupportedLayout(f"Multiple revenue cells fall under FY{header.cell.text}.")
    if filled:
        return filled[0]
    return candidates[0] if len(candidates) == 1 else None


def _revenue_fact(
    document: StatementHTML, source: dict[str, Any], evidence: StatementEvidence,
    header: GridCell, value: GridCell | None, year: int,
) -> dict[str, Any]:
    table = evidence.table
    annual = evidence.annual_header
    label = evidence.metric_label
    units = evidence.unit_header
    annual_match = ANNUAL_HEADER.fullmatch(annual.cell.text)
    assert annual_match is not None
    try:
        end = date.fromisoformat(
            f"{year}-{MONTHS[annual_match[1].casefold()]:02d}-{int(annual_match[2]):02d}"
        )
        start = end.replace(year=year - 1) + timedelta(days=1)
    except (ValueError, KeyError) as exc:
        raise UnsupportedLayout("The annual period heading contains an unsupported date.") from exc
    raw = value.cell.text if value else None
    scale_match = SCALE.search(units.cell.text) if units else None
    scale = SCALES[scale_match[1].casefold()] if scale_match else None
    currency = "USD" if units and USD.search(units.cell.text) else None
    measure = None
    inline_evidence = None
    context_locator = None
    if value and value.cell.inline_facts:
        if len(value.cell.inline_facts) != 1:
            raise UnsupportedLayout("Multiple inline XBRL observations occupy a revenue cell.")
        inline = value.cell.inline_facts[0]
        if (inline.get("name") or "").casefold() != REVENUE_CONCEPT.casefold():
            raise UnsupportedLayout("The inline XBRL concept conflicts with the Total revenue label.")
        context_ref = inline.get("contextref")
        contexts = document.contexts.get(context_ref or "", [])
        if len(contexts) != 1:
            raise UnsupportedLayout("The annual inline XBRL context does not resolve uniquely.")
        context = contexts[0]
        fields = {key: field.text for key, field in context.fields.items()}
        if context.dimensioned or fields != {
            "xbrli:identifier": MICROSOFT_CIK, "xbrli:startdate": start.isoformat(),
            "xbrli:enddate": end.isoformat(),
        }:
            raise UnsupportedLayout("The inline XBRL context conflicts with the entity, scope, or annual header.")
        context_locator = EvidenceText(context.position).locator()
        inline_evidence = {
            "fact_element_id": inline.get("id"), "concept": inline.get("name"),
            "context_id": context_ref, "unit_id": inline.get("unitref"),
        }
        measures = document.unit_measures.get(inline.get("unitref") or "", [])
        if len(measures) == 1 and measures[0].text.casefold() == "iso4217:usd":
            currency = "USD"
            measure = measures[0].locator()
        elif measures:
            currency = None
        if scale is not None and inline.get("scale") != str(len(str(scale)) - 1):
            raise UnsupportedLayout("Inline XBRL scale conflicts with the table's scale declaration.")
        if inline.get("sign") == "-" and raw and not raw.startswith(("-", "(")):
            raise UnsupportedLayout("Inline XBRL sign conflicts with the displayed revenue amount.")
    elif source["provenance"]["kind"] == "local_original" and _normalize(raw, 1) is not None:
        raise UnsupportedLayout("The selected filing layout requires an inline XBRL tag for numeric revenue.")
    identity = f'{source["source_id"]}:reported_consolidated_revenue:{year}'
    heading = table.caption if table.caption and is_statement_heading(table.caption.text) else table.heading
    assert heading is not None
    return {
        "fact_id": "fact:" + hashlib.sha256(identity.encode()).hexdigest(),
        "source_id": source["source_id"], "parser_version": PARSER_VERSION,
        "company": "Microsoft Corporation" if source["provenance"]["kind"] == "local_original"
        else source["company"],
        "filing_date": source["filing_date"],
        "metric": "reported_consolidated_revenue", "metric_label": label.cell.text,
        "raw_amount": raw, "normalized_amount": _normalize(raw, scale) if currency else None,
        "currency": currency, "scale": scale, "basis": "as_reported_in_filing",
        "scope": "consolidated", "status": "provisional",
        "reporting_period": {"kind": "annual", "fiscal_year": year,
                             "start": start.isoformat(), "end": end.isoformat()},
        "comparative": year < max(TARGET_YEARS),
        "parent_table_id": f'{source["source_id"]}#table-{table.number}',
        "inline_xbrl": inline_evidence,
        "locators": {
            "table": table.locator(), "statement_heading": heading.locator(),
            "metric_label": label.locator(table), "annual_header": annual.locator(table),
            "year_header": header.locator(table), "value": value.locator(table) if value else None,
            "unit_header": units.locator(table) if units else None, "currency_measure": measure,
            "inline_context": context_locator,
        },
        "applicable_notes": [],
        "unresolved_requirements": ["applicable_notes", "independent_evidence_verification"],
    }


def _normalize(raw: str | None, scale: int | None) -> str | None:
    if not raw or scale is None:
        return None
    negative = raw.startswith("-") or (raw.startswith("(") and raw.endswith(")"))
    magnitude = raw[1:-1] if raw.startswith("(") and raw.endswith(")") else raw.removeprefix("-")
    magnitude = magnitude.strip().removeprefix("$").strip()
    if not NUMBER.fullmatch(magnitude):
        return None
    digits = magnitude.replace(",", "")
    with localcontext() as context:
        context.prec = len(digits) + len(str(scale))
        amount = Decimal(digits) * (-scale if negative else scale)
    return format(amount, "f")


MONTHS = {
    name: month for month, name in enumerate((
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ), 1)
}
