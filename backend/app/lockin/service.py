"""In-season data for the Season tab: one fantasy week from Sleeper (schedule, rosters, standings, matchups, per-game
projections and box scores) plus ESPN tip-off times and game status, cached briefly so the page can poll.

Per-game fantasy points use the league's scoring:
  projected = base scoring of Sleeper's projected stat line for that game + the player's last-season bonus rate
              per game (the same as the draft rankings);
  actual    = the full formula on the box score, bonuses (40-point games, triple-doubles, ...) included.
Times are Central (the league's clock); a fantasy week runs Monday-Sunday (Sleeper's `week` on each game).
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Callable
from zoneinfo import ZoneInfo

from nba_fantasy_shared.models.players import GameLine
from nba_fantasy_shared.reconcile.names import normalize_name
from nba_fantasy_shared.scoring import base_points
from nba_fantasy_shared.scoring.formula import score_game

CT = ZoneInfo("America/Chicago")   # default; each league picks its own (LeagueSettings.timezone)


def league_tz(lg) -> ZoneInfo:
    try:
        return ZoneInfo(getattr(lg, "timezone", None) or "America/Chicago")
    except Exception:   # an unknown zone name: fall back rather than break the page
        return CT
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
    fetch.platform = platform   # week_view adds rostered players the pool left out from Sleeper's (cached) player list
    return fetch


def today_ct(tz: ZoneInfo = CT) -> date:
    return datetime.now(tz).date()


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
        score = {c["homeAway"]: c.get("score") for c in comp["competitors"]}
        st = e["status"]["type"]
        for side, team in teams.items():
            other = "away" if side == "home" else "home"
            out[team] = {"tip": e["date"], "state": st["state"], "detail": st.get("shortDetail", ""), "event": e.get("id"),
                         "opp": teams[other], "home": side == "home",
                         "score": score[side] if st["state"] != "pre" else None, "opp_score": score[other] if st["state"] != "pre" else None,
                         "period": e["status"].get("period") or 0, "clock": float(e["status"].get("clock") or 0)}
    return out


BOX_KEYS = ("pts", "reb", "ast", "blk", "fgm", "fga", "ftm", "fta", "to", "pf")   # Sleeper's per-game stat keys
SLEEPER_FLIP_HOUR = 4   # ponytail: guessed hour (ET) Sleeper's lineup day rolls over; set it from the measured flip


def week_view(session, fetch: Fetch, week: int | None = None, today: date | None = None, extra: tuple[str, ...] = ()) -> dict:
    from .weekplan import Game, beat_chance, live_estimate, swing_of

    lg = session.league
    if not lg.sleeper_league_id:
        raise ValueError("league is not linked to Sleeper (Settings)")
    preview = today is not None   # a fixed day (tests, previews): no wall clock
    tz = league_tz(lg)
    year, today = lg.roster_season.split("-")[0], today or today_ct(tz)
    schedule = fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or []
    weeks = week_dates(schedule)
    week = week or current_week(weeks, today)
    dates = weeks.get(week, [])
    # every (date, team) with a game all season: a game is the second night of a back-to-back when his team also
    # played the day before (Monday's look back into last week too)
    played_on = {(g["date"], g[side]["team"]) for g in schedule for side in ("home", "away")}
    b2b = lambda d, team: ((date.fromisoformat(d) - timedelta(days=1)).isoformat(), team) in played_on   # noqa: E731
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
    ls = league.get("settings") or {}
    # The league's waiver rules, from Sleeper; None when Sleeper didn't send them (the Waivers tab says so).
    waiver = {"type": WAIVER_TYPES.get(ls["waiver_type"], "unknown"), "budget": ls.get("waiver_budget"),
              "min_bid": ls.get("waiver_bid_min", 1), "daily": bool(ls.get("daily_waivers"))} if "waiver_type" in ls else None
    faab_budget = (waiver or {}).get("budget") or FAAB_TOTAL
    rosters = fetch(f"{SLEEPER}/v1/league/{lid}/rosters", LIVE_TTL) or []
    users = {u["user_id"]: u for u in fetch(f"{SLEEPER}/v1/league/{lid}/users", WEEK_TTL) or []}
    matchups = fetch(f"{SLEEPER}/v1/league/{lid}/matchups/{week}", LIVE_TTL) or []
    by_roster = {m.sleeper_roster_id: m for m in session.managers if m.sleeper_roster_id is not None}

    teams, nicks = [], {}   # nicks: sid -> the nickname his manager gave him on Sleeper
    for r in rosters:
        s, m = r.get("settings") or {}, by_roster.get(r["roster_id"])
        u = users.get(r.get("owner_id")) or {}
        um = u.get("metadata") or {}
        own = set(r.get("players") or [])
        nicks.update({k[7:]: v.strip() for k, v in (r.get("metadata") or {}).items()
                      if k.startswith("p_nick_") and k[7:] in own and isinstance(v, str) and v.strip()})
        teams.append({"roster_id": r["roster_id"], "manager_id": m.manager_id if m else None,
                      # the Sleeper team name when the manager set one, else his username
                      "name": um.get("team_name") or u.get("display_name") or (m.name if m else f"Team {r['roster_id']}"),
                      "user": u.get("display_name"),
                      "avatar": um.get("avatar") or (f"https://sleepercdn.com/avatars/thumbs/{u['avatar']}" if u.get("avatar") else None),
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
    from ..core.services.sleeper_league import _add_sleeper_only
    for sid in rostered - by_sleeper.keys():   # rostered but not in the pool (retired / FA at pull time): name, positions, status
        rec = _add_sleeper_only(getattr(fetch, "platform", None), session, sid)
        if rec:
            by_sleeper[sid] = rec
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
                          "period": tip.get("period", 0), "clock": tip.get("clock", 0.0),
                          "score": tip.get("score"), "opp_score": tip.get("opp_score"),   # the game's score (live or final)
                          "b2b": b2b(d, team), "event": tip.get("event"),   # ESPN's game id (the game card on the right)
                          # his box score (live games too), for the game card's hover
                          "box": {k: int(st.get(k) or 0) for k in BOX_KEYS} if played else None})
            g = games[-1]
            if g["state"] == "in" and played:   # where his game will likely finish (the chip colours his projection by it)
                g["pace"] = round(live_estimate(Game(date=d, proj=g["proj"], fp=g["fp"], started=True, live=True, min=g["min"],
                                                     proj_min=g["proj_min"], period=g["period"], clock=g["clock"])), 2)
        inj, note = injury.get(sid, ("healthy", ""))   # Sleeper's live tag; none = healthy
        # each final game: the chance one of his unfinished games this week beats it (the chip's hover)
        left = [Game(date=g["date"], proj=g["proj"], fp=g["fp"], started=g["state"] != "pre", live=g["state"] == "in",
                     min=g["min"], proj_min=g["proj_min"], period=g["period"], clock=g["clock"], b2b=g["b2b"]) for g in games if g["state"] != "post"]
        swing = swing_of(val.per_game_fpts if val else [])
        for g in games:
            if g["state"] == "post" and g["fp"] is not None:
                g["beat"] = round(beat_chance(g["fp"], left, swing, inj), 3)
        players[sid] = {"sleeper_id": sid, "player_id": rec.player_id if rec else None, "name": rec.full_name if rec else sid,
                        "team": team, "pos": list(ov.eligibility) if ov else [], "injury": inj,
                        "injury_tag": injury_tags.get(sid), "injury_note": note, "retired": retired, "games": games,
                        "nick": nicks.get(sid)}

    team_games: dict[str, int] = {}
    for (d, team) in plays:
        team_games[team] = team_games.get(team, 0) + 1
    # The lineup day: today until all of today's games are over, then the next game day. The rules re-run on every
    # request against the clock, so the page is always "what to do now".
    iso = today.isoformat()
    # The Sleeper gap: Sleeper's API serves one day's lineup at a time and keeps serving that day's after its games
    # are over (until it flips to the next day), so the next day's lineup a manager may already have set is unseen.
    sday = (datetime.now(ZoneInfo("America/New_York")) - timedelta(hours=SLEEPER_FLIP_HOUR)).date().isoformat()
    gap = not preview and bool(tips.get(sday)) and all(t["state"] == "post" for t in tips[sday].values())
    day = iso if preview else next((d for d in dates if d > iso or (d == iso and (not tips[d] or any(t["state"] != "post" for t in tips[d].values())))), None)
    return {"week": week, "weeks": sorted(weeks), "dates": dates, "today": iso, "day": day,
            "now": None if preview else datetime.now(tz).isoformat(), "tz": tz.key, "roster_positions": positions,
            "sleeper_gap": gap,
            "reserve_slots": reserve_slots,
            "team_games": team_games, "injury_tags": injury_tags, "faab_budget": faab_budget, "waiver": waiver,
            "teams": teams,
            "matchups": [sides for _, sides in sorted(pairs.items())], "players": players}


ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={}"
# ESPN box score columns (statistics[0].keys) -> Sleeper stat keys, so actual_fp scores them with the league's formula
ESPN_BOX = {"points": "pts", "rebounds": "reb", "assists": "ast", "steals": "stl", "blocks": "blk", "turnovers": "to",
            "offensiveRebounds": "oreb", "defensiveRebounds": "dreb", "fouls": "pf", "plusMinus": "plus_minus"}
ESPN_PAIRS = {"fieldGoalsMade-fieldGoalsAttempted": ("fgm", "fga"), "threePointFieldGoalsMade-threePointFieldGoalsAttempted": ("tpm", "tpa"),
              "freeThrowsMade-freeThrowsAttempted": ("ftm", "fta")}


def _num(s) -> float:
    try:
        return float(str(s).replace("+", ""))
    except ValueError:
        return 0.0


LEAD_STATS = (("PTS", "pts"), ("REB", "reb"), ("AST", "ast"), ("STL", "stl"), ("BLK", "blk"), ("3PM", "tpm"))


def lead_stats(stats: dict, scoring) -> list[list]:
    """A player's headline stat line (the game card's top performers, like Sleeper's): points always, then up to 4
    more, any he has (not 0), the ones worth the most fantasy points in the league's scoring first."""
    worth = {k: actual_fp({k: stats.get(k, 0)}, scoring) for _, k in LEAD_STATS[1:]}
    rest = sorted((x for x in LEAD_STATS[1:] if stats.get(x[1])), key=lambda x: -worth[x[1]])[:4]
    return [[label, int(stats.get(k, 0))] for label, k in [LEAD_STATS[0], *rest]]


