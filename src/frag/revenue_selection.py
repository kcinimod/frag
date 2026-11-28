"""Offline table and row selection for reported consolidated revenue."""

from dataclasses import asdict, dataclass, replace
from collections.abc import Iterator
from datetime import date
from hashlib import sha256
import re
from typing import Any

from frag.dated_revenue import SHARED_REVENUE_LABELS, TOTAL_REVENUE_NOTE, inspect_original_revenue
from frag.income_html import (
    Cell, EvidenceText, GridRow, StatementHTML, Table, UnsupportedLayout,
    is_statement_heading, table_grid,
)
from frag.revenue import REVENUE_CONCEPT, _normalize

REVENUE_LABELS = SHARED_REVENUE_LABELS | {"net revenue", "net revenues", "net sales"}
AMOUNT = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")
OPERATING_REVENUE_TOTAL = re.compile(r"total operating revenues?")
COMPONENT_LABEL = re.compile(r"\b(?:subtotals?|segments?|divisions?)\b", re.I)
STATEMENT_CONTEXT = re.compile(
    r"^(?:\((?:in|dollars in|amounts in)\s|(?:for the )?(?:fiscal )?years? ended\b)"
    r"|\b(?:inc\.?|corp\.?|corporation|company)(?: and subsidiaries)?$", re.I,
)


@dataclass(frozen=True)
class FilingInventory:
    original_sha256: str
    document: StatementHTML
    lines: list[str]

    def record(self) -> list[dict[str, Any]]:
        """Serialize the common inventory without financial shortlisting."""
        return [_table_record(table) for table in self.document.visible_tables]

    def inline_definitions(self) -> dict[str, Any]:
        """Expose original context and unit definitions for Inline XBRL references."""
        return {
            "contexts": {
                key: [
                    {
                        "locator": EvidenceText(context.position).locator(),
                        "fields": {name: _text_record(value) for name, value in context.fields.items()},
                        "dimensioned": context.dimensioned, "identifier_scheme": context.identifier_scheme,
                    }
                    for context in contexts
                ]
                for key, contexts in self.document.contexts.items()
            },
            "unit_measures": {
                key: [_text_record(measure) for measure in measures]
                for key, measures in self.document.unit_measures.items()
            },
        }


def filing_inventory(original: bytes) -> FilingInventory:
    html = original.decode("utf-8-sig")
    document = StatementHTML(inventory=True)
    document.feed(html)
    document.close()
    return FilingInventory(sha256(original).hexdigest(), document, html.split("\n"))


@dataclass(frozen=True)
class Selection:
    table_id: str
    row_id: str


def _candidate_rows(inventory: FilingInventory) -> Iterator[tuple[Table, dict[int, bool]]]:
    for table in inventory.document.visible_tables:
        if _statement_heading(table):
            yield table, _revenue_rows(inventory.document, table)


def shortlist_revenue(inventory: FilingInventory) -> list[Selection]:
    """Return every plausible pair before the rules rank them."""
    return [_selection(table, row) for table, rows in _candidate_rows(inventory) for row in rows]


def run_rules(inventory: FilingInventory, source: dict[str, Any]) -> dict[str, Any]:
    """Shortlist plausible statement rows and select a unique strongest total."""
    candidates: list[Selection] = []
    strongest: list[Selection] = []
    for table, rows in _candidate_rows(inventory):
        candidates.extend(_selection(table, row) for row in rows)
        strongest.extend(_selection(table, row) for row in _strongest_rows(rows))
    if len(strongest) == 1:
        result = extract_selection(inventory, source, strongest[0])
    else:
        stop = "ambiguous_candidates" if strongest else "no_candidate"
        result = selection_stop(stop, "Rules did not find a unique consolidated revenue row.")
    return {**result, "candidates": [asdict(candidate) for candidate in candidates]}


