"""Player search (autocomplete), detail (sidebar), and the user's per-player notes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.reconcile.names import normalize_name

from ..services.app_state import AppState
from .deps import get_state
from .schemas import OverridePatch

router = APIRouter(prefix="/players", tags=["players"])


def _brief(state: AppState, player_id: int, drafted_by: str | None = None) -> dict:
    rec = state.players[player_id]
    ov = state.overrides.get(player_id)
    return {
        "player_id": player_id,
        "full_name": rec.full_name,
        "sleeper_id": rec.sleeper_id,
        "team_abbr": rec.team_abbr,
        "eligibility": list(ov.eligibility) if ov else [],
        "eligibility_source": ov.eligibility_source if ov else "none",
        "injury_status": ov.injury_status if ov else "healthy",
        "has_stats": rec.has_stats,
        "sleeper_status": rec.sleeper_status,
        "match_method": rec.match_method,
        "drafted_by": drafted_by,
    }


@router.get("")
def search_players(
    q: str = Query("", description="name prefix or substring, accent-insensitive"),
    limit: int = Query(20, ge=1, le=100),
    league_id: str | None = Query(None, description="mark players already drafted in this league"),
    state: AppState = Depends(get_state),
) -> list[dict]:
    query = normalize_name(q)
    drafted: dict[int, str] = {}
    if league_id:
        session = state.get_session(league_id)
        drafted = {p.player_id: p.manager_id for p in session.draft.picks}
    prefix, inner = [], []
    for pid, rec in state.players.items():
        name = rec.normalized_name
        if not query:
            prefix.append(pid)
        elif name.startswith(query) or any(part.startswith(query) for part in name.split()):
            prefix.append(pid)
        elif query in name:
            inner.append(pid)
    key = lambda pid: (not state.players[pid].has_stats, state.players[pid].last_name.lower(), state.players[pid].first_name.lower())  # noqa: E731
    ordered = sorted(prefix, key=key) + sorted(inner, key=key)
    return [_brief(state, pid, drafted.get(pid)) for pid in ordered[:limit]]


@router.get("/{player_id}")
def player_detail(
    player_id: int,
    league_id: str | None = Query(None, description="use this league's scoring for the valuation"),
    include_history: bool = Query(True, description="fetch per-season totals (network on first request, cached)"),
    state: AppState = Depends(get_state),
) -> dict:
    rec = state.players.get(player_id)
    if rec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown player {player_id}")
    if league_id:
        session = state.get_session(league_id)
        valuation = session.valuations.get(player_id)
        scoring_hash = session.league.scoring.scoring_hash()
    else:
        valuation = state.valuations_for(ScoringSettings()).get(player_id)
        scoring_hash = ScoringSettings().scoring_hash()
    detail = state.details.get(player_id) if (include_history and rec.has_stats) else None
    return {
        "team": _team_block(state, state.get_session(league_id), player_id) if league_id and rec.team_abbr else None,
        "record": rec.model_dump(mode="json"),
        "overrides": state.overrides.get(player_id).model_dump(mode="json") if player_id in state.overrides else None,
        "valuation": valuation.model_dump(mode="json") if valuation else None,
        "scoring_hash": scoring_hash,
        "detail": detail.model_dump(mode="json") if detail else None,
    }


@router.patch("/{player_id}/overrides")
def patch_overrides(player_id: int, body: OverridePatch, state: AppState = Depends(get_state)) -> dict:
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "nothing to change")
    try:
        updated = state.update_override(player_id, changes)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown player {player_id}") from exc
    return updated.model_dump(mode="json")


ROTATION = 8   # players per team counted for the team's projected fantasy talent


def team_rosters(session) -> tuple[dict[str, list[tuple[float, int]]], dict[str, float]]:
    """({team: [(projected FP/G, player id), ...]}, {team: sum of the top 8 projected FP/G})."""
    from ..engine.ranking import expected_fpts

    lg = session.league
    by_team: dict[str, list[tuple[float, int]]] = {}
    for pid, rec in session.players.items():
        if not rec.team_abbr or not (rec.projection or session.valuations.get(pid)):
            continue
        fpg = expected_fpts(rec, session.valuations.get(pid), lg.ranking, lg.scoring)[0]
        by_team.setdefault(rec.team_abbr, []).append((fpg, pid))
    talent = {t: sum(f for f, _ in sorted(lst, reverse=True)[:ROTATION]) for t, lst in by_team.items()}
    return by_team, talent


def _team_block(state: AppState, session, player_id: int) -> dict:
    """His NBA team: logo, his rank on the team, the team's projected-fantasy-talent rank (sum of the top 8
    players' projected FP/G, 1 = most), and the top teammates with photos. Not a win projection."""
    drafted = {p.player_id: p.manager_id for p in session.draft.picks}
    names = {m.manager_id: m.name for m in session.managers}
    by_team, talent = team_rosters(session)
    order = sorted(talent, key=lambda t: -talent[t])
    abbr = session.players[player_id].team_abbr
    roster = sorted(by_team.get(abbr, []), reverse=True)
    # Card order: Sleeper's starting five PG -> C, then 'next up' by depth (all the #2s PG -> C, then #3s ...).
    pos_order = ("PG", "SG", "SF", "PF", "C")

    def depth(pid: int) -> tuple[int, int]:
        f = session.players[pid].fantasy
        if not f or not f.depth_chart_order or f.depth_chart_position not in pos_order:
            return (99, 9)
        return (f.depth_chart_order, pos_order.index(f.depth_chart_position))
    by_depth = sorted((pid for _, pid in roster), key=lambda pid: (depth(pid), -dict((p, f) for f, p in roster)[pid]))
    shown = by_depth[:ROTATION + 2]
    if player_id not in shown:
        shown.append(player_id)
    fpg_of = {pid: f for f, pid in roster}
    team_ref = next((t for t in state.stats.list_teams() if t.abbreviation == abbr), None) if hasattr(state.stats, "list_teams") else None

    def mate(fpg: float, pid: int) -> dict:
        rec = session.players[pid]
        proj_min = (rec.projection or {}).get("sp")
        f = rec.fantasy
        return {"player_id": pid, "name": rec.full_name, "sleeper_id": rec.sleeper_id, "fpg": round(fpg, 1),
                "depth": f"{f.depth_chart_position}{f.depth_chart_order}" if f and f.depth_chart_order else None,
                "starter": bool(f and f.depth_chart_order == 1),
                "min": round(proj_min / 60, 1) if proj_min else None,
                "pos": (session.overrides.get(pid).eligibility if session.overrides.get(pid) else []),
                "drafted_by": names.get(drafted.get(pid)), "is_self": pid == player_id}

    from .. import config

    rel = config.standings_rel(session.league.stats_season)
    conference = ((state.store.read_json(rel)["teams"] if state.store.exists(rel) else {}).get(abbr) or {}).get("conference")
    return {
        "abbr": abbr, "name": team_ref.full_name if team_ref else abbr, "conference": conference,
        "logo": f"https://sleepercdn.com/images/team_logos/nba/{abbr.lower()}.png",
        "talent_rank": order.index(abbr) + 1 if abbr in talent else None, "teams": len(order),
        "talent_fpg": round(talent.get(abbr, 0.0), 1),
        "player_rank": next((i for i, (_, pid) in enumerate(roster, 1) if pid == player_id), None),
        "teammates": [mate(fpg_of[pid], pid) for pid in shown],
        "role": _team_role(session, roster, player_id),
    }


def _team_role(session, roster: list[tuple[float, int]], player_id: int) -> dict | None:
    """Is he his team's star? Rank by Sleeper's projected FP/G on the team (usage, minutes and role are baked into
    it), his share of the top 8's projected FP/G, and the teammate he is compared with (#2 if he is #1, else #1)."""
    rank = next((i for i, (_, pid) in enumerate(roster, 1) if pid == player_id), None)
    if rank is None:
        return None
    fpg = roster[rank - 1][0]
    top8 = sum(f for f, _ in roster[:8]) or 1.0
    other = roster[1] if rank == 1 and len(roster) > 1 else roster[0]
    lead = fpg / other[0] if other[0] else 1.0
    if rank == 1:
        label = "Clear #1 option" if lead >= 1.15 else "#1 option (shared)"
    else:
        label = {2: "#2 option", 3: "#3 option"}.get(rank, "Role player")
    return {"rank": rank, "label": label, "star": rank == 1, "share": round(fpg / top8, 3), "fpg": round(fpg, 1),
            "vs": {"name": session.players[other[1]].full_name, "fpg": round(other[0], 1)} if other[1] != player_id else None}
