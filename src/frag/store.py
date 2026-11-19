"""Preserve local input bytes separately from immutable source records."""

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal


class SourceError(ValueError):
    """The requested source cannot be preserved or inspected safely."""


class StoreMissing(SourceError):
    """No source catalogue exists yet."""


class SourceNotFound(SourceError):
    """The catalogue does not contain the requested source."""


class SourceConflict(SourceError):
    """Preserved bytes already have different claims."""


@dataclass(frozen=True)
class SourceMetadata:
    """Caller-supplied identity claims, never inferred from the filename or HTML."""

    company: str | None = None
    accession: str | None = None
    form: str | None = None
    filing_date: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if value is not None and not value.strip():
                raise SourceError("Metadata must be nonempty or omitted (unknown).")
        if self.filing_date is not None:
            try:
                parsed = date.fromisoformat(self.filing_date)
            except ValueError as exc:
                raise SourceError("Filing date must be YYYY-MM-DD.") from exc
            if parsed.isoformat() != self.filing_date:
                raise SourceError("Filing date must be YYYY-MM-DD.")


class SourceStore:
    """A local byte archive and SQLite catalogue; reading never creates a store."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def ingest(
        self,
        path: Path,
        *,
        provenance: Literal["local_original", "synthetic"],
        metadata: SourceMetadata | None = None,
    ) -> dict[str, Any]:
        return self.ingest_bytes(
            path.read_bytes(), provenance=provenance, metadata=metadata,
            input_path=str(path.resolve()),
        )

    def ingest_bytes(
        self,
        original: bytes,
        *,
        provenance: Literal["local_original", "synthetic"],
        metadata: SourceMetadata | None = None,
        input_path: str | None = None,
        upload_name: str | None = None,
    ) -> dict[str, Any]:
        """Preserve bytes from either a local path or a browser upload."""
        if provenance not in ("local_original", "synthetic"):
            raise SourceError("Explicit local_original or synthetic provenance is required.")
        metadata = metadata or SourceMetadata()
        if not original:
            raise SourceError("Input is empty; supply original HTML or a labeled synthetic fixture.")
        digest = hashlib.sha256(original).hexdigest()
        source_id = "sha256:" + digest
        raw_path = self.root / "originals" / (digest + ".html")
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "schema_version": "source-v1",
            "source_id": source_id,
            "source_hash": digest,
            "hash_algorithm": "sha256",
            **asdict(metadata),
            "metadata_status": "supplied_unverified",
            "provenance": {
                "kind": provenance,
                "input_path": input_path,
                **({"upload_name": upload_name} if upload_name is not None else {}),
                "preserved_at": datetime.now(timezone.utc).isoformat(),
            },
            "original_path": str(raw_path),
            "byte_count": len(original),
            "parser_version": None,
            "status": "source_preserved",
            "facts": [],
            "real_source_acceptance": False,
            "unresolved_requirements": [
                "source_identity_verification", "extraction", "evidence_verification",
            ],
        }
        with closing(sqlite3.connect(self.root / "sources.sqlite3")) as connection, connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sources "
                "(source_id TEXT PRIMARY KEY, record TEXT NOT NULL)"
            )
            # Serialize writers so a retry cannot overwrite the first provenance record.
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT record FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
            if existing is not None:
                saved: dict[str, Any] = json.loads(existing[0])
                if saved["provenance"]["kind"] != provenance or any(
                    saved[key] != value for key, value in asdict(metadata).items()
                ):
                    raise SourceConflict(
                        "Identical bytes already have different metadata or provenance; "
                        "existing evidence is unchanged. Replay with the original metadata."
                    )
                self._check_original(saved)
                return saved
            try:
                with raw_path.open("xb") as handle:
                    handle.write(original)
            except FileExistsError:
                if raw_path.read_bytes() != original:
                    raise SourceError("Preserved original bytes have changed; refusing overwrite.")
            connection.execute(
                "INSERT INTO sources (source_id, record) VALUES (?, ?)",
                (source_id, json.dumps(record, sort_keys=True)),
            )
        return record

    def inspect(self, source_id: str | None = None) -> dict[str, Any]:
        database = self.root / "sources.sqlite3"
        if not database.is_file():
            raise StoreMissing("Store does not exist; ingest a local HTML file first.")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            if source_id is None:
                rows = connection.execute("SELECT record FROM sources ORDER BY source_id")
                records = [json.loads(row[0]) for row in rows]
                for record in records:
                    self._check_original(record)
                return {"source_count": len(records), "sources": records}
            row = connection.execute(
                "SELECT record FROM sources WHERE source_id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise SourceNotFound(f"Source not found: {source_id}")
        result: dict[str, Any] = json.loads(row[0])
        self._check_original(result)
        return result

    def _check_original(self, record: dict[str, Any]) -> None:
        original_path = self.root / "originals" / (record["source_hash"] + ".html")
        if hashlib.sha256(original_path.read_bytes()).hexdigest() != record["source_hash"]:
            raise SourceError("Preserved original hash mismatch; evidence integrity failed.")
        # Resolve the path for this store, including after an offline copy or move.
        record["original_path"] = str(original_path)
