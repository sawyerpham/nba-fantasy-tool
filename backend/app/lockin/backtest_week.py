"""Backtest of the week plan's inputs and win chance on finished weeks (weekplan.py).

Run from backend: python -m app.lockin.backtest_week [league_id]

  games     every projected game of a rotation player: did he play, and how far from Sleeper's projection he landed.
            Fits the one-game spread (swing_of) and the chance to play (PLAY_CHANCE, B2B_PLAY).
  lock rule every player week replayed game by game with the plan's own rule (lock a game that beats what waiting is
            worth): what the rule really banked against the wait value W it promised on Monday.
  matchups  each finished matchup replayed from Monday morning: every game still to come, the week planned for both
            teams, then the predicted totals and win chance against Sleeper's final score.

Sleeper serves projections, stats and matchups for past weeks; responses are cached under data/cache/backtest_live/.
ponytail: the lineup is the roster the week ended with (Sleeper keeps no Monday snapshot) and nobody carries an
injury tag (Sleeper keeps no history of those either), so the matchup replay runs a little rosier than Monday really was.
"""

from __future__ import annotations

import math
import sys

import requests

from ..main import build_default_state
from .backtest_live import cached
from .service import SLEEPER, _slot_counts, actual_fp, projected_fp
from .weekplan import MAX_SWING, MIN_GAMES_FOR_SWING, MIN_SWING, Game, PlanPlayer, plan_week, swing_of, team_total, wait_value, win_chance

MIN_PROJ_MIN = 15.0   # rotation players only: the ones a lineup call is about


def raw_cv(per_game: list[float]) -> float | None:
    """Last season's std / mean of a player's per-game FP, clamped like swing_of but unscaled; None with too few games."""
    m = sum(per_game) / len(per_game) if per_game else 0.0
    if len(per_game) < MIN_GAMES_FOR_SWING or m <= 0:
        return None
    return min(MAX_SWING, max(MIN_SWING, math.sqrt(sum((f - m) ** 2 for f in per_game) / len(per_game)) / m))


def rms(xs: list[float]) -> float:
    """Root mean square (0 for an empty list)."""
    return math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else 0.0


def load(league_id: str) -> dict:
    """Everything the reports need: the session, the finished weeks' projections, stats and matchups, the schedule."""
    session = build_default_state().get_session(league_id)
    lg = session.league
    year, lid = lg.roster_season.split("-")[0], lg.sleeper_league_id
    get = lambda name, url: cached(name, lambda: requests.get(url, timeout=30).json())   # noqa: E731
    now = requests.get(f"{SLEEPER}/v1/state/nba", timeout=30).json()["week"]
    weeks = list(range(1, now))   # finished weeks only: they never change, so they cache
    return {"session": session, "weeks": weeks,
            "schedule": get(f"wk_schedule_{year}_{now}.json", f"{SLEEPER}/schedule/nba/regular/{year}"),
            "league": get(f"wk_league_{lid}_{now}.json", f"{SLEEPER}/v1/league/{lid}"),
            "proj": {w: get(f"wk_proj_{year}_{w}.json", f"{SLEEPER}/projections/nba/{year}/{w}?season_type=regular") for w in weeks},
            "stats": {w: get(f"wk_stats_{year}_{w}.json", f"{SLEEPER}/stats/nba/{year}/{w}?season_type=regular") for w in weeks},
            "matchups": {w: get(f"wk_matchups_{lid}_{w}.json", f"{SLEEPER}/v1/league/{lid}/matchups/{w}") for w in weeks}}


def game_rows(d: dict) -> list[dict]:
    """One row per projected game of a rotation player: projection, result (None = didn't play), swing, back-to-back."""
    session = d["session"]
    scoring = session.league.scoring
    by_sleeper = {r.sleeper_id: r for r in session.players.values() if r.sleeper_id}
    played_on = {(g["date"], g[side]["team"]) for g in d["schedule"] for side in ("home", "away")}
    from datetime import date, timedelta
    out = []
    for w in d["weeks"]:
        stats = {(str(e["player_id"]), e["date"]): e.get("stats") or {} for e in d["stats"][w] or []}
        for e in d["proj"][w] or []:
            sid, st = str(e["player_id"]), e.get("stats") or {}
            rec = by_sleeper.get(sid)
            if rec is None or float(st.get("sp") or 0) / 60 < MIN_PROJ_MIN:
                continue
            val = session.valuations.get(rec.player_id)
            proj = projected_fp(st, scoring, val.bonus_fpts_per_game if val else 0.0)
            got = stats.get((sid, e["date"]))
            played = bool(got and (got.get("sp") or got.get("gp")))
            day_before = (date.fromisoformat(e["date"]) - timedelta(days=1)).isoformat()
            out.append({"week": w, "sid": sid, "date": e["date"], "proj": proj, "fp": actual_fp(got, scoring) if played else None,
                        "cv": raw_cv(val.per_game_fpts) if val else None, "swing": swing_of(val.per_game_fpts if val else []),
                        "b2b": (day_before, e.get("team")) in played_on})
    return out


