"""FastAPI application factory.

    uvicorn app.main:app --port 8000          (real providers, data in ./data)
    python -m app.serve                         (same, with sensible defaults)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nba_fantasy_shared.providers.base import CallRunner, RetryPolicy
from nba_fantasy_shared.providers.nba_api_provider import NbaApiProvider
from nba_fantasy_shared.providers.sleeper_provider import SleeperProvider
from nba_fantasy_shared.storage import JsonStore

from . import config
from .core.api import data, leagues, players
from .draft import api as draft
from .lockin import api as season
from .core.engine.draft_state import DraftError
from .core.services.app_state import AppState, PullAlreadyRunning
from .core.services.league_repository import LeagueNotFound

log = logging.getLogger(__name__)

API_VERSION = "0.1.0"
DEFAULT_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000", "http://127.0.0.1:3000"]


def build_default_state(data_dir=None) -> AppState:
    store = JsonStore(data_dir or config.DEFAULT_DATA_DIR)
    policy = RetryPolicy()
    stats = NbaApiProvider(CallRunner(policy))
    platform = SleeperProvider(store, CallRunner(policy))
    return AppState(store, stats, platform)


def create_app(state: AppState | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "app_state", None) is None:
            app.state.app_state = build_default_state()
            log.info("AppState initialised from %s", app.state.app_state.store.root)
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

    @app.get("/api/health")
    def health() -> dict:
        st = app.state.app_state
        return {"ok": True, "version": API_VERSION, "players": len(st.players) if st else 0}

    @app.exception_handler(DraftError)
    async def draft_error(_: Request, exc: DraftError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(LeagueNotFound)
    async def league_not_found(_: Request, exc: LeagueNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"unknown league {exc}"})

    @app.exception_handler(PullAlreadyRunning)
    async def pull_running(_: Request, exc: PullAlreadyRunning) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    return app


app = create_app()
