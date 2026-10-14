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
.\venv\Scripts\python.exe -m app.pull                 # nba_api pool + game logs, Sleeper players, projections with Sleeper rostered %, and linked leagues; ~1.5 min first time
.\venv\Scripts\python.exe -m app.pull --skip-logs     # re-reconcile and re-seed overrides only (seconds)
.\venv\Scripts\python.exe -m app.pull --force-sleeper # bypass the 24 h Sleeper cache guard
.\venv\Scripts\python.exe -m app.pull --fixtures      # offline run from tests\fixtures
```

The pull writes to `data\`: `cache\nba_player_pool_<season>.json`, `cache\game_logs_<season>.json`, `cache\sleeper_players.json`, `cache\sleeper_projections_<season>.json` (Sleeper's season projections; FP/G blends them with last season, see *projection weight* in Settings), `cache\nba_schedule_<season>.json` (games per team per NBA week; under Lock-In a team with more games in a week, especially in the fantasy playoff weeks from the linked Sleeper league, gets a higher weekly-best ceiling, see *schedule weight*), `cache\reconcile_<season>.json`, `cache\sleeper_details_<sleeper league id>.json` (for every saved league with a linked Sleeper league, see below), and `player_overrides.json` (positions and injury straight from Sleeper, re-seeded on every pull; only your notes are kept). Before the regular season (Sleeper state `pre`/`off`), DTD/GTD tags (preseason rest days, minor knocks) seed as healthy with the Sleeper tag kept as a note; Out/IR still count, and a `Rest` tag never counts as an injury. The command prints a reconciliation summary: every player that could not be matched between NBA.com and Sleeper is listed, never dropped.

### Linked Sleeper league

Set **Settings → Sleeper league → linked league** to your Sleeper league id (the number in `sleeper.com/leagues/<id>/...`), save, then pull data. Every pull (CLI or *Pull now*) then also fetches that league's users, rosters, this season's keepers, and each past season's auction picks (following `previous_league_id`, up to 3 seasons) into `cache\sleeper_details_<id>.json`. This is public read-only data: no login, and nobody in the league is notified. It powers:

- **League tab → Sync from Sleeper** (one click, ~10 s): downloads the linked league (and any history league not cached yet), refreshes projections, and, while the draft is in setup, replaces the managers with this season's Sleeper rosters (you stay marked as you; a replaced manager shows up as a new person with no history) and applies Sleeper's scoring, roster slots and keeper limit. It lists what changed. Once the draft has started it only downloads.
- **League activity** (League tab, `data\sleeper_changelog_<id>.json`): who did what, when. Sleeper transactions (adds, drops, waivers with FAAB, trades) carry Sleeper's exact time; things Sleeper keeps no time for (members joining or leaving, keepers set or removed, roster/scoring/keeper-limit changes, the draft being scheduled) are found by comparing each sync or pull with the previous one and marked *noticed*, with the window they happened in on hover.
- **Start draft dialog**: keepers already set in Sleeper are filled in and priced from last year's auction with the escalation rule.
- **Manager cards**: how each manager spent in last year's auction (*star chaser* / *typical* / *spreads money*, relative to the league, with their top buys), their favourite NBA teams (5+ players drafted from one team) and whether they lean to young players or veterans.
- **`data\manager_profiles.json`**: rebuilt on every pull from all cached Sleeper leagues. One entry per Sleeper username: leagues, each completed auction (style, top buys, max price, $1 picks), favourite NBA teams and team counts, young/veteran lean, early-pick positions, *reach* (average Sleeper ADP minus pick number over their first 6 snake picks; positive = takes players earlier than usual), players they drafted more than once, and every player they drafted with how. Only the `notes` field is yours to edit; it survives regeneration.
- **History leagues** (Settings → *history leagues*, comma-separated ids): other Sleeper leagues with the same people, any format (e.g. an old dynasty league with a snake draft). They are pulled the same way but used only for draft habits; the record bar then warns "Watch out: X (drafted him 2024 Dynasty!: round 1 · ATL fan)" when a nominated player has history with a rival.
- **Draft tab → Sleeper sync** (off by default): every 3 s the backend reads the Sleeper draft's picks and records any not recorded here yet, matched by Sleeper user/roster and player id. Manual entries win; picks it cannot match are listed for hand entry. The status shows how long after Sleeper registered the latest pick it landed here. To test before draft day, start a Sleeper mock draft and paste its id (from `sleeper.com/draft/nba/<id>`) into **sync draft id**; leave it empty for the real draft.

## Valuations (scoring formula over the cached game logs)

In the app, value also counts **position scarcity** (*position scarcity weight* in Settings): every team's starting slots are filled greedily by value, and a player is measured against the best player left at the scarcest position he can fill instead of one league-wide replacement level. Hover a player's Value to see every factor (games confidence, injury, age, availability, schedule, scarcity).

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
| `GET /players?q=`, `GET /players/{id}`, `PATCH /players/{id}/overrides` | autocomplete, sidebar detail, your notes on a player |
| `POST /leagues`, `GET/PUT /leagues/{id}/settings`, `.../managers`, `.../keepers/history` | league setup, editable any time |
| `POST /leagues/{id}/sleeper/preview` and `/apply` | pull a real Sleeper league's settings and diff/apply them |
| `POST /leagues/{id}/sleeper/managers`, `GET /leagues/{id}/sleeper/keepers`, `POST /leagues/{id}/draft/sync` | managers and keepers from the linked Sleeper league; record new picks from the Sleeper draft |
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

Run the backend first (`python -m app.serve` in `draft-advisor\backend`). Tabs: **Data** (pull with per-source progress, cache ages, reconcile report), **League** (create/select leagues, managers, keeper history), **Settings** (every league, roster, keeper, scoring, and ranking value; Sleeper preview/apply), **Draft** (rankings, autocomplete search, nominate / record winning bid, player sidebar with Sleeper positions and injury, your notes, and a bid guide with a go/pass call on the selected player, spending guide (your money vs the room, price inflation vs the opening rate, a plan for your open slots, targets you can afford), managers panel with budgets, open slots, stacks and every pick as a chip: drag a chip onto another manager to change who drafted the player, click it to change the manager, price or slot or to remove the pick; undo, complete, export).

### Running a draft (walkthrough)

1. **Data tab** → *Pull now*. First run takes about 1.5 minutes (one league-wide game-log call plus per-player fallbacks; Sleeper is fetched at most once per 24 h). The reconcile report lists players Sleeper could not be matched to; they have no positions until Sleeper lists them.
2. **League tab** → create a league (12 managers, SPEC defaults). Name the managers, mark yourself, set each rival's spend pace (early / even / late) and budget. Enter prior-season keeper history if you have it.
3. **Settings tab** → confirm roster slots (PG SG SF PF C UTIL×2 BN×8 IR×2), budget, min bid, keeper limit, scoring values, and ranking knobs. With a Sleeper league id, *Preview* and *Apply* the live settings. Everything here stays editable during the draft.
4. **Draft tab** → *Start draft…*. The keeper dialog already has one row per manager: find the player and type **last year's price**; this year's price follows the league rule (+$1 per full $5, editable in Settings) and a GOOD / EVEN / BAD badge compares it to the player's fair value. Rows left empty are ignored. The nomination order lives behind the *Order* button in the top line (open before the draft, folded once it is live; the line always shows who nominates now and the next two): drag (or use the arrows) to reorder at any time, click a name to make that manager nominate next. Then, lot by lot: double-click a player's row (or use *On the block* in his profile) (or turn on *Sleeper sync* and let picks arrive by themselves). The record bar pinned under the top nav shows the player with the price prefilled at the recommendation; adjust it with the on-screen numpad (the first digit replaces the prefill, the big ✕ erases the whole price), the keyboard, or arrow keys (±1, Shift ±5), then click the winning manager: one click records the pick, slot assigned automatically. `/` to search opens the same bar for a player who was never nominated here. Player photos come from Sleeper's image server (`sleepercdn.com/content/nba/players/thumb/<sleeper id>.jpg`), loaded as rows scroll into view; the first column shows each player's tier and overall rank side by side (T4 12). Tier tags (T1, T2 …) group players of similar value and warn when a tier is down to its last two; the spending guide suggests whom to nominate (DRAIN: players rivals will overpay for that you won't buy; SNEAK: players you want that few rivals can afford right now). The *Fit* column (0-100) scores each player for your team: his value against the best player left, ×0.6 if he would only reach your bench, and once the draft is live ×0.85 past your stretch price, ×0.4 past your walk-away, 0 if you can't afford him (hover for the breakdown). The # / T column is always the overall best-to-worst order; click the Fit header to sort by fit instead. Selecting a player shows a *Fit for your team* card that explains the same number as the Fit column, part by part (quality, role, price), followed by *worth knowing* notes that do not change the score (injury, missed weeks, age, Lock-In schedule with playoff-week games, tier running out, the alternatives at his slot). *Copy for Claude* (top line) puts the whole draft on the clipboard as Markdown (`GET /leagues/{id}/context`, ~10k characters): rules and scoring, every pick so far, each manager's money, needs, roster and habits, your money vs the room and affordable targets, the top 60 available players with tier, FP/G, weekly best, availability, value and your price, and the selected (or on-the-block) player with the tool's fit read and which rivals drafted him before. The draft page has two screens. The first fills the window: spending guide | on-the-block bar over the rankings | the selected player's profile (packed to fit without scrolling). Scroll down (or *Room ↓* in the top line) for *the room*: one card per manager (six per row, each half a screen tall) with money, max bid, open spots, every roster spot (photo, NBA team, positions, age, projected FP/G, price), needs and last year's habits (`GET /leagues/{id}/room`). Click a player for his profile; hover and click ✎ to edit a pick, or drag it onto another card to move it. Positions are colour-coded everywhere (PG blue, SG teal, SF amber, PF orange, C purple). Position chips and sortable columns filter the rankings; budgets, open slots, and stacks update after every pick; *Undo* reverts the last one.
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
