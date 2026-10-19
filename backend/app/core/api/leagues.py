"""League documents: settings, managers, keeper history, Sleeper preview/apply, export."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from nba_fantasy_shared.models.league import LeagueSettings, Manager, RosterSlotSpec
from nba_fantasy_shared.models.players import SLOT_ACCEPTS
from nba_fantasy_shared.scoring import map_sleeper_scoring

from ..engine import roster
from ..services.app_state import AppState
from ..services.league_repository import default_managers, validate_league_id
from .deps import _session, get_state
from .schemas import CreateLeague, KeeperEvaluateIn, KeeperHistoryIn, ManagerPatch, SleeperApplyIn, SleeperPreviewIn

router = APIRouter(prefix="/leagues", tags=["leagues"])


@router.get("")
def list_leagues(state: AppState = Depends(get_state)) -> list[dict]:
    return state.list_leagues()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_league(body: CreateLeague, state: AppState = Depends(get_state)) -> dict:
    try:
        validate_league_id(body.league_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if body.settings is not None:
        league = body.settings.model_copy(update={"league_id": body.league_id, "name": body.name})
    else:
        league = LeagueSettings(league_id=body.league_id, name=body.name,
                                roster_season=state.roster_season, stats_season=state.stats_season)
    try:
        session = state.create_league(league, body.managers)
    except FileExistsError:
        raise HTTPException(status.HTTP_409_CONFLICT, f"league {body.league_id} already exists")
    return session.to_export().model_dump(mode="json")


@router.get("/{league_id}")
def get_league(league_id: str, state: AppState = Depends(get_state)) -> dict:
    return _session(state, league_id).to_export().model_dump(mode="json")


@router.delete("/{league_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_league(league_id: str, state: AppState = Depends(get_state)) -> None:
    _session(state, league_id)
    state.delete_league(league_id)


# ------------------------------------------------------------------ settings

@router.get("/{league_id}/settings")
def get_settings(league_id: str, state: AppState = Depends(get_state)) -> LeagueSettings:
    return _session(state, league_id).league


@router.put("/{league_id}/settings")
def put_settings(league_id: str, body: LeagueSettings, state: AppState = Depends(get_state)) -> LeagueSettings:
    _session(state, league_id)
    try:
        session = state.replace_league_settings(league_id, body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return session.league


# ------------------------------------------------------------------ managers

@router.get("/{league_id}/managers")
def get_managers(league_id: str, state: AppState = Depends(get_state)) -> list[Manager]:
    return _session(state, league_id).managers


@router.put("/{league_id}/managers")
def put_managers(league_id: str, body: list[Manager], state: AppState = Depends(get_state)) -> list[Manager]:
    session = _session(state, league_id)
    if session.draft.status != "setup":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "managers can only be replaced while the draft is in setup; use PATCH")
    if sum(1 for m in body if m.is_user) != 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "exactly one manager must be marked is_user")
    if len({m.manager_id for m in body}) != len(body):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "manager ids must be unique")
    session.managers = list(body)
    session.draft.nomination_order = [m.manager_id for m in body]
    session.invalidate()
    state.save_session(league_id)
    return session.managers


@router.post("/{league_id}/sleeper/managers")
def load_managers_from_sleeper(league_id: str, state: AppState = Depends(get_state)) -> list[Manager]:
    """Replace the managers with this season's Sleeper rosters (setup only; needs a data pull for the league)."""
    from ..services.sleeper_league import managers_from_sleeper

    session = _session(state, league_id)
    if session.draft.status != "setup":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "managers can only be replaced while the draft is in setup")
    if not session.sleeper_details:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no Sleeper league data: set the Sleeper league id in Settings, then pull data")
    session.managers = managers_from_sleeper(session.sleeper_details, session.managers)
    session.draft.nomination_order = [m.manager_id for m in session.managers]
    session.invalidate()
    state.save_session(league_id)
    return session.managers


