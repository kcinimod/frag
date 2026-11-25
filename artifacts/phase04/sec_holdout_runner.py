"""Freeze, run, and replay the label-blind SEC holdout through public FRAG interfaces."""

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
from io import StringIO
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import sys
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from frag import local_model
from frag.cli import main as frag_cli
from frag.store import SourceStore
from frag.web import create_app

DEVELOPMENT_CIKS = {320193, 789019}
RECEIPT = Path(__file__).with_name("sec-holdout-receipt.json")
WEIGHTS_SHA256 = "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_bytes())  # type: ignore[no-any-return]


def write_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        from hashlib import file_digest

        return file_digest(stream, "sha256").hexdigest()


def freeze_inputs() -> dict[str, Any]:
    phase = Path(__file__).parent
    paths = [
        *(ROOT / "src/frag").glob("*.py"),
        *(phase.glob("sec_holdout_*.py")),
        Path(__file__), RECEIPT, phase / "SEC_ACCEPTANCE_PROTOCOL.md",
        ROOT / "scripts/start-local-model.ps1", ROOT / "pyproject.toml", ROOT / "uv.lock",
    ]
    return {
        "files": {path.relative_to(ROOT).as_posix(): digest(path) for path in sorted(set(paths))},
        "python": platform.python_version(),
        "dependencies": {package: version(package) for package in (
            "blinker", "click", "colorama", "flask", "itsdangerous", "jinja2", "markupsafe", "werkzeug",
        )},
        "model": local_model.MODEL_SETTINGS,
        "weights_sha256": WEIGHTS_SHA256,
    }


def runtime_hashes(model_directory: Path) -> dict[str, str]:
    runtime = model_directory / "runtime"
    return {
        path.name: digest(path)
        for path in [runtime / "llama-server.exe", *sorted(runtime.glob("*.dll"))]
    }


def restrict_runner(*, replay: bool, allowed_processes: tuple[str, ...] = ()) -> None:
    """Keep Python file access in the frozen workspace and its interpreter environment."""
    roots = [ROOT, Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()]
    if any(ROOT != root and ROOT.is_relative_to(root) for root in roots):
        raise ValueError("Use a dedicated snapshot and interpreter environment.")
    endpoint = (local_model.HOST, local_model.PORT)

    def audit(event: str, args: tuple[Any, ...]) -> None:
        if event in {"open", "sqlite3.connect", "os.listdir", "os.scandir"}:
            value = args[0]
            if isinstance(value, (str, bytes, Path)):
                filename = value.decode() if isinstance(value, bytes) else str(value)
                if event == "open" and allowed_processes and filename == os.devnull:
                    return
                if event == "sqlite3.connect" and filename.startswith("file:"):
                    uri = urlsplit(filename)
                    if uri.netloc:
                        raise PermissionError("SQLite must use a local file.")
                    filename = url2pathname(uri.path)
                path = Path(filename).resolve()
                if not any(path.is_relative_to(root) for root in roots):
                    raise PermissionError(f"Path outside the evaluation workspace: {path}")
        if event == "socket.getaddrinfo" and (replay or args[:2] != endpoint):
            raise PermissionError("Only the frozen local planner can be resolved during a live run.")
        if event == "socket.connect" and (replay or args[1] != endpoint):
            raise PermissionError("Network connection outside the evaluation protocol.")
        if event == "os.system" or (event == "subprocess.Popen" and args[1] not in allowed_processes):
            raise PermissionError("Evaluation must use in-process public interfaces.")

    sys.addaudithook(audit)


