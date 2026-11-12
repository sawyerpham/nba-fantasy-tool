"""Backtest of live_estimate (weekplan.py): replay finished games at fixed points on the game clock and compare the
estimated finish with the real final, then fit PRIOR_MINUTES (the weight of his projected rate against tonight's).

Run from backend: python -m app.lockin.backtest_live [league_id]
Box scores as of each checkpoint come from nba_api (BoxScoreTraditionalV3, range_type=2 = up to a game-clock time),
projections from Sleeper's weekly feed (still served for past weeks). Responses are cached under
data/cache/backtest_live/ so a rerun only fetches new games.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

import requests

import app.lockin.weekplan as weekplan
from nba_fantasy_shared.models.players import GameLine
from nba_fantasy_shared.scoring.formula import score_game
from nba_fantasy_shared.storage import JsonStore

from .. import config
from ..core.services.league_repository import LeagueRepository
from .service import SLEEPER, projected_fp
from .weekplan import Game, live_estimate

CHECKPOINTS = (12, 24, 36, 42)   # minutes of game clock elapsed: end of Q1, half, end of Q3, midway through Q4
MIN_PROJ_MIN = 15.0              # only rotation players: the ones a lineup call is about
DATA = Path(config.DEFAULT_DATA_DIR)
CACHE = DATA / "cache" / "backtest_live"


def cached(name: str, get):
    """JSON from CACHE/name, else get() saved there (finished games never change)."""
    path = CACHE / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    data = get()
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def nba(endpoint, **kw) -> dict:
    """One nba_api call, retried, paced so stats.nba.com doesn't throttle us."""
    for attempt in range(4):
        try:
            time.sleep(0.6)
            return endpoint(timeout=30, **kw).get_dict()
        except Exception:  # noqa: BLE001 - stats.nba.com times out at random; retry
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def box(game_id: str, upto_min: int | None) -> dict[int, dict]:
    """personId -> stat line for one game, as of `upto_min` minutes of game clock (None = final)."""
    from nba_api.stats.endpoints import boxscoretraditionalv3 as b

    def get():
        kw = {} if upto_min is None else dict(start_period=0, end_period=0, range_type=2, start_range=0,
                                                end_range=upto_min * 600)   # tenths of a second
        bt = nba(b.BoxScoreTraditionalV3, game_id=game_id, **kw)["boxScoreTraditional"]
        return {str(p["personId"]): p["statistics"] for side in ("homeTeam", "awayTeam") for p in bt[side]["players"]}
    return {int(k): v for k, v in cached(f"box_{game_id}_{upto_min or 'final'}.json", get).items()}


def game_ids(day: str) -> list[str]:
    """NBA game ids played on a date."""
    from nba_api.stats.endpoints import scoreboardv3

    def get():
        return [g["gameId"] for g in nba(scoreboardv3.ScoreboardV3, game_date=day)["scoreboard"]["games"]]
    return cached(f"games_{day}.json", get)


def minutes(s: dict) -> float:
    """'27:31' -> 27.52."""
    m = s.get("minutes") or ""
    if ":" not in m:
        return 0.0
    mm, ss = m.split(":")
    return int(mm) + int(ss) / 60


def fp(s: dict, scoring) -> float:
    """An nba_api stat line in league fantasy points."""
    line = GameLine(player_id=0, season="", game_id="", game_date=date(2000, 1, 1), team_abbr="", opponent_abbr="",
                    home=False, minutes=minutes(s), pts=s["points"], reb=s["reboundsTotal"], ast=s["assists"],
                    stl=s["steals"], blk=s["blocks"], tov=s["turnovers"], fgm=s["fieldGoalsMade"],
                    fga=s["fieldGoalsAttempted"], ftm=s["freeThrowsMade"], fta=s["freeThrowsAttempted"],
                    fg3m=s["threePointersMade"], fg3a=s["threePointersAttempted"], oreb=s["reboundsOffensive"],
                    dreb=s["reboundsDefensive"], pf=s["foulsPersonal"], plus_minus=int(s["plusMinusPoints"] or 0))
    return score_game(line, scoring).fpts


