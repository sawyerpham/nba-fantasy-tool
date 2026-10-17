"""In-season data for the Season tab: one fantasy week from Sleeper (schedule, rosters, standings, matchups, per-game
projections and box scores) plus ESPN tip-off times and game status, cached briefly so the page can poll.

Per-game fantasy points use the league's scoring:
  projected = base scoring of Sleeper's projected stat line for that game + the player's last-season bonus rate
              per game (the same as the draft rankings);
  actual    = the full formula on the box score, bonuses (40-point games, triple-doubles, ...) included.
Times are Central (the league's clock); a fantasy week runs Monday-Sunday (Sleeper's `week` on each game).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from nba_fantasy_shared.models.players import GameLine
from nba_fantasy_shared.scoring import base_points
from nba_fantasy_shared.scoring.formula import score_game

CT = ZoneInfo("America/Chicago")
SLEEPER = "https://api.sleeper.app"
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={}"
LIVE_TTL, WEEK_TTL, DAY_TTL = 90, 30 * 60, 6 * 3600    # seconds: game-day data / projections / schedule
ESPN_TEAM = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}   # ESPN -> Sleeper codes
# Sleeper stat keys -> GameLine fields (the box score feed uses the same keys as the projections).
STAT_KEYS = {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk", "tov": "to",
             "fgm": "fgm", "fga": "fga", "ftm": "ftm", "fta": "fta", "fg3m": "tpm", "fg3a": "tpa",
             "oreb": "oreb", "dreb": "dreb", "pf": "pf", "plus_minus": "plus_minus"}

# Retired players: no games, always 0, whatever Sleeper's feed says (Sleeper still lists Westbrook as an active FA).
# Anyone Sleeper itself marks RET is treated the same way.
RETIRED = {"1434"}   # Russell Westbrook

# Sleeper injury tags -> the site's statuses (engine/weekplan.py PLAY_CHANCE).
SLEEPER_INJURY = {"GTD": "day_to_day", "DTD": "day_to_day", "Questionable": "day_to_day", "Doubtful": "day_to_day",
                  "Probable": "healthy", "Out": "out_short_term", "Suspended": "out_short_term", "Sus": "out_short_term",
                  "IR": "out_long_term"}
LOCKS_FILE = "season_locks.json"   # your "I locked it" answers: {league: {week: {sleeper id: game date or ""}}}

Fetch = Callable[[str, int], Any]
_cache: dict[str, tuple[float, Any]] = {}


def http_fetch(platform: Any) -> Fetch:
    """GET JSON through the Sleeper provider's HTTP session, cached per URL for `ttl` seconds; None on 404."""
    def fetch(url: str, ttl: int) -> Any:
        hit = _cache.get(url)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        resp = platform.session.get(url, timeout=10)
        data = None if resp.status_code == 404 else (resp.raise_for_status() or resp.json())
        _cache[url] = (time.monotonic(), data)
        return data
    return fetch


def today_ct() -> date:
    return datetime.now(CT).date()


def projected_fp(stats: dict, scoring, bonus_per_game: float = 0.0) -> float:
    line = SimpleNamespace(**{f: float(stats.get(k) or 0.0) for f, k in STAT_KEYS.items()})
    return base_points(line, scoring.base) + bonus_per_game


def actual_fp(stats: dict, scoring) -> float:
    line = GameLine(player_id=0, season="", game_id="", game_date=date(2000, 1, 1), team_abbr="", opponent_abbr="",
                    home=False, minutes=float(stats.get("sp") or 0) / 60,
                    **{f: int(round(float(stats.get(k) or 0))) for f, k in STAT_KEYS.items()})
    return score_game(line, scoring).fpts


def week_dates(schedule: list[dict]) -> dict[int, list[str]]:
    out: dict[int, set[str]] = {}
    for g in schedule:
        out.setdefault(int(g["week"]), set()).add(g["date"])
    return {w: sorted(ds) for w, ds in out.items()}