def load_bundle(path: Path, run_directory: Path) -> tuple[dict[str, Any], str]:
    receipt = read_json(RECEIPT)
    if digest(path) != receipt["runner_bundle"]["sha256"]:
        raise ValueError("Runner bundle does not match the custody receipt.")
    with ZipFile(path) as bundle:
        manifest_bytes = bundle.read("manifest.json")
        manifest = json.loads(manifest_bytes)
        filings = {item["source_id"]: item for item in manifest["sources"]}
        cases = manifest["cases"]
        if (manifest["version"] != 1 or manifest["cohort"] != receipt["cohort"]
                or len(manifest["sources"]) != len(filings) or len(filings) != receipt["issuer_count"]
                or len(cases) != receipt["case_count"]
                or len({item["case_id"] for item in cases}) != len(cases)
                or any(set(item) != {"case_id", "source_id", "question"} for item in cases)
                or Counter(item["source_id"] for item in cases) != dict.fromkeys(filings, 3)):
            raise ValueError("Invalid holdout manifest or case coverage.")
        ciks = {int(item["cik"]) for item in filings.values()}
        if len(ciks) != len(filings) or ciks & DEVELOPMENT_CIKS:
            raise ValueError("Holdout issuers must be distinct and excluded from development.")
        archive_paths = [item["path"] for item in filings.values()]
        if sorted(bundle.namelist()) != sorted(["manifest.json", *archive_paths]):
            raise ValueError("Runner archive contains unexpected files.")
        for source_id, filing in filings.items():
            member = PurePosixPath(filing["path"])
            filename = filing["original_filename"]
            if (source_id != filing["accession"] or filing["form"] != "10-K"
                    or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", source_id)
                    or not re.fullmatch(r"[\w.-]+\.html?", filename, flags=re.ASCII)
                    or member.is_absolute() or ".." in member.parts or member.name != filename):
                raise ValueError("Invalid original filing identity or path.")
            original = bundle.read(filing["path"])
            if len(original) != filing["byte_length"] or sha256(original).hexdigest() != filing["sha256"]:
                raise ValueError(f"Original does not match manifest for {source_id}.")
            directory = run_directory / "originals" / source_id
            directory.mkdir(parents=True)
            (directory / filename).write_bytes(original)
    return manifest, sha256(manifest_bytes).hexdigest()


def command(*args: str) -> dict[str, Any]:
    output, errors = StringIO(), StringIO()
    with redirect_stdout(output), redirect_stderr(errors):
        status = frag_cli(args)
    if status:
        return {"command_error": errors.getvalue().strip(), "exit_code": status}
    result: dict[str, Any] = json.loads(output.getvalue())
    return result


def ingest(store: Path, original: Path, filing: dict[str, Any]) -> dict[str, Any]:
    return command(
        "ingest", str(original), "--store", str(store), "--provenance", "local_original",
        "--company", filing["issuer"], "--accession", filing["accession"], "--form", filing["form"],
        "--filing-date", filing["filing_date"], "--source-url", filing["source_url"],
    )


def open_citations(store: Path, result: dict[str, Any]) -> dict[str, Any]:
    opened: dict[str, Any] = {}
    if not result.get("citations"):
        return opened
    client = create_app(SourceStore(store), ROOT / "web/dist").test_client()
    base = f'/api/sources/{result["source_id"]}'
    for citation in result["citations"]:
        citation_id = citation["id"]
        if "prior_year" in result:
            route = f'{base}/growth/citations/{citation_id}?prior={result["prior_year"]}&current={result["current_year"]}'
        else:
            route = f'{base}/lookup/citations/{result["fiscal_year"]}/{citation_id}'
        response = client.get(route)
        opened[citation_id] = {"path": route, "http_status": response.status_code, "text": response.text}
    return opened


def ask_case(store: Path, case: dict[str, Any], source: dict[str, Any], saved: Path) -> dict[str, Any]:
    if "command_error" in source:
        return {"result": {"status": "ingestion_failed"}, "record": None, "citations": {}}
    start = perf_counter()
    args = ("ask", source["source_id"], case["question"], "--store", str(store))
    result = command(*args, "--record", str(saved))
    record = read_json(saved) if saved.is_file() else None
    error = result if "command_error" in result else None
    if error and "Validation runs require a supported" in error["command_error"]:
        # The public command presents clarification without validation-record mode.
        result = command(*args)
    return {
        "result": result, "record": record, "citations": open_citations(store, result),
        "record_error": error, "elapsed_ms": round((perf_counter() - start) * 1000, 3),
    }


def replay_case(
    store: Path, case: dict[str, Any], source: dict[str, Any], saved: dict[str, Any],
) -> dict[str, Any]:
    expected = saved["result"]
    if "command_error" in source:
        return {"status": "matched" if expected.get("status") == "ingestion_failed" else "mismatch"}
    record = saved["record"]
    if record is None and expected.get("status") == "clarify":
        result = command("ask", source["source_id"], case["question"], "--store", str(store))
    elif record is not None:
        if record["proposed_plan"] is None and record["model_request"] is not None:
            return {"status": "transport_failure_recorded", "original_status": expected["status"]}
        record_path = store.parent / f'{case["case_id"]}.json'
        write_json(record_path, record)
        result = command("replay-ask", str(record_path), "--store", str(store))
    else:
        return {"status": "unreplayable", "original_result": expected}
    citations = open_citations(store, result)
    if result == expected and citations == saved["citations"]:
        return {"status": "matched"}
    return {"status": "mismatch", "result": result, "citations": citations}


