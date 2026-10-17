"""Live draft: state, nomination, picks, undo, rankings, bid recommendation, spending guide."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
    return {**result, "view": _draft_view(session) if result["added"] else None}   # the view only changes with a pick


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
    # The call (buy / star / pricey / cannot), your max and the market price: the same numbers as the spending guide.
    # Before the draft: Worth at the first nomination (after keepers); Max and the call need the live room.
    live = session.draft.status == "live"
    calls = session.spending_guide(manager_id, call_ids=[r.player_id for r in rows]).calls if live else {}
    # Why FP/G moved vs last season: data/fpg_reasons.json, written by hand / an LLM pass (optional).
    reasons = state.store.read_json("fpg_reasons.json").get("players", {}) if state.store.exists("fpg_reasons.json") else {}
    from ..engine.fit import fit_scores

    fits = fit_scores(session, manager_id or session.user_manager_id(), rows, calls)
    pos_rank, pos_ranks = _sleeper_pos_ranks(session)
    r_values = session.r_values()
    return [{**asdict(r), "r_value": r_values.get(r.player_id), "tier": tier.get(r.player_id), "tier_left": left[tier.get(r.player_id)], "tier_size": size[tier.get(r.player_id)],
             **(_call_fields(calls.get(r.player_id)) if live else {"worth": session.start_worth(r.value), "max": None, "call": None}),
             "fpg_reason": reasons.get(str(r.player_id)), "fit": fits.get(r.player_id),
             "pos_rank": pos_rank.get(r.player_id), "pos_ranks": pos_ranks.get(r.player_id, {})}
            for r in rows]


def _sleeper_pos_ranks(session) -> tuple[dict[int, str], dict[int, dict[str, str]]]:
    """Positional ranks by Sleeper's standard ADP, over the whole pool (drafted players keep their pre-draft rank):
    - main: within each player's main Sleeper position, as Sleeper shows it ("#2 SG");
    - every position he is eligible at ({"PG": "#3 PG", "SG": "#2 SG"}), for the position filter."""
    main_lists: dict[str, list[tuple[float, int]]] = {}
    elig_lists: dict[str, list[tuple[float, int]]] = {}
    for pid, rec in session.players.items():
        adp = (rec.projection or {}).get("adp_std")
        if not adp or not rec.fantasy:
            continue
        if rec.fantasy.position:
            main_lists.setdefault(rec.fantasy.position, []).append((adp, pid))
        for pos in rec.fantasy.fantasy_positions:
            elig_lists.setdefault(pos, []).append((adp, pid))
    main = {pid: f"#{i} {pos}" for pos, lst in main_lists.items() for i, (_, pid) in enumerate(sorted(lst), 1)}
    every: dict[int, dict[str, str]] = {}
    for pos, lst in elig_lists.items():
        for i, (_, pid) in enumerate(sorted(lst), 1):
            every.setdefault(pid, {})[pos] = f"#{i} {pos}"
    return main, every


def _call_fields(c) -> dict:
    """worth = what he's worth in this room (same for every manager); max = worth + the competition premium, i.e. where
    bidding likely ends (None when you can't bid); call = buy | star | pricey | cannot (max vs your comfort / walk-away)."""
    if c is None:
        return {"worth": None, "max": None, "call": None}
    return {"worth": round(c.fair_value), "max": c.recommended if c.verdict != "cannot" else None, "call": c.verdict}


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


@router.get("/market")
def market(league_id: str, manager_id: str | None = Query(None), state: AppState = Depends(get_state)) -> dict:
    """Per-position supply vs demand, tier cliffs and who's chasing; recent sales vs their Worth."""
    from ..engine.market import market_board

    session = _session(state, league_id)
    try:
        return market_board(session, manager_id or session.user_manager_id())
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


@router.get("/nba-teams")
def nba_teams(league_id: str, state: AppState = Depends(get_state)) -> list[dict]:
    """The 30 NBA teams: projected wins (preseason betting win totals from data/win_totals.json, user-editable),
    projected fantasy talent (top 8 projected FP/G), and last season's record and point differential."""
    from .. import config
    from .players import team_rosters

    session = _session(state, league_id)
    by_team, talent = team_rosters(session)
    rel = config.standings_rel(session.league.stats_season)
    standings = state.store.read_json(rel)["teams"] if state.store.exists(rel) else {}
    totals = state.store.read_json("win_totals.json") if state.store.exists("win_totals.json") else {}
    lines = totals.get("teams", {})
    refs = {t.abbreviation: t.full_name for t in state.stats.list_teams()} if hasattr(state.stats, "list_teams") else {}
    out = []
    for abbr, fp in talent.items():
        roster = sorted(by_team[abbr], reverse=True)
        best = session.players[roster[0][1]] if roster else None
        st = standings.get(abbr)
        out.append({
            "abbr": abbr, "name": refs.get(abbr, abbr), "logo": f"https://sleepercdn.com/images/team_logos/nba/{abbr.lower()}.png",
            "proj_wins": lines.get(abbr), "proj_source": f"{totals.get('source', '').split(',')[0]} ({totals.get('as_of', '?')})" if lines else None,
            "talent_fpg": round(fp, 1), "best": best.full_name if best else None, "best_sleeper_id": best.sleeper_id if best else None,
            "best_fpg": round(roster[0][0], 1) if roster else None, "best_id": best.player_id if best else None,
            "wins": st["wins"] if st else None, "losses": st["losses"] if st else None, "diff": st["diff"] if st else None,
            "conference": st["conference"] if st else None,
        })
    return sorted(out, key=lambda t: (t["proj_wins"] is None, -(t["proj_wins"] or 0), -t["talent_fpg"]))
