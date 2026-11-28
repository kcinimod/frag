"""Verify revenue in consolidated statements with separately dated columns."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from importlib.resources import files
from typing import Any
from urllib.parse import urlsplit

from frag.income_html import (
    EvidenceText, GridCell, StatementHTML, Table, UnsupportedLayout, is_statement_heading, original_span,
    statement_periods, table_grid,
)
from frag.revenue import MONTHS, REVENUE_CONCEPT, SCALES, _normalize, _value_cell, revenue_fact_id
from frag.revenue_notes import (
    StatementPolicies, accounting_policy_notes, acquisition_revenue_notes, comparison_disclosures,
    cross_section_policy_notes, dated_policy_notes, fiscal_year_policy_notes, january_calendar_policy_notes,
    numbered_policy_notes, referenced_revenue_policy, reporting_period_policy, statement_policy_notes,
    unnumbered_revenue_policy,
)

PARSER_VERSION = "dated-annual-revenue-v1"
SHARED_YEAR_PARSER_VERSION = "shared-year-revenue-v1"
TITLED_TABLE_PARSER_VERSION = "titled-table-revenue-v1"
DATED_COLUMNS_PARSER_VERSION = "dated-columns-revenue-v1"
ORIGINAL_EVIDENCE_PARSERS = {SHARED_YEAR_PARSER_VERSION, TITLED_TABLE_PARSER_VERSION, DATED_COLUMNS_PARSER_VERSION}
FILING_SCOPED_PARSERS = ORIGINAL_EVIDENCE_PARSERS | {PARSER_VERSION}
SHARED_YEAR_EVIDENCE_VERSION = "original-revenue-evidence-v1"
REFERENCE = json.loads(files("frag").joinpath("apple-revenue-reference.json").read_text(encoding="utf-8"))
EVIDENCE_VERSION: str = REFERENCE["evidence_version"]
EXTRACTION_CACHE_REVISION = "statement-periods-v9"
OPERATIONS_HEADING = re.compile(r"consolidated statements? of operations", re.I)
DATE_HEADER = re.compile(r"([A-Za-z]+) ([0-9]{1,2}), ([0-9]{4})")
MONTH_DAY = re.compile(r"[A-Za-z]+ [0-9]{1,2},?")
FISCAL_YEAR = re.compile(r"(?:19|20)[0-9]{2}")
MONEY_DECLARATION = (
    r"(?:dollars |amounts )?in (thousands|millions|billions)(?:,? except per[- ]share (?:data|amounts))?"
)
SHARED_YEAR_HEADER = re.compile(
    rf"(?:{MONEY_DECLARATION}; )?(?:for the )?(?:fiscal )?years? ended ([A-Za-z]+ [0-9]{{1,2}}),?"
    r"(?: \(in (thousands|millions|billions); per-share amounts in dollars\))?", re.I,
)
MONEY_PREAMBLE = re.compile(r"^\(?(?:dollars |amounts )?in (thousands|millions|billions)\b", re.I)
SHARED_MONEY_PREAMBLE = re.compile(rf"\({MONEY_DECLARATION}\)", re.I)
DATED_MONEY_HEADER = re.compile(r"years ended (\(.+\))", re.I)
FISCAL_YEAR_UNITS = re.compile(r"\((thousands|millions|billions), except per[- ]share (?:data|amounts)\)", re.I)
DATE_MONTHS = MONTHS | {name[:3]: month for name, month in MONTHS.items()}
DATED_ANNUAL_HEADERS = {"year ended", "years ended"}
SHARED_REVENUE_LABELS = {"total net sales", "total revenue", "total revenues", "revenues", "revenue", "net operating revenues"}
TOTAL_REVENUE_NOTE = re.compile(r"total revenues? \(note (\d+)\)", re.I)
COMBINED_YEAR_HEADER = re.compile(rf"(?:for the )?years? ended ({DATE_HEADER.pattern})", re.I)
EXTERNAL_YEAR_ENDS = re.compile(
    rf"(?:for the )?(?:fiscal )?years ended {DATE_HEADER.pattern}"
    rf"(?:, {DATE_HEADER.pattern})*,? and {DATE_HEADER.pattern}", re.I,
)
DISPLAYED_WEEKS = re.compile(r"\((52|53) weeks\)", re.I)


@dataclass(frozen=True)
class DatedStatement:
    table: Table
    rows: list[list[GridCell]]
    label: GridCell
    annual: GridCell
    scale: int
    unit_header: dict[str, int]
    shared_year: bool = False
    date_prefixes: dict[date, GridCell] = field(default_factory=dict)
    original_dated_columns: bool = False
    fiscal_labels: dict[date, int] = field(default_factory=dict)
    disclosed_year_end_weekday: int | None = None
    calendar_starts: dict[date, date] = field(default_factory=dict)
    external_annual_header: EvidenceText | None = None
    accepts_aggregate_revenues_tag: bool = False

    @property
    def uses_original_evidence(self) -> bool:
        return (self.shared_year or self.table.separate_title or self.original_dated_columns
                or bool(self.fiscal_labels or self.calendar_starts))

    @property
    def issuer_heading(self) -> EvidenceText | None:
        issuer = self.table.issuer
        if issuer is not None and issuer.text.casefold() == "table of contents":
            return None
        if self.disclosed_year_end_weekday is not None and issuer is not None and DATE_HEADER.fullmatch(issuer.text):
            return None
        return issuer


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
    reviewed_dated_filing = _cover(document, "entitycentralindexkey") == REFERENCE["identity"]["cik"]
    return [
        table for table in document.tables
        if table.heading and (table.embedded_heading
                              or is_statement_heading(table.heading.text, allow_short_income_heading=False)
                              or (table.preamble is not None and re.fullmatch(
                                  r"consolidated income statements?", table.heading.text, re.I,
                              )))
        and (table.separate_title or any(
                 SHARED_YEAR_HEADER.fullmatch(cell.text) or COMBINED_YEAR_HEADER.fullmatch(cell.text)
                 or (table.preamble is not None and FISCAL_YEAR.fullmatch(cell.text))
                 for row in table.rows for cell in row
             )
             or (not reviewed_dated_filing and any(
                 cell.text.casefold() in DATED_ANNUAL_HEADERS | {"fiscal"} or FISCAL_YEAR_UNITS.fullmatch(cell.text)
                 for row in table.rows for cell in row
             )))
    ]


def _displayed_date(text: str) -> date:
    match = DATE_HEADER.fullmatch(text)
    if match is None:
        raise UnsupportedLayout("Expected a full fiscal year-end date in the statement.")
    try:
        return date(int(match[3]), DATE_MONTHS[match[1].casefold()], int(match[2]))
    except (KeyError, ValueError) as exc:
        raise UnsupportedLayout("Invalid fiscal year-end date in the statement.") from exc


def _original_cover_end(document: StatementHTML) -> date | None:
    dates: set[date] = set()
    for fact in document.cover_facts.get("dei:documentperiodenddate", []):
        try:
            if numeric := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", fact.text):
                dates.add(date(int(numeric[3]), int(numeric[1]), int(numeric[2])))
            else:
                dates.add(_displayed_date(fact.text))
        except ValueError:
            return None
    return next(iter(dates)) if len(dates) == 1 else None


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
        "metric_label": label.locator(table),
        "annual_header": (statement.external_annual_header.locator() if statement.external_annual_header
                          else statement.annual.locator(table)),
        "year_header": header.locator(table), "value": value.locator(table),
        "unit_header": statement.unit_header, "currency_symbol": markers[0].locator(table),
    }
    if statement.uses_original_evidence and not table.separate_title and (issuer := statement.issuer_heading):
        locators["statement_issuer"] = issuer.locator()
    if end in statement.date_prefixes:
        locators["date_prefix"] = statement.date_prefixes[end].locator(table)
    calendar_start = statement.calendar_starts.get(end)
    start = calendar_start.isoformat() if calendar_start else None
    if statement.shared_year:
        try:
            start = (end.replace(year=end.year - 1) + timedelta(days=1)).isoformat()
        except ValueError:
            pass
    year = statement.fiscal_labels.get(end, end.year)
    return {
        **base, "fact_id": revenue_fact_id(base["source_id"], year),
        "metric": "reported_consolidated_revenue", "metric_label": label.cell.text,
        "raw_amount": raw, "normalized_amount": amount, "currency": "USD", "scale": scale,
        "basis": "as_reported_in_filing", "scope": "consolidated",
        "reporting_period": {"kind": "annual", "fiscal_year": year, "start": start, "end": end.isoformat()},
        "inline_xbrl": None, "locators": locators,
    }, value


def _verify_inline(
    document: StatementHTML, statement: DatedStatement, value: GridCell, end: date,
    prior_end: date | None, cik: str, fact: dict[str, Any], weeks: int | None,
) -> None:
    if (end in statement.calendar_starts
            and not value.cell.inline_facts and not document.contexts and not document.unit_measures):
        raise UnsupportedLayout(
            "The consolidated statement displays revenue for this year, "
            "but the original lacks the inline XBRL fact, context, and unit needed for verification."
        )
    tagged = _one(value.cell.inline_facts, "Expected one inline XBRL fact in the revenue cell.")
    inline = tagged.attrs
    concepts = {REVENUE_CONCEPT.casefold()}
    if statement.shared_year or statement.accepts_aggregate_revenues_tag or (
        end in statement.calendar_starts
        and statement.label.cell.text.casefold() in {"revenue", "revenues", "total revenue", "total revenues"}
    ):
        concepts.add("us-gaap:revenues")
    if (inline.get("name") or "").casefold() not in concepts:
        raise UnsupportedLayout("The inline XBRL concept conflicts with the total revenue row.")
    start, context = _inline_period(document, inline, cik, end, prior_end,
                                    statement=statement, weeks=weeks)
    if inline.get("scale") != str(len(str(statement.scale)) - 1):
        raise UnsupportedLayout("Inline XBRL scale conflicts with the visible statement scale.")
    formats = {"ixt:num-dot-decimal"}
    if statement.external_annual_header is not None:
        formats.add("ixt:numdotdecimal")
    if (inline.get("format") not in formats or inline.get("sign") is not None
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
    weeks: dict[int, int], qualified_years: set[int] | None = None,
) -> list[dict[str, Any]]:
    facts = []
    ordered = sorted(periods)
    for index, end in enumerate(ordered):
        calendar_start = statement.calendar_starts.get(end)
        prior_end = calendar_start - timedelta(days=1) if calendar_start else (ordered[index - 1] if index else None)
        fact = None
        year = statement.fiscal_labels.get(end, end.year)
        if statement.fiscal_labels and statement.external_annual_header is None:
            weekday = statement.disclosed_year_end_weekday
            prior_end = _fiscal_week_year_end(year - 1, weekday if weekday is not None else 6)
        week_count = weeks.get(year)
        try:
            fact, value = _visible_fact(statement, periods[end], end, base)
            _verify_inline(document, statement, value, end, prior_end, cik, fact, week_count)
        except UnsupportedLayout as exc:
            diagnostics.append({"code": "unsupported_observation", "fiscal_year": year, "message": str(exc)})
            if fact is None or not statement.uses_original_evidence:
                continue
            fact.update(status="provisional",
                        unresolved_requirements=[*fact["unresolved_requirements"], "inline_xbrl_verification"])
        if (statement.table.separate_title or statement.original_dated_columns
                or statement.fiscal_labels) and week_count is None:
            fact.update(status="provisional",
                        unresolved_requirements=[*fact["unresolved_requirements"], "fiscal_calendar_verification"])
        if qualified_years and year in qualified_years:
            fact.update(status="provisional",
                        unresolved_requirements=[*fact["unresolved_requirements"], "applicable_notes"])
        facts.append(fact | {"comparative": end < ordered[-1]})
    return facts


def inspect_dated_revenue(
    document: StatementHTML, lines: list[str], source: dict[str, Any],
) -> dict[str, Any]:
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    unresolved = []
    coverage = None
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
        if len(document.tables) == 1 and not _shared_source_requirements(source, company, cik, current):
            coverage = statement_periods(table, annual, {end.year: header for end, header in periods.items()},
                                         label, rows)
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
        **({"statement_periods": coverage} if coverage else {}),
    }


def inspect_original_revenue(
    document: StatementHTML, tables: list[Table], lines: list[str], source: dict[str, Any],
    *, selected_label: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Find an annual observation and verify its evidence without a reviewed reference."""
    facts: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    requirements: list[str] = []
    parser_version = SHARED_YEAR_PARSER_VERSION
    comparison = legacy_comparison()
    coverage = None
    try:
        table = _one(tables, "Expected one visible consolidated income statement.")
        if selected_label is None and len(document.tables) != 1:
            raise UnsupportedLayout("More than one statement table could contain consolidated revenue.")
        rows = [row.cells for row in table_grid(table)]
        if selected_label is None:
            label = _original_revenue_label(table, rows)
        else:
            row_number, cell_number = selected_label
            label = rows[row_number - 1][cell_number - 1]
        headers = rows[:label.row - 1]
        date_prefixes: dict[date, GridCell] = {}
        fiscal_labels: dict[date, int] = {}
        fiscal_header = any(cell.cell.text.casefold() == "fiscal" for row in headers for cell in row)
        fiscal_unit_headers = [cell for row in headers for cell in row if FISCAL_YEAR_UNITS.fullmatch(cell.cell.text)]
        disclosed_fiscal_years = False
        policy = StatementPolicies()
        company = _cover(document, "entityregistrantname")
        cik = _cover(document, "entitycentralindexkey")
        cover_end = _original_cover_end(document)
        shared_row = False
        combined_headers = [cell for row in headers for cell in row if COMBINED_YEAR_HEADER.fullmatch(cell.cell.text)]
        has_shared_header = any(SHARED_YEAR_HEADER.fullmatch(cell.cell.text) for row in headers for cell in row)
        calendar_starts: dict[date, date] = {}
        calendar_year_labels = False
        external_header = None
        displayed_weeks: dict[int, int] = {}
        if table.separate_title:
            parser_version = TITLED_TABLE_PARSER_VERSION
            annual, periods = _titled_table_columns(headers)
        elif any(cell.cell.text.casefold() in DATED_ANNUAL_HEADERS for row in headers for cell in row):
            parser_version = DATED_COLUMNS_PARSER_VERSION
            annual, periods, date_prefixes = _dated_columns(headers, label)
        elif fiscal_header:
            policy = statement_policy_notes(document, lines, after=table.position, layout="week_based")
            if not policy.week_based_calendar:
                raise UnsupportedLayout("The filing does not establish the calendar for its fiscal year labels.")
            if cover_end is None:
                raise UnsupportedLayout("The fiscal year-end on the filing cover is unresolved.")
            annual, periods, fiscal_labels, date_prefixes = _fiscal_week_columns(
                headers, label, cover_end,
            )
        elif fiscal_unit_headers:
            disclosed_fiscal_years = True
            annual = _one(fiscal_unit_headers, "Expected one fiscal year and units header.")
            policy = fiscal_year_policy_notes(document, lines, after=table.position)
            periods, fiscal_labels = _disclosed_fiscal_year_columns(headers, label, annual, policy)
        elif combined_headers:
            annual, periods = _combined_year_columns(headers, label, combined_headers)
        elif selected_label is not None and (external_header := _external_annual_header(table)) is not None:
            annual, periods, fiscal_labels, displayed_weeks = _external_year_columns(headers, label, external_header)
            requirements.append("fiscal_calendar_verification")
        elif not has_shared_header and table.preamble:
            calendar_year_labels = True
            policy = reporting_period_policy(document, lines, after=table.position)
            annual, periods, calendar_starts = _disclosed_calendar_columns(headers, label, policy)
        else:
            annual = _one([cell for row in headers for cell in row if SHARED_YEAR_HEADER.fullmatch(cell.cell.text)],
                          "Expected one shared fiscal year-end above the revenue row.")
            shared_row = annual.columns.stop <= label.columns.stop
            periods = _shared_year_columns(headers, annual, label, shared_row=shared_row)
        if not table.separate_title:
            _check_revenue_columns(rows[label.row - 1], label, periods)
        current = max(periods)
        if (not company or not re.fullmatch(r"[0-9]{10}", cik)
                or _cover(document, "documenttype") != "10-K"
                or cover_end != current):
            requirements.append("source_identity_verification")
        scale, unit_locator = _original_statement_scale(table, headers, annual, external_header=external_header)
        singular_annual_header = parser_version == DATED_COLUMNS_PARSER_VERSION and annual.cell.text.casefold() == "year ended"
        if singular_annual_header:
            policy = january_calendar_policy_notes(document, lines, after=table.position)
            if policy.year_end_weekday is not None:
                calendar_starts = _january_calendar_starts(periods, policy.weeks, policy.year_end_weekday, diagnostics)
            policy.weeks = {end.year: policy.weeks[end.year] for end in calendar_starts}
            company = company or policy.issuer or ""
        statement = DatedStatement(table, rows, label, annual, scale, unit_locator,
                                   shared_year=parser_version == SHARED_YEAR_PARSER_VERSION
                                   and not (fiscal_labels or calendar_year_labels),
                                   date_prefixes=date_prefixes,
                                   original_dated_columns=parser_version == DATED_COLUMNS_PARSER_VERSION,
                                   fiscal_labels=fiscal_labels,
                                   disclosed_year_end_weekday=policy.year_end_weekday if fiscal_labels else None,
                                   calendar_starts=calendar_starts, external_annual_header=external_header,
                                   accepts_aggregate_revenues_tag=selected_label is not None and (
                                       external_header is not None or (
                                           parser_version == DATED_COLUMNS_PARSER_VERSION
                                           and label.cell.text.casefold() in {"total revenue", "total revenues"}
                                       )
                                   ))
        issuer = statement.issuer_heading
        conflicting_heading = issuer is not None and _company_words(issuer.text, statement=True) != _company_words(company)
        if disclosed_fiscal_years:
            if conflicting_heading or not policy.issuer or _issuer_name(policy.issuer) != _issuer_name(company):
                requirements.append("statement_issuer_verification")
        elif calendar_year_labels and (
            not policy.issuer or _company_words(policy.issuer) != _company_words(company) or conflicting_heading
        ):
            requirements.append("statement_issuer_verification")
        elif not (table.separate_title or table.embedded_heading or calendar_year_labels) and (
            issuer is None or conflicting_heading
        ):
            requirements.append("statement_issuer_verification")
        if singular_annual_header and (not policy.issuer or _issuer_name(policy.issuer) != _issuer_name(company)):
            requirements.append("statement_issuer_verification")
        requirements.extend(_shared_source_requirements(source, company, cik, current))
        if not requirements:
            coverage = statement_periods(
                table, annual, {fiscal_labels.get(end, end.year): header for end, header in periods.items()},
                label, rows, date_prefixes={fiscal_labels.get(end, end.year): cell for end, cell in date_prefixes.items()},
            )
            if (shared_row or combined_headers or calendar_year_labels or fiscal_labels
                    or parser_version == DATED_COLUMNS_PARSER_VERSION) and not coverage:
                raise UnsupportedLayout("The visible fiscal year headers do not establish an unambiguous period inventory.")
        weeks = displayed_weeks
        qualified_years: set[int] = set()
        acquisition_notes: list[dict[str, Any]] = []
        caveats: list[str] | None = []
        pair = sorted(periods)[-2:]
        current_year = fiscal_labels.get(current, current.year)
        if table.separate_title:
            notes, weeks, qualified_years = dated_policy_notes(document, lines, after=table.position, issuer=company)
        elif singular_annual_header:
            notes, weeks, qualified_years = policy.notes, policy.weeks, policy.qualified_years
        elif statement.original_dated_columns:
            notes, weeks, qualified_years = numbered_policy_notes(document, lines, after=table.position)
            acquisition = acquisition_revenue_notes(document, lines, after=table.position, year=current.year)
            if acquisition is None:
                qualified_years.add(current.year)
                diagnostics.append({
                    "code": "unsupported_notes", "fiscal_year": current.year,
                    "message": "The applicable acquisition disclosures could not be established.",
                })
            else:
                acquisition_notes, caveats = acquisition
        elif disclosed_fiscal_years:
            notes, weeks, qualified_years = policy.notes, policy.weeks, policy.qualified_years
        elif calendar_year_labels:
            notes, weeks, qualified_years = policy.notes, policy.weeks, policy.qualified_years
            caveats = policy.caveats
        elif combined_headers:
            policy = unnumbered_revenue_policy(document, lines, after=table.position)
            notes, qualified_years, caveats = policy.notes, policy.qualified_years, policy.caveats
        elif (reference := TOTAL_REVENUE_NOTE.fullmatch(label.cell.text)) and not table.embedded_heading:
            policy = referenced_revenue_policy(document, lines, after=table.position, number=int(reference[1]))
            notes, qualified_years, caveats = policy.notes, policy.qualified_years, policy.caveats
        elif fiscal_header or table.embedded_heading or (
            table.heading and re.fullmatch(r"statements? of consolidated income", table.heading.text, re.I)
        ):
            if not fiscal_header:
                policy = statement_policy_notes(
                    document, lines, after=table.position,
                    layout="continuing_operations" if table.embedded_heading else "transportation",
                )
            notes, weeks, qualified_years = policy.notes, policy.weeks, policy.qualified_years
            acquisition_notes, caveats = policy.comparison_notes, policy.caveats
            if table.embedded_heading:
                if not notes or not policy.issuer:
                    coverage = None
                elif _company_words(policy.issuer) != _company_words(company):
                    requirements.append("statement_issuer_verification")
                    coverage = None
            elif not _transaction_in_period(policy.transaction_date, pair[0], current):
                qualified_years.add(current_year)
                acquisition_notes, caveats = [], None
        else:
            extended_notes = cross_section_policy_notes(
                document, lines, after=table.position, comparison_years={end.year for end in pair},
            )
            if extended_notes is None:
                notes = accounting_policy_notes(
                    document, lines, after=table.position, includes_fees=any(
                        cell.cell.text.casefold() == "membership and other income"
                        for row in headers for cell in row
                    ),
                )
            else:
                notes, caveats, qualified_years = extended_notes
        if len(notes) < 2:
            requirements.append("applicable_notes")
            diagnostics.append({"code": "unsupported_notes",
                                "message": "The applicable filing disclosures could not be established."})
        base = {
            "source_id": source["source_id"], "company": company or None,
            "filing_date": source["filing_date"], "parser_version": parser_version,
            "evidence_version": SHARED_YEAR_EVIDENCE_VERSION, "applicable_notes": notes,
            "status": "provisional" if requirements else "verified",
            "unresolved_requirements": requirements.copy(),
            "parent_table_id": f'{source["source_id"]}#table-{table.number}',
        }
        facts = _annual_facts(document, statement, periods, cik, base, diagnostics, weeks, qualified_years)
        for fact in facts:
            if fact["reporting_period"]["fiscal_year"] == current_year and acquisition_notes:
                fact["applicable_notes"] = [*fact["applicable_notes"], *acquisition_notes]
        pair_years = [fiscal_labels.get(end, end.year) for end in pair]
        disclosures = comparison_disclosures(document, lines, after=table.position, years=set(pair_years))
        comparison = _original_comparison(facts, pair_years, weeks, disclosures, unresolved_notes=caveats is None)
        if comparison["status"] == "compatible" and caveats:
            comparison["scope_caveats"].extend(caveats)
    except UnsupportedLayout as exc:
        diagnostics.append({"code": "unsupported_layout", "message": str(exc)})
    unresolved = list(dict.fromkeys([*requirements, *(
        requirement for fact in facts for requirement in fact["unresolved_requirements"]
    )]))
    return {
        "parser_version": parser_version, "evidence_version": SHARED_YEAR_EVIDENCE_VERSION,
        "facts": facts, "diagnostics": diagnostics, "comparison": comparison,
        "unresolved_requirements": [*unresolved, *(["extraction"] if diagnostics else []),
                                    *comparison["unresolved_requirements"]],
        "verification_reference": None, "real_source_acceptance": False,
        **({"statement_periods": coverage} if coverage else {}),
    }


