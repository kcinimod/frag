"""Synthetic evidence checks for the scorer-custody verifier."""

from hashlib import sha256
from typing import Any

import pytest

from artifacts.phase06.revenue_selection_holdout import audit_observations


def span(original: bytes, fragment: bytes) -> dict[str, Any]:
    start = original.index(fragment)
    return {"start_byte": start, "end_byte": start + len(fragment), "sha256": sha256(fragment).hexdigest()}


@pytest.mark.parametrize(("layout", "visible_scale", "error"), [
    ("aligned", b"millions", None),
    ("swapped", b"millions", "Observation evidence differs"),
    ("shifted", b"millions", "Observation evidence differs"),
    ("aligned", b"thousands", "Statement evidence differs"),
])
def test_review_binds_amount_to_physical_year_column_and_statement_scale(
    layout: str, visible_scale: bytes, error: str | None,
) -> None:
    heading = b"<h2>Consolidated statements of operations</h2>"
    units = b"<p>(In " + visible_scale + b")</p>"
    period_cell = b'<th colspan="2">2024</th>'
    header = b"<tr><th>Years</th>" + period_cell + b'<th colspan="2">2023</th></tr>'
    inline = (b'<ix:nonFraction id="f" contextRef="c" unitRef="usd" '
              b'name="us-gaap:Revenues" scale="6">19</ix:nonFraction>')
    value_cell = b"<td>" + inline + b"</td>"
    amount = b"<td>$</td>" + value_cell
    other = b"<td>$</td><td>12</td>"
    cells = {
        "aligned": amount + other,
        "swapped": other + amount,
        "shifted": b"<td></td><td></td>" + value_cell + b"<td>12</td>",
    }
    row = b"<tr><td>Revenue</td>" + cells[layout] + b"</tr>"
    statement = b"<table>" + header + row + b"</table>"
    context = b'<xbrli:context id="c">1 2024-01-01 2024-12-31</xbrli:context>'
    unit = b'<xbrli:unit id="usd">iso4217:USD</xbrli:unit>'
    original = heading + units + statement + context + unit
    source = {"source_id": "synthetic", "cik": "1", "accession": "synthetic-accession"}
    review = {
        "statement_title": "Consolidated statements of operations", "statement_row": "Revenue",
        "locators": {
            "statement_heading": span(original, heading), "statement_title_and_units": span(original, units),
            "revenue_row": span(original, row), "statement": span(original, statement),
            "period_header": span(original, header),
        },
        "facts": {"2024": {
            "raw_amount": "19", "normalized_amount": "19000000", "scale": 1_000_000, "scope": "consolidated",
            "period_start": "2024-01-01", "period_end": "2024-12-31", "currency": "USD", "fiscal_year": 2024,
            "concept": "us-gaap:Revenues", "context_id": "c", "element_id": "f",
            "locators": {
                "period_cell": span(original, period_cell), "statement_cell": span(original, value_cell),
                "inline_fact": span(original, inline), "context": span(original, context), "unit": span(original, unit),
            },
        }},
    }
    corroboration = {
        "cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"accn": "synthetic-accession", "start": "2024-01-01", "end": "2024-12-31", "val": 19_000_000},
        ]}}}},
    }
    if error is None:
        audit_observations(original, source, review, corroboration)
    else:
        with pytest.raises(ValueError, match=error):
            audit_observations(original, source, review, corroboration)
