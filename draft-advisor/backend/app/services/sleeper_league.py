"""Sleeper league details: managers, this year's keepers, past auctions, and the live draft's picks.

Everything here is read-only public Sleeper data (no login; league members are not notified).
pull_details() follows previous_league_id back up to MAX_SEASONS and caches
  cache/sleeper_details_<id>.json = {pulled_at, seasons: [{league, users, rosters, draft, picks}, ...]}  (newest first)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from collections import Counter, defaultdict
from typing import Any, Mapping

from nba_fantasy_shared.models.league import KeeperEscalation, Manager
from nba_fantasy_shared.models.players import PlayerRecord
from nba_fantasy_shared.storage import JsonStore

log = logging.getLogger(__name__)

MAX_SEASONS = 3


def details_rel(sleeper_league_id: str) -> str:
    return f"cache/sleeper_details_{sleeper_league_id}.json"  # not sleeper_league_<id>: SleeperProvider.fetch_league owns that name


def pull_details(platform: Any, store: JsonStore, sleeper_league_id: str) -> dict:
    seasons: list[dict] = []
    league_id: str | None = sleeper_league_id
    while league_id and league_id != "0" and len(seasons) < MAX_SEASONS:
        league = platform.get_json(f"league/{league_id}")
        if not league:
            break
        draft_id = league.get("draft_id")
        draft = platform.get_json(f"draft/{draft_id}") if draft_id else None
        picks = (platform.get_json(f"draft/{draft_id}/picks") or []) if draft_id else []
        seasons.append({
            "league": league,
            "users": platform.get_json(f"league/{league_id}/users") or [],
            "rosters": platform.get_json(f"league/{league_id}/rosters") or [],
            "draft": draft,
            "picks": picks,
            "adp": _draft_adp(platform, league, draft, picks),
        })
        league_id = league.get("previous_league_id")
    doc = {"pulled_at": datetime.now(timezone.utc).isoformat(), "seasons": seasons}
    old = load_details(store, sleeper_league_id)
    if seasons:
        from .sleeper_changelog import fetch_transactions, update_changelog

        txs = fetch_transactions(platform, seasons[0]["league"]["league_id"])
        update_changelog(store, sleeper_league_id, old, doc, txs)
    store.write_json(details_rel(sleeper_league_id), doc, indent=None)
    log.info("Sleeper league %s: %d season(s) cached", sleeper_league_id, len(seasons))
    return doc


def _draft_adp(platform: Any, league: dict, draft: dict | None, picks: list[dict]) -> dict[str, float]:
    """For snake drafts: Sleeper's average draft position that season for each drafted player, so a profile can
    say whether a manager reaches. Dynasty leagues use dynasty ADP. Empty for auctions (prices say more)."""
    if not picks or (draft or {}).get("type") == "auction" or not hasattr(platform, "base_url"):
        return {}
    host = platform.base_url.rsplit("/v1", 1)[0]
    try:
        rows = platform.get_json(f"{host}/projections/nba/{league.get('season')}?season_type=regular") or []
    except Exception:  # noqa: BLE001 - ADP is a nice-to-have
        return {}
    key = "adp_dynasty" if (league.get("settings") or {}).get("type") == 2 else "adp_std"
    picked = {str(p.get("player_id")) for p in picks}
    return {str(r["player_id"]): float(r["stats"][key]) for r in rows
            if str(r.get("player_id")) in picked and (r.get("stats") or {}).get(key)}


def load_details(store: JsonStore, sleeper_league_id: str | None) -> dict | None:
    if not sleeper_league_id or not store.exists(details_rel(sleeper_league_id)):
        return None
    return store.read_json(details_rel(sleeper_league_id))


def _amount(pick: dict) -> int:
    try:
        return int((pick.get("metadata") or {}).get("amount") or 0)
    except (TypeError, ValueError):
        return 0


def last_auction(details: dict | None) -> dict | None:
    """The most recent completed auction (usually last season)."""
    for season in (details or {}).get("seasons", []):
        draft = season.get("draft") or {}
        if draft.get("type") == "auction" and draft.get("status") == "complete" and season.get("picks"):
            return season
    return None


def tendencies(details: dict | None) -> dict[str, dict]:
    """Per Sleeper user id, how they spent in the last completed auction."""
    season = last_auction(details)
    if season is None:
        return {}
    budget = int((season["draft"].get("settings") or {}).get("budget") or 200)
    by_user: dict[str, list[tuple[int, str]]] = {}
    for p in season["picks"]:
        meta = p.get("metadata") or {}
        by_user.setdefault(p.get("picked_by") or "", []).append((_amount(p), f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip()))
    shares = {}
    for uid, buys in by_user.items():
        buys.sort(reverse=True)
        shares[uid] = sum(a for a, _ in buys[:3]) / budget if budget else 0.0
    median = sorted(shares.values())[len(shares) // 2] if shares else 0.0
    out = {}
    for uid, buys in by_user.items():
        share = shares[uid]
        # relative to this league: everyone here spends top-heavy, so an absolute cut-off labels them all alike
        style = "star chaser" if share >= median + 0.07 else "spreads money" if share <= median - 0.07 else "typical"
        out[uid] = {
            "season": season["league"].get("season"),
            "top_buys": [{"name": n, "price": a} for a, n in buys[:3]],
            "top3_share": round(share, 2),
            "max_price": buys[0][0] if buys else 0,
            "dollar_picks": sum(1 for a, _ in buys if a <= 1),
            "style": style,
        }
    return out


FAVORITE_TEAM_MIN = 5   # ponytail: raw count across all drafts; 3–4 of one team happens by chance in ~30 picks


def draft_habits(all_details: list[dict]) -> dict[str, dict]:
    """Per Sleeper user, across every draft in every given league (auction or snake): favourite NBA teams,
    young/veteran lean of their early picks, and every Sleeper player id they have drafted (with where)."""
    teams: dict[str, Counter] = defaultdict(Counter)
    early_exp: dict[str, list[int]] = defaultdict(list)
    early_pos: dict[str, Counter] = defaultdict(Counter)
    reach: dict[str, list[float]] = defaultdict(list)
    drafted: dict[str, dict[str, str]] = defaultdict(dict)
    names: dict[str, str] = {}
    times: dict[str, Counter] = defaultdict(Counter)    # how many drafts each user took each player in
    for details in all_details:
        for season in (details or {}).get("seasons", []):
            draft = season.get("draft") or {}
            kind = {2: "dynasty ", 1: "keeper "}.get((season["league"].get("settings") or {}).get("type"), "")
            year = season["league"].get("season")
            picks = season.get("picks") or []
            adp = season.get("adp") or {}
            by_user: dict[str, list[dict]] = defaultdict(list)
            for p in picks:
                by_user[p.get("picked_by") or ""].append(p)
            for uid, ps in by_user.items():
                if draft.get("type") == "auction":
                    ps = sorted(ps, key=lambda p: -_amount(p))
                    how = lambda p: f"paid ${_amount(p)} in the {year} {kind}auction"
                else:
                    ps = sorted(ps, key=lambda p: p.get("pick_no") or 0)
                    how = lambda p: f"took him in round {p.get('round')} of the {year} {kind}draft"
                for i, p in enumerate(ps):
                    meta = p.get("metadata") or {}
                    sid = str(p.get("player_id"))
                    names[sid] = f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip() or sid
                    times[uid][sid] += 1
                    if meta.get("team"):
                        teams[uid][meta["team"]] += 1
                    if i < 6:
                        try:
                            early_exp[uid].append(int(meta.get("years_exp") or 0))
                        except ValueError:
                            pass
                        if meta.get("position"):
                            early_pos[uid][meta["position"]] += 1
                        if sid in adp and p.get("pick_no"):
                            reach[uid].append(adp[sid] - p["pick_no"])   # + = taken earlier than usual
                    drafted[uid].setdefault(sid, how(p))
    out = {}
    for uid in set(teams) | set(drafted):
        exp = early_exp.get(uid) or []
        avg = sum(exp) / len(exp) if exp else None
        r = reach.get(uid) or []
        avg_reach = sum(r) / len(r) if r else None
        out[uid] = {
            "favorite_teams": [t for t, n in teams[uid].most_common() if n >= FAVORITE_TEAM_MIN],
            "team_counts": dict(teams[uid].most_common(5)),
            "lean": None if avg is None else "young players" if avg <= 3.5 else "veterans" if avg >= 8 else None,
            "early_years_exp": round(avg, 1) if avg is not None else None,
            "early_positions": dict(early_pos[uid].most_common()),
            "reach": round(avg_reach, 1) if avg_reach is not None else None,
            "reach_style": None if avg_reach is None else "reaches early" if avg_reach >= 3 else "waits for value" if avg_reach <= -3 else None,
            "repeat_players": sorted(names[s] for s, n in times[uid].items() if n >= 2),
            "drafted": drafted[uid],
            "drafted_names": {s: names[s] for s in drafted[uid]},
        }
    return out


PROFILES_REL = "manager_profiles.json"


def write_profiles(store: JsonStore) -> dict:
    """data/manager_profiles.json: one entry per Sleeper username with their traits from every cached Sleeper
    league (auctions and snake drafts). Rebuilt on every pull; the 'notes' field is yours and is kept."""
    all_details = [store.read_json(f"cache/{p.name}") for p in sorted((store.root / "cache").glob("sleeper_details_*.json"))]
    habits = draft_habits(all_details)
    old = store.read_json(PROFILES_REL)["managers"] if store.exists(PROFILES_REL) else {}
    old_notes = {v.get("user_id"): v.get("notes", "") for v in old.values()}
    users: dict[str, str] = {}
    leagues: dict[str, list[str]] = defaultdict(list)
    auctions: dict[str, list[dict]] = defaultdict(list)
    sources = []
    for details in all_details:
        for season in details.get("seasons", []):
            lg, draft = season["league"], season.get("draft") or {}
            kind = {2: "dynasty", 1: "keeper", 0: "redraft"}.get((lg.get("settings") or {}).get("type"), "")
            label = f"{lg.get('season')} {lg.get('name')} ({kind} {draft.get('type') or 'no draft'})"
            sources.append({"league_id": lg.get("league_id"), "label": label, "picks": len(season.get("picks") or [])})
            for u in season.get("users", []):
                users.setdefault(u["user_id"], u.get("display_name") or u["user_id"])
                leagues[u["user_id"]].append(label)
            if draft.get("type") == "auction" and draft.get("status") == "complete":
                for uid, t in tendencies({"seasons": [season]}).items():
                    auctions[uid].append({"league": label, **t})
    managers = {}
    for uid, name in sorted(users.items(), key=lambda kv: kv[1].lower()):
        h = habits.get(uid, {})
        managers[name] = {
            "user_id": uid,
            "leagues": leagues[uid],
            "auctions": auctions.get(uid, []),
            "favorite_teams": h.get("favorite_teams", []),
            "team_counts": h.get("team_counts", {}),
            "lean": h.get("lean"),
            "early_years_exp": h.get("early_years_exp"),
            "early_positions": h.get("early_positions", {}),
            "reach": h.get("reach"),
            "reach_style": h.get("reach_style"),
            "repeat_players": h.get("repeat_players", []),
            "drafted": [{"player": h["drafted_names"][s], "how": how} for s, how in h.get("drafted", {}).items()],
            "notes": old_notes.get(uid, ""),
        }
    doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "about": "Built from Sleeper drafts on every data pull. Edit only 'notes'; everything else is regenerated. "
                 "reach = average (Sleeper ADP minus pick number) over each manager's first 6 snake picks: + takes players "
                 "earlier than usual. Auction style is relative to that league (star chaser / typical / spreads money).",
        "sources": sources,
        "managers": managers,
    }
    store.write_json(PROFILES_REL, doc)
    return doc


def manager_tendency(details: dict | None, manager: Manager) -> dict | None:
    if not manager.sleeper_user_id:
        return None
    return tendencies(details).get(manager.sleeper_user_id)


def current_keepers(
    details: dict | None, managers: list[Manager], players: Mapping[int, PlayerRecord], escalation: KeeperEscalation
) -> list[dict]:
    """Keepers already set in Sleeper for this season, priced with the league's escalation rule."""
    if not details or not details.get("seasons"):
        return []
    current = details["seasons"][0]
    prev = last_auction({"seasons": details["seasons"][1:]})
    last_price = {p.get("player_id"): _amount(p) for p in (prev or {}).get("picks", [])}
    by_sleeper = {r.sleeper_id: r for r in players.values() if r.sleeper_id}
    by_roster = {m.sleeper_roster_id: m for m in managers if m.sleeper_roster_id is not None}
    by_user = {m.sleeper_user_id: m for m in managers if m.sleeper_user_id}
    out = []
    for roster in current.get("rosters", []):
        manager = by_roster.get(roster.get("roster_id")) or by_user.get(roster.get("owner_id"))
        for sid in roster.get("keepers") or []:
            rec = by_sleeper.get(str(sid))
            if manager is None or rec is None:
                log.warning("Sleeper keeper %s on roster %s could not be mapped", sid, roster.get("roster_id"))
                continue
            last = last_price.get(str(sid))
            out.append({
                "manager_id": manager.manager_id, "player_id": rec.player_id, "full_name": rec.full_name,
                "last_price": last, "cost": escalation.price(last) if last else None,
            })
    return out


