"""Exercise the public upload API and CLI against the same local store."""

import hashlib
import io
import json
from pathlib import Path

import pytest

from frag.cli import main
from frag.store import SourceStore
from frag.web import create_app


def test_cli_and_browser_api_share_preserved_sources(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "store"
    client = create_app(SourceStore(root), tmp_path).test_client()
    assert client.get("/api/sources").json == {"source_count": 0, "sources": []}
    assert not root.exists()

    fixture = Path(__file__).parent / "fixtures" / "synthetic.html"
    assert main(["ingest", str(fixture), "--store", str(root), "--provenance", "synthetic"]) == 0
    local = json.loads(capsys.readouterr().out)
    assert client.get(f"/api/sources/{local['source_id']}").json == local

    original = b"<html>Synthetic browser fixture\r\n\xff</html>"

    def upload(company: str) -> tuple[int, dict[str, object]]:
        response = client.post(
            "/api/sources", headers={"X-Frag-Upload": "1"},
            data={"file": (io.BytesIO(original), "synthetic.html"),
                  "provenance": "synthetic", "company": company},
        )
        result: dict[str, object] = response.get_json()
        return response.status_code, result

    status, saved = upload("Synthetic browser source")
    assert status == 200
    assert saved["source_hash"] == hashlib.sha256(original).hexdigest()
    assert saved["source_url"] is None
    assert saved["provenance"]["upload_name"] == "synthetic.html"  # type: ignore[index]
    assert saved["real_source_acceptance"] is False
    assert upload("Synthetic browser source") == (200, saved)
    assert upload("Conflicting company")[0] == 409
    assert client.get("/api/sources").get_json()["source_count"] == 2
    assert main(["inspect", str(saved["source_id"]), "--store", str(root)]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record == saved
    assert Path(record["original_path"]).read_bytes() == original


def test_upload_requires_local_form_and_explicit_provenance(tmp_path: Path) -> None:
    root = tmp_path / "store"
    client = create_app(SourceStore(root), tmp_path).test_client()
    assert client.post("/api/sources").status_code == 403
    response = client.post(
        "/api/sources", headers={"X-Frag-Upload": "1"},
        data={"file": (io.BytesIO(b"<p>Synthetic</p>"), "synthetic.html")},
    )
    assert response.status_code == 400
    assert "provenance" in response.get_json()["error"]
    assert not root.exists()
