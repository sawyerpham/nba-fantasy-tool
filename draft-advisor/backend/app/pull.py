"""CLI: run the pre-draft data pull.

    python -m app.pull                       # real providers, default seasons
    python -m app.pull --force-sleeper       # bypass the 24 h Sleeper cache guard
    python -m app.pull --skip-logs           # everything except game logs (fast re-seed)
    python -m app.pull --fixtures            # offline, from tests/fixtures
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from nba_fantasy_shared.providers.base import CallRunner, RetryPolicy
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.providers.nba_api_provider import NbaApiProvider
from nba_fantasy_shared.providers.sleeper_provider import SleeperProvider
from nba_fantasy_shared.storage import JsonStore

from . import config
from .services.pull_service import PullService


def build_service(
    data_dir: Path,
    fixtures: Path | None = None,
    roster_season: str | None = None,
    stats_season: str | None = None,
    delay_s: float = 0.6,
) -> PullService:
    store = JsonStore(data_dir)
    if fixtures is not None:
        stats = FixtureStatsProvider(fixtures)
        platform = FixturePlatformProvider(fixtures)
    else:
        policy = RetryPolicy(delay_s=delay_s)
        stats = NbaApiProvider(CallRunner(policy))
        platform = SleeperProvider(store, CallRunner(policy))
    return PullService(store, stats, platform, roster_season=roster_season, stats_season=stats_season)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull nba_api + Sleeper data into the JSON store")
    parser.add_argument("--data-dir", type=Path, default=config.DEFAULT_DATA_DIR)
    parser.add_argument("--roster-season", default=None, help="e.g. 2026-27 (default: from Sleeper state)")
    parser.add_argument("--stats-season", default=None, help="e.g. 2025-26 (default: previous season)")
    parser.add_argument("--sources", default="nba_api,sleeper")
    parser.add_argument("--force-sleeper", action="store_true", help="ignore the 24 h Sleeper players cache")
    parser.add_argument("--skip-logs", action="store_true", help="do not pull game logs")
    parser.add_argument("--fixtures", nargs="?", const=str(config.FIXTURES_DIR), default=None,
                        help="use fixture providers (optionally pass a fixtures dir)")
    parser.add_argument("--delay", type=float, default=0.6, help="seconds between nba_api calls")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    service = build_service(
        args.data_dir,
        fixtures=Path(args.fixtures) if args.fixtures else None,
        roster_season=args.roster_season,
        stats_season=args.stats_season,
        delay_s=args.delay,
    )
    status = service.run(
        sources=[s.strip() for s in args.sources.split(",") if s.strip()],
        force_sleeper=args.force_sleeper,
        skip_game_logs=args.skip_logs,
    )

    print(json.dumps(status.as_dict(), indent=2, ensure_ascii=False))
    if status.reconcile:
        rep = status.reconcile
        print(f"\nreconcile: {rep.counts}")
        print(f"team conflicts: {[(c['name'], c['nba_api'], c['sleeper']) for c in rep.team_conflicts]}")
        print(f"unsigned per Sleeper: {len(rep.unsigned_per_sleeper)} | collisions: {len(rep.collisions)}")
        print(f"unmatched nba_api ({len(rep.unmatched_nba)}): {[u['name'] for u in rep.unmatched_nba]}")
        print(f"unmatched sleeper ({len(rep.unmatched_sleeper)}): {[u['name'] for u in rep.unmatched_sleeper]}")
    return 0 if status.state == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
