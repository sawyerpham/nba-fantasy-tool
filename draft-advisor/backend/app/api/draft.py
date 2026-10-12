"""Live draft: state, nomination, picks, undo, rankings, bid recommendation, spending guide."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse

from ..engine.draft_state import DraftError, KeeperAssignment
from ..services.app_state import AppState
from ..services.league_repository import LeagueNotFound
from .deps import get_state
from .schemas import EditPickIn, NextNominatorIn, NominateIn, NominationOrderIn, PickIn, ReassignIn, StartDraft

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


@router.get("/sleeper/keepers")
def sleeper_keepers(league_id: str, state: AppState = Depends(get_state)) -> list[dict]:
    """This season's keepers as set in Sleeper, priced with the league's escalation rule (needs a data pull)."""
    from ..services.sleeper_league import current_keepers

    s = _session(state, league_id)
    return current_keepers(s.sleeper_details, s.managers, s.players, s.league.keeper.escalation)


@router.post("/draft/sync")
def sync_from_sleeper(league_id: str, state: AppState = Depends(get_state)) -> dict:
    """Record every pick made in the Sleeper draft that is not recorded here yet. Safe to call repeatedly."""
    from ..services.sleeper_league import draft_id, sync_picks

    session = _session(state, league_id)
    did = draft_id(session.sleeper_details, session.league.sleeper_draft_id)
    if state.platform is None or not hasattr(state.platform, "get_json"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    if not did:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no Sleeper draft: link the league (Settings) and pull data, or set a draft id")
    result = sync_picks(state.platform, session, did)
    if result["added"]:
        state.save_session(league_id)
    return {**result, "view": _draft_view(session)}


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


@router.patch("/draft/picks/{pick_number}")
def edit_pick(league_id: str, pick_number: int, body: EditPickIn, state: AppState = Depends(get_state)) -> dict:
    """Fix who drafted whom: move a pick to another manager and/or change its price or slot."""
    return _mutate(state, league_id, lambda s: s.edit_pick(pick_number, body.manager_id, body.price, body.slot))


@router.delete("/draft/picks/{pick_number}")
def remove_pick(league_id: str, pick_number: int, state: AppState = Depends(get_state)) -> dict:
    """Remove any recorded pick (not only the last one); the player becomes available again."""
    return _mutate(state, league_id, lambda s: s.remove_pick(pick_number))


@router.post("/draft/complete")
def complete(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.complete())


@router.post("/draft/reset")
def reset(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.reset())


@router.put("/draft/nomination-order")
def set_nomination_order(league_id: str, body: NominationOrderIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.set_nomination_order(body.order))


@router.put("/draft/next-nominator")
def set_next_nominator(league_id: str, body: NextNominatorIn, state: AppState = Depends(get_state)) -> dict:
    return _mutate(state, league_id, lambda s: s.engine.set_next_nominator(body.manager_id))


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
            manager = manager_id or session.user_manager_id()
            rows = session.rank(session.engine.picks_for(manager), session.available_ids())
            rows = rows[:limit] if limit else rows
        else:
            rows = session.rankings(manager_id, limit)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    from collections import Counter

    from ..engine.ranking import tiers

    tier = tiers(session.pool_values())
    left = Counter(tier.get(pid) for pid in session.available_ids())
    size = Counter(tier.values())
    prices = _prices(session, rows, manager_id) if session.draft.status == "live" else {}
    # Why FP/G moved vs last season: data/fpg_reasons.json, written by hand / an LLM pass (optional).
    reasons = state.store.read_json("fpg_reasons.json").get("players", {}) if state.store.exists("fpg_reasons.json") else {}
    from ..engine.fit import fit_scores

    fits = fit_scores(session, manager_id or session.user_manager_id(), rows, prices)
    return [{**asdict(r), "tier": tier.get(r.player_id), "tier_left": left[tier.get(r.player_id)], "tier_size": size[tier.get(r.player_id)],
             "price": prices.get(r.player_id), "fpg_reason": reasons.get(str(r.player_id)), "fit": fits.get(r.player_id)}
            for r in rows]


def _prices(session, rows, manager_id: str | None) -> dict[int, int]:
    """'Pay up to' for each listed player (the record bar's number), sharing one market rate across rows."""
    from ..engine.bidding import market_rate, recommend_bid

    manager = manager_id or session.user_manager_id()
    available = session.rank(session.engine.picks_for(manager), session.available_ids())
    pool = session.pool_values()
    rate = market_rate(session.league, session.managers, session.draft.picks, (p.value for p in available), pool)
    progress = session.engine.progress()
    out = {}
    for r in rows:
        rec = recommend_bid(session.league, session.managers, session.draft.picks, manager, r, available, pool, progress, rate=rate)
        out[r.player_id] = rec.recommended_max if rec.can_bid else round(rec.fair_value)
    return out


@router.get("/spending")
def spending(
    league_id: str,
    manager_id: str | None = Query(None),
    player_id: int | None = Query(None, description="player to give a go/pass call on (the one on the block or selected)"),
    state: AppState = Depends(get_state),
) -> dict:
    session = _session(state, league_id)
    try:
        guide = session.spending_guide(manager_id, player_id)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return asdict(guide)


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


@router.get("/fit/{player_id}")
def fit(league_id: str, player_id: int, manager_id: str | None = Query(None), state: AppState = Depends(get_state)) -> dict:
    """Is this available player good for the manager's team? Verdict, one-line headline, reasons."""
    from ..engine.fit import team_fit

    session = _session(state, league_id)
    try:
        return asdict(team_fit(session, manager_id or session.user_manager_id(), player_id))
    except (DraftError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/context", response_class=PlainTextResponse)
def context(league_id: str, manager_id: str | None = Query(None), player_id: int | None = Query(None),
            top: int = Query(60, ge=10, le=300), state: AppState = Depends(get_state)) -> str:
    """Everything about the draft as Markdown, to paste into a chat with Claude."""
    from ..engine.context import draft_context

    session = _session(state, league_id)
    try:
        return draft_context(session, manager_id or session.user_manager_id(), player_id, top)
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/room")
def room(league_id: str, manager_id: str | None = Query(None), state: AppState = Depends(get_state)) -> list[dict]:
    """Every manager's money, roster and habits, plus the players to nominate to make each rival spend."""
    from ..engine.room import room_board

    session = _session(state, league_id)
    try:
        return room_board(session, manager_id or session.user_manager_id())
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