def team_stat_rows(fetch: Fetch, year: str) -> tuple[list[dict], set[str]]:
    """This season's per-game Sleeper rows (every week that has a finished game) and the finished games' ids: what
    team_ranks reads."""
    schedule = fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or []
    done = {g.get("game_id") for g in schedule if g.get("status") == "complete"}
    last = max((int(g["week"]) for g in schedule if g.get("status") == "complete"), default=0)
    rows = [e for w in range(1, last + 1)
            for e in fetch(f"{SLEEPER}/stats/nba/{year}/{w}?season_type=regular", LIVE_TTL if w == last else DAY_TTL) or []]
    return rows, done


def game_detail(session, fetch: Fetch, event: str) -> dict:
    """One NBA game for the right-side game card (ESPN's summary): status and date, then both teams (before the tip
    too): name, logo, record and score, every player's box score once it starts (players who got minutes; DNPs listed
    apart) with fantasy points in the league's scoring and a headline stat line, the team's offense / defense ranks
    (team_ranks) and its depth chart (the player profile's, Sleeper's): PG -> C, 1st / 2nd / 3rd."""
    from ..core.api.players import depth_grid, team_rosters

    by_team, hurt = team_rosters(session)[0], sleeper_injuries(fetch)
    data = fetch(ESPN_SUMMARY.format(event), LIVE_TTL) or {}
    comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
    st = (comp.get("status") or {}).get("type") or {}
    rows, done = team_stat_rows(fetch, session.league.roster_season.split("-")[0])
    box = {ESPN_TEAM.get(t["team"]["abbreviation"], t["team"]["abbreviation"]): t
           for t in (data.get("boxscore") or {}).get("players") or []}
    teams = []
    for c in comp.get("competitors") or []:
        abbr = ESPN_TEAM.get(c["team"]["abbreviation"], c["team"]["abbreviation"])
        t = box.get(abbr) or {}   # no box score before the tip
        # ESPN's names -> our player ids (any player, rostered or not, opens his profile); his own team's wins a shared name
        ids = {normalize_name(r.full_name): pid for pid, r in sorted(session.players.items(), key=lambda x: x[1].team_abbr == abbr)}
        block = (t.get("statistics") or [{}])[0]
        keys, played, dnp = block.get("keys") or [], [], []
        for a in block.get("athletes") or []:
            ath, vals = a.get("athlete") or {}, a.get("stats") or []
            if a.get("didNotPlay") or not vals or _num(vals[0]) == 0:
                dnp.append({"name": ath.get("displayName"), "reason": a.get("reason") if a.get("didNotPlay") else None})
                continue
            raw = dict(zip(keys, vals))
            st_ = {"sp": _num(raw.get("minutes")) * 60}
            for k, v in raw.items():
                if k in ESPN_BOX:
                    st_[ESPN_BOX[k]] = _num(v)
                elif k in ESPN_PAIRS and "-" in str(v):
                    m, att = str(v).split("-", 1)
                    st_[ESPN_PAIRS[k][0]], st_[ESPN_PAIRS[k][1]] = _num(m), _num(att)
            played.append({"name": ath.get("displayName"), "player_id": ids.get(normalize_name(ath.get("displayName"))), "pos": (ath.get("position") or {}).get("abbreviation"),
                           "head": (ath.get("headshot") or {}).get("href"), "starter": bool(a.get("starter")),
                           "min": int(_num(raw.get("minutes"))), "stats": {k: int(v) for k, v in st_.items() if k != "sp"},
                           "fp": round(actual_fp(st_, session.league.scoring), 2), "lead": lead_stats(st_, session.league.scoring)})
        teams.append({"abbr": abbr, "name": c["team"].get("displayName"), "logo": ((c["team"].get("logos") or [{}])[0]).get("href"),
                      "score": c.get("score"), "home": c.get("homeAway") == "home",
                      "record": next((r.get("summary") for r in c.get("record") or [] if r.get("type") == "total"), None),
                      "players": played, "dnp": dnp, "ranks": team_ranks(rows, abbr, done),
                      "depth_grid": depth_grid(session, sorted(by_team.get(abbr, []), reverse=True), inj=hurt)})
    teams.sort(key=lambda t: t["home"])   # away first, home second ("LAC @ LAL")
    return {"event": event, "tip": comp.get("date"), "state": st.get("state"), "detail": st.get("shortDetail"), "teams": teams}


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
    from .weekplan import Game, PlanPlayer, swing_of, wait_value

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
        games = [Game(date=g["date"], proj=g["proj"], fp=g["fp"], started=g["state"] != "pre" or g["fp"] is not None or tipped(g),
                      live=g["state"] == "in" or (g["state"] == "pre" and tipped(g)), tip=g["tip"], final=g["state"] == "post", min=g.get("min"),
                      proj_min=g.get("proj_min"), period=g.get("period", 0), clock=g.get("clock", 0.0), b2b=g.get("b2b", False))
                 for g in p["games"]]
        swing = swing_of(val.per_game_fpts) if val else swing_of([])
        status, when = detect_lock(counted.get(sid), p["games"], manual.get(sid)) if slot not in ("BN", "IR") else ("no", None)
        if status == "maybe" and not team.get("is_user"):   # rivals: Sleeper can't tell yet, so guess locked when it's
            # the right call (beats waiting for his later games); your own locks you know (the ✓ / your answers).
            # Only a final game can be locked: one still in progress is just counting so far.
            then = next(g for g in p["games"] if g["date"] == when)
            final = then["state"] == "post"
            status = "guess" if final and then["fp"] >= wait_value([g for g in games if not g.started], swing, p["injury"]) else "maybe"
        locks[sid] = (status, when)
        locked = next((g["fp"] for g in p["games"] if g["date"] == when), None) if status in ("locked", "guess") else None
        out.append(PlanPlayer(sid=sid, name=p["name"], eligibility=p["pos"], games=games, slot=slot, locked=locked,
                              swing=swing, injury=p["injury"]))
    return out, locks, side