def _original_revenue_label(table: Table, rows: list[list[GridCell]]) -> GridCell:
    labels = SHARED_REVENUE_LABELS | {"net revenue"} if table.separate_title else SHARED_REVENUE_LABELS
    candidates = [cell for row in rows for cell in row
                  if (cell.cell.text.casefold() in labels or TOTAL_REVENUE_NOTE.fullmatch(cell.cell.text))
                  and any(entry is not cell and entry.cell.text for entry in row)]
    if table.embedded_heading:
        candidates = [cell for cell in candidates if cell.cell.text.casefold().startswith("total ")]
    # Net sales may be a subtotal when the statement also reports total revenue.
    if not candidates:
        candidates = [cell for row in rows for cell in row if cell.cell.text.casefold() == "net sales"]
    return _one(candidates, "Expected one total revenue row in the consolidated statement.")


def _dated_columns(
    rows: list[list[GridCell]], label: GridCell,
) -> tuple[GridCell, dict[date, GridCell], dict[date, GridCell]]:
    annual = _one([cell for row in rows for cell in row if cell.cell.text.casefold() in DATED_ANNUAL_HEADERS],
                  "Expected one annual period header above the revenue row.")
    dated_rows = []
    for row in rows[annual.row - 1:]:
        cells = [cell for cell in row if cell is not annual and cell.cell.text
                 and cell.columns.start >= label.columns.stop]
        if any(DATE_HEADER.fullmatch(cell.cell.text) or MONTH_DAY.fullmatch(cell.cell.text)
               or FISCAL_YEAR.fullmatch(cell.cell.text) for cell in cells):
            dated_rows.append(cells)

    message = "The displayed fiscal year columns are ambiguous."
    prefixes: dict[date, GridCell] = {}
    if len(dated_rows) == 1:
        periods = {_displayed_date(cell.cell.text): cell for cell in dated_rows[0]}
    elif len(dated_rows) == 2:
        month_days, years = dated_rows
        if (len(month_days) != len(years) or not all(MONTH_DAY.fullmatch(cell.cell.text) for cell in month_days)
                or not all(FISCAL_YEAR.fullmatch(cell.cell.text) for cell in years)):
            raise UnsupportedLayout(message)
        periods = {}
        for prefix, year in zip(month_days, years, strict=True):
            if prefix.columns != year.columns:
                raise UnsupportedLayout(message)
            end = _displayed_date(f"{prefix.cell.text.rstrip(',')}, {year.cell.text}")
            periods[end], prefixes[end] = year, prefix
    else:
        raise UnsupportedLayout(message)

    headers = dated_rows[-1]
    if (len(periods) != len(headers) or len({end.year for end in periods}) != len(headers) or len(headers) < 2
            or (annual.columns.stop > label.columns.stop and not all(
                set(header.columns) <= set(annual.columns) for header in headers
            ))):
        raise UnsupportedLayout(message)
    return annual, periods, prefixes


