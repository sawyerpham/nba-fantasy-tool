# NBA Fantasy Tool

A local helper for Sleeper NBA fantasy leagues.

- **Draft**: rankings, bid guide and live Sleeper sync for auction drafts
- **Season**: best lineup, lock calls, week timeline, news and waivers for Lock-In leagues

## Features

### Draft

- Auction value rankings
- Worth and max bid per player
- Live bid calls on the nominee
- Live Sleeper draft sync
- Budget plan for open roster spots
- Position scarcity and tier cliffs
- Rival manager money and needs
- Rival drafting habits from past leagues
- Fantasy team strength estimates
- NBA team win totals and fantasy talent
- Keeper keep-or-cut verdicts
- Nomination rotation
- Manual pick entry and fixes

### Season

- Optimal lineup at any time of the week
- Lineup swap instructions
- Lock-or-wait calls
- Live keep-or-swap calls
- Swap and lock alarms
- Next Sleeper check-in
- Win probability by strategy
- Lockable games
- Injury watch
- Opponent lineups
- Live NBA game cards
- Box scores and top performers
- Game stream links
- Player game logs and news
- NBA team offense and defense ranks
- NBA depth charts
- League standings and FAAB
- Waiver targets with FAAB bids

## Layout

```
backend/app/    core/ (leagues, players, data pull, Sleeper)   draft/ (auction)   lockin/ (season)
frontend/src/   core/                                          draft/             lockin/
shared/         models, data providers, scoring
```

## Run

Needs Python 3.13 and Node 20+.

```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m app.pull
.\venv\Scripts\python.exe -m app.serve --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create a league, add your Sleeper league id in Settings and pick which manager you are.

## Test

```powershell
cd backend
.\venv\Scripts\python.exe -m pytest -q
```
