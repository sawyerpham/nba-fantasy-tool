"""Backend configuration: data directory and season defaults."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = Path(os.environ.get("DRAFT_ADVISOR_DATA_DIR", BACKEND_ROOT / "data"))
FIXTURES_DIR = BACKEND_ROOT / "tests" / "fixtures"

DEFAULT_ROSTER_SEASON = "2026-27"
DEFAULT_STATS_SEASON = "2025-26"

# Relative paths inside the data directory (DESIGN.md 1.8).
OVERRIDES_REL = "player_overrides.json"


def nba_pool_rel(roster_season: str) -> str:
    return f"cache/nba_player_pool_{roster_season}.json"


def game_logs_rel(stats_season: str) -> str:
    return f"cache/game_logs_{stats_season}.json"


def reconcile_rel(roster_season: str) -> str:
    return f"cache/reconcile_{roster_season}.json"


def valuations_rel(stats_season: str, scoring_hash: str) -> str:
    return f"cache/valuations_{stats_season}_{scoring_hash}.json"


def player_detail_rel(player_id: int) -> str:
    return f"cache/player_detail/{player_id}.json"


def league_rel(league_id: str) -> str:
    return f"leagues/{league_id}.json"