LOCK_REMINDER_MIN = 30   # a LOCK call still not locked: alarm this long before his next tip (the window closes there)
CHECK_LEAD_MIN = 15      # timeline check-ins sit this long before the tip they're for (on the quarter hour)
GAME_MINUTES = 135       # ponytail: a game runs ~2 h 15 m; overtime runs longer, use ESPN's final status if that bites


def week_timeline(players, counts: dict[str, int], view: dict, today_seats: dict | None) -> dict:
    """The best lineup at every moment from now to the end of the week, for the timeline slider. The lineup changes
    only at check-ins, CHECK_LEAD_MIN before a tip where someone moves in, so you open Sleeper as few times as
    possible: at that check every swap available then happens at once (later players too, e.g. the 9:30 game
    moves in at the 8:45 check for the 9:00 games). A game counts as in progress for GAME_MINUTES after its tip,
    so a player still playing is never swapped out. Each check plans the games still to come (plan_today for the
    next game's day) from the previous lineup, so the moves chain; locked players never move."""
    from .weekplan import plan_today

    tz = ZoneInfo(view.get("tz") or "America/Chicago")
    first = date.fromisoformat(view["dates"][0])
    start = datetime.combine(first - timedelta(days=first.weekday()), datetime.min.time(), tz)   # Monday 12 AM, league time
    end = start + timedelta(days=7)
    if not view.get("day") or not view["dates"]:
        return {"start": start.isoformat(), "end": end.isoformat(), "segments": []}

    def at(iso: str) -> datetime:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    active = [p for p in players if p.slot != "IR"]
    tips = sorted({at(g.tip) for p in active for g in p.games if g.tip and not g.started})

    def starters(seats: dict) -> set[str]:
        return {sid for ids in seats.values() for sid in ids}

    def next_day() -> str | None:   # the date of the next game still to tip
        g = min((g for p in active for g in p.games if not g.started), key=lambda g: (g.date, g.tip or "~"), default=None)
        return g.date if g else None
    saved = {id(g): (g.started, g.live) for p in players for g in p.games}
    slots = {p.sid: p.slot for p in players}
    seats = today_seats if today_seats is not None else plan_today(players, counts, next_day() or view["day"]).seats
    segments = [{"date": view["day"], "seats": seats}]
    lead, length = timedelta(minutes=CHECK_LEAD_MIN), timedelta(minutes=GAME_MINUTES)
    for t in tips:
        check = t - lead
        for p in players:   # at the check: earlier games have started; still in progress = can't be moved
            for g in p.games:
                if g.tip and at(g.tip) <= check:
                    g.started, g.live = True, check < at(g.tip) + length
            if p.slot != "IR" and p.locked is None:   # start from the previous segment's lineup
                p.slot = next((s for s, ids in seats.items() if p.sid in ids), "BN")
        d = next_day()
        if d is None:
            break
        nxt = plan_today(players, counts, d).seats
        tipping = {p.sid for p in active for g in p.games if g.tip and at(g.tip) == t}
        if (starters(nxt) - starters(seats)) & tipping:   # someone moves in for this tip: check in now, every swap at once
            segments[-1]["to"] = check.astimezone(tz).isoformat()
            seats = nxt
            segments.append({"date": d, "seats": seats})
    for p in players:
        p.slot = slots[p.sid]
        for g in p.games:
            g.started, g.live = saved[id(g)]
    segments[-1]["to"] = end.isoformat()   # the last lineup stands until the week is over
    return {"start": start.isoformat(), "end": end.isoformat(), "segments": segments}


