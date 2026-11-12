"""FastAPI application factory.

    uvicorn app.main:app --port 8000          (real providers, data in ./data)
    python -m app.serve                         (same, with sensible defaults)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from nba_fantasy_shared.providers.base import CallRunner, RetryPolicy
from nba_fantasy_shared.providers.nba_api_provider import NbaApiProvider
from nba_fantasy_shared.providers.sleeper_provider import SleeperProvider
from nba_fantasy_shared.storage import JsonStore

from . import config, notify
from .core.api import data, leagues, players
from .core.engine.draft_state import DraftError
from .core.services.app_state import AppState, PullAlreadyRunning
from .core.services.league_repository import LeagueNotFound
from .draft import api as draft
from .lockin import api as season

log = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"]
# The built frontend (frontend/dist from `npm run build`; the Docker image): served at / by this process when it exists.
STATIC_DIR = Path(os.environ.get("STATIC_DIR", config.BACKEND_ROOT.parent / "frontend" / "dist"))


def build_default_state(data_dir=None) -> AppState:
    """Build the application state with the real providers (nba_api and Sleeper) and a JSON store in `data_dir` (default: the configured data directory)."""
    store = JsonStore(data_dir or config.DEFAULT_DATA_DIR)
    policy = RetryPolicy()
    stats = NbaApiProvider(CallRunner(policy))
    platform = SleeperProvider(store, CallRunner(policy))
    return AppState(store, stats, platform)


def create_app(state: AppState | None = None) -> FastAPI:
    """Build the FastAPI app: CORS for the dev servers, the data / players / leagues / draft / season routers under /api, a health check, error handlers (draft errors 400, unknown league 404, pull already running 409), and the built frontend at / when STATIC_DIR exists."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Create the real application state on startup when none was injected (tests inject one)."""
        if getattr(app.state, "app_state", None) is None:
            app.state.app_state = build_default_state()
            log.info("AppState initialised from %s", app.state.app_state.store.root)
            notify.start_watcher(app.state.app_state)
        yield

    app = FastAPI(title="NBA Fantasy Tool API", version=API_VERSION, lifespan=lifespan)
    app.state.app_state = state
    app.add_middleware(CORSMiddleware, allow_origins=DEFAULT_ORIGINS, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    app.include_router(data.router, prefix="/api")
    app.include_router(players.router, prefix="/api")
    app.include_router(leagues.router, prefix="/api")
    app.include_router(draft.router, prefix="/api")
    app.include_router(season.router, prefix="/api")
    app.include_router(notify.router, prefix="/api")

    @app.get("/api/health")
    def health() -> dict:
        """Health check: API version and the number of players loaded."""
        st = app.state.app_state
        return {"ok": True, "version": API_VERSION, "players": len(st.players) if st else 0}

    @app.exception_handler(DraftError)
    async def draft_error(_: Request, exc: DraftError) -> JSONResponse:
        """Turn a DraftError into a 400 response."""
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(LeagueNotFound)
    async def league_not_found(_: Request, exc: LeagueNotFound) -> JSONResponse:
        """Turn an unknown league into a 404 response."""
        return JSONResponse(status_code=404, content={"detail": f"unknown league {exc}"})

    @app.exception_handler(PullAlreadyRunning)
    async def pull_running(_: Request, exc: PullAlreadyRunning) -> JSONResponse:
        """Turn a second concurrent pull into a 409 response."""
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    if STATIC_DIR.is_dir():   # after the API routes: anything not under /api is the app (index.html at /)
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="frontend")
    return app


app = create_app()
