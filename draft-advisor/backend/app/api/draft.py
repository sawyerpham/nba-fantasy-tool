"""Live draft: state, nomination, picks, undo, rankings, bid recommendation."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..engine.draft_state import DraftError, KeeperAssignment
from ..services.app_state import AppState
from ..services.league_repository import LeagueNotFound
from .deps import get_state
from .schemas import NominateIn, NominationOrderIn, PickIn, ReassignIn, StartDraft

router = APIRouter(prefix="/leagues/{league_id}", tags=["draft"])


def _session(state: AppState, league_id: str):
    try:
        return state.get_session(league_id)
    except LeagueNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown league {league_id}") from exc


def _draft_view(session) -> dict:
    engine = session.engine
    return {
        "status": session.draft.status,
        "nomination_order": session.draft.nomination_order,
        "nomination_pointer": session.draft.nomination_pointer,
        "next_nominator": engine.next_nominator(),
        "current_nomination": session.draft.current_nomination.model_dump(mode="json") if session.draft.current_nomination else None,
        "picks": [p.model_dump(mode="json") for p in session.draft.picks],
        "progress": round(engine.progress(), 4),
        "available_count": len(session.available_ids()),
        "managers": [asdict(m) for m in session.manager_summaries()],
    }


@router.get("/draft")
def get_draft(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _draft_view(_session(state, league_id))


def _mutate(state: AppState, league_id: str, action) -> dict:
    session = _session(state, league_id)
    try:
        action(session)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    state.save_session(league_id)
    return _draft_view(session)


@router.post("/draft/start")
def start_draft(league_id: str, body: StartDraft, state: AppState = Depends(get_state)) -> dict:
    keepers = [KeeperAssignment(k.manager_id, k.player_id, k.cost) for k in body.keepers]
    return _mutate(state, league_id, lambda s: s.start(keepers))


@router.post("/draft/nominate")
def nominate(league_id: str, body: NominateIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.nominate(body.player_id, body.manager_id, body.force))


@router.post("/draft/pick")
def pick(league_id: str, body: PickIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.pick(body.player_id, body.manager_id, body.price, body.slot))


@router.post("/draft/undo")
def undo(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.undo())


@router.post("/draft/reassign")
def reassign(league_id: str, body: ReassignIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.reassign_slot(body.pick_number, body.slot))


@router.post("/draft/complete")
def complete(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.complete())


@router.post("/draft/reset")
def reset(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.reset())


@router.put("/draft/nomination-order")
def set_nomination_order(league_id: str, body: NominationOrderIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.set_nomination_order(body.order))


@router.get("/rankings")
def rankings(
    league_id: str,
    manager_id: str | None = Query(None, description="defaults to the user's manager"),
    limit: int | None = Query(None, ge=1),
    include_unrosterable: bool = Query(False),
    state: AppState = Depends(get_state),
) -> list[dict]:
    session = _session(state, league_id)
    try:
        if include_unrosterable:
            from ..engine.ranking import rank_players

            manager = manager_id or session.user_manager_id()
            rows = rank_players(session.league, session.players, session.overrides, session.valuations,
                                session.engine.picks_for(manager), session.available_ids())
            rows = rows[:limit] if limit else rows
        else:
            rows = session.rankings(manager_id, limit)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return [asdict(r) for r in rows]


@router.get("/recommend/{player_id}")
def recommend(league_id: str, player_id: int, manager_id: str | None = Query(None), state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    try:
        rec = session.recommend(player_id, manager_id)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except StopIteration as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown player {player_id}") from exc
    return asdict(rec)
