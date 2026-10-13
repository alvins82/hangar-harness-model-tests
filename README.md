# Hangar Harness / Model Tests

This repository compares model and harness combinations on the same coding task: build a single-page Three.js sci-fi hangar with hovering drones, animated warning lights, emissive runway strips, subtle volumetric-style fog planes, a drone formation toggle, and a cinematic camera path.

Results here - https://alvins82.github.io/hangar-harness-model-tests/

## Repository layout

- `index.html` — sortable benchmark summary and cost table.
- `hangar-*/` — generated HTML outputs and any available transcripts or artifacts for each session.
- `hangar-gemini3.8flashhigh/preview.png` — final Antigravity screenshot for the Gemini run.
- `hangar-gemini3.8flashhigh/run-metadata.json` — source timestamps, token totals, tool checks, and cost calculation for the Gemini run.
- `artifacts/astra-hangar.png` — Astra session screenshot artifact.

Transcripts are retained as JSONL where the source format is JSONL. OpenCode transcripts are sanitized JSON exports.
The Antigravity transcript is a sanitized export with internal thinking text omitted, per-response reasoning counts added from local metadata, and local paths normalized.

## Viewing locally

Open `index.html` in a browser, or serve the repository with any static file server.