def locked_points(players) -> float:
    """The team's score so far: locked games only. Sleeper's own total also counts each starter's latest game,
    which isn't banked until it's locked (a later game replaces it)."""
    return round(sum(p.locked for p in players if p.locked is not None), 2)


def team_plan(session, view: dict, roster_id: int | None = None, manual: dict[str, str] | None = None) -> dict:
    """The week plan (engine/weekplan.py) for one team of a week_view (default: yours), with lock status, the
    opponent's outlook, every lock / pass / swap decided by the chance to win the week, and today's lineup."""
    from .weekplan import (_minus_minutes, decide_by_win_chance, lock_slots, plan_today, plan_week, scenario_total,
                           swap_win_chance, team_total, win_chance)

    team = next((t for t in view["teams"] if (t["roster_id"] == roster_id if roster_id else t["is_user"])), None)
    if team is None:
        raise ValueError("no such team in this league")
    counts = _slot_counts(view["roster_positions"])
    players, locks, side = _plan_players(session, view, team, manual or {})
    plan = plan_week(players, counts)

    opp = None
    pair = next((pr for pr in view["matchups"] if any(m["roster_id"] == team["roster_id"] for m in pr)), [])
    other = next((m for m in pair if m["roster_id"] != team["roster_id"]), None)
    mode, chance, theirs, outlook = "even", None, None, None
    if other:
        oteam = next(t for t in view["teams"] if t["roster_id"] == other["roster_id"])
        oplayers, olocks, _ = _plan_players(session, view, oteam, manual or {})   # your answers about their locks too
        oplan = plan_week(oplayers, counts)
        theirs = team_total(oplayers)
        chance = decide_by_win_chance(players, theirs)   # LOCK / PASS by the chance to win, not expected points
        mode = "ahead" if chance >= 0.6 else "behind" if chance <= 0.4 else "even"
        # this week's advice: the chance to win locking everything you can now (safe) vs waiting on later games (risky)
        outlook = {"safe": round(win_chance(scenario_total(players, True), theirs), 3),
                   "risky": round(win_chance(scenario_total(players, False), theirs), 3)}
        opp = {"roster_id": oteam["roster_id"], "name": oteam["name"], "user": oteam.get("user"), "avatar": oteam.get("avatar"),
               "expected": oplan.expected,
               "points": locked_points(oplayers), "locked": sum(1 for v in olocks.values() if v[0] in ("locked", "guess")),
               "games_left": sum(1 for q in oplayers if q.slot != "IR" for g in q.games if not g.started),
               "players": [_player_out(q, olocks) for q in sorted(oplan.players, key=lambda q: (q.seat is None, -q.value))]}

    for q in players:   # every lockable game: which slot to lock him in (the one leaving the rest of the lineup most)
        if q.seat and q.x is not None and q.x_final and q.locked is None:
            q.lock_at = lock_slots(q, players, counts)
            if theirs and q.win_lock is not None and q.lock_at:
                # the win chance locked in each slot: win_lock assumes the best one; a worse slot costs the rest of
                # the lineup (best team - that slot's team), e.g. locking where he sits instead of moving him first
                mean, var = team_total(players, skip=q)
                for o in q.lock_at:
                    o["win"] = round(win_chance((mean + q.x - (q.lock_at[0]["team"] - o["team"]), var), theirs), 3)
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
    timeline = week_timeline(players, counts, view, t.seats if t else None) if view["dates"] else None
    if opp:   # their best lineup over the week too: the matchup draws their swap arrows, mirrored on the right
        ot = plan_today(oplayers, counts, today) if today in view["dates"] else None
        opp["today"] = {"date": today, "seats": ot.seats} if ot else None
        opp["timeline"] = week_timeline(oplayers, counts, view, ot.seats if ot else None) if view["dates"] else None
    out_now = ("out_short_term", "out_long_term")   # what the league lets you put on IR (Sleeper: Out / IR)
    active = [q for q in players if q.slot != "IR"]
    healthy_ir = [q.name for q in players if q.slot == "IR" and q.injury not in out_now]
    ir_open = max(0, view.get("reserve_slots", 0) - sum(1 for q in players if q.slot == "IR"))
    roster_state = {"active": len(active), "limit": len(view["roster_positions"]), "ir_open": ir_open,
                    # a healthy player on IR counts as a 16th man: Sleeper freezes the lineup and locks until you drop
                    "illegal": healthy_ir if len(active) + len(healthy_ir) > len(view["roster_positions"]) else [],
                    "ir_candidates": [q.name for q in active if q.injury in out_now] if ir_open else []}
    return {"roster_id": team["roster_id"], "name": team["name"], "user": team.get("user"), "avatar": team.get("avatar"),
            "expected": plan.expected, "slots": counts,
            "points": locked_points(players), "mode": mode, "win_chance": round(chance, 3) if chance is not None else None,
            "outlook": outlook,
            "games_left": sum(1 for q in players if q.slot != "IR" for g in q.games if not g.started),
            "players": [_player_out(q, locks) for q in sorted(plan.players, key=lambda q: (q.seat is None, -q.value))],
            "today": {"date": today, "seats": t.seats, "moves": t.moves, "watch": reminders + t.watch} if t else
                     ({"date": today, "seats": {}, "moves": [], "watch": reminders} if reminders else None),
            "roster": roster_state, "timeline": timeline,
            "opponent": opp}


