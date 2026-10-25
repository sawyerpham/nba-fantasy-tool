# NBA Fantasy Tool

A local helper for Sleeper NBA fantasy leagues.

- **Draft**: rankings, bid guide and live Sleeper sync for auction drafts
- **Season**: best lineup, lock calls, week timeline, news and waivers for Lock-In leagues

## Features

### Draft

- Rankings
- Player profiles
- Bid guide
- Spending guide
- Position market
- Live Sleeper sync
- Live lot
- My team
- Room board
- Managers view
- NBA teams view
- Nomination order
- Pick recording and editing
- Keepers

### Season

- Matchup view
- Best lineup
- Swap arrows
- Lock calls
- Week timeline
- Next check-in
- Swap windows
- Alarms
- Win probability
- Game cards
- Top performers
- Stream links
- Player profiles
- Team ranks
- Depth charts
- News
- League standings
- Waivers

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
