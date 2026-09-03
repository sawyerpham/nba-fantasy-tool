"""Compute and cache PlayerValuations for every player with game logs.

Cache key is (stats_season, scoring hash): editing any scoring value produces a new file and a
recompute from the cached game lines. No network is involved.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Mapping

from nba_fantasy_shared.models.players import GameLine, PlayerValuation
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.scoring import valuate_all
from nba_fantasy_shared.storage import JsonStore

from .. import config
from .pull_service import load_game_logs

log = logging.getLogger(__name__)


class ValuationService:
    def __init__(self, store: JsonStore, stats_season: str) -> None:
        self.store = store
        self.stats_season = stats_season

    def cache_rel(self, scoring: ScoringSettings) -> str:
        return config.valuations_rel(self.stats_season, scoring.scoring_hash())

    def load_cached(self, scoring: ScoringSettings) -> dict[int, PlayerValuation] | None:
        rel = self.cache_rel(scoring)
        if not self.store.exists(rel):
            return None
        raw = self.store.read_json(rel)
        return {int(k): PlayerValuation.model_validate(v) for k, v in raw["valuations"].items()}

    def compute(
        self,
        scoring: ScoringSettings,
        logs: Mapping[int, list[GameLine]] | None = None,
        force: bool = False,
    ) -> dict[int, PlayerValuation]:
        if not force:
            cached = self.load_cached(scoring)
            if cached is not None:
                return cached
        if logs is None:
            logs = load_game_logs(self.store, self.stats_season)
        valuations = valuate_all(logs, scoring, self.stats_season)
        self.store.write_json(
            self.cache_rel(scoring),
            {
                "computed_at": datetime.now(timezone.utc).isoformat(),
                "stats_season": self.stats_season,
                "scoring_hash": scoring.scoring_hash(),
                "scoring": scoring.model_dump(mode="json"),
                "valuations": {str(pid): v.model_dump(mode="json") for pid, v in valuations.items()},
            },
            indent=None,
        )
        log.info("valuations computed for %d players (hash %s)", len(valuations), scoring.scoring_hash())
        return valuations
