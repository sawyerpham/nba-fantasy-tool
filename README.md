# NBA Fantasy Tool

A local helper for Sleeper NBA fantasy leagues.

- **Draft**: rankings, bid guide and live Sleeper sync for auction drafts
- **Season**: best lineup, lock calls, week timeline, news and waivers for Lock-In leagues

## Features

### Draft

- **Live Sleeper draft sync**
- **Live bid calls on the nominee**
- **Rival drafting habits from past leagues**
- Auction value rankings
- Worth and max bid per player
- Budget plan for open roster spots
- Position scarcity and tier cliffs
- Rival manager money and needs
- Fantasy team strength estimates
- NBA team win totals and fantasy talent
- Keeper keep-or-cut verdicts

### Season

- **Optimal lineup at any time of the week**
- **Live keep-or-swap calls**
- **Swap and lock alarms**
- **Next Sleeper check-in**
- **Live NBA game cards**
- **Injury watch**
- Lineup swap instructions
- Lock-or-wait calls
- Win probability by strategy
- Lockable games
- Opponent lineups
- Box scores and top performers
- Game stream links
- Player game logs and news
- NBA team offense and defense ranks
- NBA depth charts
- League standings and FAAB
- Waiver targets with FAAB bids

## Run

Needs Python 3.13 and Node 20+.

### macOS / Linux

```sh
cd backend
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
./venv/bin/python -m app.pull
./venv/bin/python -m app.serve --port 8000
```

### Windows PowerShell

```powershell
cd backend
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m app.pull
.\venv\Scripts\python.exe -m app.serve --port 8000
```

In another terminal, start the frontend:

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:5173, create a league, add your Sleeper league id in Settings and pick which manager you are.

To retune the live finish estimate against this season's finished games (`PRIOR_MINUTES` / `MINUTES_LEFT_SCALE` in
`backend/app/lockin/weekplan.py`), run `python -m app.lockin.backtest_live [league_id]` from `backend`. It prints the
error at each game-clock checkpoint and caches box scores under `backend/data/cache/backtest_live/`.
## Telegram notifications
1. In Telegram, message @BotFather, send `/newbot`, copy the token. Message your new bot once, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.
2. Create `backend/.env` (gitignored) with your two values:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC-your-token
   TELEGRAM_CHAT_ID=123456789
   ```
3. Check delivery: `python -m app.notify "hello"` (from `backend`). Then restart `python -m app.serve`; it sends each GTD / OUT / swap / lock call once, at its alarm time, while the backend is running.