def extract_selection(
    inventory: FilingInventory, source: dict[str, Any], selection: Selection,
) -> dict[str, Any]:
    """Resolve a selector's IDs and apply the original-evidence checks to the chosen cells."""
    table = next((table for table in inventory.document.visible_tables
                  if f"table-{table.number}" == selection.table_id), None)
    if table is None:
        return selection_stop("invalid_selection", "The selected table ID is absent.", selection)
    row = next((row for row in range(1, len(table.rows) + 1)
                if _selection(table, row) == selection), None)
    if row is None:
        return selection_stop("invalid_selection", "The selected row ID is absent from the table.", selection)
    heading = _statement_heading(table)
    if heading is None or not _supports_consolidated_total(inventory.document, table, row):
        return selection_stop("unsupported_scope", "The selection does not establish a consolidated revenue total.",
                        selection)
    try:
        rows = table_grid(table)
    except UnsupportedLayout as exc:
        return selection_stop("unsupported_layout", str(exc), selection)
    label = next(cell for cell in rows[row - 1].cells if cell.cell.text)
    statement = replace(table, heading=heading)
    result = inspect_original_revenue(
        inventory.document, [statement], inventory.lines,
        {**source, "source_id": f"sha256:{inventory.original_sha256}"},
        selected_label=(label.row, label.physical_cell),
    )
    observations = result["facts"]
    observed_years = {fact["reporting_period"]["fiscal_year"] for fact in observations}
    missing_observations = any(
        diagnostic["code"] == "unsupported_observation" and diagnostic.get("fiscal_year") not in observed_years
        for diagnostic in result["diagnostics"]
    )
    if not observations or missing_observations or any(
        fact["reporting_period"]["start"] is None for fact in observations
    ):
        stop = "extraction_gap"
    elif any(fact["status"] != "verified" for fact in observations) or result["diagnostics"]:
        stop = "verification_gap"
    else:
        stop = None
    return {
        "selected": asdict(selection), "stop": stop, "observations": observations,
        "diagnostics": result["diagnostics"], "unresolved_requirements": result["unresolved_requirements"],
        "parser_version": result["parser_version"], "evidence_version": result["evidence_version"],
    }


def selection_stop(stop: str, message: str, selection: Selection | None = None) -> dict[str, Any]:
    return {
        "selected": asdict(selection) if selection else None, "stop": stop, "observations": [],
        "diagnostics": [{"code": stop, "message": message}], "unresolved_requirements": [stop],
    }


def _selection(table: Table, row: int) -> Selection:
    table_id = f"table-{table.number}"
    return Selection(table_id, f"{table_id}/row-{row}")


def _statement_heading(table: Table) -> EvidenceText | None:
    if table.caption and table.caption.text and not STATEMENT_CONTEXT.search(table.caption.text):
        return table.caption if _consolidated_heading(table.caption.text) else None
    if table.embedded_heading:
        return table.heading
    first_cell = next((cell for row in table.rows for cell in row if cell.text), None)
    for heading in (table.heading, first_cell):
        if heading and _consolidated_heading(heading.text):
            return heading
    for block in reversed(table.nearby):
        if _consolidated_heading(block.text):
            return block
        if not STATEMENT_CONTEXT.search(block.text):
            break
    return None


def _consolidated_heading(text: str) -> bool:
    return is_statement_heading(text, allow_short_income_heading=False) or text.casefold() in {
        "consolidated income statement", "consolidated income statements",
    }


def _supports_consolidated_total(document: StatementHTML, table: Table, selected_row: int) -> bool:
    """Check the chosen label and competing totals independently of candidate shortlisting."""
    totals = []
    revenue_rows = []
    for row_number, row in enumerate(table.rows, 1):
        texts = [cell.text for cell in row if cell.text]
        if (not texts or not any(_normalize(text, 1) is not None for text in texts[1:])
                or _has_dimensioned_context(document, row)):
            continue
        label = texts[0].casefold()
        if (TOTAL_REVENUE_NOTE.fullmatch(label) or OPERATING_REVENUE_TOTAL.fullmatch(label)
                or (label in REVENUE_LABELS and label.startswith("total "))):
            totals.append(row_number)
        elif label in REVENUE_LABELS or _tagged_annual_revenue(document, row):
            revenue_rows.append(row_number)
    return (totals or revenue_rows) == [selected_row]


def _revenue_rows(document: StatementHTML, table: Table) -> dict[int, bool]:
    candidates = {}
    for row_number, row in enumerate(table.rows, 1):
        texts = [cell.text for cell in row if cell.text]
        if (not texts or sum(AMOUNT.fullmatch(text) is not None for text in texts[1:]) < 2
                or _has_dimensioned_context(document, row)):
            continue
        label = texts[0].casefold()
        if label in REVENUE_LABELS or TOTAL_REVENUE_NOTE.fullmatch(label):
            candidates[row_number] = label.startswith("total ")
        elif _tagged_annual_revenue(document, row):
            candidates[row_number] = False
    return candidates


