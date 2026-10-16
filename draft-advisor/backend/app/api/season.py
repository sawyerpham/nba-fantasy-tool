"""In-season: the fantasy week (matchups, standings, per-game projections and scores) from Sleeper + ESPN."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..services.app_state import AppState
from ..services.season import http_fetch, team_plan, week_view
from .deps import get_state
from .draft import _session

router = APIRouter(prefix="/leagues/{league_id}/season", tags=["season"])


@router.get("/week")
def week(league_id: str, week: int | None = Query(None, ge=1), state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    if state.platform is None or not hasattr(state.platform, "session"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    try:
        return week_view(session, http_fetch(state.platform), week)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/plan")
def plan(league_id: str, week: int | None = Query(None, ge=1), roster_id: int | None = Query(None),
         state: AppState = Depends(get_state)) -> dict:
    """Lock / pass / where to seat every player of one team this week (default: yours)."""
    session = _session(state, league_id)
    if state.platform is None or not hasattr(state.platform, "session"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    try:
        return team_plan(session, week_view(session, http_fetch(state.platform), week), roster_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