def samples(league_id: str) -> list[dict]:
    """One row per (player game, checkpoint) he had played in by then: projection, minutes and FP then, and final."""
    lg = LeagueRepository(JsonStore(DATA)).load(league_id).league
    year = lg.roster_season.split("-")[0]
    recs = json.loads((DATA / "cache" / f"reconcile_{lg.roster_season}.json").read_text(encoding="utf-8"))["records"]
    nba_id = {r["sleeper_id"]: r["player_id"] for r in recs if r.get("sleeper_id")}
    today = date.today().isoformat()
    proj: dict[tuple[int, str], dict] = {}
    for week in range(1, 30):
        rows = requests.get(f"{SLEEPER}/projections/nba/{year}/{week}?season_type=regular", timeout=30).json() or []
        rows = [e for e in rows if e["date"] < today]
        if not rows:
            break
        for e in rows:
            if str(e["player_id"]) in nba_id and (e.get("stats") or {}).get("sp"):
                proj[(nba_id[str(e["player_id"])], e["date"])] = e["stats"]
    out = []
    for day in sorted({d for _, d in proj}):
        for gid in game_ids(day):
            final = box(gid, None)
            at = {m: box(gid, m) for m in CHECKPOINTS}
            for pid, s in final.items():
                p = proj.get((pid, day))
                if not p or minutes(s) == 0:
                    continue
                proj_min = p["sp"] / 60
                if proj_min < MIN_PROJ_MIN:
                    continue
                for m in CHECKPOINTS:
                    sm = at[m].get(pid)
                    if not sm or minutes(sm) == 0:
                        continue
                    out.append({"day": day, "pid": pid, "at": m, "proj": projected_fp(p, lg.scoring),
                                "proj_min": proj_min, "fp_at": fp(sm, lg.scoring), "min_at": minutes(sm),
                                "final": fp(s, lg.scoring), "min_final": minutes(s)})
    return out


def estimate(r: dict, prior: float) -> float:
    """live_estimate for a sample with PRIOR_MINUTES set to `prior`."""
    weekplan.PRIOR_MINUTES = prior
    period, into = divmod(r["at"], 12)
    g = Game(date=r["day"], proj=r["proj"], fp=r["fp_at"], started=True, live=True, min=r["min_at"],
             proj_min=r["proj_min"], period=period + 1, clock=(12 - into) * 60.0)
    return live_estimate(g)


def report(rows: list[dict]) -> None:
    """Bias / MAE by checkpoint for the current prior and a grid of priors, plus the minutes-left bias."""
    current = weekplan.PRIOR_MINUTES
    games = {(r["day"], r["pid"]) for r in rows}
    print(f"{len(games)} player games, {len(rows)} checkpoints\n")
    grid = (0, 5, 10, 15, 20, 30, 40, 60, 80, 120, 1e9)
    print("prior  " + "  ".join(f"{m:>2}' bias   MAE" for m in CHECKPOINTS) + "   all MAE")
    for prior in grid:
        cells, tot = [], 0.0
        for m in CHECKPOINTS:
            sub = [r for r in rows if r["at"] == m]
            err = [estimate(r, prior) - r["final"] for r in sub]
            tot += sum(abs(e) for e in err)
            cells.append(f"{sum(err) / len(err):+8.2f} {sum(abs(e) for e in err) / len(err):5.2f}")
        label = "proj" if prior >= 1e9 else f"{prior:g}"
        print(f"{label:>5}  " + "  ".join(cells) + f"   {tot / len(rows):6.3f}" + ("   <- now" if prior == current else ""))
    weekplan.PRIOR_MINUTES = current
    print(f"\nminutes left: predicted (proj_min x share left x {weekplan.MINUTES_LEFT_SCALE}) vs actual")
    for m in CHECKPOINTS:
        sub = [r for r in rows if r["at"] == m]
        pred = sum(r["proj_min"] * (1 - m / 48) * weekplan.MINUTES_LEFT_SCALE for r in sub) / len(sub)
        real = sum(r["min_final"] - r["min_at"] for r in sub) / len(sub)
        print(f"  {m:>2}': predicted {pred:5.1f}  actual {real:5.1f}")


if __name__ == "__main__":
    report(samples(sys.argv[1] if len(sys.argv) > 1 else "tobedecided"))
