"""CLI: compute valuations from the cached game logs and print a sanity-check leaderboard.

    python -m app.valuate                 # default SPEC scoring, top 25 by blended value
    python -m app.valuate --top 40 --sort ceiling
    python -m app.valuate --player 203999 # one player's detail
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nba_fantasy_shared.models.league import RankingSettings
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.scoring import blended_value, confidence_factor
from nba_fantasy_shared.storage import JsonStore

from . import config
from .services.pull_service import load_records
from .services.valuation_service import ValuationService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute fantasy valuations from cached game logs")
    parser.add_argument("--data-dir", type=Path, default=config.DEFAULT_DATA_DIR)
    parser.add_argument("--stats-season", default=config.DEFAULT_STATS_SEASON)
    parser.add_argument("--roster-season", default=config.DEFAULT_ROSTER_SEASON)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--sort", choices=["value", "avg", "ceiling"], default="value")
    parser.add_argument("--player", type=int, default=None)
    parser.add_argument("--force", action="store_true", help="recompute even if cached")
    args = parser.parse_args(argv)

    store = JsonStore(args.data_dir)
    scoring = ScoringSettings()
    ranking = RankingSettings()
    service = ValuationService(store, args.stats_season)
    valuations = service.compute(scoring, force=args.force)
    names = {r.player_id: r for r in load_records(store, args.roster_season)}
    print(f"scoring hash {scoring.scoring_hash()} | {len(valuations)} players valued | cache {service.cache_rel(scoring)}")

    if args.player is not None:
        v = valuations.get(args.player)
        if v is None:
            print(f"no valuation for {args.player}")
            return 1
        rec = names.get(args.player)
        print(f"{rec.full_name if rec else args.player}: gp={v.games_played} avg={v.avg_fpts} best={v.best_game_fpts} "
              f"min={v.minutes_avg} teams={v.teams_played_for} bonuses={v.bonus_counts} "
              f"confidence={confidence_factor(v.games_played, ranking.min_games_full_confidence):.2f}")
        print("per game:", v.per_game_fpts)
        return 0

    keyfn = {
        "value": lambda v: blended_value(v, ranking),
        "avg": lambda v: v.avg_fpts,
        "ceiling": lambda v: v.best_game_fpts,
    }[args.sort]
    rows = sorted(valuations.values(), key=keyfn, reverse=True)[: args.top]
    print(f"{'#':>3} {'player':28} {'team':5} {'gp':>3} {'avg':>7} {'best':>7} {'conf':>5} {'value':>7}  bonuses")
    for i, v in enumerate(rows, 1):
        rec = names.get(v.player_id)
        name = rec.full_name if rec else str(v.player_id)
        team = (rec.team_abbr if rec else None) or "-"
        conf = confidence_factor(v.games_played, ranking.min_games_full_confidence)
        hits = {k: n for k, n in v.bonus_counts.items() if n}
        print(f"{i:>3} {name:28.28} {team:5} {v.games_played:>3} {v.avg_fpts:>7.2f} {v.best_game_fpts:>7.2f} {conf:>5.2f} {blended_value(v, ranking):>7.2f}  {hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