def current_week(weeks: dict[int, list[str]], today: date) -> int:
    """The week whose Monday-Sunday span holds today; before the season week 1, after it the last week."""
    iso = today.isoformat()
    for w in sorted(weeks):
        monday = date.fromisoformat(weeks[w][0]) - timedelta(days=date.fromisoformat(weeks[w][0]).weekday())
        if iso <= (monday + timedelta(days=6)).isoformat():
            return w
    return max(weeks) if weeks else 1


def espn_day(fetch: Fetch, day: str, today: date) -> dict[str, dict]:
    """team code -> {tip (UTC ISO), state pre/in/post, detail, opp, home} for one date's games."""
    ttl = LIVE_TTL if day >= (today - timedelta(days=1)).isoformat() else DAY_TTL
    data = fetch(ESPN_SCOREBOARD.format(day.replace("-", "")), ttl) or {}
    out: dict[str, dict] = {}
    for e in data.get("events", []):
        comp = e["competitions"][0]
        teams = {c["homeAway"]: ESPN_TEAM.get(c["team"]["abbreviation"], c["team"]["abbreviation"]) for c in comp["competitors"]}
        st = e["status"]["type"]
        for side, team in teams.items():
            out[team] = {"tip": e["date"], "state": st["state"], "detail": st.get("shortDetail", ""),
                         "opp": teams["away" if side == "home" else "home"], "home": side == "home",
                         "period": e["status"].get("period") or 0, "clock": float(e["status"].get("clock") or 0)}
    return out