def _has_dimensioned_context(document: StatementHTML, row: list[Cell]) -> bool:
    return any(context.dimensioned for cell in row for fact in cell.inline_facts
               for context in document.contexts.get(fact.attrs.get("contextref") or "", []))


def _tagged_annual_revenue(document: StatementHTML, row: list[Cell]) -> bool:
    """Recognize unfamiliar labels through consistent company-wide annual revenue tags."""
    visible = [cell for cell in row if cell.text]
    amounts = [cell for cell in visible[1:] if _normalize(cell.text, 1) is not None]
    if len(amounts) < 2 or COMPONENT_LABEL.search(visible[0].text):
        return False
    registrants = document.cover_facts.get("dei:entitycentralindexkey", [])
    if len(registrants) != 1 or not re.fullmatch(r"[0-9]{10}", registrants[0].text):
        return False
    ends = set()
    for cell in amounts:
        if len(cell.inline_facts) != 1:
            return False
        fact = cell.inline_facts[0].attrs
        if (fact.get("name") or "").casefold() != REVENUE_CONCEPT.casefold():
            return False
        contexts = document.contexts.get(fact.get("contextref") or "", [])
        measures = document.unit_measures.get(fact.get("unitref") or "", [])
        if len(contexts) != 1 or len(measures) != 1 or measures[0].text.casefold() != "iso4217:usd":
            return False
        context = contexts[0]
        fields = {name: value.text for name, value in context.fields.items()}
        if (context.dimensioned or fields.get("xbrli:identifier") != registrants[0].text
                or context.identifier_scheme not in {"http://www.sec.gov/CIK", "https://www.sec.gov/CIK"}):
            return False
        try:
            start = date.fromisoformat(fields.get("xbrli:startdate", ""))
            end = date.fromisoformat(fields.get("xbrli:enddate", ""))
        except ValueError:
            return False
        if (end - start).days + 1 not in {364, 365, 366, 371}:
            return False
        ends.add(end)
    return len(ends) == len(amounts)


def _strongest_rows(candidates: dict[int, bool]) -> list[int]:
    return [row for row, total in candidates.items() if total] or list(candidates)


def _text_record(entry: EvidenceText | None) -> dict[str, Any] | None:
    return {"text": entry.text, "locator": entry.locator()} if entry else None


def _table_record(table: Table) -> dict[str, Any]:
    grid: list[GridRow] = []
    grid_error = None
    try:
        grid = table_grid(table, inventory=True)
    except UnsupportedLayout as exc:
        grid_error = str(exc)
    return {
        "table_id": f"table-{table.number}",
        "html_id": table.html_id,
        "locator": table.locator(),
        "nearby": [_text_record(block) for block in table.nearby],
        "heading": _text_record(table.heading),
        "preamble": _text_record(table.preamble),
        "caption": _text_record(table.caption),
        "complete": table.complete,
        "nested": table.nested,
        "grid_error": grid_error,
        "rows": [
            {
                "row_id": _selection(table, row_number).row_id,
                "html_id": html_id,
                "locator": EvidenceText(position).locator(),
                "width": grid[row_number - 1].width if grid else None,
                "cells": [
                    _cell_record(table, cell, row_number, cell_number, grid)
                    for cell_number, cell in enumerate(row, 1)
                ],
            }
            for row_number, (row, (position, html_id)) in enumerate(
                zip(table.rows, table.row_sources, strict=True), 1
            )
        ],
    }


def _cell_record(
    table: Table, cell: Cell, row_number: int, cell_number: int, grid: list[GridRow],
) -> dict[str, Any]:
    placement = grid[row_number - 1].cells[cell_number - 1] if grid else None
    return {
        "text": cell.text,
        "locator": placement.locator(table) if placement else {
            **cell.locator(), "table": table.number, "row": row_number, "cell": cell_number,
        },
        "column": placement.columns.start if placement else None,
        "colspan": cell.attrs.get("colspan"),
        "rowspan": cell.attrs.get("rowspan"),
        "inline_facts": [
            {"text": fact.text, "locator": fact.locator(), "attributes": fact.attrs}
            for fact in cell.inline_facts
        ],
    }
