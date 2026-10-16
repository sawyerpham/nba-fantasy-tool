"""In-season: the fantasy week (matchups, standings, per-game projections and scores) from Sleeper + ESPN, the week
plan (lock / pass / today's lineup), your lock answers, any player's season page and waiver claims."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..services.app_state import AppState
from ..services.season import http_fetch, read_locks, season_player, team_plan, waivers, week_view, write_lock
from .deps import get_state
from .draft import _session

router = APIRouter(prefix="/leagues/{league_id}/season", tags=["season"])


def _fetch(state: AppState):
    if state.platform is None or not hasattr(state.platform, "session"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    return http_fetch(state.platform)


@router.get("/week")
def week(league_id: str, week: int | None = Query(None, ge=1), state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    try:
        return week_view(session, _fetch(state), week)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/plan")
def plan(league_id: str, week: int | None = Query(None, ge=1), roster_id: int | None = Query(None),
         today: date | None = Query(None, description="preview another day's lineup (testing)"),
         state: AppState = Depends(get_state)) -> dict:
    """Lock / pass / where to seat every player of one team this week (default: yours), today's lineup and the opponent."""
    session = _session(state, league_id)
    try:
        view = week_view(session, _fetch(state), week, today)
        manual = read_locks(state.store, league_id, view["week"]) if not roster_id else {}
        return team_plan(session, view, roster_id, manual)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


class LockIn(BaseModel):
    week: int
    sleeper_id: str
    game_date: str | None   # the locked game's date; "" = not locked; null = forget (use detection)


@router.post("/locks")
def set_lock(league_id: str, body: LockIn, state: AppState = Depends(get_state)) -> dict:
    _session(state, league_id)
    write_lock(state.store, league_id, body.week, body.sleeper_id, body.game_date)
    return {"locks": read_locks(state.store, league_id, body.week)}


@router.get("/player/{player_id}")
def player(league_id: str, player_id: int, week: int | None = Query(None, ge=1), state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    try:
        return season_player(session, _fetch(state), player_id, week)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/waivers")
def waiver_claims(league_id: str, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    try:
        return waivers(session, week_view(session, _fetch(state)))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
