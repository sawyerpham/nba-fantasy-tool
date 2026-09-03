# nba-fantasy-tool

Two independent apps for a Sleeper NBA fantasy league, sharing one Python package:

- `draft-advisor/` — Phase 1: pre-draft rankings and live auction assistant (backend: Python + FastAPI, frontend: React).
- `fantasy-tracker/` — Phase 2: in-season tracker (not started).
- `shared/nba_fantasy_shared` — models, data providers (`nba_api`, Sleeper public API), player reconciliation, JSON storage, scoring.

Data sources are free and need no keys: the `nba_api` package (NBA.com stats) for per-game logs and bios, and Sleeper's public API for fantasy position eligibility and injury status. All persistence is flat JSON under `draft-advisor/backend/data/` (gitignored).

## Prerequisites

- Python 3.13 (the backend venv lives at `draft-advisor/backend/venv`)
- Node 20+ and npm (frontend; Playwright uses the installed Edge or Chrome for the mock draft, no browser download)
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

## Frontend (React + Vite)

```powershell
cd draft-advisor\frontend
npm install
npm run dev            # http://localhost:5173, proxies /api to the backend on port 8000
npm run build          # production build into dist\
```

Run the backend first (`python -m app.serve` in `draft-advisor\backend`). Tabs: **Data** (pull with per-source progress, cache ages, reconcile report), **League** (create/select leagues, managers, keeper history), **Settings** (every league, roster, keeper, scoring, and ranking value; Sleeper preview/apply), **Draft** (rankings, autocomplete search, nominate / record winning bid, player sidebar with eligibility and injury editing plus a bid guide with a go/pass call on the selected player, spending guide (your money vs the room, price inflation vs the opening rate, a plan for your open slots, targets you can afford), managers panel with budgets, open slots, stacks and every pick as a chip: drag a chip onto another manager to change who drafted the player, click it to change the manager, price or slot or to remove the pick; undo, complete, export).

### Running a draft (walkthrough)

1. **Data tab** → *Pull now*. First run takes about 1.5 minutes (one league-wide game-log call plus per-player fallbacks; Sleeper is fetched at most once per 24 h). Check the reconcile report for players that need manual eligibility.
2. **League tab** → create a league (12 managers, SPEC defaults). Name the managers, mark yourself, set each rival's spend pace (early / even / late) and budget. Enter prior-season keeper history if you have it.
3. **Settings tab** → confirm roster slots (PG SG SF PF C UTIL×2 BN×8 IR×2), budget, min bid, keeper limit, scoring values, and ranking knobs. With a Sleeper league id, *Preview* and *Apply* the live settings. Everything here stays editable during the draft.
4. **Draft tab** → *Start draft…*. The keeper dialog already has one row per manager: find the player and type **last year's price**; this year's price follows the league rule (+$1 per full $5, editable in Settings) and a GOOD / EVEN / BAD badge compares it to the player's fair value. Rows left empty are ignored. The nomination order is the row of chips under the toolbar: drag (or use the arrows) to reorder at any time, click a name to make that manager nominate next. Then, lot by lot: click *Nominate* on a player, open the sidebar for the bid recommendation, and *Record winning bid* with the winner and price (rec / max / +1 / +5 buttons, Enter to submit). Press `/` to jump to the search box and mark any player drafted. Position chips and sortable columns filter the rankings; budgets, open slots, and stacks update after every pick; *Undo* reverts the last one.
5. When the room finishes, *Complete draft* and *Export JSON*. The file under `data\exports\` is the `schema_version: 1` document the Fantasy Tracker will import.

### End-to-end mock draft (Playwright)

With the backend and `npm run dev` running:

```powershell
npm run e2e            # drives a full 12-manager auction through the UI; screenshots in e2e\screenshots
```

Uses the installed Edge (`DA_BROWSER=chrome` to switch); set `DA_SKIP_PULL=1` to reuse cached data instead of pulling through the UI first.

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
| 1E | React frontend (Vite), Playwright mock draft | done |
| 1F | Definition-of-Done walkthrough | done (see DESIGN.md) |

Design details, decisions, and verified API facts: `DESIGN.md`. Enhancement ideas awaiting approval: `PROPOSALS.md`.
