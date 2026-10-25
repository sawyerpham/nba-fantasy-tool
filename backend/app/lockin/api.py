"""In-season: the fantasy week (matchups, standings, per-game projections and scores) from Sleeper + ESPN, the week
plan (lock / pass / today's lineup), your lock answers, any player's season page and waiver claims."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from ..core.services.app_state import AppState
from .service import (_cache, game_detail, http_fetch, injury_report, read_locks, season_news, season_player, sleeper_injuries,
                      team_news, team_plan, team_player_stats, team_ranks, team_schedule, team_stat_rows, trending, waivers,
                      week_view, write_lock, SLEEPER, DAY_TTL)
from ..core.api.deps import _session, get_state

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
        manual = read_locks(state.store, league_id, view["week"])   # your answers, any team's player (rivals too)
        return team_plan(session, view, roster_id, manual)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/game")
def game(league_id: str, event: str = Query(..., pattern=r"^\d+$"), state: AppState = Depends(get_state)) -> dict:
    """One NBA game (ESPN event id) for the game card: score, box scores in league FP, depth charts."""
    return game_detail(_session(state, league_id), _fetch(state), event)


@router.get("/team")
def team(league_id: str, abbr: str = Query(..., pattern=r"^[A-Z]{2,4}$"), state: AppState = Depends(get_state)) -> dict:
    """One NBA team for the Team card: name, logo, fantasy-talent rank, offense / defense ranks and depth chart."""
    from ..core.api.players import team_header

    session = _session(state, league_id)
    head = team_header(state, session, abbr)
    if head["talent_rank"] is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown team {abbr}")
    fetch, year = _fetch(state), session.league.roster_season.split("-")[0]
    rows, done = team_stat_rows(fetch, year)
    by_sid = {r.sleeper_id: pid for pid, r in session.players.items() if r.sleeper_id}
    hurt = [{**h, "player_id": by_sid.get(sid)} for sid, h in sleeper_injuries(fetch).items() if h["team"] == abbr]
    return {**head, "ranks": team_ranks(rows, abbr, done), "names": _team_names(state),
            "schedule": team_schedule(fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or [], abbr),
            "stats": team_player_stats(session, rows, done, abbr),
            "injuries": sorted(hurt, key=lambda h: (h["group"] != "out", h["name"]))}


def _team_names(state: AppState) -> dict[str, str]:
    """Abbreviation -> full name, every NBA team (the schedule's opponents)."""
    return {t.abbreviation: t.full_name for t in state.stats.list_teams()} if hasattr(state.stats, "list_teams") else {}


@router.get("/team/news")
def team_news_feed(league_id: str, abbr: str = Query(..., pattern=r"^[A-Z]{2,4}$"), state: AppState = Depends(get_state)) -> dict:
    """The Team card's News tab: notes on every player of one NBA team, newest first."""
    return {"news": team_news(_session(state, league_id), _fetch(state), abbr)}


@router.get("/injuries")
def injuries(league_id: str, state: AppState = Depends(get_state)) -> dict:
    """The News tab's teams report: every NBA team with injured players, most first, with names."""
    _session(state, league_id)
    return {"teams": injury_report(sleeper_injuries(_fetch(state))), "names": _team_names(state)}


@router.post("/sync")
def sync(league_id: str, state: AppState = Depends(get_state)) -> dict:
    """Forget every cached Sleeper / ESPN response: the next load pulls the lineup, scores and news fresh. Also takes
    the Sleeper league's name if it was renamed there."""
    _session(state, league_id)
    _cache.clear()
    return {"ok": True, "renamed": state.sync_league_name(league_id)}


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


@router.get("/news")
def news(league_id: str, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    fetch = _fetch(state)
    try:
        free = trending(fetch)
        return season_news(week_view(session, fetch, extra=tuple(free)), fetch, free)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/waivers")
def waiver_claims(league_id: str, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    try:
        fetch = _fetch(state)
        return waivers(session, fetch, week_view(session, fetch))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
