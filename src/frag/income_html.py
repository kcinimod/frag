"""Read statement tables and preserve their coordinates in the original HTML."""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


class UnsupportedLayout(ValueError):
    """The statement cannot be interpreted unambiguously."""


def is_statement_heading(text: str) -> bool:
    # The filing can split a heading across styled inline runs.
    compact = re.sub(r"\s+", "", text).casefold()
    return compact in {
        "incomestatement", "incomestatements",
        "consolidatedincomestatement", "consolidatedincomestatements",
    }


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
class Cell(EvidenceText):
    attrs: dict[str, str | None] = field(default_factory=dict)
    inline_facts: list[dict[str, str | None]] = field(default_factory=list)


@dataclass
class InlineContext:
    position: tuple[int, int]
    fields: dict[str, EvidenceText] = field(default_factory=dict)
    dimensioned: bool = False


@dataclass
class Table:
    number: int
    position: tuple[int, int]
    heading: EvidenceText | None
    caption: EvidenceText | None = None
    rows: list[list[Cell]] = field(default_factory=list)
    nested: bool = False
    complete: bool = False

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
        self._cover_fact: EvidenceText | None = None
        self._context: InlineContext | None = None
        self._context_field: EvidenceText | None = None
        self._unit: str | None = None
        self._measure: EvidenceText | None = None
        self._count = 0
        self._depth = 0
        self._table: Table | None = None
        self._cell: Cell | None = None
        self._caption: EvidenceText | None = None
        self._heading: EvidenceText | None = None
        self._block: EvidenceText | None = None
        self._ignored: str | None = None

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        if self._ignored:
            return
        if tag in {"script", "style"}:
            self._ignored = tag
            return
        if tag == "ix:nonnumeric":
            name = (dict(attributes).get("name") or "").casefold()
            if name in COVER_FACTS:
                self._cover_fact = EvidenceText(self.getpos())
                self.cover_facts.setdefault(name, []).append(self._cover_fact)
        if tag == "xbrli:unit":
            self._unit = dict(attributes).get("id")
        elif tag == "xbrli:measure" and self._unit:
            self._measure = EvidenceText(self.getpos())
            self.unit_measures.setdefault(self._unit, []).append(self._measure)
        elif tag == "xbrli:context":
            context_id = dict(attributes).get("id")
            if context_id:
                self._context = InlineContext(self.getpos())
                self.contexts.setdefault(context_id, []).append(self._context)
        elif self._context:
            if tag in CONTEXT_FIELDS:
                if tag in self._context.fields:
                    self._context.dimensioned = True
                self._context_field = self._context.fields[tag] = EvidenceText(self.getpos())
            elif tag in {"xbrli:segment", "xbrli:scenario"}:
                self._context.dimensioned = True
        if tag == "table":
            self._count += 1
            self._depth += 1
            if self._depth == 1:
                self._table = Table(self._count, self.getpos(), self._heading)
                self._heading = None
            elif self._table:
                self._table.nested = True
            return
        if self._depth == 0:
            if tag in BLOCK_TAGS:
                self._finish_block()
                self._block = EvidenceText(self.getpos())
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
            self._cell = Cell(self.getpos(), attrs=dict(attributes))
            table.rows[-1].append(self._cell)
        elif self._cell and tag == "ix:nonfraction":
            self._cell.inline_facts.append(dict(attributes))
        elif tag == "br":
            active = self._cell or self._caption
            if active:
                active.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._ignored:
            if tag == self._ignored:
                self._ignored = None
            return
        if tag == "ix:nonnumeric":
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
        if tag == "table" and self._depth:
            self._depth -= 1
            if self._depth == 0 and self._table:
                self._table.complete = True
                self._finish_table()
        elif self._depth == 1:
            if tag in {"td", "th", "tr"}:
                self._cell = None
            elif tag == "caption":
                self._caption = None
        elif self._depth == 0 and tag in BLOCK_TAGS:
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
        if self._depth == 1:
            active = self._cell or self._caption
            if active:
                active.parts.append(data)
        elif self._depth == 0 and self._block:
            self._block.parts.append(data)
        elif self._depth == 0 and data.strip():
            self._heading = None

    def close(self) -> None:
        super().close()
        self._finish_table()

    def _finish_block(self) -> None:
        if self._block and self._block.text:
            self._heading = self._block if is_statement_heading(self._block.text) else None
        self._block = None

    def _finish_table(self) -> None:
        if self._table:
            if self._table.heading or (
                self._table.caption and is_statement_heading(self._table.caption.text)
            ):
                self.tables.append(self._table)
            self._table = None
        self._cell = self._caption = None


BLOCK_TAGS = {"div", "p", "h1", "h2", "h3", "h4", "h5", "h6"}
CONTEXT_FIELDS = {"xbrli:identifier", "xbrli:startdate", "xbrli:enddate"}
COVER_FACTS = {"dei:documenttype", "dei:documentperiodenddate", "dei:entitycentralindexkey"}


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
