"""Exercise the built workspace and CLI using Chrome and a temporary store."""

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[2]
CLI = "from frag.cli import main; raise SystemExit(main())"


def main() -> None:
    with TemporaryDirectory() as temp:
        base = Path(temp)
        upload = base / "browser-synthetic.html"
        upload.write_bytes(b"<html><p>Synthetic browser replay input.</p></html>")
        store = str(base / "store")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        origin = f"http://127.0.0.1:{port}"
        server = subprocess.Popen(
            [sys.executable, "-c", CLI, "serve", "--store", store, "--port", str(port)],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            deadline = monotonic() + 15
            while True:
                try:
                    with urlopen(origin, timeout=1):
                        break
                except URLError:
                    if monotonic() >= deadline or server.poll() is not None:
                        raise
                    sleep(0.1)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    channel=os.environ.get("FRAG_BROWSER", "chrome"),
                    args=["--disable-background-networking"],
                )
                try:
                    context = browser.new_context(service_workers="block")
                    context.route("**/*", lambda route: route.continue_()
                                  if route.request.url.startswith(origin + "/") else route.abort())
                    page = context.new_page()
                    page.goto(origin)
                    expect(page.get_by_text("No sources saved yet.")).to_be_visible()
                    page.get_by_label("HTML file").set_input_files(upload)
                    page.get_by_label("Synthetic fixture").check()
                    save = page.get_by_role("button", name="Preserve source")
                    save.click()
                    digest = hashlib.sha256(upload.read_bytes()).hexdigest()
                    expect(page.get_by_text(f"sha256:{digest}", exact=True)).to_be_visible()
                    expect(page.get_by_text(digest, exact=True)).to_be_visible()
                    expect(page.get_by_text("Synthetic input · Source preserved")).to_be_visible()
                    expect(page.get_by_text("Unknown", exact=True)).to_have_count(5)
                    save.click()
                    expect(page.get_by_text("Source saved and open for inspection.")).to_be_visible()
                    expect(page.get_by_role("heading", name="Saved sources (1)")).to_be_visible()
                    page.get_by_text("Optional filing metadata", exact=True).click()
                    page.get_by_label("Company", exact=True).fill("Conflicting company")
                    save.click()
                    expect(page.get_by_role("alert")).to_contain_text("different metadata or provenance")

                    def cli(*args: str) -> dict:
                        return json.loads(subprocess.check_output(
                            [sys.executable, "-c", CLI, *args, "--store", store], cwd=ROOT,
                        ))

                    saved = cli("inspect", f"sha256:{digest}")
                    assert Path(saved["original_path"]).read_bytes() == upload.read_bytes()
                    assert saved["company"] is None and saved["real_source_acceptance"] is False
                    cli("ingest", "tests/fixtures/synthetic.html", "--provenance", "synthetic",
                        "--company", "CLI synthetic fixture")
                    page.get_by_role("button", name="Refresh").click()
                    page.get_by_role("button", name="CLI synthetic fixture").click()
                    expect(page.get_by_role("heading", name="CLI synthetic fixture")).to_be_visible()
                    expect(page.get_by_text("Expected exactly one table headed Income Statements.")).to_be_visible()
                    page.get_by_label("Company", exact=True).fill("Synthetic revenue fixture")
                    page.get_by_label("HTML file").set_input_files(ROOT / "tests/fixtures/synthetic_income.html")
                    save.click()
                    expect(page.get_by_text("FY2023 · USD 963,000,000 · Provisional")).to_be_visible()
                    page.get_by_text("FY2022 · USD 817,000,000 · Provisional").click()
                    expect(page.get_by_text("2021-07-01 through 2022-06-30")).to_be_visible()
                    expanded = page.locator("details[open]").filter(has_text="FY2022")
                    expect(expanded.get_by_text("Revenue cell", exact=True)).to_be_visible()
                finally:
                    browser.close()
            print("Browser replay passed: upload, hash, unknowns, retry, conflict, CLI interoperability, provisional facts and evidence. External page requests blocked.")
        finally:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