def managers_from_sleeper(details: dict | None, existing: list[Manager]) -> list[Manager]:
    """This season's Sleeper rosters as managers (roster order); keeps budgets/behaviour of known roster ids."""
    if not details or not details.get("seasons"):
        return existing
    current = details["seasons"][0]
    users = {u["user_id"]: u.get("display_name") or u["user_id"] for u in current.get("users", [])}
    old = {m.sleeper_roster_id: m for m in existing if m.sleeper_roster_id is not None}
    me = next((m.sleeper_user_id for m in existing if m.is_user), None)
    out = []
    for r in sorted(current.get("rosters", []), key=lambda r: r["roster_id"]):
        owner = r.get("owner_id")
        prev = old.get(r["roster_id"])
        same_person = prev is not None and prev.sleeper_user_id == owner
        out.append(Manager(
            manager_id=f"m{r['roster_id']}",
            name=users.get(owner, f"open spot {r['roster_id']}") if owner else f"open spot {r['roster_id']}",
            is_user=bool(owner) and owner == me,
            budget_total=prev.budget_total if prev else 200,
            behavior=prev.behavior if same_person else Manager.model_fields["behavior"].default_factory(),
            sleeper_user_id=owner,
            sleeper_roster_id=r["roster_id"],
        ))
    if out and not any(m.is_user for m in out):
        out[0].is_user = True
    return out


