"""Synthetic local originals for the standalone revenue selection experiment."""

import pytest

from frag.revenue_selection import Selection, extract_selection, filing_inventory, run_rules

SYNTHETIC_SOURCE = {
    "filing_date": None, "company": None, "form": None,
    "source_url": None, "accession": None, "provenance": {"kind": "synthetic"},
}


def test_inventory_retains_visible_tables_before_shortlisting() -> None:
    original = (
        b'\xef\xbb\xbf<table hidden><tr><td>Hidden</td></tr></table>\n'
        b'<h2>Segment data</h2>\n'
        b'<table><tr><th rowspan="2">Region</th><th colspan="2">Years ended December 31</th></tr>\n'
        b'<tr><td>2024</td><td>2023</td></tr>\n'
        b'<tr><td>Retail<table><tr><td>Nested</td></tr></table></td><td>19</td><td>12</td></tr></table>\n'
        b'<table><tr><td>Navigation</td></tr></table>'
    )
    inventory = filing_inventory(original).record()
    assert [table["table_id"] for table in inventory] == ["table-2", "table-3", "table-4"]
    table = inventory[0]
    assert table["nearby"][-1] == {"text": "Segment data", "locator": {"line": 2, "character": 1}}
    assert table["rows"][1]["row_id"] == "table-2/row-2"
    assert table["rows"][1]["locator"] == {"line": 4, "character": 1}
    assert table["rows"][1]["cells"][0]["column"] == 2
    assert table["rows"][0]["cells"][0]["rowspan"] == "2"
    assert table["rows"][0]["cells"][1]["colspan"] == "2"
    assert table["rows"][2]["cells"][0]["text"] == "Retail"
    assert inventory[1]["rows"][0]["cells"][0]["text"] == "Nested"


@pytest.mark.parametrize("total_present", [True, False])
def test_rules_select_consolidated_total_or_report_missing_target(total_present: bool) -> None:
    original = b"""
    <h2>Segment results</h2>
    <table><tr><td>Net revenues</td><td>12</td><td>10</td></tr></table>
    <h2>Example Corporation</h2>
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td></tr>
    <tr><td>Retail segment</td><td>$</td><td>12</td><td>$</td><td>10</td></tr>
    TOTAL
    <tr><td>Net income</td><td></td><td>7</td><td></td><td>6</td></tr>
    </table>
    """
    total = b"<tr><td>Net revenues</td><td>$</td><td>19</td><td>$</td><td>15</td></tr>"
    inventory = filing_inventory(original.replace(b"TOTAL", total if total_present else b""))
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    if total_present:
        assert result["selected"] == {"table_id": "table-2", "row_id": "table-2/row-4"}
        assert [(fact["normalized_amount"], fact["status"]) for fact in result["observations"]] == [
            ("15000000", "provisional"), ("19000000", "provisional"),
        ]
        assert result["observations"][0]["source_id"] == f"sha256:{inventory.original_sha256}"
    else:
        assert result["selected"] is None
        assert result["stop"] == "no_candidate"
        assert result["observations"] == []
    segment = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-1"))
    assert segment["stop"] == "unsupported_scope"
    assert segment["observations"] == []


def test_rules_abstain_between_consolidated_statement_candidates() -> None:
    statement = b"""
    <h2>Consolidated Statements of Income</h2>
    <table><tr><td>LABEL</td><td>19</td><td>15</td></tr></table>
    """
    original = statement.replace(b"LABEL", b"Net revenues") + statement.replace(b"LABEL", b"Total revenue")
    result = run_rules(filing_inventory(original), SYNTHETIC_SOURCE)
    assert len(result["candidates"]) == 2
    assert result["selected"] is None
    assert result["stop"] == "ambiguous_candidates"


def test_shared_extractor_rejects_a_subtotal_in_the_selected_statement() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Net sales</td><td>19</td><td>15</td></tr>
    <tr><td>Total revenues</td><td>22</td><td>17</td></tr>
    </table>
    """)
    result = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-1"))
    assert result["stop"] == "unsupported_scope"
    assert result["observations"] == []


def test_an_intervening_segment_heading_blocks_a_stale_statement_title() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <h2>Segment results</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td></tr>
    <tr><td>Net revenues</td><td>$</td><td>12</td><td>$</td><td>10</td></tr>
    </table>
    """)
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    assert result["stop"] == "no_candidate"
    assert result["observations"] == []


def test_explicit_selection_can_extract_a_supported_label_outside_shortlisting() -> None:
    inventory = filing_inventory(b"""
    <h2>Consolidated Statements of Income</h2>
    <table>
    <tr><td>Years Ended December 31,</td><td colspan="2">2024</td><td colspan="2">2023</td></tr>
    <tr><td>(In millions)</td><td>$</td><td></td><td>$</td><td></td></tr>
    <tr><td>Total operating revenue</td><td></td><td>$ 22</td><td></td><td>$ 17</td></tr>
    </table>
    """)
    result = run_rules(inventory, SYNTHETIC_SOURCE)
    assert result["selected"] is None
    result = extract_selection(inventory, SYNTHETIC_SOURCE, Selection("table-1", "table-1/row-3"))
    assert [fact["normalized_amount"] for fact in result["observations"]] == ["17000000", "22000000"]


def test_bom_and_unicode_text_do_not_change_original_locator_conventions() -> None:
    inventory = filing_inventory("\ufeff<table><tr><td>\u2028</td></tr></table>\n<table></table>".encode())
    first, second = inventory.record()
    assert first["locator"] == {"table": 1, "line": 1, "character": 1}
    assert second["locator"] == {"table": 2, "line": 2, "character": 1}
    assert len(inventory.lines) == 2
