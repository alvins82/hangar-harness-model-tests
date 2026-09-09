# Harness / Model Tests

This repository compares model and harness combinations on the same task. There are
two tasks.

## 1. Hangar (build)

The original coding task: build a single-page Three.js sci-fi hangar with hovering drones, animated warning lights, emissive runway strips, subtle volumetric-style fog planes, a drone formation toggle, and a cinematic camera path.

Results here - https://alvins82.github.io/hangar-harness-model-tests/

## 2. Restaurant Pick (research)

A second task over the same matrix, in `restaurant-pick/`. Plan dinner for two in
Sydney on a fixed date against a fixed taste profile, verify each recommendation
against the venue's real booking system rather than its opening hours, and output one
self-contained HTML file.

A fabricated recommendation renders exactly like a checked one, so every run is
scored out of 100 against a fixed rubric and cross-checked against its own
transcript. Results, with speed and cost separated from quality of recommendation, are in
[`restaurant-pick/results.html`](restaurant-pick/results.html); the method is in
[`restaurant-pick/README.md`](restaurant-pick/README.md).

## Repository layout

- `index.html` — sortable benchmark summary and cost table for the hangar task.
- `hangar-*/` — one generated HTML output and transcript for each hangar session.
- `artifacts/astra-hangar.png` — Astra session screenshot artifact.
- `restaurant-pick/` — the second task: prompt, rubric, results table, and a
  transcript-to-row metrics extractor that reproduces the hangar table's token,
  reasoning and cost columns.
- `rpick-*/` — one recommendation output and transcript for each restaurant-pick
  session.

Transcripts are retained as JSONL where the source format is JSONL. OpenCode transcripts are sanitized JSON exports.

## Viewing locally

Open `index.html` or `restaurant-pick/index.html` in a browser, or serve the
repository with any static file server.