def week_view(session, fetch: Fetch, week: int | None = None, today: date | None = None, extra: tuple[str, ...] = ()) -> dict:
    lg = session.league
    if not lg.sleeper_league_id:
        raise ValueError("league is not linked to Sleeper (Settings)")
    preview = today is not None   # a fixed day (tests, previews): no wall clock
    year, today = lg.roster_season.split("-")[0], today or today_ct()
    schedule = fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or []
    weeks = week_dates(schedule)
    week = week or current_week(weeks, today)
    dates = weeks.get(week, [])
    plays = {}   # (date, team) -> opponent, from Sleeper's schedule
    for g in schedule:
        if int(g["week"]) == week:
            plays[(g["date"], g["home"]["team"])] = g["away"]["team"]
            plays[(g["date"], g["away"]["team"])] = g["home"]["team"]
    tips = {d: espn_day(fetch, d, today) for d in dates}

    proj, stats, injury, injury_tags = {}, {}, {}, {}
    for e in fetch(f"{SLEEPER}/projections/nba/{year}/{week}?season_type=regular", WEEK_TTL) or []:
        proj[(str(e["player_id"]), e["date"])] = e.get("stats") or {}
        pl = e.get("player") or {}
        if pl.get("injury_status"):
            note = " - ".join(x for x in (pl.get("injury_body_part"), pl.get("injury_notes")) if x)
            injury[str(e["player_id"])] = (SLEEPER_INJURY.get(pl["injury_status"], "day_to_day"), f"{pl['injury_status']}: {note}".rstrip(": "))
            injury_tags[str(e["player_id"])] = pl["injury_status"]   # Sleeper's own tag (GTD, DTD, Out, ...) for display
    for e in fetch(f"{SLEEPER}/stats/nba/{year}/{week}?season_type=regular", LIVE_TTL) or []:
        stats[(str(e["player_id"]), e["date"])] = e.get("stats") or {}

    lid = lg.sleeper_league_id
    league = fetch(f"{SLEEPER}/v1/league/{lid}", WEEK_TTL) or {}
    positions = league.get("roster_positions") or []
    reserve_slots = (league.get("settings") or {}).get("reserve_slots", 0)
    faab_budget = (league.get("settings") or {}).get("waiver_budget", FAAB_TOTAL)   # the league's real FAAB (2026: $100)
    rosters = fetch(f"{SLEEPER}/v1/league/{lid}/rosters", LIVE_TTL) or []
    users = {u["user_id"]: u.get("display_name") for u in fetch(f"{SLEEPER}/v1/league/{lid}/users", WEEK_TTL) or []}
    matchups = fetch(f"{SLEEPER}/v1/league/{lid}/matchups/{week}", LIVE_TTL) or []
    by_roster = {m.sleeper_roster_id: m for m in session.managers if m.sleeper_roster_id is not None}

    teams = []
    for r in rosters:
        s, m = r.get("settings") or {}, by_roster.get(r["roster_id"])
        teams.append({"roster_id": r["roster_id"], "manager_id": m.manager_id if m else None,
                      "name": users.get(r.get("owner_id")) or (m.name if m else f"Team {r['roster_id']}"),
                      "is_user": bool(m and m.is_user), "wins": s.get("wins", 0), "losses": s.get("losses", 0),
                      "ties": s.get("ties", 0), "fpts": round(s.get("fpts", 0) + s.get("fpts_decimal", 0) / 100, 2),
                      "faab_used": s.get("waiver_budget_used", 0),
                      "players": r.get("players") or [], "starters": r.get("starters") or [], "reserve": r.get("reserve") or []})

    pairs: dict[int, list[dict]] = {}
    for m in matchups:
        side = {k: m.get(k) for k in ("roster_id", "points", "starters", "starters_points", "players_points")}
        pairs.setdefault(m.get("matchup_id") or -m["roster_id"], []).append(side)

    by_sleeper = {r.sleeper_id: r for r in session.players.values() if r.sleeper_id}
    rostered = {sid for t in teams for sid in t["players"]} | set(extra)
    players = {}
    for sid in rostered:
        rec = by_sleeper.get(sid)
        ov = session.overrides.get(rec.player_id) if rec else None
        val = session.valuations.get(rec.player_id) if rec else None
        team = rec.team_abbr if rec else None
        bonus = val.bonus_fpts_per_game if val else 0.0
        retired = sid in RETIRED or (rec is not None and rec.sleeper_status == "RET")
        games = []
        for d in ([] if retired else dates):
            opp = plays.get((d, team)) if team else None
            if opp is None:
                continue
            tip, p, st = tips.get(d, {}).get(team, {}), proj.get((sid, d)), stats.get((sid, d))
            played = bool(st and (st.get("sp") or st.get("gp")))   # live games count too: the feed updates in-game
            games.append({"date": d, "opp": opp, "home": tip.get("home"), "tip": tip.get("tip"), "state": tip.get("state", "pre"),
                          "detail": tip.get("detail", ""), "proj": round(projected_fp(p, lg.scoring, bonus), 2) if p else None,
                          "fp": round(actual_fp(st, lg.scoring), 2) if played else None,
                          "min": round(float(st.get("sp") or 0) / 60, 1) if played else None,
                          "proj_min": round(float(p.get("sp") or 0) / 60, 1) if p else None,
                          "period": tip.get("period", 0), "clock": tip.get("clock", 0.0)})
        inj, note = injury.get(sid, ("healthy", ""))   # Sleeper's live tag; none = healthy
        players[sid] = {"sleeper_id": sid, "player_id": rec.player_id if rec else None, "name": rec.full_name if rec else sid,
                        "team": team, "pos": list(ov.eligibility) if ov else [], "injury": inj,
                        "injury_tag": injury_tags.get(sid), "injury_note": note, "retired": retired, "games": games}

    team_games: dict[str, int] = {}
    for (d, team) in plays:
        team_games[team] = team_games.get(team, 0) + 1
    # The lineup day: today until all of today's games are over, then the next game day. The rules re-run on every
    # request against the clock, so the page is always "what to do now".
    iso = today.isoformat()
    day = iso if preview else next((d for d in dates if d > iso or (d == iso and (not tips[d] or any(t["state"] != "post" for t in tips[d].values())))), None)
    return {"week": week, "weeks": sorted(weeks), "dates": dates, "today": iso, "day": day,
            "now": None if preview else datetime.now(CT).isoformat(), "roster_positions": positions,
            "reserve_slots": reserve_slots,
            "team_games": team_games, "injury_tags": injury_tags, "faab_budget": faab_budget,
            "teams": teams,
            "matchups": [sides for _, sides in sorted(pairs.items())], "players": players}