def _january_calendar_starts(
    periods: dict[date, GridCell], weeks: dict[int, int], weekday: int, diagnostics: list[dict[str, Any]],
) -> dict[date, date]:
    def last_weekday(year: int) -> date:
        january_end = date(year, 1, 31)
        return january_end - timedelta(days=(january_end.weekday() - weekday) % 7)

    starts = {}
    for end in periods:
        week_count = weeks.get(end.year)
        if week_count is None:
            continue
        prior_end = last_weekday(end.year - 1)
        if end == last_weekday(end.year) and end - prior_end == timedelta(weeks=week_count):
            starts[end] = prior_end + timedelta(days=1)
        else:
            diagnostics.append({
                "code": "unsupported_calendar", "fiscal_year": end.year,
                "message": "The displayed fiscal year-end or week count conflicts with the disclosed January calendar.",
            })
    return starts


def _fiscal_week_columns(
    rows: list[list[GridCell]], label: GridCell, current: date,
) -> tuple[GridCell, dict[date, GridCell], dict[date, int], dict[date, GridCell]]:
    prefixes = [cell for row in rows for cell in row if cell.cell.text.casefold() == "fiscal"]
    years = [cell for row in rows for cell in row if FISCAL_YEAR.fullmatch(cell.cell.text)]
    message = "The fiscal labels and disclosed week-based calendar do not resolve to unique periods."
    if (len(years) < 2 or len(prefixes) != len(years)
            or len({cell.row for cell in prefixes}) != 1 or len({cell.row for cell in years}) != 1
            or prefixes[0].row + 1 != years[0].row):
        raise UnsupportedLayout(message)
    periods, labels, date_prefixes = {}, {}, {}
    for index, (prefix, cell) in enumerate(zip(prefixes, years, strict=True)):
        year = int(cell.cell.text)
        end = _fiscal_week_year_end(year)
        if (prefix.columns != cell.columns or cell.columns.start < label.columns.stop
                or year != current.year - 1 - index or (index == 0 and end != current)):
            raise UnsupportedLayout(message)
        periods[end], labels[end], date_prefixes[end] = cell, year, prefix
    return prefixes[0], periods, labels, date_prefixes


