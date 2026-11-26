"""Synthetic controls at the fresh SEC citation scoring boundary."""

from hashlib import sha256
from typing import Any

import pytest

from artifacts.phase06.fresh_score import amount_citation_supported, period_citation_supported


def span(original: bytes, part: bytes) -> dict[str, Any]:
    start = original.index(part)
    return {"start_byte": start, "end_byte": start + len(part), "sha256": sha256(part).hexdigest()}


def locator(original: bytes, part: bytes) -> dict[str, int]:
    return {"line": 1, "character": original.index(part) + 1}


@pytest.mark.parametrize(("declaration", "supported"), [("Amounts in thousands", True), ("Amounts in millions", False)])
def test_citations_require_the_reviewed_scale_and_period_cell(declaration: str, supported: bool) -> None:
    original = b"<div>Amounts in thousands</div><td>Fiscal 2024</td><td>Fiscal 2023</td><td>Revenue</td><td>42</td>"
    units, year, other, row, cell = (b"<div>", b"<td>Fiscal 2024", b"<td>Fiscal 2023", b"<td>Revenue", b"<td>42")
    review = {"locators": {
        "statement_title_and_units": span(original, b"<div>Amounts in thousands</div>"),
        "revenue_row": span(original, b"<td>Revenue</td><td>42</td>"),
    }}
    fact = {"raw_amount": "42", "currency": "USD", "scale": 1000, "fiscal_year": 2024,
            "locators": {"statement_cell": span(original, b"<td>42</td>"),
                         "period_cell": span(original, b"<td>Fiscal 2024</td>")}}
    citation: dict[str, Any] = {"locator": locator(original, cell), "context_locators": {
        "metric_label": locator(original, row), "unit_header": locator(original, units),
        "year_header": locator(original, year),
    }}
    excerpt = f"Revenue\nFiscal 2024\n{declaration}\niso4217:USD\n42"
    assert amount_citation_supported([original], citation, excerpt, review, fact) is supported
    citation["context_locators"]["year_header"] = locator(original, other)
    assert not amount_citation_supported([original], citation, excerpt, review, fact)


def test_absence_citation_covers_every_reviewed_fiscal_header() -> None:
    title, annual, year, prior, metric = (
        b"<div>Consolidated Statements of Income</div>", b"<td>Fiscal</td>",
        b"<td>2024</td>", b"<td>2023</td>", b"<td>Revenue</td>",
    )
    original = title + annual + year + prior + metric
    review = {"locators": {
        "statement_title_and_units": span(original, title),
        "period_header": span(original, annual + year + prior), "revenue_row": span(original, metric),
    }, "facts": {str(fy): {"locators": {"period_cell": span(original, header)}}
                 for fy, header in ((2024, year), (2023, prior))}}
    citation: dict[str, Any] = {"locator": locator(original, year), "context_locators": {
        "statement_heading": locator(original, title), "metric_label": locator(original, metric),
        "annual_header": locator(original, annual), "year_2023": locator(original, prior),
    }}
    assert period_citation_supported([original], citation, review)
    citation["context_locators"]["year_2023"] = locator(original, year)
    assert not period_citation_supported([original], citation, review)
