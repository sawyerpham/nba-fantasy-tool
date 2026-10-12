"""Player search (autocomplete), detail (sidebar), and user-editable overrides."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.reconcile.names import normalize_name

from ..services.app_state import AppState
from .deps import get_state
from .schemas import OverridePatch, OverrideReset

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


@router.post("/{player_id}/overrides/reset")
def reset_overrides(player_id: int, body: OverrideReset, state: AppState = Depends(get_state)) -> dict:
    try:
        updated = state.reset_override(player_id, body.fields)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown player {player_id}") from exc
    return updated.model_dump(mode="json")