def report_games(rows: list[dict]) -> None:
    """The one-game spread against swing_of, Sleeper's projection bias, and how often a projected player played."""
    played = [r for r in rows if r["fp"] is not None and r["proj"] > 5]
    print(f"{len(rows)} projected rotation games, {len(played)} played with a projection over 5 FP\n")
    print("one-game spread, as a share of the projection: (actual - proj) / proj")
    rel = [(r["fp"] - r["proj"]) / r["proj"] for r in played]
    print(f"  all            n={len(rel):5}  bias {sum(rel) / len(rel):+.3f}  spread {rms(rel):.3f}")
    hist = [r for r in played if r["cv"] is not None]
    new = [r for r in played if r["cv"] is None]
    print(f"  no history     n={len(new):5}  spread {rms([(r['fp'] - r['proj']) / r['proj'] for r in new]):.3f}   (DEFAULT_SWING x SWING_SCALE should match)")
    fit = rms([(r["fp"] - r["proj"]) / (r["proj"] * r["cv"]) for r in hist])
    print(f"  with history   n={len(hist):5}  spread / last season's std-over-mean = {fit:.3f}   (SWING_SCALE should match)")
    for lo, hi in ((0, 0.3), (0.3, 0.4), (0.4, 0.5), (0.5, 9)):
        sub = [r for r in hist if lo <= r["cv"] < hi]
        if sub:
            print(f"    std/mean {lo:.1f}-{min(hi, MAX_SWING):.1f}  n={len(sub):5}  ratio {rms([(r['fp'] - r['proj']) / (r['proj'] * r['cv']) for r in sub]):.3f}")
    z = rms([(r["fp"] - r["proj"]) / (r["proj"] * r["swing"]) for r in played])
    print(f"  the code's swing_of: actual spread / predicted spread = {z:.3f}   (1.0 = calibrated)\n")
    print("played, of projected rotation games")
    for label, sub in (("all", rows), ("back-to-back 2nd night", [r for r in rows if r["b2b"]]), ("other nights", [r for r in rows if not r["b2b"]])):
        print(f"  {label:<24} n={len(sub):5}  played {sum(r['fp'] is not None for r in sub) / len(sub):.3f}")
    print()


def report_policy(rows: list[dict]) -> None:
    """Replay the lock rule on every player week: lock the first game that beats the wait value of the games after it
    (his last game counts whatever it is, a missed one 0). Predicted = wait_value on Monday; banked = what that got."""
    weeks: dict[tuple[int, str], list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["date"]):
        weeks.setdefault((r["week"], r["sid"]), []).append(r)
    out = []
    for games in weeks.values():
        plan = [Game(date=g["date"], proj=g["proj"], b2b=g["b2b"]) for g in games]
        swing, banked = games[0]["swing"], 0.0
        for i, g in enumerate(games):
            if g["fp"] is None:
                continue
            if i == len(games) - 1 or g["fp"] >= wait_value(plan[i + 1:], swing, "healthy"):
                banked = g["fp"]
                break
        out.append((len(games), wait_value(plan, swing, "healthy"), banked, sum(g["proj"] for g in games) / len(games)))
    print("lock rule replayed on every player week: W promised on Monday against what the rule banked")
    for n in sorted({o[0] for o in out}):
        sub = [o for o in out if o[0] == n]
        print(f"  {n} games  n={len(sub):4}  avg projection {sum(o[3] for o in sub) / len(sub):5.2f}  W {sum(o[1] for o in sub) / len(sub):5.2f}  banked {sum(o[2] for o in sub) / len(sub):5.2f}")
    print(f"  all      n={len(out):4}  W {sum(o[1] for o in out) / len(out):5.2f}  banked {sum(o[2] for o in out) / len(out):5.2f}"
          f"  spread of (banked - W) {rms([o[2] - o[1] for o in out]):.2f}\n")