@router.patch("/{league_id}/managers/{manager_id}")
def patch_manager(league_id: str, manager_id: str, body: ManagerPatch, state: AppState = Depends(get_state)) -> Manager:
    session = _session(state, league_id)
    target = next((m for m in session.managers if m.manager_id == manager_id), None)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown manager {manager_id}")
    changes = body.model_dump(exclude_none=True)
    if changes.get("is_user"):
        for m in session.managers:
            m.is_user = False
    for key, value in changes.items():
        setattr(target, key, value if key != "behavior" else body.behavior)
    session.invalidate()
    state.save_session(league_id)
    return target


# ------------------------------------------------------------------ keeper history

@router.get("/{league_id}/keepers/history")
def get_keeper_history(league_id: str, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    return {"records": [r.model_dump(mode="json") for r in session.keeper_history.records]}


@router.put("/{league_id}/keepers/history")
def put_keeper_history(league_id: str, body: KeeperHistoryIn, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    per_season_manager = Counter((r.season, r.manager_id) for r in body.records)
    over = [k for k, n in per_season_manager.items() if n > session.league.keeper.max_per_manager]
    if over:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"more than {session.league.keeper.max_per_manager} keeper(s) for {over}")
    session.keeper_history.records = list(body.records)
    state.save_session(league_id)
    return {"records": [r.model_dump(mode="json") for r in session.keeper_history.records]}


@router.post("/{league_id}/keepers/evaluate")
def evaluate_keepers_route(league_id: str, body: KeeperEvaluateIn, state: AppState = Depends(get_state)) -> list[dict]:
    from ..engine.draft_state import DraftError
    from ..engine.keepers import KeeperCandidate, evaluate_keepers

    session = _session(state, league_id)
    candidates = [KeeperCandidate(c.manager_id, c.player_id, c.last_price, c.keeper_price) for c in body.candidates]
    try:
        return [asdict(e) for e in evaluate_keepers(session, candidates)]
    except DraftError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


# ------------------------------------------------------------------ Sleeper preview / apply

def _sleeper_league(state: AppState, sleeper_league_id: str):
    if state.platform is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    league = state.platform.fetch_league(sleeper_league_id)
    if league is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Sleeper league {sleeper_league_id} not found")
    if league.sport != "nba":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Sleeper league {sleeper_league_id} is {league.sport!r}, not nba")
    return league


def _sleeper_positions(league) -> list[str]:
    """roster_positions plus IR: Sleeper keeps IR slots in settings.reserve_slots, not in roster_positions."""
    positions = list(league.roster_positions)
    if "IR" not in positions:
        positions += ["IR"] * int(league.settings.get("reserve_slots") or 0)
    return positions


def _roster_specs(positions: list[str]) -> tuple[list[RosterSlotSpec], list[str]]:
    counts = Counter(positions)
    specs, unknown = [], []
    for slot, n in counts.items():
        if slot in SLOT_ACCEPTS:
            specs.append(RosterSlotSpec(slot=slot, count=n))  # type: ignore[arg-type]
        else:
            unknown.append(slot)
    return specs, unknown


def _diffs(session, league, mapping) -> list[dict]:
    diffs: list[dict] = []
    current = session.league
    if league.name and league.name != current.name:
        diffs.append({"field": "name", "current": current.name, "sleeper": league.name})
    for key, cur_val in current.scoring.base.model_dump().items():
        new_val = getattr(mapping.settings.base, key)
        if new_val != cur_val:
            diffs.append({"field": f"scoring.base.{key}", "current": cur_val, "sleeper": new_val})
    cur_rules = {r.id: r for r in current.scoring.bonuses}
    new_rules = {r.id: r for r in mapping.settings.bonuses}
    for rule_id in sorted(set(cur_rules) | set(new_rules)):
        c, n = cur_rules.get(rule_id), new_rules.get(rule_id)
        if (c.bonus if c else None) != (n.bonus if n else None) or (c.threshold if c else None) != (n.threshold if n else None):
            diffs.append({"field": f"scoring.bonus.{rule_id}", "current": c.model_dump() if c else None,
                          "sleeper": n.model_dump() if n else None})
    specs, unknown = _roster_specs(_sleeper_positions(league))
    if {s.slot: s.count for s in specs} != roster.slot_capacity(current):
        diffs.append({"field": "roster_slots", "current": roster.slot_capacity(current),
                      "sleeper": {s.slot: s.count for s in specs}, "unknown_positions": unknown})
    if league.total_rosters and league.total_rosters != len(session.managers):
        diffs.append({"field": "num_managers", "current": len(session.managers), "sleeper": league.total_rosters})
    max_keepers = league.settings.get("max_keepers")
    if max_keepers is not None and int(max_keepers) != current.keeper.max_per_manager:
        diffs.append({"field": "keepers.max_per_manager", "current": current.keeper.max_per_manager, "sleeper": int(max_keepers)})
    return diffs


@router.post("/{league_id}/sleeper/preview")
def sleeper_preview(league_id: str, body: SleeperPreviewIn, state: AppState = Depends(get_state)) -> dict:
    session = _session(state, league_id)
    league = _sleeper_league(state, body.sleeper_league_id)
    mapping = map_sleeper_scoring(league.scoring_settings)
    return {
        "league": league.model_dump(mode="json"),
        "scoring_map": {**asdict(mapping), "settings": mapping.settings.model_dump(mode="json")},
        "diffs": _diffs(session, league, mapping),
    }


@router.post("/{league_id}/sleeper/apply")
def sleeper_apply(league_id: str, body: SleeperApplyIn, state: AppState = Depends(get_state)) -> LeagueSettings:
    session = _session(state, league_id)
    league = _sleeper_league(state, body.sleeper_league_id)
    new = _applied(session, league, body.sleeper_league_id, body.apply)
    try:
        state.replace_league_settings(league_id, new)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return session.league


def _applied(session, league, sleeper_league_id: str, fields: list[str]) -> LeagueSettings:
    """A copy of the league settings with the chosen Sleeper fields applied (managers changed in place)."""
    mapping = map_sleeper_scoring(league.scoring_settings)
    new = session.league.model_copy(deep=True)
    new.sleeper_league_id = sleeper_league_id
    for field in fields:
        if field == "name" and league.name:
            new.name = league.name
        elif field == "scoring":
            new.scoring = mapping.settings
        elif field == "roster_slots":
            specs, unknown = _roster_specs(_sleeper_positions(league))
            if unknown:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown roster positions from Sleeper: {unknown}")
            new.roster_slots = specs
        elif field == "num_managers":
            if session.draft.status != "setup":
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot change the manager count once the draft started")
            target = league.total_rosters
            managers = list(session.managers)
            if target > len(managers):
                extra = default_managers(target, new.budget_per_manager)[len(managers):]
                managers.extend(extra)
            elif target < len(managers):
                managers = managers[:target]
                if not any(m.is_user for m in managers):
                    managers[0].is_user = True
            session.managers = managers
            session.draft.nomination_order = [m.manager_id for m in managers]
        elif field == "keepers":
            max_keepers = league.settings.get("max_keepers")
            if max_keepers is not None:
                new.keeper.max_per_manager = int(max_keepers)
                new.keeper.enabled = int(max_keepers) > 0
    return new


@router.post("/{league_id}/sleeper/sync")
def sleeper_sync(league_id: str, state: AppState = Depends(get_state)) -> dict:
    """The one-click pre-draft sync: download the linked Sleeper league (and history leagues), refresh projections,
    then (before the draft) take over its managers and rules. Returns what changed in plain words."""
    from datetime import datetime, timezone

    from nba_fantasy_shared.providers.base import CallFailed

    from ... import config
    from ..services.sleeper_changelog import load_changelog
    from ..services.sleeper_league import current_keepers, load_details, managers_from_sleeper, pull_details, write_profiles

    session = _session(state, league_id)
    sid = session.league.sleeper_league_id
    if state.platform is None or not hasattr(state.platform, "get_json"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Sleeper provider not configured")
    if not sid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "link a Sleeper league first (Settings → Sleeper league → linked league)")
    changes: list[str] = []
    log_before = {e["id"] for e in load_changelog(state.store, sid)}
    try:
        details = pull_details(state.platform, state.store, sid)
        for hid in session.league.sleeper_history_league_ids:
            if load_details(state.store, hid) is None:   # past leagues don't change; Pull now refreshes them anyway
                pull_details(state.platform, state.store, hid)
    except CallFailed as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Sleeper unavailable: {exc}") from exc
    write_profiles(state.store)
    try:
        proj = state.platform.fetch_projections(session.league.roster_season)
        state.store.write_json(config.projections_rel(session.league.roster_season),
                               {"pulled_at": datetime.now(timezone.utc).isoformat(), "projections": proj}, indent=None)
        state.load_pool()   # re-reads projections and every session's Sleeper details
    except (CallFailed, ValueError, AttributeError) as exc:
        changes.append(f"projections not refreshed ({exc})")
    session = _session(state, league_id)

    if session.draft.status == "setup":
        before = {m.manager_id: m.name for m in session.managers}
        session.managers = managers_from_sleeper(details, session.managers)
        session.draft.nomination_order = [m.manager_id for m in session.managers]
        for m in session.managers:
            if before.get(m.manager_id) != m.name:
                changes.append(f"{m.name} replaced {before[m.manager_id]}" if m.manager_id in before else f"{m.name} added")
        league = _sleeper_league(state, sid)
        rule_diffs = [d for d in _diffs(session, league, map_sleeper_scoring(league.scoring_settings)) if d["field"] != "name"]
        for d in rule_diffs:
            changes.append(_describe(d))
        try:
            state.replace_league_settings(league_id, _applied(session, league, sid, ["scoring", "roster_slots", "keepers"]))
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        session.invalidate()
        state.save_session(league_id)
    else:
        changes.append("draft already started: managers and rules were left as they are")

    old_name = session.league.name
    if renamed := state.sync_league_name(league_id):   # before or after the draft
        changes.append(f"league name: {old_name} → {renamed}")
    keepers = current_keepers(session.sleeper_details, session.managers, session.players, session.league.keeper.escalation)
    new_log = [e for e in load_changelog(state.store, sid) if e["id"] not in log_before]
    return {"changes": changes or ["managers and rules already match Sleeper"], "keepers_set": len(keepers),
            "changelog_new": new_log, "synced_at": details.get("pulled_at")}


def _describe(d: dict) -> str:
    field, cur, new = d["field"], d["current"], d["sleeper"]
    if field == "roster_slots":
        fmt = lambda c: " ".join(f"{k}×{v}" for k, v in (c or {}).items() if v)
        return f"roster: {fmt(cur)} → {fmt(new)}"
    if field.startswith("scoring.bonus."):
        bonus = lambda r: f"+{r['bonus']:g}" if r else "none"
        return f"bonus {field.rsplit('.', 1)[1]}: {bonus(cur)} → {bonus(new)}"
    if field.startswith("scoring.base."):
        return f"scoring {field.rsplit('.', 1)[1]}: {cur:g} → {new:g}"
    if field == "keepers.max_per_manager":
        return f"keeper limit: {cur} → {new}"
    return f"{field}: {cur} → {new}"


@router.get("/{league_id}/sleeper/changelog")
def sleeper_changelog(league_id: str, state: AppState = Depends(get_state)) -> list[dict]:
    from ..services.sleeper_changelog import load_changelog

    return load_changelog(state.store, _session(state, league_id).league.sleeper_league_id)


# ------------------------------------------------------------------ export

@router.post("/{league_id}/export")
def export_league(league_id: str, state: AppState = Depends(get_state)) -> dict:
    _session(state, league_id)
    rel, doc = state.export_league(league_id)
    return {"path": str(state.store.path(rel)), "relative_path": rel, "document": doc.model_dump(mode="json")}
