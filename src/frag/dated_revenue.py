"""Verify revenue in consolidated statements with separately dated columns."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, timedelta
from importlib.resources import files
from typing import Any
from urllib.parse import urlsplit

from frag.income_html import (
    EvidenceText, GridCell, StatementHTML, Table, UnsupportedLayout, original_span, table_grid,
)
from frag.revenue import MONTHS, REVENUE_CONCEPT, SCALES, _normalize, _value_cell, revenue_fact_id
from frag.revenue_notes import accounting_policy_notes, dated_policy_notes

PARSER_VERSION = "dated-annual-revenue-v1"
SHARED_YEAR_PARSER_VERSION = "shared-year-revenue-v1"
TITLED_TABLE_PARSER_VERSION = "titled-table-revenue-v1"
FILING_SCOPED_PARSERS = {PARSER_VERSION, SHARED_YEAR_PARSER_VERSION, TITLED_TABLE_PARSER_VERSION}
SHARED_YEAR_EVIDENCE_VERSION = "original-revenue-evidence-v1"
REFERENCE = json.loads(files("frag").joinpath("apple-revenue-reference.json").read_text(encoding="utf-8"))
EVIDENCE_VERSION: str = REFERENCE["evidence_version"]
EXTRACTION_CACHE_REVISION = "titled-table-v1"
OPERATIONS_HEADING = re.compile(r"consolidated statements? of operations", re.I)
CONSOLIDATED_HEADING = re.compile(r"consolidated statements? of (?:operations|income)", re.I)
DATE_HEADER = re.compile(r"([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})")
SHARED_YEAR_HEADER = re.compile(r"(?:fiscal )?years? ended ([A-Za-z]+ [0-9]{1,2}),?", re.I)
MONEY_PREAMBLE = re.compile(r"^\((?:dollars |amounts )?in (thousands|millions|billions)\b", re.I)
SHARED_MONEY_PREAMBLE = re.compile(
    r"\((?:dollars |amounts )?in (thousands|millions|billions)(?:, except per[- ]share (?:data|amounts))?\)",
    re.I,
)
DATED_MONEY_HEADER = re.compile(r"years ended (\(.+\))", re.I)
DATE_MONTHS = MONTHS | {name[:3]: month for name, month in MONTHS.items()}
SHARED_REVENUE_LABELS = {"total net sales", "total revenue", "total revenues", "revenues"}


@dataclass(frozen=True)
class DatedStatement:
    table: Table
    rows: list[list[GridCell]]
    label: GridCell
    annual: GridCell
    scale: int
    unit_header: dict[str, int]
    shared_year: bool = False

    @property
    def uses_original_evidence(self) -> bool:
        return self.shared_year or self.table.separate_title


def is_dated_statement(table: Table) -> bool:
    return bool(table.heading and OPERATIONS_HEADING.fullmatch(table.heading.text))


def _cover(document: StatementHTML, concept: str) -> str:
    values = document.cover_facts.get(f"dei:{concept}", [])
    if concept == "documenttype" and values and all(value.text == values[0].text for value in values):
        return values[0].text
    return values[0].text if len(values) == 1 else ""


def applies_to(document: StatementHTML) -> bool:
    return (_cover(document, "entitycentralindexkey") == REFERENCE["identity"]["cik"]
            or any(is_dated_statement(table) for table in document.tables))


def original_evidence_tables(document: StatementHTML) -> list[Table]:
    return [
        table for table in document.tables
        if table.heading and CONSOLIDATED_HEADING.fullmatch(table.heading.text)
        and (table.separate_title or any(SHARED_YEAR_HEADER.fullmatch(cell.text) for row in table.rows for cell in row))
    ]


def _displayed_date(text: str) -> date:
    match = DATE_HEADER.fullmatch(text)
    if match is None:
        raise UnsupportedLayout("Expected a full fiscal year-end date in the statement.")
    try:
        return date(int(match[3]), DATE_MONTHS[match[1].casefold()], int(match[2]))
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
    end: date, prior_end: date | None, *, statement: DatedStatement, weeks: int | None,
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
    if statement.uses_original_evidence and context.identifier_scheme not in {
        "http://www.sec.gov/CIK", "https://www.sec.gov/CIK",
    }:
        raise UnsupportedLayout("The inline XBRL entity does not use an SEC CIK.")
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
            or (statement.shared_year and days not in {365, 366})
            or (weeks is not None and days != 7 * weeks)):
        raise UnsupportedLayout("Inline XBRL duration conflicts with the annual statement or fiscal calendar.")
    return start, EvidenceText(context.position).locator()


def _visible_fact(
    statement: DatedStatement, header: GridCell, end: date, base: dict[str, Any],
) -> tuple[dict[str, Any], GridCell]:
    table, rows, label, scale = statement.table, statement.rows, statement.label, statement.scale
    value = _value_cell(rows[label.row - 1], label, header)
    if value is None:
        raise UnsupportedLayout("The revenue cell is missing from the displayed fiscal year column.")
    raw = value.cell.text
    amount = _normalize(raw, scale)
    if amount is None or amount.startswith("-"):
        raise UnsupportedLayout("Inline XBRL amount or sign conflicts with the displayed revenue amount.")
    markers = [
        entry for row in rows[header.row:label.row] for entry in row
        if entry.cell.text in {"$", "US$", "USD"} and set(entry.columns) <= set(header.columns)
    ]
    if not markers:
        raise UnsupportedLayout("The visible statement currency could not be established.")
    assert table.heading is not None
    locators = {
        "table": table.locator(), "statement_heading": table.heading.locator(),
        "metric_label": label.locator(table), "annual_header": statement.annual.locator(table),
        "year_header": header.locator(table), "value": value.locator(table),
        "unit_header": statement.unit_header, "currency_symbol": markers[0].locator(table),
    }
    if statement.shared_year and table.issuer:
        locators["statement_issuer"] = table.issuer.locator()
    start = None
    if statement.shared_year:
        try:
            start = (end.replace(year=end.year - 1) + timedelta(days=1)).isoformat()
        except ValueError:
            pass
    return {
        **base, "fact_id": revenue_fact_id(base["source_id"], end.year),
        "metric": "reported_consolidated_revenue", "metric_label": label.cell.text,
        "raw_amount": raw, "normalized_amount": amount, "currency": "USD", "scale": scale,
        "basis": "as_reported_in_filing", "scope": "consolidated",
        "reporting_period": {"kind": "annual", "fiscal_year": end.year, "start": start, "end": end.isoformat()},
        "inline_xbrl": None, "locators": locators,
    }, value


def _verify_inline(
    document: StatementHTML, statement: DatedStatement, value: GridCell, end: date,
    prior_end: date | None, cik: str, fact: dict[str, Any], weeks: int | None,
) -> None:
    tagged = _one(value.cell.inline_facts, "Expected one inline XBRL fact in the revenue cell.")
    inline = tagged.attrs
    concepts = {REVENUE_CONCEPT.casefold()}
    if statement.shared_year:
        concepts.add("us-gaap:revenues")
    if (inline.get("name") or "").casefold() not in concepts:
        raise UnsupportedLayout("The inline XBRL concept conflicts with the total revenue row.")
    start, context = _inline_period(document, inline, cik, end, prior_end,
                                    statement=statement, weeks=weeks)
    if inline.get("scale") != str(len(str(statement.scale)) - 1):
        raise UnsupportedLayout("Inline XBRL scale conflicts with the visible statement scale.")
    if (inline.get("format") != "ixt:num-dot-decimal" or inline.get("sign") is not None
            or inline.get("xsi:nil") in {"true", "1"}
            or fact["normalized_amount"] != _normalize(tagged.text, statement.scale)):
        raise UnsupportedLayout("Inline XBRL amount or sign conflicts with the displayed revenue amount.")
    measure = _one(
        document.unit_measures.get(inline.get("unitref") or "", []),
        "The inline XBRL currency unit does not resolve uniquely.",
    )
    if measure.text.casefold() != "iso4217:usd":
        raise UnsupportedLayout("The USD inline XBRL unit and visible statement currency could not be reconciled.")
    fact["reporting_period"]["start"] = start.isoformat()
    fact["inline_xbrl"] = {
        "fact_element_id": inline.get("id"), "concept": inline["name"],
        "context_id": inline["contextref"], "unit_id": inline["unitref"],
    }
    fact["locators"].update(currency_measure=measure.locator(), inline_context=context, inline_fact=tagged.locator())


def _annual_facts(
    document: StatementHTML, statement: DatedStatement, periods: dict[date, GridCell],
    cik: str, base: dict[str, Any], diagnostics: list[dict[str, Any]],
    weeks: dict[int, int],
) -> list[dict[str, Any]]:
    facts = []
    ordered = sorted(periods)
    for index, end in enumerate(ordered):
        prior_end = ordered[index - 1] if index else None
        fact = None
        week_count = weeks.get(end.year)
        try:
            fact, value = _visible_fact(statement, periods[end], end, base)
            _verify_inline(document, statement, value, end, prior_end, cik, fact, week_count)
        except UnsupportedLayout as exc:
            diagnostics.append({"code": "unsupported_observation", "fiscal_year": end.year, "message": str(exc)})
            if fact is None or not statement.uses_original_evidence:
                continue
            fact.update(status="provisional",
                        unresolved_requirements=[*fact["unresolved_requirements"], "inline_xbrl_verification"])
        if statement.table.separate_title and week_count is None:
            fact.update(status="provisional",
                        unresolved_requirements=[*fact["unresolved_requirements"], "fiscal_calendar_verification"])
        facts.append(fact | {"comparative": end < ordered[-1]})
    return facts


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
        assert table.preamble is not None
        statement = DatedStatement(table, rows, label, annual, scale,
                                   {"table": table.number, **table.preamble.locator()})
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
        weeks = {int(year): count for year, count in REFERENCE["period_weeks"].items()} if (
            cik == REFERENCE["identity"]["cik"]
        ) else {}
        facts = _annual_facts(document, statement, periods, cik, base, diagnostics, weeks)
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


def inspect_original_revenue(
    document: StatementHTML, tables: list[Table], lines: list[str], source: dict[str, Any],
) -> dict[str, Any]:
    """Find an annual observation and verify its evidence without a reviewed reference."""
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    requirements: list[str] = []
    parser_version = SHARED_YEAR_PARSER_VERSION
    try:
        table = _one(tables, "Expected one visible consolidated income statement.")
        if len(document.tables) != 1:
            raise UnsupportedLayout("More than one statement table could contain consolidated revenue.")
        rows = [row.cells for row in table_grid(table)]
        labels = SHARED_REVENUE_LABELS | {"net revenue"} if table.separate_title else SHARED_REVENUE_LABELS
        label = _one([cell for row in rows for cell in row if cell.cell.text.casefold() in labels],
                     "Expected one total revenue row in the consolidated statement.")
        headers = rows[:label.row - 1]
        if table.separate_title:
            parser_version = TITLED_TABLE_PARSER_VERSION
            annual, periods = _titled_table_columns(headers)
        else:
            annual = _one([cell for row in headers for cell in row if SHARED_YEAR_HEADER.fullmatch(cell.cell.text)],
                          "Expected one shared fiscal year-end above the revenue row.")
            periods = _shared_year_columns(headers, annual)
        current = max(periods)
        company = _cover(document, "entityregistrantname")
        cik = _cover(document, "entitycentralindexkey")
        if (not company or not re.fullmatch(r"[0-9]{10}", cik)
                or _cover(document, "documenttype") != "10-K"
                or _displayed_date(_cover(document, "documentperiodenddate")) != current):
            requirements.append("source_identity_verification")
        if not table.separate_title and (
            table.issuer is None or _normalized_company(table.issuer.text) != _normalized_company(company)
        ):
            requirements.append("statement_issuer_verification")
        requirements.extend(_shared_source_requirements(source, company, cik, current))
        scale, unit_locator = _original_statement_scale(table, headers, annual)
        statement = DatedStatement(table, rows, label, annual, scale, unit_locator,
                                   shared_year=not table.separate_title)
        weeks: dict[int, int] = {}
        if table.separate_title:
            notes, weeks = dated_policy_notes(document, lines, after=table.position, issuer=company)
        else:
            notes = accounting_policy_notes(
                document, lines, after=table.position, includes_fees=any(
                    cell.cell.text.casefold() == "membership and other income"
                    for row in headers for cell in row
                ),
            )
        if len(notes) != 2:
            requirements.append("applicable_notes")
        base = {
            "source_id": source["source_id"], "company": company or None,
            "filing_date": source["filing_date"], "parser_version": parser_version,
            "evidence_version": SHARED_YEAR_EVIDENCE_VERSION, "applicable_notes": notes,
            "status": "provisional" if requirements else "verified",
            "unresolved_requirements": requirements.copy(),
            "parent_table_id": f'{source["source_id"]}#table-{table.number}',
        }
        facts = _annual_facts(document, statement, periods, cik, base, diagnostics, weeks)
    except UnsupportedLayout as exc:
        diagnostics.append({"code": "unsupported_layout", "message": str(exc)})
    unresolved = list(dict.fromkeys([*requirements, *(
        requirement for fact in facts for requirement in fact["unresolved_requirements"]
    )]))
    return {
        "parser_version": parser_version, "evidence_version": SHARED_YEAR_EVIDENCE_VERSION,
        "facts": facts, "diagnostics": diagnostics, "comparison": legacy_comparison(),
        "unresolved_requirements": [*unresolved, *(["extraction"] if diagnostics else []),
                                    "comparison_compatibility"],
        "verification_reference": None, "real_source_acceptance": False,
    }


def _original_statement_scale(
    table: Table, headers: list[list[GridCell]], annual: GridCell,
) -> tuple[int, dict[str, int]]:
    if table.separate_title:
        declaration = DATED_MONEY_HEADER.fullmatch(annual.cell.text)
        units = SHARED_MONEY_PREAMBLE.fullmatch(declaration[1]) if declaration else None
        locator = annual.locator(table)
    else:
        unit_entries: list[tuple[EvidenceText, dict[str, int]]] = [
            (cell.cell, cell.locator(table)) for row in headers for cell in row if MONEY_PREAMBLE.match(cell.cell.text)
        ]
        if table.preamble:
            unit_entries.append((table.preamble, {"table": table.number, **table.preamble.locator()}))
        unit, locator = _one(unit_entries, "Expected one visible consolidated statement scale.")
        units = SHARED_MONEY_PREAMBLE.fullmatch(unit.text)
    if units is None:
        raise UnsupportedLayout("The visible statement currency or scale declaration is unsupported.")
    return SCALES[units[1].casefold()], locator


def _titled_table_columns(rows: list[list[GridCell]]) -> tuple[GridCell, dict[date, GridCell]]:
    annual = _one([cell for row in rows for cell in row if DATED_MONEY_HEADER.fullmatch(cell.cell.text)],
                  "Expected one annual period and scale header.")
    header_cells = [cell for cell in rows[annual.row - 1] if cell is not annual and cell.cell.text]
    periods = {_displayed_date(cell.cell.text): cell for cell in header_cells}
    if len({end.year for end in periods}) != len(header_cells) or len(periods) < 2:
        raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
    return annual, periods


def _shared_year_columns(rows: list[list[GridCell]], annual: GridCell) -> dict[date, GridCell]:
    match = SHARED_YEAR_HEADER.fullmatch(annual.cell.text)
    assert match is not None
    candidates = [
        [cell for cell in row if cell.cell.text and cell.columns.start in annual.columns]
        for row in rows[annual.row:]
    ]
    headers = _one([row for row in candidates if row and all(re.fullmatch(r"(?:19|20)\d{2}", cell.cell.text)
                                                            for cell in row)],
                   "Expected one row of fiscal years below the shared year-end.")
    periods = {_displayed_date(f"{match[1]}, {cell.cell.text}"): cell for cell in headers}
    if (len(periods) != len(headers) or len(periods) < 2
            or not all(set(cell.columns) <= set(annual.columns) for cell in headers)):
        raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
    return periods


def _normalized_company(name: str) -> str:
    return " ".join(re.sub(r"[,\.]", "", name).casefold().split())


def _shared_source_requirements(source: dict[str, Any], company: str, cik: str, end: date) -> list[str]:
    unresolved = []
    if source["provenance"]["kind"] == "synthetic":
        unresolved.append("original_filing")
    if source["company"] is not None and _normalized_company(source["company"]) != _normalized_company(company):
        unresolved.append("supplied_company_conflict")
    if source["form"] not in (None, "10-K"):
        unresolved.append("supplied_form_conflict")
    if source["filing_date"] is not None and source["filing_date"] < end.isoformat():
        unresolved.append("supplied_filing_date_conflict")
    if source["source_url"] is not None:
        try:
            path = urlsplit(source["source_url"]).path
        except ValueError:
            path = ""
        match = re.fullmatch(r"(?:/Archives/edgar/data)?/(\d+)/(\d{18})/[^/]+", path)
        if (not match or not cik or match[1].lstrip("0") != cik.lstrip("0")
                or (source["accession"] is not None and source["accession"].replace("-", "") != match[2])):
            unresolved.append("supplied_source_url_conflict")
    return unresolved