def _fiscal_week_year_end(fiscal_year: int, weekday: int = 6) -> date:
    january_end = date(fiscal_year + 1, 1, 31)
    days_to_week_end = weekday - january_end.weekday()
    return january_end + timedelta(days=(days_to_week_end + 3) % 7 - 3)


def _disclosed_fiscal_year_columns(
    rows: list[list[GridCell]], label: GridCell, annual: GridCell, policy: StatementPolicies,
) -> tuple[dict[date, GridCell], dict[date, int]]:
    headers = [cell for cell in rows[annual.row - 1] if cell.cell.text and cell is not annual]
    message = "The displayed fiscal years do not match the disclosed fiscal calendar."
    if (annual.columns.stop > label.columns.stop or len(headers) < 2 or any(
        not FISCAL_YEAR.fullmatch(cell.cell.text) or cell.columns.start < label.columns.stop for cell in headers
    )):
        raise UnsupportedLayout(message)
    years = [int(cell.cell.text) for cell in headers]
    weekday = policy.year_end_weekday
    if (weekday is None or years != list(range(years[0], years[0] - len(years), -1))
            or any(year not in policy.period_ends for year in years)):
        raise UnsupportedLayout(message)
    ends = [_displayed_date(policy.period_ends[year]) for year in years]
    if any(end != _fiscal_week_year_end(year, weekday) for end, year in zip(ends, years, strict=True)):
        raise UnsupportedLayout("The disclosed fiscal year-end dates conflict with the filing's calendar rule.")
    return dict(zip(ends, headers, strict=True)), dict(zip(ends, years, strict=True))


