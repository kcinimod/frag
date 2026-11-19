"""Same-origin localhost API and built browser assets for the source inspector."""

import sqlite3
from pathlib import Path
from typing import Literal, cast

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

from frag.store import (
    SourceConflict,
    SourceError,
    SourceMetadata,
    SourceNotFound,
    SourceStore,
    StoreMissing,
)


def create_app(store: SourceStore, assets: Path) -> Flask:
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
