"""League changelog: who did what, when.

Two kinds of entries, newest first, in data/sleeper_changelog_<sleeper league id>.json:
- exact:   Sleeper transactions (adds, drops, waivers with FAAB, trades, commissioner moves), timestamped by Sleeper.
- noticed: changes Sleeper keeps no timestamp for (members joining/leaving, keepers set/removed, roster/scoring/
           keeper-limit changes, draft scheduled). Found by comparing a sync with the previous one, so they carry
           the window they happened in: since (previous sync) .. at (this sync).
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from nba_fantasy_shared.storage import JsonStore

log = logging.getLogger(__name__)

PLAYERS_CACHE_REL = "cache/sleeper_players.json"
MAX_TX_WEEKS = 26


def changelog_rel(sleeper_league_id: str) -> str:
    return f"sleeper_changelog_{sleeper_league_id}.json"


def load_changelog(store: JsonStore, sleeper_league_id: str | None) -> list[dict]:
    if not sleeper_league_id or not store.exists(changelog_rel(sleeper_league_id)):
        return []
    return store.read_json(changelog_rel(sleeper_league_id))["entries"]


def player_namer(store: JsonStore) -> Callable[[str], str]:
    """Sleeper player id -> name, from the cached Sleeper players file (loaded on first use)."""
    cache: dict[str, Any] = {}

    def name(sid: str) -> str:
        if "p" not in cache:
            cache["p"] = store.read_json(PLAYERS_CACHE_REL).get("payload", {}) if store.exists(PLAYERS_CACHE_REL) else {}
        p = cache["p"].get(str(sid)) or {}
        return p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or f"player {sid}"

    return name


def _iso(ms: int | float | None) -> str | None:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def _owners(season: dict) -> tuple[dict[int, str | None], dict[str, str]]:
    users = {u["user_id"]: u.get("display_name") or u["user_id"] for u in season.get("users", [])}
    owners = {r["roster_id"]: r.get("owner_id") for r in season.get("rosters", [])}
    return owners, users


def fetch_transactions(platform: Any, league_id: str) -> list[dict]:
    week = 1
    if hasattr(platform, "fetch_platform_state"):
        try:
            week = platform.fetch_platform_state().week or 1
        except Exception:  # noqa: BLE001 - fall back to the first weeks
            pass
    out: dict[str, dict] = {}
    for leg in range(0, min(week + 2, MAX_TX_WEEKS)):
        for t in platform.get_json(f"league/{league_id}/transactions/{leg}") or []:
            out[t["transaction_id"]] = t
    return list(out.values())


def transaction_entries(txs: list[dict], season: dict, name: Callable[[str], str]) -> list[dict]:
    owners, users = _owners(season)
    who = lambda rid: users.get(owners.get(rid) or "", f"roster {rid}")
    entries = []
    for t in txs:
        if t.get("status") != "complete":
            continue
        adds, drops = t.get("adds") or {}, t.get("drops") or {}
        kind = t.get("type") or "move"
        if kind == "trade":
            sides = []
            for rid in t.get("roster_ids") or []:
                got = [name(p) for p, r in adds.items() if r == rid]
                got += [f"{pk.get('season')} round {pk.get('round')} pick" for pk in t.get("draft_picks") or [] if pk.get("owner_id") == rid]
                sides.append(f"{who(rid)} gets {', '.join(got) or 'nothing'}")
            text, actor = "Trade: " + " · ".join(sides), None
        else:
            rid = (t.get("roster_ids") or [None])[0]
            parts = []
            if adds:
                parts.append("added " + ", ".join(name(p) for p in adds))
            if drops:
                parts.append("dropped " + ", ".join(name(p) for p in drops))
            bid = (t.get("settings") or {}).get("waiver_bid")
            text = " and ".join(parts) or "made a roster move"
            if kind == "waiver":
                text += f" (waiver{f', ${bid} FAAB' if bid else ''})"
            elif kind == "commissioner":
                text = "commissioner: " + text
            actor = who(rid)
        entries.append({"id": f"tx-{t['transaction_id']}", "at": _iso(t.get("status_updated") or t.get("created")),
                        "since": None, "exact": True, "who": actor, "kind": kind, "text": text})
    return entries


def _scoring_changes(old: dict, new: dict) -> list[str]:
    keys = sorted(set(old) | set(new))
    return [f"{k} {old.get(k, 0):g} → {new.get(k, 0):g}" for k in keys if old.get(k, 0) != new.get(k, 0)]


def noticed_entries(old: dict, new: dict, name: Callable[[str], str], since: str | None, at: str) -> list[dict]:
    """Differences between two snapshots of the same league season."""
    out: list[dict] = []

    def add(kind: str, text: str, who: str | None = None) -> None:
        key = hashlib.sha1(f"{at}|{kind}|{who}|{text}".encode()).hexdigest()[:12]
        out.append({"id": f"seen-{key}", "at": at, "since": since, "exact": False, "who": who, "kind": kind, "text": text})

    old_owners, old_users = _owners(old)
    new_owners, new_users = _owners(new)
    users = {**old_users, **new_users}
    for rid in sorted(set(old_owners) | set(new_owners)):
        o, n = old_owners.get(rid), new_owners.get(rid)
        if o != n:
            if o and n:
                add("member", f"took over roster {rid} from {users.get(o, o)}", users.get(n, n))
            elif n:
                add("member", f"joined the league (roster {rid})", users.get(n, n))
            else:
                add("member", f"left the league (roster {rid} is open)", users.get(o, o))
    old_keep = {r["roster_id"]: set(r.get("keepers") or []) for r in old.get("rosters", [])}
    for r in new.get("rosters", []):
        who = users.get(r.get("owner_id") or "", f"roster {r['roster_id']}")
        now, before = set(r.get("keepers") or []), old_keep.get(r["roster_id"], set())
        if now - before:
            add("keeper", "set keeper" + ("s " if len(now - before) > 1 else " ") + ", ".join(name(p) for p in sorted(now - before)), who)
        if before - now:
            add("keeper", "removed keeper" + ("s " if len(before - now) > 1 else " ") + ", ".join(name(p) for p in sorted(before - now)), who)
    ol, nl = old.get("league", {}), new.get("league", {})
    if ol.get("name") != nl.get("name"):
        add("rules", f"league renamed: {ol.get('name')} → {nl.get('name')}")
    if Counter(ol.get("roster_positions") or []) != Counter(nl.get("roster_positions") or []):
        fmt = lambda c: " ".join(f"{k}×{v}" for k, v in Counter(c).items())
        add("rules", f"roster changed: {fmt(ol.get('roster_positions') or [])} → {fmt(nl.get('roster_positions') or [])}")
    for key, label in (("max_keepers", "keeper limit"), ("reserve_slots", "IR slots"), ("waiver_budget", "FAAB budget"),
                       ("playoff_teams", "playoff teams")):
        a, b = (ol.get("settings") or {}).get(key), (nl.get("settings") or {}).get(key)
        if a != b:
            add("rules", f"{label}: {a} → {b}")
    sc = _scoring_changes(ol.get("scoring_settings") or {}, nl.get("scoring_settings") or {})
    if sc:
        add("rules", "scoring changed: " + ", ".join(sc))
    od, nd = old.get("draft") or {}, new.get("draft") or {}
    if od.get("start_time") != nd.get("start_time") and nd.get("start_time"):
        add("draft", f"draft scheduled for {_iso(nd['start_time'])}")
    if od.get("status") != nd.get("status") and nd.get("status"):
        add("draft", f"draft status: {od.get('status')} → {nd.get('status')}")
    if (od.get("settings") or {}).get("budget") != (nd.get("settings") or {}).get("budget") and od:
        add("rules", f"auction budget: {(od.get('settings') or {}).get('budget')} → {(nd.get('settings') or {}).get('budget')}")
    return out


def update_changelog(store: JsonStore, sleeper_league_id: str, old_doc: dict | None, new_doc: dict,
                     txs: list[dict]) -> list[dict]:
    """Append this sync's new entries; returns them. Transactions are de-duplicated by Sleeper id."""
    entries = load_changelog(store, sleeper_league_id)
    have = {e["id"] for e in entries}
    name = player_namer(store)
    new_season = new_doc["seasons"][0] if new_doc.get("seasons") else None
    fresh: list[dict] = []
    if new_season is not None:
        fresh += [e for e in transaction_entries(txs, new_season, name) if e["id"] not in have]
        old_season = (old_doc or {}).get("seasons", [None])[0] if (old_doc or {}).get("seasons") else None
        if old_season and old_season["league"].get("league_id") == new_season["league"].get("league_id"):
            fresh += noticed_entries(old_season, new_season, name, (old_doc or {}).get("pulled_at"), new_doc["pulled_at"])
    if fresh or not store.exists(changelog_rel(sleeper_league_id)):
        entries = sorted(entries + fresh, key=lambda e: e["at"] or "", reverse=True)
        store.write_json(changelog_rel(sleeper_league_id), {"sleeper_league_id": sleeper_league_id, "entries": entries})
    return fresh
