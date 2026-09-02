# Draft Advisor backend

Python 3.13 + FastAPI. Shared models/providers live in `../../shared` (installed editable).

```powershell
cd draft-advisor\backend
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Pre-draft data pull (nba_api + Sleeper) into .\data
$env:PYTHONIOENCODING = "utf-8"
.\venv\Scripts\python.exe -m app.pull            # first run: ~1.5 min (one batch call + per-player fallbacks)
.\venv\Scripts\python.exe -m app.pull --skip-logs   # re-reconcile / re-seed only
.\venv\Scripts\python.exe -m app.pull --force-sleeper  # bypass the 24 h Sleeper cache guard
.\venv\Scripts\python.exe -m app.pull --fixtures       # offline, from tests\fixtures

.\venv\Scripts\python.exe -m pytest -q tests
```

Data layout (`data\`, gitignored) is documented in `..\..\DESIGN.md` section 1.8.
