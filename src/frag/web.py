"""Same-origin localhost API and built browser assets for the source inspector."""

import os
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Literal, cast

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from frag.citations import citation_text
from frag.growth import calculate_growth
from frag.local_model import propose_lookup
from frag.lookup import Planner, ask_revenue, lookup_citation
from frag.sec import download_edgar_filing, download_microsoft_filing, search_edgar_filings
from frag.store import (
    SourceConflict,
    SourceError,
    SourceMetadata,
    SourceNotFound,
    SourceStore,
    StoreMissing,
)


def create_app(store: SourceStore, assets: Path, *, planner: Planner = propose_lookup) -> Flask:
    app = Flask(__name__, static_folder=str(assets.resolve()), static_url_path="")
    app.config.update(TRUSTED_HOSTS=["localhost", "127.0.0.1"], MAX_CONTENT_LENGTH=32 * 1024 * 1024)

    @app.get("/")
    def index() -> Response:
        return app.send_static_file("index.html")

    @app.get("/api/sources")
    def list_sources() -> Response:
        try:
            return jsonify(store.inspect())
        except StoreMissing:
            return jsonify(source_count=0, sources=[])

    @app.get("/api/sources/<source_id>")
    def inspect_source(source_id: str) -> Response:
        return jsonify(store.inspect(source_id))

    def fiscal_years() -> tuple[int, int]:
        prior = request.args.get("prior", type=int)
        current = request.args.get("current", type=int)
        if prior is None or current is None:
            raise SourceError("Enter a prior and current fiscal year.")
        return prior, current

    @app.get("/api/sources/<source_id>/growth")
    def growth(source_id: str) -> Response:
        years = fiscal_years()
        return jsonify(calculate_growth(store.inspect(source_id), *years))

    @app.get("/api/sources/<source_id>/growth/citations/<citation_id>")
    def growth_citation(source_id: str, citation_id: str) -> Response:
        years = fiscal_years()
        source, original = store.inspect_with_original(source_id)
        result = calculate_growth(source, *years)
        for citation in result["citations"]:
            if citation["id"] == citation_id:
                return Response(
                    citation_text(original, result["source_hash"], citation),
                    mimetype="text/plain",
                    headers={"X-Content-Type-Options": "nosniff"},
                )
        raise SourceNotFound("Citation is unavailable for this calculation.")

    @app.post("/api/sources/<source_id>/lookup")
    def lookup(source_id: str) -> Response | tuple[Response, int]:
        if request.headers.get("X-Frag-Ask") != "1":
            return jsonify(error="Chat requires the local FRAG workspace."), 403
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or not isinstance(data.get("question"), str):
            raise SourceError("Enter a question about the selected filing.")
        response = jsonify(ask_revenue(store.inspect(source_id), data["question"], planner))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/sources/<source_id>/lookup/citations/<int:year>/<citation_id>")
    def lookup_excerpt(source_id: str, year: int, citation_id: str) -> Response:
        source, original = store.inspect_with_original(source_id)
        citation = lookup_citation(source, year, citation_id)
        if citation is None:
            raise SourceNotFound("Citation is unavailable for this revenue lookup.")
        return Response(
            citation_text(original, source["source_hash"], citation),
            mimetype="text/plain",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    def filing_query(data: object) -> tuple[str, str, str]:
        if isinstance(data, dict):
            company, year, form = (data.get(field) for field in ("company", "year", "form"))
            if isinstance(company, str) and isinstance(year, str) and isinstance(form, str):
                return company, year, form
        raise SourceError("Enter a company ticker or SEC CIK, a filing year, and a form.")

    @app.post("/api/filings/search")
    def search_filings() -> Response | tuple[Response, int]:
        if request.headers.get("X-Frag-Download") != "1":
            return jsonify(error="Filing search requires the local FRAG workspace."), 403
        company, year, form = filing_query(request.get_json(silent=True))
        matches = search_edgar_filings(company, year, form, os.environ.get("SEC_USER_AGENT"))
        return jsonify(filings=[asdict(match) for match in matches])

    @app.post("/api/sources/download")
    def download_source() -> Response | tuple[Response, int]:
        if request.headers.get("X-Frag-Download") != "1":
            return jsonify(error="Download requires the local FRAG workspace."), 403
        user_agent = os.environ.get("SEC_USER_AGENT")
        if request.is_json:
            data = request.get_json(silent=True)
            company, year, form = filing_query(data)
            if not isinstance(data, dict) or not isinstance(data.get("accession"), str):
                raise SourceError("Choose a filing from the search results.")
            matches = search_edgar_filings(company, year, form, user_agent)
            for match in matches:
                if match.accession == data["accession"]:
                    return jsonify(download_edgar_filing(store, match, user_agent))
            raise SourceNotFound("This filing was not found. Search again to refresh the results.")
        return jsonify(download_microsoft_filing(store, user_agent))

    @app.post("/api/sources")
    def ingest_source() -> Response | tuple[Response, int]:
        # A cross-origin HTML form cannot supply this header. The API enables no CORS.
        if request.headers.get("X-Frag-Upload") != "1":
            return jsonify(error="Upload requires the local FRAG workspace."), 403
        upload = request.files.get("file")
        if not upload or not upload.filename:
            raise SourceError("Choose an HTML file to upload.")
        provenance = request.form.get("provenance")
        if provenance != "local_original" and provenance != "synthetic":
            raise SourceError("Choose local original or synthetic provenance.")
        metadata = SourceMetadata(
            company=request.form.get("company") or None,
            accession=request.form.get("accession") or None,
            form=request.form.get("form") or None,
            filing_date=request.form.get("filing_date") or None,
            source_url=request.form.get("source_url") or None,
        )
        return jsonify(store.ingest_bytes(
            upload.read(), provenance=cast(Literal["local_original", "synthetic"], provenance),
            metadata=metadata, upload_name=upload.filename,
        ))

    @app.errorhandler(SourceError)
    def source_error(error: SourceError) -> tuple[Response, int]:
        if isinstance(error, (StoreMissing, SourceNotFound)):
            return jsonify(error=str(error)), 404
        if isinstance(error, SourceConflict):
            return jsonify(error=str(error)), 409
        return jsonify(error=str(error)), 400

    @app.errorhandler(RequestEntityTooLarge)
    def upload_too_large(error: RequestEntityTooLarge) -> tuple[Response, int]:
        return jsonify(error="The upload request exceeds the 32 MiB limit."), 413

    @app.errorhandler(OSError)
    @app.errorhandler(sqlite3.Error)
    def storage_error(error: Exception) -> tuple[Response, int]:
        app.logger.error("Source store operation failed: %s", error)
        return jsonify(error="Could not access the local source store. Check the server output."), 500

    return app