def _transaction_in_period(disclosed: str | None, prior_end: date, current_end: date) -> bool:
    if disclosed is None:
        return False
    try:
        return prior_end < _displayed_date(disclosed) <= current_end
    except UnsupportedLayout:
        return False


def _check_revenue_columns(row: list[GridCell], label: GridCell, periods: dict[date, GridCell]) -> None:
    """Reject values without one visible period column before verifying any observations."""
    for cell in row:
        if cell is label or not cell.cell.text:
            continue
        if sum(set(cell.columns) <= set(header.columns) for header in periods.values()) != 1:
            raise UnsupportedLayout("A revenue cell cannot be associated with one displayed fiscal year column.")


def _original_comparison(
    facts: list[dict[str, Any]], years: list[int], weeks: dict[int, int], disclosures: list[dict[str, Any]],
    *, unresolved_notes: bool,
) -> dict[str, Any]:
    prior_year, current_year = years
    verified = {fact["reporting_period"]["fiscal_year"]: fact for fact in facts if fact["status"] == "verified"}
    prior, current = verified.get(prior_year), verified.get(current_year)
    comparison = legacy_comparison()
    if prior is None or current is None:
        return comparison

    comparison["fact_ids"] = [prior["fact_id"], current["fact_id"]]
    if disclosures:
        comparison.update(
            detail="The filing says reported consolidated revenue is not comparable across these fiscal years.",
            evidence=disclosures,
        )
        return comparison
    if unresolved_notes:
        comparison["detail"] = "The filing's applicable comparison disclosures could not be established."
        return comparison
    prior_end = date.fromisoformat(prior["reporting_period"]["end"])
    if (prior_year + 1 != current_year
            or current["reporting_period"]["start"] != (prior_end + timedelta(days=1)).isoformat()):
        comparison["detail"] = "The filing does not establish consecutive annual reporting periods."
        return comparison
    if prior["inline_xbrl"]["concept"].casefold() != current["inline_xbrl"]["concept"].casefold():
        comparison["detail"] = "The two revenue cells use different inline XBRL concepts. Their comparability is unresolved."
        return comparison

    caveats = ["Growth uses reported consolidated amounts, including any effects of exchange rates or acquisitions."]
    prior_weeks, current_weeks = weeks.get(prior_year), weeks.get(current_year)
    if prior_weeks is not None and current_weeks is not None and prior_weeks != current_weeks:
        caveats.append(f"FY{prior_year} spans {prior_weeks} weeks and FY{current_year} spans "
                       f"{current_weeks} weeks. Growth uses the fiscal years as reported.")
    comparison.update(
        status="compatible",
        basis="Consecutive annual consolidated revenue amounts from the same statement and reporting basis.",
        scope_caveats=caveats,
        unresolved_requirements=[],
    )
    return comparison


