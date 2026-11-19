"""JSON ingest/inspect commands. Filing content is read only as bytes."""

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from frag.store import SourceError, SourceMetadata, SourceStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frag")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Preserve local HTML without extraction")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--store", type=Path, required=True)
    ingest.add_argument("--provenance", choices=("local_original", "synthetic"), required=True)
    for field in ("company", "accession", "form", "filing-date", "source-url"):
        ingest.add_argument("--" + field)
    inspect = commands.add_parser("inspect", help="Inspect one source or list all sources")
    inspect.add_argument("source_id", nargs="?")
    inspect.add_argument("--store", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        store = SourceStore(args.store)
        if args.command == "ingest":
            result = store.ingest(
                args.path,
                provenance=args.provenance,
                metadata=SourceMetadata(
                    company=args.company, accession=args.accession, form=args.form,
                    filing_date=args.filing_date, source_url=args.source_url,
                ),
            )
        else:
            result = store.inspect(args.source_id)
    except (SourceError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0
