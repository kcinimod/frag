"""JSON ingest/inspect commands. Filing content is read only as bytes."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Sequence

from frag.sec import download_microsoft_filing
from frag.store import SourceError, SourceMetadata, SourceStore


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="frag")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="Preserve local HTML and extract supported revenue evidence")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--store", type=Path, required=True)
    ingest.add_argument("--provenance", choices=("local_original", "synthetic"), required=True)
    for field in ("company", "accession", "form", "filing-date", "source-url"):
        ingest.add_argument("--" + field)
    download = commands.add_parser("download", help="Download or reuse Microsoft's FY2023 10-K")
    download.add_argument("--store", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="Inspect one source or list all sources")
    inspect.add_argument("source_id", nargs="?")
    inspect.add_argument("--store", type=Path, required=True)
    serve = commands.add_parser("serve", help="Run the browser workspace on localhost")
    serve.add_argument("--store", type=Path, required=True)
    serve.add_argument("--assets", type=Path, default=Path("web/dist"))
    serve.add_argument("--port", type=int, default=5000)
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
        elif args.command == "download":
            result = download_microsoft_filing(store, os.environ.get("SEC_USER_AGENT"))
        elif args.command == "inspect":
            result = store.inspect(args.source_id)
        else:
            from frag.web import create_app

            if not (args.assets / "index.html").is_file():
                raise SourceError("Browser build is missing. Run npm.cmd --prefix web run build.")
            if not 1 <= args.port <= 65535:
                raise SourceError("Port must be between 1 and 65535.")
            create_app(store, args.assets).run(host="127.0.0.1", port=args.port)
            return 0
    except (SourceError, OSError, sqlite3.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0
