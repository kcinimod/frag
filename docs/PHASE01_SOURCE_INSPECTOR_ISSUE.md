# Upload and inspect a local source in the browser

Part of #1. Follows closed issue #2 and gives issue #3 a source view to extend.

Add a local browser workflow for uploading HTML and inspecting the preserved
source. Build the TypeScript frontend and start the app with uv on Windows.
Use the same source store and ingestion rules as the CLI. The stack uses
React with Vite and a small Flask API. Serve the built frontend and API
locally so review works without internet access.

- [x] Select a local HTML file, explicitly declare local-original or synthetic
  provenance, and optionally supply company, accession, form, filing date, and
  source URL. After success, open the saved source record.
- [x] Browse saved sources and inspect the source ID, matching SHA-256 hash,
  provenance, supplied metadata, and explicit unknowns. Visibly label synthetic
  input and keep real-source acceptance incomplete. Treat uploaded HTML as data.
- [x] Submit the same bytes and metadata twice and see one source with the same
  ID. Submit conflicting metadata or provenance and see a useful error with the
  saved record intact.
- [x] Inspect a CLI-ingested source in the browser and a browser-uploaded source
  through the CLI. Replay the browser workflow with external page requests blocked.
- [x] Record the verified Windows PowerShell setup, build, launch, and browser
  replay commands in the README.