def _original_statement_scale(
    table: Table, headers: list[list[GridCell]], annual: GridCell, *,
    external_header: EvidenceText | None = None,
) -> tuple[int, dict[str, int]]:
    if fiscal_units := FISCAL_YEAR_UNITS.fullmatch(annual.cell.text):
        return SCALES[fiscal_units[1].casefold()], annual.locator(table)
    if table.separate_title:
        declaration = DATED_MONEY_HEADER.fullmatch(annual.cell.text)
        units = SHARED_MONEY_PREAMBLE.fullmatch(declaration[1]) if declaration else None
        locator = annual.locator(table)
    else:
        declaration = SHARED_YEAR_HEADER.fullmatch(annual.cell.text)
        unit_entries: list[tuple[EvidenceText, dict[str, int]]] = [
            (cell.cell, cell.locator(table)) for row in headers for cell in row
            if cell is not annual and MONEY_PREAMBLE.match(cell.cell.text)
        ]
        if table.preamble:
            unit_entries.append((table.preamble, {"table": table.number, **table.preamble.locator()}))
        if external_header is not None:
            unit_entries.extend((block, {"table": table.number, **block.locator()})
                                for block in table.nearby if block.position > external_header.position
                                and block is not table.preamble and MONEY_PREAMBLE.match(block.text))
        if declaration and (scale := declaration[1] or declaration[3]):
            if unit_entries or (declaration[1] and declaration[3]):
                raise UnsupportedLayout("Expected one visible consolidated statement scale.")
            return SCALES[scale.casefold()], annual.locator(table)
        unit, locator = _one(unit_entries, "Expected one visible consolidated statement scale.")
        units = SHARED_MONEY_PREAMBLE.fullmatch(unit.text) or re.fullmatch(MONEY_DECLARATION, unit.text, re.I)
    if units is None:
        raise UnsupportedLayout("The visible statement currency or scale declaration is unsupported.")
    return SCALES[units[1].casefold()], locator


