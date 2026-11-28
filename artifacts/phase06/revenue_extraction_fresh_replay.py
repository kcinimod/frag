"""Replay one frozen extraction revision on the four fresh 10-Ks."""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

EVIDENCE = Path(__file__).resolve().with_name("revenue-extraction-fresh")
FIELDS = ("raw_amount", "normalized_amount", "scale", "currency", "scope")


def hashed_bytes(path: Path, expected: str) -> bytes:
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != expected:
        raise ValueError(f"SHA-256 differs for {path}.")
    return payload


def locator_byte(raw: bytes, locator: dict[str, int]) -> int:
    lines = raw.split(b"\n")
    index = locator["line"] - 1
    prefix = lines[index].decode("utf-8")[:locator["character"] - 1]
    return sum(len(line) + 1 for line in lines[:index]) + len(prefix.encode("utf-8"))


def exact_years(raw: bytes, reference: list[dict[str, Any]], facts: list[dict[str, Any]]) -> list[int]:
    lower = raw.lower()
    exact = []
    for expected in reference:
        inline_start = expected["inline_start"]
        cell_start = lower.rfind(b"<td", 0, inline_start)
        if cell_start < 0 or lower.find(b"</td", cell_start) <= inline_start:
            raise ValueError("The reviewed inline tag did not resolve to an original value cell.")
        matches = []
        for fact in facts:
            period = fact["reporting_period"]
            locator = fact["locators"]["value"]
            if (all(expected[key] == fact[key] for key in FIELDS)
                    and all(period[key] == expected[key] for key in ("fiscal_year", "start", "end"))
                    and locator["cell"] == expected["dom_physical_cell"]
                    and locator_byte(raw, locator) == cell_start):
                matches.append(fact)
        if len(matches) == 1:
            exact.append(expected["fiscal_year"])
    return sorted(exact)


def block_sockets(event: str, args: tuple[Any, ...]) -> None:
    if event.startswith("socket."):
        raise RuntimeError("Sockets are blocked in the fresh replay.")


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("variant", choices=("baseline", "candidate"))
    cli.add_argument("inputs", type=Path)
    cli.add_argument("output", type=Path)
    args = cli.parse_args()
    receipt = json.loads((EVIDENCE / "receipt.json").read_bytes())
    freeze = json.loads(hashed_bytes(EVIDENCE / "freeze.json", receipt["freeze_sha256"]))
    reviews = json.loads(hashed_bytes(EVIDENCE / "review.json", receipt["review_sha256"]))
    if [review["source"] for review in reviews] != freeze["cases"]:
        raise ValueError("The reviewed cases differ from the frozen inputs.")
    revision = freeze[args.variant]
    archive = args.output.with_suffix(".code.zip").resolve()
    with archive.open("xb") as stream:
        stream.write(subprocess.check_output(["git", "archive", revision, "src/frag"]))
    sys.path.insert(0, f"{archive}/src")
    from frag.revenue_selection import filing_inventory, run_rules

    sys.addaudithook(block_sockets)
    cases = []
    for review in reviews:
        source = review["source"]
        folder = args.inputs / source["cik"]
        originals = {name: hashed_bytes(folder / name, digest) for name, digest in source["sha256"].items()}
        raw = originals["original.htm"]
        metadata = {field: source[field] for field in ("accession", "form", "filing_date", "source_url")}
        result = run_rules(filing_inventory(raw), metadata | {
            "company": source["issuer"], "provenance": {"kind": "local_original"},
        })
        cases.append({
            "issuer": source["issuer"], "exact_years": exact_years(raw, review["observations"], result["observations"]),
            "result": result,
        })
    with args.output.open("xb") as stream:
        stream.write((json.dumps({"commit": revision, "cases": cases}, indent=2, sort_keys=True) + "\n").encode())


if __name__ == "__main__":
    main()
