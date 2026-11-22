"""Read visible citation excerpts from the original at its verified locators."""

import re
from html.parser import HTMLParser
from typing import Any

from frag.income_html import is_statement_heading
from frag.store import SourceError
from frag.verification import REFERENCE

CELL_END = re.compile(r"</(?:td|th)\s*>", re.IGNORECASE)
BLOCK_TAGS = {"div", "p", "tr", "h1", "h2", "h3", "li"}


def has_citable_amount(fact: dict[str, Any]) -> bool:
    return fact["normalized_amount"] is not None and bool(
        fact["currency"] and fact["scale"] and fact["locators"].get("value")
    )


def revenue_cell_citation(fact: dict[str, Any], citation_id: str) -> dict[str, Any]:
    year = fact["reporting_period"]["fiscal_year"]
    return {
        "id": citation_id,
        "title": f'FY{year} {fact["metric_label"]} cell',
        "locator": fact["locators"]["value"],
        "context_locators": {
            key: fact["locators"][key] for key in ("metric_label", "year_header", "unit_header")
        },
    }


class _ExcerptText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.ignored: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.ignored:
            if tag in {"script", "style"}:
                self.ignored = tag
            elif tag == "br" or tag in BLOCK_TAGS:
                self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag == self.ignored:
                self.ignored = None
        elif tag in {"td", "th"}:
            self.parts.append(" ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.ignored:
            self.parts.append(data)

    @property
    def text(self) -> str:
        paragraphs = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in paragraphs if line)


def citation_text(original: bytes, source_hash: str, citation: dict[str, Any]) -> str:
    return citation_lines(original.decode("utf-8-sig").split("\n"), source_hash, citation)


def citation_lines(lines: list[str], source_hash: str, citation: dict[str, Any]) -> str:
    locator = citation["locator"]
    heading = f'{citation["title"]}\nSource SHA-256 · {source_hash}\n'
    if "table_locators" in citation:
        table = _fragment_at(lines, locator)
        context = citation["table_locators"]
        statement = _visible_text(_fragment_at(lines, context["statement_heading"]))
        if (not re.match(r"<table[\s>]", table, re.IGNORECASE)
                or not is_statement_heading(statement)
                or not all(context[key]["table"] == locator["table"] for key in ("annual_header", "unit_header"))):
            raise SourceError("The statement table cannot be opened at its verified locators.")
        annual, unit = (_cell_text(lines, context[key]) for key in ("annual_header", "unit_header"))
        if not annual or not unit:
            raise SourceError("The statement table headers are unavailable.")
        return f"{heading}{_position(locator)} · table {locator['table']}\n\n{statement}\n{annual}\n{unit}\n"
    if "context_locators" in citation:
        excerpt = "\n".join(
            _cell_text(lines, position)
            for position in (*citation["context_locators"].values(), locator) if position
        )
        coordinates = ", ".join(
            f"{key} {locator[key]}"
            for key in ("table", "row", "cell", "column")
            if key in locator
        )
        return f"{heading}{_position(locator)} · {coordinates}\n\n{excerpt}\n"
    start, end = locator["start"], locator["end_exclusive"]
    # The current verification reference uses whole-line disclosure ranges.
    if (start.get("character") != 1 or end.get("character") != 1
            or type(start.get("line")) is not int or type(end.get("line")) is not int
            or not 1 <= start["line"] < end["line"] <= len(lines) + 1):
        raise SourceError("Unsupported disclosure locator.")
    if source_hash == REFERENCE["identity"]["source_hash"]:
        for line in REFERENCE["citation_heading_lines"].get(citation["id"], []):
            heading += f"{_visible_text(lines[line - 1])} · HTML line {line}\n"
    excerpt = _visible_text("\n".join(lines[start["line"] - 1:end["line"] - 1]))
    if not excerpt:
        raise SourceError("The disclosure has no visible text at its verified locator.")
    return f"{heading}{_position(start)} to {_position(end)} (exclusive)\n\n{excerpt}\n"


def _position(locator: dict[str, int]) -> str:
    return f'HTML line {locator["line"]}, character {locator["character"]}'


def _fragment_at(lines: list[str], locator: dict[str, int]) -> str:
    line, character = locator.get("line"), locator.get("character")
    if (type(line) is not int or type(character) is not int
            or not 1 <= line <= len(lines) or not 1 <= character <= len(lines[line - 1])):
        raise SourceError("The citation position is outside the preserved original.")
    return lines[line - 1][character - 1:]


def _cell_text(lines: list[str], locator: dict[str, int]) -> str:
    # The verified statement cells in the retained filing close on the same line.
    fragment = _fragment_at(lines, locator)
    end = CELL_END.search(fragment)
    if not end or not fragment.startswith(("<td", "<th")):
        raise SourceError("The statement cell cannot be opened at its verified locator.")
    return _visible_text(fragment[:end.end()])


def _visible_text(fragment: str) -> str:
    parser = _ExcerptText()
    parser.feed(fragment)
    parser.close()
    return parser.text
