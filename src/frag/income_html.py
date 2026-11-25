"""Read statement tables and preserve their coordinates in the original HTML."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

BASIS_NOTE_HEADING = re.compile(r"Note 1\s*:\s*Basis of Presentation", re.I)
ACCOUNTING_POLICIES_HEADING = re.compile(r"Note 2\s*:\s*Accounting Policies", re.I)
ADDITIONAL_PERIOD_LABEL = re.compile(
    r"\b[A-Za-z]+\s+\d{1,2},?\s+\d{4}\b|\b\d{4}\s*\(|\b(?:fiscal year|fy)\s*\d{4}\b", re.I,
)


class UnsupportedLayout(ValueError):
    """The statement cannot be interpreted unambiguously."""


class HTMLVisibility:
    """Track content explicitly hidden by the original markup."""

    def __init__(self) -> None:
        self._tag: str | None = None
        self._depth = 0

    @property
    def hidden(self) -> bool:
        return self._tag is not None

    def start(self, tag: str, attrs: dict[str, str | None]) -> None:
        if not self.hidden and tag not in VOID_TAGS and (
            tag in {"ix:hidden", "template"} or "hidden" in attrs
            or HIDDEN_STYLE.search(attrs.get("style") or "")
        ):
            self._tag = tag
        if tag == self._tag:
            self._depth += 1

    def end(self, tag: str) -> None:
        if tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self._tag = None


def is_statement_heading(text: str, *, allow_short_income_heading: bool = True) -> bool:
    # The filing can split a heading across styled inline runs.
    compact = re.sub(r"\s+", "", text).casefold()
    if allow_short_income_heading and compact.removeprefix("consolidated") in {"incomestatement", "incomestatements"}:
        return True
    return compact in {
        "consolidatedstatementofincome", "consolidatedstatementsofincome",
        "consolidatedstatementofearnings", "consolidatedstatementsofearnings",
        "consolidatedstatementofoperations", "consolidatedstatementsofoperations",
    }


def original_span(lines: list[str], start: dict[str, int], end: dict[str, int]) -> str:
    """Resolve a one-based half-open HTML span without changing the source bytes."""
    first_line, first_char = start.get("line"), start.get("character")
    last_line, last_char = end.get("line"), end.get("character")
    if (type(first_line) is not int or type(last_line) is not int
            or type(first_char) is not int or type(last_char) is not int
            or not 1 <= first_line <= last_line <= len(lines) + 1
            or first_line > len(lines) or not 1 <= first_char <= len(lines[first_line - 1]) + 1
            or (first_line, first_char) >= (last_line, last_char)):
        raise ValueError("The disclosure range is outside the preserved original.")
    last = lines[last_line - 1] if last_line <= len(lines) else ""
    if not 1 <= last_char <= len(last) + 1:
        raise ValueError("The disclosure range is outside the preserved original.")
    if first_line == last_line:
        return last[first_char - 1:last_char - 1]
    return "\n".join([
        lines[first_line - 1][first_char - 1:], *lines[first_line:last_line - 1], last[:last_char - 1],
    ])


@dataclass
class EvidenceText:
    position: tuple[int, int]
    parts: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join("".join(self.parts).split())

    def locator(self) -> dict[str, int]:
        line, zero_based_character = self.position
        return {"line": line, "character": zero_based_character + 1}


@dataclass
class TextBlock(EvidenceText):
    end: tuple[int, int] | None = None


@dataclass
class Cell(EvidenceText):
    attrs: dict[str, str | None] = field(default_factory=dict)
    inline_facts: list["InlineFact"] = field(default_factory=list)


@dataclass
class InlineFact(EvidenceText):
    attrs: dict[str, str | None] = field(default_factory=dict)


@dataclass
class InlineContext:
    position: tuple[int, int]
    fields: dict[str, EvidenceText] = field(default_factory=dict)
    dimensioned: bool = False
    identifier_scheme: str | None = None


@dataclass
class Table:
    number: int
    position: tuple[int, int]
    heading: EvidenceText | None
    caption: EvidenceText | None = None
    preamble: EvidenceText | None = None
    rows: list[list[Cell]] = field(default_factory=list)
    nested: bool = False
    complete: bool = False
    issuer: EvidenceText | None = None
    separate_title: bool = False
    wrapper: tuple[int, int] | None = None

    def locator(self) -> dict[str, int]:
        return {"table": self.number, **EvidenceText(self.position).locator()}


class StatementHTML(HTMLParser):
    """Collect physical rows without letting nested or outside cells leak into them."""

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[Table] = []
        self.unit_measures: dict[str, list[EvidenceText]] = {}
        self.contexts: dict[str, list[InlineContext]] = {}
        self.cover_facts: dict[str, list[EvidenceText]] = {}
        self.blocks: list[TextBlock] = []
        self._cover_fact: EvidenceText | None = None
        self._cover_depth = 0
        self._context: InlineContext | None = None
        self._context_field: EvidenceText | None = None
        self._unit: str | None = None
        self._measure: EvidenceText | None = None
        self._count = 0
        self._depth = 0
        self._table: Table | None = None
        self._cell: Cell | None = None
        self._inline_fact: InlineFact | None = None
        self._caption: EvidenceText | None = None
        self._heading: EvidenceText | None = None
        self._preamble: EvidenceText | None = None
        self._block: TextBlock | None = None
        self._issuer: EvidenceText | None = None
        self._separate_title = False
        self._ignored: str | None = None
        self._visibility = HTMLVisibility()

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if self._ignored:
            return
        if tag in {"script", "style"}:
            self._ignored = tag
            return
        attrs = dict(attributes)
        self._visibility.start(tag, attrs)
        if tag == "ix:nonnumeric":
            name = (attrs.get("name") or "").casefold()
            if self._cover_fact:
                self._cover_depth += 1
            elif name in COVER_FACTS:
                self._cover_fact = EvidenceText(self.getpos())
                self._cover_depth = 1
                self.cover_facts.setdefault(name, []).append(self._cover_fact)
        if tag == "xbrli:unit":
            self._unit = attrs.get("id")
        elif tag == "xbrli:measure" and self._unit:
            self._measure = EvidenceText(self.getpos())
            self.unit_measures.setdefault(self._unit, []).append(self._measure)
        elif tag == "xbrli:context":
            context_id = attrs.get("id")
            if context_id:
                self._context = InlineContext(self.getpos())
                self.contexts.setdefault(context_id, []).append(self._context)
        elif self._context:
            if tag in CONTEXT_FIELDS:
                if tag in self._context.fields:
                    self._context.dimensioned = True
                self._context_field = self._context.fields[tag] = EvidenceText(self.getpos())
                if tag == "xbrli:identifier":
                    self._context.identifier_scheme = attrs.get("scheme")
            elif tag in {"xbrli:segment", "xbrli:scenario", "xbrli:instant",
                         "xbrldi:explicitmember", "xbrldi:typedmember"}:
                self._context.dimensioned = True
        if tag == "table":
            self._count += 1
        if self._visibility.hidden:
            return
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                if self._block and (is_statement_heading(self._block.text)
                                    or (self._heading and self._is_preamble(self._block))):
                    self._finish_block()
                self._table = Table(self._count, self.getpos(), self._heading,
                                    preamble=self._preamble, issuer=self._issuer, separate_title=self._separate_title,
                                    wrapper=self._block.position if self._block and not self._block.text else None)
                self._heading = None
                self._preamble = None
                self._issuer = None
                self._separate_title = False
            elif self._table:
                self._table.nested = True
            return
        if self._depth == 0:
            if tag in BLOCK_TAGS:
                self._finish_block()
                self._block = TextBlock(self.getpos())
            return
        table = self._table
        if self._depth != 1 or table is None:
            return
        if tag == "caption":
            self._caption = table.caption = EvidenceText(self.getpos())
        elif tag == "tr":
            self._cell = None
            table.rows.append([])
        elif tag in {"td", "th"} and table.rows:
            self._cell = Cell(self.getpos(), attrs=attrs)
            table.rows[-1].append(self._cell)
        elif self._cell and tag == "ix:nonfraction":
            self._inline_fact = InlineFact(self.getpos(), attrs=attrs)
            self._cell.inline_facts.append(self._inline_fact)
        elif tag == "br":
            active = self._cell or self._caption
            if active:
                active.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored:
            if tag == self._ignored:
                self._ignored = None
            return
        if tag == "ix:nonnumeric" and self._cover_fact:
            self._cover_depth -= 1
            if not self._cover_depth:
                self._cover_fact = None
        if tag == "xbrli:measure":
            self._measure = None
        elif tag == "xbrli:unit":
            self._unit = None
        elif tag == "xbrli:context":
            self._context = None
            self._context_field = None
        elif tag in CONTEXT_FIELDS:
            self._context_field = None
        if self._visibility.hidden:
            self._visibility.end(tag)
            return
        if tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._table:
                self._table.complete = True
                self._finish_table()
        elif self._depth == 1:
            if tag in {"ix:nonfraction", "td", "th", "tr"}:
                self._inline_fact = None
            if tag in {"td", "th", "tr"}:
                self._cell = None
            elif tag == "caption":
                self._caption = None
        elif self._depth == 0 and tag in BLOCK_TAGS:
            if self._block:
                line, column = self.getpos()
                self._block.end = (line, column + len(tag) + 3)
            self._finish_block()

    def handle_data(self, data: str) -> None:
        if self._ignored:
            return
        if self._cover_fact:
            self._cover_fact.parts.append(data)
        if self._measure:
            self._measure.parts.append(data)
        if self._context_field:
            self._context_field.parts.append(data)
        if self._visibility.hidden:
            return
        if self._depth == 1:
            if self._inline_fact:
                self._inline_fact.parts.append(data)
            active = self._cell or self._caption
            if active:
                active.parts.append(data)
        elif self._depth == 0 and self._block:
            self._block.parts.append(data)
        elif self._depth == 0 and data.strip():
            self._heading = None
            self._preamble = None
            self._issuer = None
            self._separate_title = False

    def close(self) -> None:
        super().close()
        self._finish_table()

    def _finish_block(self) -> None:
        if self._block and self._block.text:
            previous = self.blocks[-1] if self.blocks else None
            if self._block.end is not None:
                self.blocks.append(self._block)
            if is_statement_heading(self._block.text):
                self._issuer = previous
                self._heading = self._block
                self._preamble = None
                self._separate_title = False
            elif self._heading and self._preamble is None and self._is_preamble(self._block):
                self._preamble = self._block
            else:
                self._heading = self._preamble = None
                self._issuer = None
                self._separate_title = False
        self._block = None

    @staticmethod
    def _is_preamble(block: EvidenceText) -> bool:
        return block.text.casefold().startswith(("(in ", "(dollars in ", "(amounts in "))

    def _finish_table(self) -> None:
        if self._table:
            table = self._table
            cells = [cell for row in table.rows for cell in row if cell.text]
            if (table.complete and not table.nested and len(cells) == 1
                    and is_statement_heading(cells[0].text)):
                self._heading, self._separate_title = cells[0], True
            elif table.heading or (
                self._table.caption and is_statement_heading(self._table.caption.text)
            ):
                self.tables.append(table)
            if table.complete and not table.nested and cells:
                heading = " ".join(cell.text for cell in cells)
                if BASIS_NOTE_HEADING.fullmatch(heading) or ACCOUNTING_POLICIES_HEADING.fullmatch(heading):
                    self.blocks.append(TextBlock(table.wrapper or table.position, [heading]))
            self._table = None
        self._cell = self._caption = None
        self._inline_fact = None


BLOCK_TAGS = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
             "param", "source", "track", "wbr"}
HIDDEN_STYLE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", re.I)
CONTEXT_FIELDS = {"xbrli:identifier", "xbrli:startdate", "xbrli:enddate"}
COVER_FACTS = {"dei:documenttype", "dei:documentperiodenddate", "dei:entitycentralindexkey",
               "dei:entityregistrantname"}


@dataclass(frozen=True)
class GridCell:
    cell: Cell
    row: int
    physical_cell: int
    columns: range

    def locator(self, table: Table) -> dict[str, int]:
        return {
            "table": table.number, "row": self.row, "cell": self.physical_cell,
            "column": self.columns.start, **self.cell.locator(),
        }


@dataclass(frozen=True)
class GridRow:
    cells: list[GridCell]
    width: int


def statement_periods(
    table: Table, annual: GridCell, headers: dict[int, GridCell], label: GridCell,
    rows: list[list[GridCell]], *, date_prefixes: dict[int, GridCell] | None = None,
) -> dict[str, Any] | None:
    """Capture the complete displayed period inventory independently of extracted facts."""
    heading = table.caption if table.caption and is_statement_heading(table.caption.text) else table.heading
    header_rows = {entry.row for entry in headers.values()}
    if heading is None or len(headers) < 2 or len(header_rows) != 1:
        return None
    header_row = rows[next(iter(header_rows)) - 1]
    prefixes = date_prefixes or {}
    if any(entry.cell.text and entry is not annual and entry.columns.start >= label.columns.stop
           and entry not in headers.values() for entry in header_row):
        return None
    if any(entry.cell.text and entry is not annual and entry.columns.start >= label.columns.stop
           and (not any(set(entry.columns) <= set(header.columns) for header in headers.values())
                or entry not in headers.values() and entry not in prefixes.values()
                and ADDITIONAL_PERIOD_LABEL.search(entry.cell.text))
           for row in rows[:label.row] for entry in row):
        return None
    return {
        "heading": heading.locator(), "annual_header": annual.locator(table),
        "metric_label": label.locator(table),
        "period_headers": {str(year): header.locator(table) for year, header in sorted(headers.items())},
        **({"date_prefixes": {str(year): cell.locator(table) for year, cell in prefixes.items()}} if prefixes else {}),
    }


def table_grid(table: Table) -> list[GridRow]:
    if table.nested or not table.complete:
        raise UnsupportedLayout("The income statement has nested or incomplete table markup.")
    reserved_until: dict[int, int] = {}
    grid: list[GridRow] = []
    for row_number, row in enumerate(table.rows, 1):
        placed: list[GridCell] = []
        column = 1
        for cell_number, cell in enumerate(row, 1):
            while reserved_until.get(column, 0) >= row_number:
                column += 1
            width = _span(cell, "colspan")
            height = _span(cell, "rowspan")
            columns = range(column, column + width)
            if any(reserved_until.get(slot, 0) >= row_number for slot in columns):
                raise UnsupportedLayout("Overlapping row and column spans in the income statement.")
            if height > 1:
                reserved_until.update((slot, row_number + height - 1) for slot in columns)
            placed.append(GridCell(cell, row_number, cell_number, columns))
            column += width
        last_reserved = max(
            (slot for slot, end in reserved_until.items() if end >= row_number), default=0,
        )
        grid.append(GridRow(placed, max(last_reserved, column - 1)))
    return grid


def _span(cell: Cell, kind: str) -> int:
    value = cell.attrs.get(kind, "1")
    if value is None or not re.fullmatch(r"[0-9]{1,4}", value.strip()):
        raise UnsupportedLayout(f"Invalid {kind} in the income statement.")
    span = int(value)
    if not 1 <= span <= 1000:
        raise UnsupportedLayout(f"Unsupported {kind} in the income statement.")
    return span