def detect_lock(counted: float | None, games: list[dict], manual: str | None) -> tuple[str, str | None]:
    """("locked" | "maybe" | "no", locked game date). Your answer wins; otherwise from Sleeper's counted points:
    equal to an earlier game than his latest -> locked; equal to his latest with nothing later yet -> maybe."""
    played = [g for g in games if g["fp"] is not None]
    if manual is not None:
        return ("locked", manual) if manual else ("no", None)
    if not counted or not played:
        return "no", None
    same = [g for g in played if abs(g["fp"] - counted) < 0.06]
    if not same:
        return "no", None
    g = same[-1]
    if g is not played[-1]:
        return "locked", g["date"]
    return "maybe", g["date"]


def read_locks(store, league_id: str, week: int) -> dict[str, str]:
    data = store.read_json(LOCKS_FILE) if store.exists(LOCKS_FILE) else {}
    return data.get(league_id, {}).get(str(week), {})


def write_lock(store, league_id: str, week: int, sid: str, game_date: str | None) -> None:
    """game_date = the locked game; "" = not locked; None = forget your answer (back to detection)."""
    data = store.read_json(LOCKS_FILE) if store.exists(LOCKS_FILE) else {}
    week_locks = data.setdefault(league_id, {}).setdefault(str(week), {})
    if game_date is None:
        week_locks.pop(sid, None)
    else:
        week_locks[sid] = game_date
    store.write_json(LOCKS_FILE, data)