def _player_out(q, locks: dict) -> dict:
    status, when = locks.get(q.sid, ("no", None))
    return {"sid": q.sid, "name": q.name, "pos": q.eligibility, "slot": q.slot, "seat": q.seat, "x": q.x,
            "w": round(q.w, 2), "value": round(q.value, 2), "swing": round(q.swing, 2), "locked": q.locked,
            "lock_status": status, "lock_date": when, "action": q.action, "why": q.why, "injury": q.injury,
            "win_lock": round(q.win_lock, 3) if q.win_lock is not None else None,
            "win_wait": round(q.win_wait, 3) if q.win_wait is not None else None,
            "slot_w": round(q.slot_w, 2) if q.slot_w is not None else None, "slot_from": [list(d) for d in q.slot_from],
            "lock_at": q.lock_at, "x_final": q.x_final}


# ---- injuries, league-wide -------------------------------------------------------------------------------
SLEEPER_PLAYERS = SLEEPER + "/v1/players/nba"
INJURY_TTL = 10 * 60   # Sleeper's player list (every player's injury tag) is re-read this often: the depth charts stay live
OUT_TAGS = {"Out", "IR", "Sus", "Doubtful"}   # red; any other tag (Questionable, GTD, DTD, Probable) is yellow


def sleeper_injuries(fetch: Fetch) -> dict[str, dict]:
    """Every NBA player Sleeper tags as hurt right now: sleeper id -> {sid, name, team, pos, status, group, body, note,
    starter (first on Sleeper's depth chart at his spot)}.
    group "out" (Out, IR, suspended, doubtful) or "q" (questionable / game-time / day-to-day). Colours the depth
    charts' names and fills the Team card's Injuries tab and the News tab's teams report; {} if Sleeper fails."""
    try:
        feed = fetch(SLEEPER_PLAYERS, INJURY_TTL) or {}
    except Exception:   # a depth chart must still show without it
        return {}
    return {sid: {"sid": sid, "name": p.get("full_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                  "team": p["team"], "pos": p.get("fantasy_positions") or [], "status": p["injury_status"],
                  "group": "out" if p["injury_status"] in OUT_TAGS else "q",
                  "body": p.get("injury_body_part"), "note": p.get("injury_notes"), "starter": p.get("depth_chart_order") == 1}
            for sid, p in feed.items() if p.get("injury_status") and p.get("team")}


def injury_report(hurt: dict[str, dict]) -> list[dict]:
    """The News tab's teams report: every team with an injured player, most starters out first (then starters
    questionable, then everyone out, then everyone hurt): {abbr, starters_out, starters_q, out, q, players: starters
    first, out before questionable}."""
    teams: dict[str, list[dict]] = {}
    for h in hurt.values():
        teams.setdefault(h["team"], []).append(h)
    count = lambda ps, group, starter=False: sum(h["group"] == group and (h.get("starter") or not starter) for h in ps)
    return sorted(({"abbr": t, "starters_out": count(ps, "out", True), "starters_q": count(ps, "q", True),
                    "out": count(ps, "out"), "q": count(ps, "q"),
                    "players": sorted(ps, key=lambda h: (not h.get("starter"), h["group"] != "out", h["name"]))}
                   for t, ps in teams.items()),
                  key=lambda t: (-t["starters_out"], -t["starters_q"], -t["out"], -(t["out"] + t["q"]), t["abbr"]))


# ---- an NBA team's card ----------------------------------------------------------------------------------
TEAM_STAT_KEYS = ("pts", "reb", "ast", "stl", "blk", "to", "pf", "fgm", "fga", "ftm", "fta", "tpm", "tpa")


def team_schedule(schedule: list[dict], abbr: str) -> list[dict]:
    """The Team card's Schedule tab, from Sleeper's season schedule: every game in date order, home or away, the
    opponent and, once it's over, both scores and W / L."""
    out = []
    for g in sorted(schedule, key=lambda g: g["date"]):
        side = "home" if g["home"]["team"] == abbr else "away" if g["away"]["team"] == abbr else None
        if not side:
            continue
        other = g["away" if side == "home" else "home"]
        us, them = g[side].get("points"), other.get("points")
        over = g.get("status") == "complete" and us is not None and them is not None
        out.append({"date": g["date"], "home": side == "home", "opp": other["team"], "status": g.get("status"),
                    "pts": us, "opp_pts": them, "result": ("W" if us > them else "L") if over else None})
    return out


def team_player_stats(session, rows: list[dict], done: set[str], abbr: str) -> list[dict]:
    """The Team card's Stats tab: every player's per-game line for this team (Sleeper's per-game rows, finished games
    only; a traded player counts only his games here): MIN PTS REB AST FG% FT% 3P% STL BLK TO PF, most minutes first.
    His current roster too, at 0 GP before they've played."""
    sums: dict[str, dict | None] = {}
    for e in rows:
        st = e.get("stats") or {}
        if (e.get("team") == abbr and e.get("game_id") in done and st.get("sp")
                and not str(e.get("player_id", "")).startswith("TEAM_")):
            sid = str(e["player_id"])
            s = sums[sid] = sums.get(sid) or dict.fromkeys(("gp", "sp") + TEAM_STAT_KEYS, 0.0)
            s["gp"] += 1
            s["sp"] += float(st["sp"])
            for k in TEAM_STAT_KEYS:
                s[k] += float(st.get(k) or 0)
    for r in session.players.values():
        if r.team_abbr == abbr and r.sleeper_id:
            sums.setdefault(r.sleeper_id, None)
    by_sid = {r.sleeper_id: (pid, r) for pid, r in session.players.items() if r.sleeper_id}
    out = []
    for sid, s in sums.items():
        if sid not in by_sid:   # not in the player pool: no name or position to show
            continue
        pid, r = by_sid[sid]
        ov = session.overrides.get(pid)
        row = {"player_id": pid, "sleeper_id": sid, "name": r.full_name, "pos": list(ov.eligibility) if ov else [], "gp": int(s["gp"]) if s else 0}
        if s:
            g = s["gp"]
            pct = lambda m, a: round(100 * s[m] / s[a], 1) if s[a] else None
            row.update({"min": round(s["sp"] / 60 / g, 1), **{k: round(s[k] / g, 1) for k in ("pts", "reb", "ast", "stl", "blk", "to", "pf")},
                        "fg_pct": pct("fgm", "fga"), "ft_pct": pct("ftm", "fta"), "tp_pct": pct("tpm", "tpa")})
        out.append(row)
    return sorted(out, key=lambda x: (-(x.get("min") or 0), x["name"]))


def team_news(session, fetch: Fetch, abbr: str) -> list[dict]:
    """The Team card's News tab: the News tab's notes (player_news, RotoWire via Sleeper) on every player of this
    team, newest first. One request per player, in parallel, cached NEWS_TTL."""
    from concurrent.futures import ThreadPoolExecutor

    hurt = sleeper_injuries(fetch)
    roster = [(pid, r) for pid, r in session.players.items() if r.team_abbr == abbr and r.sleeper_id]
    with ThreadPoolExecutor(8) as pool:
        notes = list(pool.map(lambda x: player_news(fetch, x[1].sleeper_id), roster))
    out = [{**n, "sid": r.sleeper_id, "player_id": pid, "name": r.full_name, "team": abbr,
            "injury_tag": (hurt.get(r.sleeper_id) or {}).get("status"), "injury_note": (hurt.get(r.sleeper_id) or {}).get("body")}
           for (pid, r), ns in zip(roster, notes) for n in ns]
    return sorted(out, key=lambda n: n["published"] or "", reverse=True)


# ---- one player's season page --------------------------------------------------------------------------
SLEEPER_NEWS = "https://api.sleeper.com/players/nba/{}/news"   # undocumented: the feed the Sleeper app shows
NEWS_TTL = 15 * 60
GAME_LOG = 10


# RotoWire tags the player's condition after his name, "Edey (ankle)"; rest and personal days aren't injuries.
# ponytail: keyword heuristic, a note on a healthy player that recaps an old injury also counts
INJURY_TAG = re.compile(r"\((?!rest\)|personal\))[a-z][a-z /-]*\)")
INJURY_WORD = re.compile(r"injur|illness|sore|sprain|strain|tear\b|torn|surgery|fractur|concussion|achilles|out indefinitely", re.I)


def player_news(fetch: Fetch, sid: str) -> list[dict]:
    """Latest fantasy notes (RotoWire, FantasyPros) on one player, from the feed the Sleeper app shows; [] if it fails."""
    try:
        feed = fetch(SLEEPER_NEWS.format(sid), NEWS_TTL) or []
    except Exception:   # undocumented endpoint: one bad player must not sink the whole tab
        return []
    out = []
    for a in feed:
        m = a.get("metadata") or {}
        if not m.get("title"):
            continue
        text = f"{m['title']} {m.get('description') or ''}"
        out.append({"published": datetime.fromtimestamp(a["published"] / 1000, timezone.utc).isoformat() if a.get("published") else None,
                    "headline": m["title"].strip(), "story": (m.get("description") or "").strip(),
                    "injury": bool(INJURY_TAG.search(text) or INJURY_WORD.search(text))})
    return out[:4]


def season_news(view: dict, fetch: Fetch, free: list[str] = ()) -> dict:
    """The News tab: fantasy notes (RotoWire, via Sleeper) on every player of yours, then on every player the other teams
    roster, newest first. Sleeper's notes feed only works one player at a time (no league-wide feed), so this is one
    request per player, in parallel and cached NEWS_TTL: only the first load after a Sync pays for it. `free`: free
    agents to cover too (Sleeper's trending adds / drops; the view must hold them, week_view(extra=...))."""
    from concurrent.futures import ThreadPoolExecutor

    players = view["players"]
    owner = {sid: t for t in view["teams"] for sid in t["players"]}
    free = [s for s in dict.fromkeys(free) if s not in owner and (players.get(s) or {}).get("player_id")]

    def notes(sid: str) -> list[dict]:
        p, t = players[sid], owner.get(sid)
        return [{**n, "sid": sid, "player_id": p["player_id"], "name": p["name"], "team": p.get("team"),
                 "injury_tag": p.get("injury_tag"), "injury_note": p.get("injury_note"), "owner": t["name"] if t else None,
                 "user": (t.get("user") or t["name"]) if t else None}
                for n in player_news(fetch, sid)]
    sids = [s for s in [*owner, *free] if s in players and s not in RETIRED]
    with ThreadPoolExecutor(16) as ex:
        every = [n for ns in ex.map(notes, sids) for n in ns]
    every.sort(key=lambda n: n.get("published") or "", reverse=True)
    side = lambda n: "free" if n["sid"] not in owner else "mine" if owner[n["sid"]]["is_user"] else "league"   # noqa: E731
    return {k: [n for n in every if side(n) == k] for k in ("mine", "league", "free")}   # all of them: the tab filters


SLEEPER_TRENDING = SLEEPER + "/v1/players/nba/trending/{}?lookback_hours=24&limit=25"


def trending(fetch: Fetch) -> list[str]:
    """Sleeper ids most dropped then most added across Sleeper in the last day: the free agents whose news matters."""
    out = []
    for kind in ("drop", "add"):
        try:
            out += [str(t["player_id"]) for t in fetch(SLEEPER_TRENDING.format(kind), WEEK_TTL) or []]
        except Exception:   # news without free agents beats no news
            pass
    return out


def _last_season_draft(fetch: Fetch, prev_lid: str | None, sid: str) -> list[dict]:
    """His pick in the previous season's draft of this league (Sleeper's previous_league_id): price, team, draft date."""
    if not prev_lid:
        return []
    prev = fetch(f"{SLEEPER}/v1/league/{prev_lid}", WEEK_TTL) or {}
    draft_id = prev.get("draft_id")
    pk = next((p for p in (fetch(f"{SLEEPER}/v1/draft/{draft_id}/picks", WEEK_TTL) or []) if p.get("player_id") == sid), None) if draft_id else None
    if not pk:
        return []
    users = {u["user_id"]: u.get("display_name") for u in fetch(f"{SLEEPER}/v1/league/{prev_lid}/users", WEEK_TTL) or []}
    owner = {r["roster_id"]: users.get(r.get("owner_id")) for r in fetch(f"{SLEEPER}/v1/league/{prev_lid}/rosters", WEEK_TTL) or []}
    amount = (pk.get("metadata") or {}).get("amount")
    return [{"kind": "drafted", "team": owner.get(pk.get("roster_id")), "price": int(amount) if amount else None,
             "when": (fetch(f"{SLEEPER}/v1/draft/{draft_id}", WEEK_TTL) or {}).get("start_time"), "season": prev.get("season")}]


def acquisitions(session, fetch: Fetch, view: dict, sid: str) -> list[dict]:
    """How he changed hands this season: the draft (auction price, keeper flag) from Sleeper's draft picks, then every
    completed transaction in order: waiver claims (FAAB bid), free-agent pickups, trades (to whom) and drops."""
    lid = session.league.sleeper_league_id
    team = {t["roster_id"]: t.get("user") or t["name"] for t in view["teams"]}   # usernames, not team names
    out = []
    league = fetch(f"{SLEEPER}/v1/league/{lid}", WEEK_TTL) or {}
    draft_id = league.get("draft_id")
    drafted_at = (fetch(f"{SLEEPER}/v1/draft/{draft_id}", DAY_TTL) or {}).get("start_time") if draft_id else None
    for pk in (fetch(f"{SLEEPER}/v1/draft/{draft_id}/picks", DAY_TTL) or []) if draft_id else []:
        if pk.get("player_id") == sid:
            amount = (pk.get("metadata") or {}).get("amount")
            if pk.get("is_keeper"):   # a keeper: what he went for in last season's draft first
                out += _last_season_draft(fetch, league.get("previous_league_id"), sid)
            out.append({"kind": "keeper" if pk.get("is_keeper") else "drafted", "team": team.get(pk.get("roster_id")),
                        "price": int(amount) if amount else None, "when": drafted_at})
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


TEAM_STATS = ("pts", "reb", "ast", "blk", "stl", "tpm", "fga", "to")   # the team ranks' stats (Sleeper's keys)


def team_ranks(rows: list[dict], team: str, done: set[str]) -> dict | None:
    """One NBA team's per-game offense (its own box scores) and defense (what its opponents put up against it), each
    stat ranked among every team (1 = best: most made, fewest allowed; turnovers the other way round). From Sleeper's
    per-game TEAM_ rows (stats/nba/{year}/{week}); the Sleeper app shows these ranks, its API sends only the totals.
    done: the schedule's finished game ids; a game in progress would count its half box score as a whole game.
    {games, teams, offense: {stat: {v, rank}}, defense: {...}} or None before his team has played."""
    sums = {"offense": {}, "defense": {}}
    games = {"offense": {}, "defense": {}}
    for e in rows:
        if not str(e.get("player_id", "")).startswith("TEAM_") or not e.get("opponent") or e.get("game_id") not in done:
            continue
        for side, t in (("offense", e["team"]), ("defense", e["opponent"])):   # his box score is what the opponent allowed
            s = sums[side].setdefault(t, {})
            for k in TEAM_STATS:
                s[k] = s.get(k, 0.0) + float((e.get("stats") or {}).get(k) or 0)
            games[side][t] = games[side].get(t, 0) + 1
    if team not in sums["offense"]:
        return None
    out = {"games": games["offense"][team], "teams": len(sums["offense"])}
    for side in ("offense", "defense"):
        per = {t: {k: v / games[side][t] for k, v in s.items()} for t, s in sums[side].items()}
        out[side] = {}
        for k in TEAM_STATS:
            more_is_better = (k == "to") == (side == "defense")   # offense: more, but fewer turnovers; defense: the reverse
            mine = per[team][k]
            better = sum(1 for t in per if (per[t][k] > mine if more_is_better else per[t][k] < mine))
            out[side][k] = {"v": round(mine, 1), "rank": better + 1}   # ties share a rank
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
                        "ast": st.get("ast"), "stl": st.get("stl"), "blk": st.get("blk"), "to": st.get("to"),
                        "pf": st.get("pf"), "pm": st.get("plus_minus")})
        if len(log) >= GAME_LOG:
            break

    # every game his team plays this season (Sleeper's schedule), his box score where he played (the weeks' logs above
    # only go back GAME_LOG games, so this reads every past week): the Game log tab, and the Summary's averages
    team_abbr = me.get("team") or rec.team_abbr
    played, season_rows = {}, []
    for w in range(1, view["week"] + 1):
        rows = fetch(f"{SLEEPER}/stats/nba/{year}/{w}?season_type=regular", LIVE_TTL if w == view["week"] else DAY_TTL) or []
        season_rows += rows
        for e in rows:
            if str(e.get("player_id")) == sid and (e.get("stats") or {}).get("sp"):
                played[e["date"]] = e["stats"]
    season_log, schedule = [], fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or []
    for g in sorted(schedule, key=lambda g: g["date"]):
        side = "home" if g["home"]["team"] == team_abbr else "away" if g["away"]["team"] == team_abbr else None
        if not side:
            continue
        other = g["away" if side == "home" else "home"]
        st = played.get(g["date"])
        row = {"week": int(g["week"]), "date": g["date"], "opp": other["team"], "home": side == "home", "status": g.get("status"),
               "team_pts": g[side].get("points"), "opp_pts": other.get("points")}
        if st:
            row.update({"fp": round(actual_fp(st, session.league.scoring), 2), "min": round(float(st.get("sp") or 0) / 60, 1),
                        **{k: int(st.get(k) or 0) for k in ("pts", "reb", "ast", "stl", "blk", "to", "pf")},
                        "pm": int(st.get("plus_minus") or 0)})
        season_log.append(row)
    games_played = [r for r in season_log if "fp" in r]
    done = [r for r in games_played if r["status"] == "complete"]   # averages: finished games only (not a half-played one)
    averages = {k: round(sum(r[k] for r in done) / len(done), 2 if k == "fp" else 1) for k in ("min", "pts", "reb", "ast", "stl", "blk", "to", "fp")} \
        if done else None
    # his latest game (live or last final), with both teams' scores; this week's from ESPN (quarter + clock)
    last = games_played[-1] if games_played else None
    if last:
        wk = next((x for x in me.get("games", []) if x["date"] == last["date"]), None)
        last = {**last, "team": team_abbr, "state": wk["state"] if wk else "post", "detail": wk.get("detail") if wk else "Final",
                "team_pts": (wk or {}).get("score") or last["team_pts"], "opp_pts": (wk or {}).get("opp_score") or last["opp_pts"],
                # ESPN's game id, so the box opens that game's card: this week's games carry it, older ones from that day's scoreboard
                "event": (wk or {}).get("event") or (espn_day(fetch, last["date"], date.fromisoformat(view["today"])).get(team_abbr) or {}).get("event")}
    research = (fetch(f"{SLEEPER}/players/nba/research/regular/{year}/{view['week']}", WEEK_TTL) or {}).get(sid) or {}

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
            "team_ranks": team_ranks(season_rows, team_abbr, {g.get("game_id") for g in schedule if g.get("status") == "complete"})
            if team_abbr else None,
            "acquired": acquisitions(session, fetch, view, sid),
            "season_log": season_log, "averages": averages, "games_played": len(done), "last_game": last,
            "owned": research.get("owned"), "started": research.get("started"),
            "news": player_news(fetch, sid)}


