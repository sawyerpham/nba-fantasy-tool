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
                         "opp": teams["away" if side == "home" else "home"], "home": side == "home"}
    return out


def week_view(session, fetch: Fetch, week: int | None = None, today: date | None = None) -> dict:
    lg = session.league
    if not lg.sleeper_league_id:
        raise ValueError("league is not linked to Sleeper (Settings)")
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

    proj, stats = {}, {}
    for e in fetch(f"{SLEEPER}/projections/nba/{year}/{week}?season_type=regular", WEEK_TTL) or []:
        proj[(str(e["player_id"]), e["date"])] = e.get("stats") or {}
    for e in fetch(f"{SLEEPER}/stats/nba/{year}/{week}?season_type=regular", LIVE_TTL) or []:
        stats[(str(e["player_id"]), e["date"])] = e.get("stats") or {}

    lid = lg.sleeper_league_id
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
                      "players": r.get("players") or [], "starters": r.get("starters") or [], "reserve": r.get("reserve") or []})

    pairs: dict[int, list[dict]] = {}
    for m in matchups:
        side = {k: m.get(k) for k in ("roster_id", "points", "starters", "starters_points", "players_points")}
        pairs.setdefault(m.get("matchup_id") or -m["roster_id"], []).append(side)

    by_sleeper = {r.sleeper_id: r for r in session.players.values() if r.sleeper_id}
    rostered = {sid for t in teams for sid in t["players"]}
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
            played = bool(st and (st.get("sp") or st.get("gp")))
            games.append({"date": d, "opp": opp, "home": tip.get("home"), "tip": tip.get("tip"), "state": tip.get("state", "pre"),
                          "detail": tip.get("detail", ""), "proj": round(projected_fp(p, lg.scoring, bonus), 2) if p else None,
                          "fp": round(actual_fp(st, lg.scoring), 2) if played else None,
                          "min": round(float(st.get("sp") or 0) / 60, 1) if played else None})
        players[sid] = {"sleeper_id": sid, "player_id": rec.player_id if rec else None, "name": rec.full_name if rec else sid,
                        "team": team, "pos": list(ov.eligibility) if ov else [], "injury": ov.injury_status if ov else "healthy",
                        "injury_note": ov.injury_note if ov else "", "retired": retired, "games": games}

    return {"week": week, "weeks": sorted(weeks), "dates": dates, "today": today.isoformat(), "teams": teams,
            "matchups": [sides for _, sides in sorted(pairs.items())], "players": players}
