# Hangar Harness / Model Tests

This repository compares model and harness combinations on the same coding task: build a single-page Three.js sci-fi hangar with hovering drones, animated warning lights, emissive runway strips, subtle volumetric-style fog planes, a drone formation toggle, and a cinematic camera path.

## Results

Open the [benchmark index](index.html) to view the sortable results table, generated hangar pages, token counts, and OpenRouter-equivalent cost breakdowns.

| Model | Harness | Total cost (USD) |
| --- | --- | ---: |
| GLM 5.3 Flash Max | Codex | $0.015278 |
| Luna 5.6 Max | Codex | $0.317003 |
| SOL 5.6 Max | Codex | $0.300243 |
| Astra 6.0 Max | Codex | $4.038190 |
| GLM 5.3 Flash Max | OMP | $0.062639 |
| Qwen 3.8 27B x-high | OMP | $0.654798 |
| GLM 5.3 Flash Max | OpenCode | $0.085234 |
| Qwen 3.8 27B x-high | OpenCode | $0.191736 |
| Qwen 3.8 27B x-high | DSH / PTC | $0.383944 |
| Qwen 3.8 27B x-high | DSH | $0.500544 |

The cost figures use current [OpenRouter model pricing](https://openrouter.ai/api/v1/models), splitting uncached input, cache-read input, and generated output. Generated output includes reasoning tokens when the harness reports reasoning separately; cache-write usage was zero for every session. The Codex session labelled “Luna 5.6 Max” records `gpt-5.6-sol` in its transcript and is priced at the Sol rate.

## Repository layout

- `index.html` — sortable benchmark summary and cost table.
- `hangar-*/` — one generated HTML output and transcript for each session.
- `artifacts/astra-hangar.png` — Astra session screenshot artifact.

Transcripts are retained as JSONL where the source format is JSONL. OpenCode transcripts are sanitized JSON exports.

## Viewing locally

Open `index.html` in a browser, or serve the repository with any static file server.