def evaluate(
    mode: str, freeze_path: Path, inputs: Path, run_directory: Path, prior_path: Path | None,
) -> dict[str, Any]:
    run_directory.mkdir()
    store = run_directory / "store"
    manifest, manifest_hash = load_bundle(inputs, run_directory)
    header = {
        "cohort": manifest["cohort"], "manifest_sha256": manifest_hash,
        "runner_zip_sha256": digest(inputs), "freeze_sha256": digest(freeze_path),
    }
    prior = read_json(prior_path) if prior_path else None
    if prior is not None and (
        any(prior.get(key) != value for key, value in header.items())
        or [item["case"] for item in prior["cases"]] != manifest["cases"]
    ):
        raise ValueError("Saved case outcomes do not match the frozen inputs.")
    sources: dict[str, Any] = {}
    for filing in manifest["sources"]:
        source_id = filing["source_id"]
        original = run_directory / "originals" / source_id / filing["original_filename"]
        start = perf_counter()
        source = ingest(store, original, filing)
        source.pop("original_path", None)
        if "provenance" in source:
            source["provenance"].pop("input_path", None)
            source["provenance"].pop("preserved_at", None)
        if "command_error" not in source and source["source_hash"] != filing["sha256"]:
            raise ValueError("Public ingestion reported a different original hash.")
        sources[source_id] = {"evidence": source, "ingest_ms": round((perf_counter() - start) * 1000, 3)}
    if prior is not None and (
        {key: value["evidence"] for key, value in sources.items()}
        != {key: value["evidence"] for key, value in prior["sources"].items()}
    ):
        raise ValueError("Reingested evidence differs from the frozen run.")
    cases: list[dict[str, Any]] = []
    for index, case in enumerate(manifest["cases"]):
        if not re.fullmatch(r"[\w.-]+", case["case_id"], re.ASCII):
            raise ValueError("Invalid holdout case identifier.")
        source = sources[case["source_id"]]["evidence"]
        if prior is None:
            outcome = ask_case(store, case, source, run_directory / f'{case["case_id"]}.json')
        else:
            outcome = replay_case(store, case, source, prior["cases"][index])
        cases.append({"case": case, **outcome})
    return {**header, "mode": mode, "sources": sources, "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("freeze", "run", "replay"))
    parser.add_argument("freeze", type=Path)
    parser.add_argument("--model-directory", type=Path)
    parser.add_argument("--planner-port", type=int)
    parser.add_argument("--inputs", type=Path)
    parser.add_argument("--work", type=Path)
    parser.add_argument("--saved-run", type=Path)
    args = parser.parse_args()
    configuration = freeze_inputs()
    if args.mode in {"freeze", "run"}:
        if args.model_directory is None:
            parser.error("Specify the frozen local model directory.")
        if digest(args.model_directory / "model.gguf") != WEIGHTS_SHA256:
            parser.error("Weights do not match the pinned model.")
        configuration["runtime_files"] = runtime_hashes(args.model_directory)
    if args.mode == "freeze":
        if args.planner_port is None or not 1 <= args.planner_port <= 65535:
            parser.error("Specify a valid isolated loopback port at freeze time.")
        write_json(args.freeze, {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "planner_port": args.planner_port, **configuration,
        })
        return
    if args.inputs is None or args.work is None or (args.mode == "replay") != bool(args.saved_run):
        parser.error("Run and replay require inputs and a fresh work directory. Replay requires --saved-run.")
    frozen = read_json(args.freeze)
    if any(frozen.get(key) != value for key, value in configuration.items()):
        parser.error("Code, dependencies or model differ from the frozen configuration.")
    local_model.PORT = frozen["planner_port"]
    restrict_runner(replay=args.mode == "replay")
    report = evaluate(args.mode, args.freeze, args.inputs, args.work, args.saved_run)
    write_json(args.work / "report.json", report)
    counts = Counter(row.get("status") or row["result"].get("status", "command_failed") for row in report["cases"])
    print(json.dumps(counts, sort_keys=True))
    if args.mode == "replay" and counts != {"matched": len(report["cases"])}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