def draft_id(details: dict | None, override: str | None = None) -> str | None:
    if override:
        return override
    seasons = (details or {}).get("seasons") or []
    return seasons[0]["league"].get("draft_id") if seasons else None


def sync_picks(platform: Any, session: Any, sleeper_draft_id: str) -> dict:
    """Fetch the Sleeper draft's picks live and record the ones not recorded yet (manual entries win)."""
    from ..engine.draft_state import DraftError

    draft = platform.get_json(f"draft/{sleeper_draft_id}") or {}
    picks = platform.get_json(f"draft/{sleeper_draft_id}/picks") or []
    by_sleeper = {r.sleeper_id: r for r in session.players.values() if r.sleeper_id}
    by_user = {m.sleeper_user_id: m for m in session.managers if m.sleeper_user_id}
    by_roster = {m.sleeper_roster_id: m for m in session.managers if m.sleeper_roster_id is not None}
    min_bid = session.league.min_bid
    added, errors = [], []
    if session.draft.status == "live":
        drafted = session.engine.drafted_ids()
        for p in sorted(picks, key=lambda x: x.get("pick_no") or 0):
            rec = by_sleeper.get(str(p.get("player_id")))
            manager = by_user.get(p.get("picked_by")) or by_roster.get(p.get("roster_id"))
            meta = p.get("metadata") or {}
            name = rec.full_name if rec else (f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip() or f"Sleeper player {p.get('player_id')}")
            if rec is not None and rec.player_id in drafted:
                continue
            if rec is None or manager is None:
                errors.append(f"pick {p.get('pick_no')}: {name} {'is not in the player pool (record it by hand)' if rec is None else 'went to a Sleeper team not linked to a manager'}")
                continue
            try:
                session.engine.pick(rec.player_id, manager.manager_id, max(min_bid, _amount(p)), None)
            except DraftError as exc:
                errors.append(f"pick {p.get('pick_no')}: {name} to {manager.name}: {exc}")
                continue
            drafted.add(rec.player_id)
            added.append({"player": name, "manager": manager.name, "price": max(min_bid, _amount(p))})
        if added:
            session.invalidate()
    last_picked = draft.get("last_picked")
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    return {
        "draft_id": sleeper_draft_id,
        "sleeper_status": draft.get("status"),
        "sleeper_picks": len(picks),
        "added": added,
        "errors": errors,
        "seconds_since_last_sleeper_pick": round((now_ms - last_picked) / 1000, 1) if last_picked else None,
    }
