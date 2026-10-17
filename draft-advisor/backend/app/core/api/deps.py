from __future__ import annotations

from fastapi import HTTPException, Request, status

from ..services.app_state import AppState
from ..services.league_repository import LeagueNotFound


def get_state(request: Request) -> AppState:
    state = getattr(request.app.state, "app_state", None)
    if state is None:
        raise RuntimeError("AppState not initialised")
    return state


def _session(state: AppState, league_id: str):
    try:
        return state.get_session(league_id)
    except LeagueNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown league {league_id}") from exc
