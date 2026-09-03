import pytest

from app import config
from app.services.pull_service import PullService
from app.services.valuation_service import ValuationService
from nba_fantasy_shared.models.scoring import BaseScoring, ScoringSettings
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.storage import JsonStore

JOKIC, WALKER = 203999, 1629022


@pytest.fixture
def store(tmp_path, fixtures_dir):
    store = JsonStore(tmp_path)
    status = PullService(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir)).run()
    assert status.state == "done"
    return store


def test_compute_caches_by_scoring_hash_and_recomputes_on_scoring_change(store):
    service = ValuationService(store, "2025-26")
    default = ScoringSettings()
    assert service.load_cached(default) is None

    first = service.compute(default)
    assert first[JOKIC].games_played == 65 and first[JOKIC].bonus_counts["triple_double"] == 34
    assert first[WALKER].games_played == 0 and first[WALKER].avg_fpts == 0.0
    assert store.exists(config.valuations_rel("2025-26", default.scoring_hash()))

    cached = service.compute(default)
    assert cached[JOKIC] == first[JOKIC]

    doubled = ScoringSettings(base=BaseScoring(pts=0.5))
    assert doubled.scoring_hash() != default.scoring_hash()
    second = service.compute(doubled)
    assert second[JOKIC].avg_fpts > first[JOKIC].avg_fpts
    assert store.exists(config.valuations_rel("2025-26", doubled.scoring_hash()))
    assert service.load_cached(default)[JOKIC].avg_fpts == first[JOKIC].avg_fpts  # old cache untouched


def test_force_recompute_rewrites_cache(store):
    service = ValuationService(store, "2025-26")
    default = ScoringSettings()
    service.compute(default)
    rel = config.valuations_rel("2025-26", default.scoring_hash())
    before = store.read_json(rel)["computed_at"]
    again = service.compute(default, force=True)
    assert again[JOKIC].games_played == 65
    assert store.read_json(rel)["computed_at"] >= before