def matchup_rows(d: dict) -> list[dict]:
    """One row per finished matchup: both teams' predicted (mean, variance) on Monday, the win chance, the real scores."""
    session = d["session"]
    scoring = session.league.scoring
    positions = d["league"]["roster_positions"]
    counts = _slot_counts(positions)
    by_sleeper = {r.sleeper_id: r for r in session.players.values() if r.sleeper_id}
    out = []
    for w in d["weeks"]:
        proj: dict[str, list[tuple[str, dict]]] = {}
        for e in d["proj"][w] or []:
            proj.setdefault(str(e["player_id"]), []).append((e["date"], e.get("stats") or {}))

        def team(side: dict) -> tuple[float, float]:
            """A team's predicted (mean, variance) with every game of the week still to come."""
            players = []
            for sid in side.get("players") or []:
                rec = by_sleeper.get(sid)
                val = session.valuations.get(rec.player_id) if rec else None
                ov = session.overrides.get(rec.player_id) if rec else None
                starters = side.get("starters") or []
                slot = positions[starters.index(sid)] if sid in starters and starters.index(sid) < len(positions) else "BN"
                games = [Game(date=day, proj=projected_fp(st, scoring, val.bonus_fpts_per_game if val else 0.0))
                         for day, st in sorted(proj.get(sid, []), key=lambda x: x[0])]
                players.append(PlanPlayer(sid=sid, name=rec.full_name if rec else sid, eligibility=list(ov.eligibility) if ov else [],
                                          slot=slot, games=games, swing=swing_of(val.per_game_fpts if val else [])))
            plan_week(players, counts)
            return team_total(players)

        pairs: dict[int, list[dict]] = {}
        for m in d["matchups"][w] or []:
            if m.get("matchup_id"):
                pairs.setdefault(m["matchup_id"], []).append(m)
        for a, b in (p for p in pairs.values() if len(p) == 2):
            ta, tb = team(a), team(b)
            out.append({"week": w, "a": ta, "b": tb, "pa": a["points"], "pb": b["points"], "win": win_chance(ta, tb)})
    return out


def report_matchups(rows: list[dict]) -> None:
    """Predicted totals against the real ones (bias, spread), and the win chance against who won (Brier, buckets)."""
    teams = [(r[k][0], math.sqrt(r[k][1]), r[p]) for r in rows for k, p in (("a", "pa"), ("b", "pb"))]
    err = [real - mean for mean, _, real in teams]
    bias = sum(err) / len(err)
    print(f"{len(rows)} matchups, {len(teams)} team weeks")
    print(f"  team total: predicted {sum(m for m, _, _ in teams) / len(teams):.1f}  real {sum(r for _, _, r in teams) / len(teams):.1f}  bias {bias:+.1f}")
    print(f"  predicted spread {sum(s for _, s, _ in teams) / len(teams):.1f}  real spread around the prediction {rms([e - bias for e in err]):.1f} (bias removed)")
    print(f"  z = (real - predicted) / predicted spread: spread of z {rms([(e - bias) / s for e, (_, s, _) in zip(err, teams)]):.2f} with the bias removed (1.0 = calibrated), {rms([e / s for e, (_, s, _) in zip(err, teams)]):.2f} as is")
    # the margin: the two teams' biases cancel, so this is the cleanest read of the win chance's spread
    zm = [((r["pa"] - r["pb"]) - (r["a"][0] - r["b"][0])) / math.sqrt(r["a"][1] + r["b"][1]) for r in rows]
    print(f"  margin z = (real margin - predicted margin) / predicted spread: {rms(zm):.2f}   (1.0 = calibrated)")
    won = [(r["win"], 1.0 if r["pa"] > r["pb"] else 0.0) for r in rows]
    print(f"  win chance: Brier {sum((p - y) ** 2 for p, y in won) / len(won):.3f}   (0.25 = coin flip, lower is better)")
    fav = [(max(p, 1 - p), y if p >= 0.5 else 1 - y) for p, y in won]   # from the favourite's side
    for lo, hi in ((0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)):
        sub = [(p, y) for p, y in fav if lo <= p < hi]
        if sub:
            print(f"    favourite at {lo:.0%}-{min(hi, 1):.0%}  n={len(sub):3}  predicted {sum(p for p, _ in sub) / len(sub):.2f}  won {sum(y for _, y in sub) / len(sub):.2f}")


if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else "tobedecided")
    report_games(game_rows(data))
    report_policy(game_rows(data))
    report_matchups(matchup_rows(data))
