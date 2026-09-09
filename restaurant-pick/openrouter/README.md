# OpenRouter runner

A fifth harness for this suite: a minimal tool-calling loop against OpenRouter, so
the five models in the matrix can be run without installing Codex, OpenCode, OMP or
DSH.

The loop is deliberately thin. It adds no planning, no retries and no prompting
beyond `PROMPT.md`, because the point is to measure the model rather than the
scaffolding. That also makes it a useful control: the difference between a model's
OpenRouter row and its Codex row is the harness.

## Setup

```bash
export OPENROUTER_API_KEY=sk-or-v1-...
node tools_server.js 8791 &          # holds one Chromium context for the run
./runner.py --model glm --out ../../rpick-openrouter-glm53-flash
```

`--model` is one of `glm`, `qwen`, `luna`, `sol`, `astra`, mapping to the same
OpenRouter ids the hangar table prices. The target date defaults to the next Saturday
at least 14 days out, per the rule in `PROMPT.md`; `--target-date "Saturday 17
October 2026"` overrides it. `--dry-run` prints the assembled prompt and sends
nothing.

**This spends real money.** Astra is $10/M input and $50/M output; the equivalent
hangar run cost $4.04. Run `glm` first — it is roughly 100× cheaper — and check the
transcript before spending on the expensive models.

Node needs to resolve `playwright`. If it is installed elsewhere,
`NODE_PATH=/path/to/node_modules node tools_server.js 8791`.

## The tools

Every model gets exactly these four, so runs stay comparable.

| Tool | What it does |
| --- | --- |
| `fetch_url` | HTTP from a real browser context. Cookies persist for the whole run |
| `maps_lookup` | Google Maps place panel: rating, address, the hours rows it exposes |
| `search_timeout` | Search timeout.com for articles and venue pages |
| `write_file` | Writes the deliverable. Only `recommendation.html` is accepted |

Two things worth knowing, both of which apply identically to every model:

- **SevenRooms responses are reduced.** The raw response for one venue-day is about
  1.35 MB — 156 slots × 55 fields, mostly photo URLs and marketing copy. That is
  ~340k input tokens per call, or $3.40 on Astra, and truncating it mid-JSON makes it
  unparseable. The tool server keeps the structure `PROMPT.md` documents —
  `data.availability[date][].times[].type === "book"` — plus the credit-card,
  cancellation and duration fields, and drops the per-slot noise. 1.35 MB becomes
  about 7.5 KB. The model still does the documented work of reading the shifts.
- **Cookie seeding is automatic.** SevenRooms only answers a request carrying cookies
  from one of its own pages, so the server pre-loads one before the first
  SevenRooms call.

## Search is narrower here than in the other harnesses

Codex, OpenCode, OMP and DSH bring their own web search. This runner cannot: every
general search engine is blocked from an automated browser — DuckDuckGo and Brave
return bot challenges, Mojeek 403s, Bing and Startpage render nothing usable. Rather
than add a paid search key, the runner offers `search_timeout` plus `maps_lookup`
plus arbitrary `fetch_url`.

**So an OpenRouter row is not perfectly comparable to a Codex row on discovery.** It
is comparable on the part the rubric weights most — whether a booking system was
actually queried and whether the result was reported honestly — and it is exactly
comparable between OpenRouter rows. Note it when reading the table.

## Review counts

`maps_lookup` returns `review_count: null` with a note saying so, because the place
panel does not expose it. The rubric asks for a review count per venue, and the
baseline run lost points on it three times. If no harness can produce one, that check
should be dropped from the rubric rather than failed by everybody — decide it before
spending on Astra.

## Files

- `runner.py` — the loop. Writes `transcript.jsonl` and `recommendation.html`
- `tools_server.js` — the browser-backed tool backend
- `test_runner.py` — runs the loop against a stub OpenRouter, so it needs no key

`transcript.jsonl` is read by `../extract_metrics.py` (`--format openrouter`, or by
auto-detection). OpenRouter reports `prompt_tokens` inclusive of cached tokens and
`completion_tokens` inclusive of reasoning, which is how the hangar table defines its
Input and Output columns.