# ---- waivers ---------------------------------------------------------------------------------------------
FAAB_TOTAL = 100   # fallback only: the budget comes from the league's settings (waiver_budget)
WAIVER_TYPES = {0: "rolling", 1: "reverse standings", 2: "FAAB"}   # Sleeper settings.waiver_type
WAIVER_SHOW = 12
# ponytail: bid = share of FAAB left that grows with the upgrade over your weakest player (8 value points = 60 %);
# no data on rivals' bids, so it is a guide, not a price.


# When claims process: the league's waiver_days / waiver_hour (Settings tab); Sleeper's daily_waivers_days bitmask
# is undocumented, so the days are set by hand
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
AVG_STATS = ("pts", "reb", "ast", "stl", "blk", "tpm", "to")


def next_waiver_run(now: datetime, days: list[int], hour: int) -> datetime:
    """The next time claims process after `now` (aware, league time): one of `days` (Mon = 0) at `hour`."""
    for d in range(8):
        t = (now + timedelta(days=d)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if t.weekday() in days and t > now:
            return t
    raise ValueError("no waiver run day set")


def season_averages(rows: list[dict], sids: set[str], done: set[str], scoring) -> dict[str, dict]:
    """Per-game averages over his finished games (done: the schedule's complete game ids; a game in progress would
    count its first half as a whole game) from Sleeper's per-game rows: FP in the league's scoring and AVG_STATS."""
    sums: dict[str, dict] = {}
    for e in rows:
        sid, st = str(e.get("player_id")), e.get("stats") or {}
        if sid in sids and st.get("sp") and e.get("game_id") in done:
            s = sums.setdefault(sid, dict.fromkeys(("gp", "fp") + AVG_STATS, 0.0))
            s["gp"] += 1
            s["fp"] += actual_fp(st, scoring)
            for k in AVG_STATS:
                s[k] += float(st.get(k) or 0)
    return {sid: {"gp": int(s["gp"]), "fp": round(s["fp"] / s["gp"], 2), **{k: round(s[k] / s["gp"], 1) for k in AVG_STATS}}
            for sid, s in sums.items()}


def waivers(session, fetch: Fetch, view: dict) -> dict:
    """Free agents worth claiming: rest-of-season value (the draft value: projection, Lock-In ceiling, availability),
    his season averages, the games he plays once he lands (claims process at the next waiver run, the league's
    waiver_days at waiver_hour: this week's games after it and next week's), the player of yours to drop and a
    suggested blind bid."""
    waiver = view.get("waiver")
    if waiver is None:
        return {"error": "Couldn't receive Sleeper waiver and FAAB data.", "claims": []}
    tz = ZoneInfo(view.get("tz") or "America/Chicago")
    lg = session.league
    run = next_waiver_run(datetime.fromisoformat(view["now"]).astimezone(tz) if view.get("now") else datetime.now(tz),
                          lg.waiver_days, lg.waiver_hour)
    lands = run.date().isoformat()
    year, week = session.league.roster_season.split("-")[0], view["week"]
    schedule = fetch(f"{SLEEPER}/schedule/nba/regular/{year}", DAY_TTL) or []
    after: dict[tuple[str, int], int] = {}   # (team, week) -> his games on or after the day he lands
    for g in schedule:
        if g["date"] >= lands and int(g["week"]) in (week, week + 1):
            for side in ("home", "away"):
                key = (g[side]["team"], int(g["week"]))
                after[key] = after.get(key, 0) + 1
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
    faab = waiver["type"] == "FAAB"
    faab_left = budget - (me.get("faab_used") or 0)
    floor = drop.value if drop else 0.0   # only real upgrades over your weakest player
    shown = sorted((pid for pid in fa_ids if pid in rows and rows[pid].value > floor), key=lambda pid: -rows[pid].value)[:WAIVER_SHOW]
    stat_rows = [e for w in range(1, week + 1)
                 for e in fetch(f"{SLEEPER}/stats/nba/{year}/{w}?season_type=regular", LIVE_TTL if w == week else DAY_TTL) or []]
    done = {g.get("game_id") for g in schedule if g.get("status") == "complete"}
    avg = season_averages(stat_rows, {rows[pid].sleeper_id for pid in shown}, done, session.league.scoring)
    out = []
    for pid in shown:
        r = rows[pid]
        up = r.value - (drop.value if drop else 0)
        bid = (max(1, min(faab_left, round(faab_left * min(0.6, max(0.0, up) / 8 * 0.6)))) if up > 0 else 1) if faab else None
        out.append({"player_id": pid, "sleeper_id": r.sleeper_id, "name": r.full_name, "team": r.team_abbr,
                    "pos": r.eligibility, "value": round(r.value, 2), "proj_fpg": r.proj_fpts, "injury": r.injury_status,
                    "injury_tag": view.get("injury_tags", {}).get(r.sleeper_id), "season": avg.get(r.sleeper_id),
                    "games_left": after.get((r.team_abbr, week), 0), "games_next": after.get((r.team_abbr, week + 1), 0),
                    "upgrade": round(up, 2), "bid": bid})
    return {"faab_left": faab_left, "drop": {"player_id": drop.player_id, "sleeper_id": drop.sleeper_id, "name": drop.full_name,
                                             "value": round(drop.value, 2)} if drop else None,
            "claims": out, "budget": budget if faab else None, "type": waiver["type"],
            "next_run": run.isoformat(), "runs": [DAY_NAMES[d] for d in lg.waiver_days], "run_hour": lg.waiver_hour}
