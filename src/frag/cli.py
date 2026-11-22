"""JSON ingest/inspect commands. Filing content is read only as bytes."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Sequence

from frag.collection import GROWTH_CONTEXT_LIMIT, CollectionIndex, ask_collection, replay_collection
from frag.growth import calculate_growth
from frag.local_model import propose_lookup
from frag.lookup import ask_revenue, replay_revenue
from frag.sec import download_microsoft_filing
from frag.store import SourceError, SourceMetadata, SourceStore


def _write_validation_record(path: Path, record: dict[str, Any]) -> None:
    body = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".frag-lookup-", delete=False) as output:
            temporary = Path(output.name)
            output.write(body)
        # Publish the complete file without replacing another run.
        if os.name == "nt":
            temporary.rename(path)
        else:
            os.link(temporary, path)
    except FileExistsError as exc:
        raise SourceError("Choose a new validation record path.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_question(question: str | None) -> str:
    if question is not None:
        return question
    if sys.stdin.isatty():
        print("Question: ", end="", file=sys.stderr, flush=True)
    return sys.stdin.readline(301).rstrip("\r\n")


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
    growth = commands.add_parser("growth", help="Calculate verified fiscal-year revenue growth")
    growth.add_argument("source_id")
    growth.add_argument("prior_year", type=int)
    growth.add_argument("current_year", type=int)
    growth.add_argument("--store", type=Path, required=True)
    ask = commands.add_parser("ask", help="Ask for verified annual revenue or revenue growth in a selected filing")
    ask.add_argument("source_id")
    ask.add_argument("question", nargs="?", help="Question text. Omit to read from standard input.")
    ask.add_argument("--store", type=Path, required=True)
    ask.add_argument("--record", type=Path, help="Save an explicit validation run to a new JSON file")
    replay = commands.add_parser("replay-ask", aliases=["replay-lookup"], help="Validate and execute a saved chatbot plan offline")
    replay.add_argument("record", type=Path)
    replay.add_argument("--store", type=Path, required=True)
    collection_index = commands.add_parser("index-collection", help="Build and show the validated local index snapshot")
    collection_index.add_argument("--store", type=Path, required=True)
    collection = commands.add_parser("ask-collection", help="Search preserved filings for annual revenue and growth")
    collection.add_argument("question", nargs="?", help="Question text. Omit to read from standard input.")
    collection.add_argument("--store", type=Path, required=True)
    collection.add_argument("--record", type=Path, help="Save the candidates and outcome to a new JSON file")
    collection.add_argument("--context-limit", type=int, default=GROWTH_CONTEXT_LIMIT,
                            help="Maximum evidence records selected for a growth question")
    collection_replay = commands.add_parser("replay-collection", help="Reproduce a saved collection run offline")
    collection_replay.add_argument("record", type=Path)
    collection_replay.add_argument("--store", type=Path, required=True)
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
        elif args.command == "growth":
            result = calculate_growth(store.inspect(args.source_id), args.prior_year, args.current_year)
        elif args.command == "ask":
            record: dict[str, Any] | None = {} if args.record else None
            if args.record and args.record.exists():
                raise SourceError("Choose a new validation record path.")
            source = store.inspect(args.source_id)
            result = ask_revenue(source, _read_question(args.question), propose_lookup, record=record)
            if args.record and record is not None:
                _write_validation_record(args.record, record)
        elif args.command in ("replay-ask", "replay-lookup"):
            saved = json.loads(args.record.read_text(encoding="utf-8"))
            identity = saved.get("source") if isinstance(saved, dict) else None
            if not isinstance(identity, dict) or not isinstance(identity.get("source_id"), str):
                raise SourceError("The validation record must identify its preserved filing.")
            result = replay_revenue(store.inspect(identity["source_id"]), saved)
        elif args.command == "index-collection":
            result = CollectionIndex.build(store).manifest
        elif args.command == "ask-collection":
            collection_record: dict[str, Any] | None = {} if args.record else None
            if args.record and args.record.exists():
                raise SourceError("Choose a new validation record path.")
            question = _read_question(args.question)
            result = ask_collection(CollectionIndex.build(store), question, record=collection_record,
                                    context_limit=args.context_limit)
            if args.record and collection_record is not None:
                _write_validation_record(args.record, collection_record)
        elif args.command == "replay-collection":
            result = replay_collection(store, json.loads(args.record.read_text(encoding="utf-8")))
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
