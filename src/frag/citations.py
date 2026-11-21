"""Read visible citation excerpts from the original at its verified locators."""

import re
from html.parser import HTMLParser
from typing import Any

from frag.store import SourceError
from frag.verification import REFERENCE

CELL_END = re.compile(r"</(?:td|th)\s*>", re.IGNORECASE)
BLOCK_TAGS = {"div", "p", "tr", "h1", "h2", "h3", "li"}


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
    lines = original.decode("utf-8-sig").split("\n")
    locator = citation["locator"]
    heading = f'{citation["title"]}\nSource SHA-256 · {source_hash}\n'
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
    first_line, last_line = start["line"] - 1, end["line"] - 1
    # The current verification reference uses whole-line disclosure ranges.
    if start["character"] != 1 or end["character"] != 1:
        raise SourceError("Unsupported disclosure locator.")
    if source_hash == REFERENCE["identity"]["source_hash"]:
        for line in REFERENCE["citation_heading_lines"].get(citation["id"], []):
            heading += f"{_visible_text(lines[line - 1])} · HTML line {line}\n"
    excerpt = _visible_text("\n".join(lines[first_line:last_line]))
    return f"{heading}{_position(start)} to {_position(end)} (exclusive)\n\n{excerpt}\n"


def _position(locator: dict[str, int]) -> str:
    return f'HTML line {locator["line"]}, character {locator["character"]}'


def _cell_text(lines: list[str], locator: dict[str, int]) -> str:
    line, offset = locator["line"] - 1, locator["character"] - 1
    # The verified statement cells in the retained filing close on the same line.
    fragment = lines[line][offset:]
    end = CELL_END.search(fragment)
    if not end or not fragment.startswith(("<td", "<th")):
        raise SourceError("The statement cell cannot be opened at its verified locator.")
    return _visible_text(fragment[:end.end()])


def _visible_text(fragment: str) -> str:
    parser = _ExcerptText()
    parser.feed(fragment)
    parser.close()
    return parser.text
