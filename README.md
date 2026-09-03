# nba-fantasy-tool

Two independent apps for a Sleeper NBA fantasy league, sharing one Python package:

- `draft-advisor/` — Phase 1: pre-draft rankings and live auction assistant (backend: Python + FastAPI, frontend: React).
- `fantasy-tracker/` — Phase 2: in-season tracker (not started).
- `shared/nba_fantasy_shared` — models, data providers (`nba_api`, Sleeper public API), player reconciliation, JSON storage, scoring.

Data sources are free and need no keys: the `nba_api` package (NBA.com stats) for per-game logs and bios, and Sleeper's public API for fantasy position eligibility and injury status. All persistence is flat JSON under `draft-advisor/backend/data/` (gitignored).

## Prerequisites

- Python 3.13 (the backend venv lives at `draft-advisor/backend/venv`)
- Node 20+ (frontend, Phase 1E — not yet wired up)
- Windows users: set `PYTHONIOENCODING=utf-8` before running Python, or accented player names crash console output.

## Backend setup

```powershell
cd draft-advisor\backend
python -m venv venv                       # once, if the venv does not exist
.\venv\Scripts\python.exe -m pip install -r requirements.txt   # installs ..\..\shared editable too
$env:PYTHONIOENCODING = "utf-8"
```

## Pull player data (pre-draft)

```powershell
.\venv\Scripts\python.exe -m app.pull                 # nba_api pool + game logs, Sleeper players; ~1.5 min first time
.\venv\Scripts\python.exe -m app.pull --skip-logs     # re-reconcile and re-seed overrides only (seconds)
.\venv\Scripts\python.exe -m app.pull --force-sleeper # bypass the 24 h Sleeper cache guard
.\venv\Scripts\python.exe -m app.pull --fixtures      # offline run from tests\fixtures
```

The pull writes to `data\`: `cache\nba_player_pool_<season>.json`, `cache\game_logs_<season>.json`, `cache\sleeper_players.json`, `cache\reconcile_<season>.json`, and the user-editable `player_overrides.json` (seeded from Sleeper; fields marked `manual` are never overwritten). The command prints a reconciliation summary: every player that could not be matched between NBA.com and Sleeper is listed, never dropped.

## Valuations (scoring formula over the cached game logs)

```powershell
.\venv\Scripts\python.exe -m app.valuate                  # top 25 by blended value (SPEC scoring defaults)
.\venv\Scripts\python.exe -m app.valuate --sort ceiling --top 40
.\venv\Scripts\python.exe -m app.valuate --player 203999  # one player's per-game points and bonus counts
```

Valuations are cached per scoring hash in `data\cache\valuations_<season>_<hash>.json`; editing any scoring value recomputes from the cached logs without a network call.

## API server

```powershell
.\venv\Scripts\python.exe -m app.serve --port 8000        # or: uvicorn app.main:app --port 8000
```

Interactive docs at `http://127.0.0.1:8000/docs`. Main routes (all under `/api`):

| Route | Purpose |
|---|---|
| `POST /data/pull`, `GET /data/pull/status`, `GET /data/status` | start the background pull, poll progress, cache ages and reconcile report |
| `GET /players?q=`, `GET /players/{id}`, `PATCH /players/{id}/overrides`, `POST /players/{id}/overrides/reset` | autocomplete, sidebar detail, manual eligibility / injury edits |
| `POST /leagues`, `GET/PUT /leagues/{id}/settings`, `.../managers`, `.../keepers/history` | league setup, editable any time |
| `POST /leagues/{id}/sleeper/preview` and `/apply` | pull a real Sleeper league's settings and diff/apply them |
| `GET /leagues/{id}/draft`, `POST .../draft/start|nominate|pick|undo|reassign|complete|reset` | live auction draft |
| `GET /leagues/{id}/rankings`, `GET /leagues/{id}/recommend/{player_id}` | ranked available players and bid recommendation |
| `POST /leagues/{id}/export` | versioned `schema_version: 1` export (also the on-disk league file) |

## Tests

```powershell
cd draft-advisor\backend
.\venv\Scripts\python.exe -m pytest -q tests
```

Tests are offline; `tests\fixtures` holds real API responses captured on 2026-09-02.

## Status

| Phase | Scope | Status |
|---|---|---|
| 1A | shared package, both providers, reconciler, override seeding, budget reservation, pull CLI | done |
| 1B | per-game scoring formula, avg / ceiling valuation, confidence factor, provisional Sleeper scoring-key map | done |
| 1C | draft engine: rosters, nomination rotation, picks, keepers, stacking, ranking, bid recommendation | done |
| 1D | FastAPI routes, background pull with progress, export | done |
| 1E | React frontend | next |
| 1F | Definition-of-Done walkthrough | |

Design details, decisions, and verified API facts: `DESIGN.md`. Enhancement ideas awaiting approval: `PROPOSALS.md`.