def _slot_counts(positions: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pos in positions:
        if pos not in ("BN", "IR"):
            counts[pos] = counts.get(pos, 0) + 1
    return counts


def _plan_players(session, view: dict, team: dict, manual: dict[str, str]):
    from ..engine.weekplan import Game, PlanPlayer, swing_of

    positions = view["roster_positions"]
    slot_of = {sid: positions[i] for i, sid in enumerate(team["starters"]) if i < len(positions) and sid and sid != "0"}
    side = next((m for pair in view["matchups"] for m in pair if m["roster_id"] == team["roster_id"]), {}) or {}
    counted = side.get("players_points") or {}
    now = datetime.fromisoformat(view["now"]) if view.get("now") else None
    def tipped(g: dict) -> bool:   # the clock says he has tipped off (ESPN's state can lag a minute or two)
        return bool(now and g["tip"] and datetime.fromisoformat(g["tip"].replace("Z", "+00:00")) <= now)
    out, locks = [], {}
    for sid in team["players"]:
        p = view["players"].get(sid)
        if p is None:
            continue
        val = session.valuations.get(p["player_id"]) if p["player_id"] else None
        slot = "IR" if sid in team["reserve"] else slot_of.get(sid, "BN")
        status, when = detect_lock(counted.get(sid), p["games"], manual.get(sid)) if slot not in ("BN", "IR") else ("no", None)
        locks[sid] = (status, when)
        locked = next((g["fp"] for g in p["games"] if g["date"] == when), None) if status == "locked" else None
        games = [Game(date=g["date"], proj=g["proj"], fp=g["fp"], started=g["state"] != "pre" or g["fp"] is not None or tipped(g),
                      live=g["state"] == "in" or (g["state"] == "pre" and tipped(g)), tip=g["tip"], final=g["state"] == "post", min=g.get("min"),
                      proj_min=g.get("proj_min"), period=g.get("period", 0), clock=g.get("clock", 0.0))
                 for g in p["games"]]
        out.append(PlanPlayer(sid=sid, name=p["name"], eligibility=p["pos"], games=games, slot=slot, locked=locked,
                              swing=swing_of(val.per_game_fpts) if val else swing_of([]), injury=p["injury"]))
    return out, locks, side


LOCK_REMINDER_MIN = 30   # a LOCK call still not locked: alarm this long before his next tip (the window closes there)


def team_plan(session, view: dict, roster_id: int | None = None, manual: dict[str, str] | None = None) -> dict:
    """The week plan (engine/weekplan.py) for one team of a week_view (default: yours), with lock status, the
    opponent's outlook, every lock / pass / swap decided by the chance to win the week, and today's lineup."""
    from ..engine.weekplan import _minus_minutes, decide_by_win_chance, plan_today, plan_week, swap_win_chance, team_total

    team = next((t for t in view["teams"] if (t["roster_id"] == roster_id if roster_id else t["is_user"])), None)
    if team is None:
        raise ValueError("no such team in this league")
    counts = _slot_counts(view["roster_positions"])
    players, locks, side = _plan_players(session, view, team, manual or {})
    plan = plan_week(players, counts)

    opp = None
    pair = next((pr for pr in view["matchups"] if any(m["roster_id"] == team["roster_id"] for m in pr)), [])
    other = next((m for m in pair if m["roster_id"] != team["roster_id"]), None)
    mode, chance, theirs = "even", None, None
    if other:
        oteam = next(t for t in view["teams"] if t["roster_id"] == other["roster_id"])
        oplayers, olocks, _ = _plan_players(session, view, oteam, {})
        oplan = plan_week(oplayers, counts)
        theirs = team_total(oplayers)
        chance = decide_by_win_chance(players, theirs)   # LOCK / PASS by the chance to win, not expected points
        mode = "ahead" if chance >= 0.6 else "behind" if chance <= 0.4 else "even"
        opp = {"roster_id": oteam["roster_id"], "name": oteam["name"], "expected": oplan.expected,
               "points": other.get("points") or 0, "locked": sum(1 for v in olocks.values() if v[0] == "locked"),
               "games_left": sum(1 for q in oplayers if q.slot != "IR" for g in q.games if not g.started),
               "players": [_player_out(q, olocks) for q in sorted(oplan.players, key=lambda q: (q.seat is None, -q.value))]}

    today = view.get("day", view["today"])
    t = plan_today(players, counts, today) if today in view["dates"] else None
    if t and theirs:   # KEEP / SWAP by the chance to win as well
        swings = {q.name: q.swing for q in players}
        for w in t.watch:
            if w["kind"] == "swap" and w["decision"] in ("KEEP", "SWAP"):
                both = swap_win_chance(players, w["sid"], w, swings.get(w["backup"], 0.3), theirs)
                if both:
                    w["win_keep"], w["win_swap"] = round(both[0], 3), round(both[1], 3)
                    w["decision"] = "SWAP" if both[1] > both[0] else "KEEP"
                    w["text"] += f" Win chance: keep {both[0]:.0%} · swap {both[1]:.0%}."
    # LOCK calls not locked yet: remind before his next tip, when the window closes
    reminders = []
    for q in players:
        if q.action == "LOCK" and q.locked is None:
            nxt = next((g for g in q.games if not g.started), None)
            if nxt and nxt.tip:
                reminders.append({"kind": "lock", "sid": q.sid, "name": q.name, "slot": q.seat, "by": nxt.tip,
                                  "alarm": _minus_minutes(nxt.tip, LOCK_REMINDER_MIN), "decision": "LOCK",
                                  "text": f"Lock {q.name} ({q.x:.1f}) in the {q.seat} slot before his next tip: {q.why}."})
    out_now = ("out_short_term", "out_long_term")   # what the league lets you put on IR (Sleeper: Out / IR)
    active = [q for q in players if q.slot != "IR"]
    healthy_ir = [q.name for q in players if q.slot == "IR" and q.injury not in out_now]
    ir_open = max(0, view.get("reserve_slots", 0) - sum(1 for q in players if q.slot == "IR"))
    roster_state = {"active": len(active), "limit": len(view["roster_positions"]), "ir_open": ir_open,
                    # a healthy player on IR counts as a 16th man: Sleeper freezes the lineup and locks until you drop
                    "illegal": healthy_ir if len(active) + len(healthy_ir) > len(view["roster_positions"]) else [],
                    "ir_candidates": [q.name for q in active if q.injury in out_now] if ir_open else []}
    return {"roster_id": team["roster_id"], "name": team["name"], "expected": plan.expected, "slots": counts,
            "points": side.get("points") or 0, "mode": mode, "win_chance": round(chance, 3) if chance is not None else None,
            "games_left": sum(1 for q in players if q.slot != "IR" for g in q.games if not g.started),
            "players": [_player_out(q, locks) for q in sorted(plan.players, key=lambda q: (q.seat is None, -q.value))],
            "today": {"date": today, "seats": t.seats, "moves": t.moves, "watch": reminders + t.watch} if t else
                     ({"date": today, "seats": {}, "moves": [], "watch": reminders} if reminders else None),
            "roster": roster_state,
            "opponent": opp}


def _player_out(q, locks: dict) -> dict:
    status, when = locks.get(q.sid, ("no", None))
    return {"sid": q.sid, "name": q.name, "pos": q.eligibility, "slot": q.slot, "seat": q.seat, "x": q.x,
            "w": round(q.w, 2), "value": round(q.value, 2), "swing": round(q.swing, 2), "locked": q.locked,
            "lock_status": status, "lock_date": when, "action": q.action, "why": q.why, "injury": q.injury,
            "win_lock": round(q.win_lock, 3) if q.win_lock is not None else None,
            "win_wait": round(q.win_wait, 3) if q.win_wait is not None else None}


# ---- one player's season page --------------------------------------------------------------------------
ESPN_CODE = {v: k for k, v in ESPN_TEAM.items()}
ESPN_ROSTER = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"
ESPN_NEWS = "https://site.api.espn.com/apis/fantasy/v2/games/fba/news/players?playerId={}&limit=6"
NEWS_TTL = 15 * 60
GAME_LOG = 10


def espn_news(fetch: Fetch, name: str, team: str | None) -> list[dict]:
    """Latest fantasy news blurbs from ESPN (the same RotoWire-style notes Sleeper shows), matched by name on his team."""
    from nba_fantasy_shared.reconcile.names import normalize_name

    if not team:
        return []
    roster = fetch(ESPN_ROSTER.format(ESPN_CODE.get(team, team).lower()), DAY_TTL) or {}
    want = normalize_name(name)
    espn_id = next((a["id"] for a in roster.get("athletes", []) if normalize_name(a.get("displayName", "")) == want), None)
    if not espn_id:
        return []
    feed = (fetch(ESPN_NEWS.format(espn_id), NEWS_TTL) or {}).get("feed") or []
    import re

    last = normalize_name(name).split()[-1]
    clean = lambda t: re.sub(r"<[^>]+>", " ", t or "").strip()   # noqa: E731 - some items carry raw HTML
    return [{"published": a.get("published"), "headline": clean(a.get("headline")), "story": clean(a.get("story") or a.get("description"))}
            for a in feed if a.get("headline") and last in normalize_name(a["headline"])   # notes about him, not league articles
            and a.get("type") != "Media"][:4]   # Media = video clips / highlights, no note


LEAGUE_NEWS = 80   # newest league-wide notes shown


def season_news(view: dict, fetch: Fetch) -> dict:
    """The News tab: fantasy notes (RotoWire, via ESPN) on every player of yours, then on every player the other teams
    roster, newest first. ESPN's notes feed only works one player at a time (no league-wide feed), so this is one
    request per player, in parallel and cached NEWS_TTL: only the first load after a Sync pays for it."""
    from concurrent.futures import ThreadPoolExecutor

    players = view["players"]
    owner = {sid: t for t in view["teams"] for sid in t["players"]}

    def notes(sid: str) -> list[dict]:
        p, t = players[sid], owner[sid]
        return [{**n, "sid": sid, "player_id": p["player_id"], "name": p["name"], "owner": t["name"]}
                for n in espn_news(fetch, p["name"], p["team"])]
    sids = [s for s in owner if s in players and s not in RETIRED]
    with ThreadPoolExecutor(16) as ex:
        every = [n for ns in ex.map(notes, sids) for n in ns]
    every.sort(key=lambda n: n.get("published") or "", reverse=True)
    mine = [n for n in every if owner[n["sid"]]["is_user"]]
    return {"mine": mine, "league": [n for n in every if not owner[n["sid"]]["is_user"]][:LEAGUE_NEWS]}


def acquisitions(session, fetch: Fetch, view: dict, sid: str) -> list[dict]:
    """How he changed hands this season: the draft (auction price, keeper flag) from Sleeper's draft picks, then every
    completed transaction in order: waiver claims (FAAB bid), free-agent pickups, trades (to whom) and drops."""
    lid = session.league.sleeper_league_id
    team = {t["roster_id"]: t["name"] for t in view["teams"]}
    out = []
    draft_id = (fetch(f"{SLEEPER}/v1/league/{lid}", WEEK_TTL) or {}).get("draft_id")
    for pk in (fetch(f"{SLEEPER}/v1/draft/{draft_id}/picks", DAY_TTL) or []) if draft_id else []:
        if pk.get("player_id") == sid:
            amount = (pk.get("metadata") or {}).get("amount")
            out.append({"kind": "keeper" if pk.get("is_keeper") else "drafted", "team": team.get(pk.get("roster_id")),
                        "price": int(amount) if amount else None, "when": None})
    moves = []
    for w in range(1, view["week"] + 1):
        moves += fetch(f"{SLEEPER}/v1/league/{lid}/transactions/{w}", LIVE_TTL if w == view["week"] else DAY_TTL) or []
    for t in sorted(moves, key=lambda t: t.get("status_updated") or 0):
        adds, drops = t.get("adds") or {}, t.get("drops") or {}
        if t.get("status") != "complete" or sid not in adds and sid not in drops:
            continue
        if sid in adds:   # a trade both adds and drops him: "traded to" the team that got him
            # ponytail: waiver_bid is Sleeper's documented field; no claim had run yet to confirm it (2026-10-16)
            bid = (t.get("settings") or {}).get("waiver_bid") if t.get("type") == "waiver" else None
            kind = {"waiver": "claimed", "free_agent": "picked up", "trade": "traded to"}.get(t.get("type"), "added")
            out.append({"kind": kind, "team": team.get(adds[sid]), "price": bid, "when": t.get("status_updated")})
        else:
            out.append({"kind": "dropped", "team": team.get(drops[sid]), "price": None, "when": t.get("status_updated")})
    return out


def season_player(session, fetch: Fetch, player_id: int, week: int | None = None) -> dict:
    """Owner, this week's games, recent game log, ranks and news for any player (rostered or not)."""
    rec = session.players.get(player_id)
    if rec is None or not rec.sleeper_id:
        raise ValueError("unknown player")
    sid = rec.sleeper_id
    view = week_view(session, fetch, week, extra=(sid,))
    owner = next((t for t in view["teams"] if sid in t["players"]), None)
    me = view["players"].get(sid, {})

    year, log = session.league.roster_season.split("-")[0], []
    for w in range(view["week"], 0, -1):   # walk back through the season's box scores
        ttl = LIVE_TTL if w == view["week"] else DAY_TTL
        rows = [e for e in fetch(f"{SLEEPER}/stats/nba/{year}/{w}?season_type=regular", ttl) or []
                if str(e.get("player_id")) == sid and (e.get("stats") or {}).get("sp")]
        for e in sorted(rows, key=lambda e: e["date"], reverse=True):
            st = e["stats"]
            log.append({"date": e["date"], "opp": e.get("opponent"), "fp": round(actual_fp(st, session.league.scoring), 2),
                        "min": round(float(st.get("sp") or 0) / 60, 1), "pts": st.get("pts"), "reb": st.get("reb"),
                        "ast": st.get("ast"), "stl": st.get("stl"), "blk": st.get("blk"), "to": st.get("to")})
        if len(log) >= GAME_LOG:
            break

    adp = sorted(((r.projection or {}).get("adp_std"), pid) for pid, r in session.players.items()
                 if (r.projection or {}).get("adp_std"))
    overall = next((i for i, (_, pid) in enumerate(adp, 1) if pid == player_id), None)
    main = rec.fantasy.position if rec.fantasy else None
    same = [pid for _, pid in adp if main and session.players[pid].fantasy and session.players[pid].fantasy.position == main]
    pos_rank = f"#{same.index(player_id) + 1} {main}" if player_id in same else None
    return {"player_id": player_id, "sleeper_id": sid, "week": view["week"], "today": view["today"],
            "owner": {"name": owner["name"], "is_user": owner["is_user"], "roster_id": owner["roster_id"],
                      "ir": sid in owner["reserve"]} if owner else None,
            "games": me.get("games", []), "injury": me.get("injury", "healthy"), "injury_tag": me.get("injury_tag"),
            "injury_note": me.get("injury_note", ""),
            "retired": me.get("retired", False), "game_log": log[:GAME_LOG], "overall_rank": overall, "pos_rank": pos_rank,
            "acquired": acquisitions(session, fetch, view, sid),
            "news": espn_news(fetch, rec.full_name, rec.team_abbr)}


# ---- waivers ---------------------------------------------------------------------------------------------
FAAB_TOTAL = 100   # fallback only: the budget comes from the league's settings (waiver_budget)
WAIVER_SHOW = 12
# ponytail: bid = share of FAAB left that grows with the upgrade over your weakest player (8 value points = 60 %);
# no data on rivals' bids, so it is a guide, not a price.


def waivers(session, view: dict) -> dict:
    """Free agents worth claiming: rest-of-season value (the draft value: projection, Lock-In ceiling, availability),
    this week's games, the player of yours to drop and a suggested blind bid. Waivers run daily (league setting)."""
    me = next(t for t in view["teams"] if t["is_user"])
    rostered = {sid for t in view["teams"] for sid in t["players"]}
    by_sleeper = {r.sleeper_id: pid for pid, r in session.players.items() if r.sleeper_id}
    fa_ids = [pid for pid, r in session.players.items()
              if r.sleeper_id and r.team_abbr and r.sleeper_id not in rostered and r.sleeper_id not in RETIRED
              and r.sleeper_status != "RET"]
    mine = [by_sleeper[sid] for sid in me["players"] if sid in by_sleeper and sid not in me["reserve"]]
    rows = {r.player_id: r for r in session.rank([], fa_ids + mine)}
    drop = min((rows[pid] for pid in mine if pid in rows), key=lambda r: r.value, default=None)
    budget = view.get("faab_budget", FAAB_TOTAL)
    faab_left = budget - (me.get("faab_used") or 0)
    out = []
    floor = drop.value if drop else 0.0   # only real upgrades over your weakest player
    for pid in sorted((pid for pid in fa_ids if pid in rows and rows[pid].value > floor), key=lambda pid: -rows[pid].value)[:WAIVER_SHOW]:
        r = rows[pid]
        up = r.value - (drop.value if drop else 0)
        bid = max(1, min(faab_left, round(faab_left * min(0.6, max(0.0, up) / 8 * 0.6)))) if up > 0 else 1
        out.append({"player_id": pid, "sleeper_id": r.sleeper_id, "name": r.full_name, "team": r.team_abbr,
                    "pos": r.eligibility, "value": round(r.value, 2), "proj_fpg": r.proj_fpts, "injury": r.injury_status,
                    "injury_tag": view.get("injury_tags", {}).get(r.sleeper_id),
                    "games_this_week": view["team_games"].get(r.team_abbr, 0), "upgrade": round(up, 2), "bid": bid})
    return {"faab_left": faab_left, "drop": {"player_id": drop.player_id, "name": drop.full_name, "value": round(drop.value, 2)} if drop else None,
            "claims": out, "budget": budget, "process": "daily"}