def _external_annual_header(table: Table) -> EvidenceText | None:
    assert table.heading is not None
    headers = [block for block in table.nearby if table.heading.position < block.position
               and EXTERNAL_YEAR_ENDS.fullmatch(block.text)]
    return _one(headers, "Expected one external annual date list.") if headers else None


def _external_year_columns(
    headers: list[list[GridCell]], label: GridCell, annual_header: EvidenceText,
) -> tuple[GridCell, dict[date, GridCell], dict[date, int], dict[int, int]]:
    ends = [_displayed_date(match[0]) for match in DATE_HEADER.finditer(annual_header.text)]
    data_rows = [[cell for cell in row if cell.cell.text and cell.columns.start >= label.columns.stop]
                 for row in headers]
    columns = _one([row for row in data_rows if any(FISCAL_YEAR.fullmatch(cell.cell.text) for cell in row)],
                   "Expected one row of fiscal years for the external annual dates.")
    if len(columns) != len(ends) or not all(FISCAL_YEAR.fullmatch(cell.cell.text) for cell in columns):
        raise UnsupportedLayout("The external annual dates do not align with the fiscal year columns.")
    years = [int(cell.cell.text) for cell in columns]
    offsets = {end.year - year for end, year in zip(ends, years, strict=True)}
    if (len(offsets) != 1 or not offsets <= {0, 1}
            or not all(newer - older == 1 for newer, older in zip(years, years[1:]))):
        raise UnsupportedLayout("The external annual dates conflict with the displayed fiscal years.")
    periods = dict(zip(ends, columns, strict=True))
    week_rows = [row for row in data_rows if any(DISPLAYED_WEEKS.fullmatch(cell.cell.text) for cell in row)]
    weeks = {}
    if week_rows:
        week_row = _one(week_rows, "Expected one row of week counts for the external annual dates.")
        if len(week_row) != len(columns):
            raise UnsupportedLayout("The displayed week counts do not align with the fiscal year columns.")
        for week_cell, column, year in zip(week_row, columns, years, strict=True):
            week = DISPLAYED_WEEKS.fullmatch(week_cell.cell.text)
            if week is None or not set(week_cell.columns) <= set(column.columns):
                raise UnsupportedLayout("The displayed week counts do not align with the fiscal year columns.")
            weeks[year] = int(week[1])
    return columns[0], periods, dict(zip(ends, years, strict=True)), weeks


def _titled_table_columns(rows: list[list[GridCell]]) -> tuple[GridCell, dict[date, GridCell]]:
    annual = _one([cell for row in rows for cell in row if DATED_MONEY_HEADER.fullmatch(cell.cell.text)],
                  "Expected one annual period and scale header.")
    header_cells = [cell for cell in rows[annual.row - 1] if cell is not annual and cell.cell.text]
    periods = {_displayed_date(cell.cell.text): cell for cell in header_cells}
    if len({end.year for end in periods}) != len(header_cells) or len(periods) < 2:
        raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
    return annual, periods


def _combined_year_columns(
    rows: list[list[GridCell]], label: GridCell, combined: list[GridCell],
) -> tuple[GridCell, dict[date, GridCell]]:
    annual = _one(combined, "Expected one annual header containing a full year-end.")
    match = COMBINED_YEAR_HEADER.fullmatch(annual.cell.text)
    assert match is not None
    current = _displayed_date(match[1])
    row = [cell for cell in rows[annual.row - 1] if cell.cell.text and cell.columns.stop > label.columns.stop]
    if (not row or row[0] is not annual or annual.columns.start >= label.columns.stop
            or not all(FISCAL_YEAR.fullmatch(cell.cell.text) for cell in row[1:])):
        raise UnsupportedLayout("The full year-end does not identify the first revenue column unambiguously.")
    # The first cell also spans the label. Restrict the year to the data columns.
    first = replace(annual, columns=range(label.columns.stop, annual.columns.stop))
    periods = {current: first}
    for cell in row[1:]:
        end = _displayed_date(f"{match[2]} {match[3]}, {cell.cell.text}")
        if end in periods or end > current:
            raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
        periods[end] = cell
    if len(periods) < 2:
        raise UnsupportedLayout("Expected comparative fiscal year columns beside the full year-end.")
    if any((FISCAL_YEAR.fullmatch(cell.cell.text) or SHARED_YEAR_HEADER.fullmatch(cell.cell.text))
           and cell.columns.stop > label.columns.stop
           for other in rows if other is not rows[annual.row - 1] for cell in other):
        raise UnsupportedLayout("More than one row displays fiscal years above the consolidated revenue.")
    return annual, periods


def _disclosed_calendar_columns(
    rows: list[list[GridCell]], label: GridCell, policy: StatementPolicies,
) -> tuple[GridCell, dict[date, GridCell], dict[date, date]]:
    headers = _one([
        populated for row in rows
        if (populated := [cell for cell in row if cell.cell.text and cell.columns.stop > label.columns.stop])
        and all(cell.columns.start >= label.columns.stop and FISCAL_YEAR.fullmatch(cell.cell.text)
                for cell in populated)
    ], "Expected one row of fiscal year labels.")
    if any(FISCAL_YEAR.fullmatch(cell.cell.text) and cell.columns.stop > label.columns.stop
           for row in rows for cell in row if cell.row != headers[0].row):
        raise UnsupportedLayout("More than one row displays fiscal years above the consolidated revenue.")
    anchor_month_day, weekday = policy.calendar_anchor, policy.year_end_weekday
    if anchor_month_day is None or weekday is None:
        raise UnsupportedLayout("The applicable fiscal-calendar disclosure could not be established.")

    def year_end(year: int) -> date:
        anchor = date(year, *anchor_month_day)
        offset = (weekday - anchor.weekday() + 3) % 7 - 3
        return anchor + timedelta(days=offset)

    periods: dict[date, GridCell] = {}
    starts: dict[date, date] = {}
    for header in headers:
        year = int(header.cell.text)
        end, start = year_end(year), year_end(year - 1) + timedelta(days=1)
        if end in periods or end.year != year:
            raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
        if (end - start).days + 1 != 7 * policy.weeks.get(year, 0):
            raise UnsupportedLayout("The displayed years conflict with the disclosed fiscal calendar.")
        periods[end] = header
        starts[end] = start
    if len(periods) < 2:
        raise UnsupportedLayout("Expected comparative fiscal years in the consolidated statement.")
    return headers[0], periods, starts


def _shared_year_columns(
    rows: list[list[GridCell]], annual: GridCell, label: GridCell, *, shared_row: bool,
) -> dict[date, GridCell]:
    match = SHARED_YEAR_HEADER.fullmatch(annual.cell.text)
    assert match is not None
    if shared_row:
        headers = [cell for cell in rows[annual.row - 1]
                   if cell.cell.text and cell.columns.start >= label.columns.stop]
        if not all(FISCAL_YEAR.fullmatch(cell.cell.text) for cell in headers):
            raise UnsupportedLayout("Expected fiscal year columns beside the shared year-end.")
        if any(FISCAL_YEAR.fullmatch(cell.cell.text) and cell.columns.stop > label.columns.stop
               for row in rows if row is not rows[annual.row - 1] for cell in row):
            raise UnsupportedLayout("More than one row displays fiscal years above the consolidated revenue.")
    else:
        candidates = [
            [cell for cell in row if cell.cell.text and cell.columns.start in annual.columns]
            for row in rows[annual.row:]
        ]
        headers = _one([row for row in candidates if row and all(FISCAL_YEAR.fullmatch(cell.cell.text)
                                                                for cell in row)],
                       "Expected one row of fiscal years below the shared year-end.")
    periods = {_displayed_date(f"{match[2]}, {cell.cell.text}"): cell for cell in headers}
    if (len(periods) != len(headers) or len(periods) < 2
            or (not shared_row and not all(set(cell.columns) <= set(annual.columns) for cell in headers))):
        raise UnsupportedLayout("The displayed fiscal year columns are ambiguous.")
    return periods


def _normalized_company(name: str) -> str:
    return " ".join(re.sub(r"[,\.]", "", name).casefold().split())


def _company_words(name: str, *, statement: bool = False) -> str:
    name = _normalized_company(re.sub(r"(?<=\w)['’](?=\w)", "", name.replace("-", " "))).removesuffix("/")
    if statement:
        name = re.sub(r"^[0-9]+ ", "", name).removesuffix(" and subsidiaries")
        name = re.sub(r" \d{4} annual report \d+$", "", name)
    name = re.sub(r"\bco$", "company", name.removeprefix("the "))
    return re.sub(r"\bcorp$", "corporation", name)


def _issuer_name(name: str) -> str:
    return re.sub(r" (?:corp(?:oration)?|inc(?:orporated)?)$", "", _company_words(name))


def _shared_source_requirements(source: dict[str, Any], company: str, cik: str, end: date) -> list[str]:
    unresolved = []
    if source["provenance"]["kind"] == "synthetic":
        unresolved.append("original_filing")
    if company and source["company"] is not None and _company_words(source["company"]) != _company_words(company):
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
        if (not match or (cik and match[1].lstrip("0") != cik.lstrip("0"))
                or (source["accession"] is not None and source["accession"].replace("-", "") != match[2])):
            unresolved.append("supplied_source_url_conflict")
    return unresolved
