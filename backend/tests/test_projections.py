"""Sleeper projections blended into FP/G, and auction money spread over starters + priced bench only."""

import pytest

from app.core.engine.bidding import market_rate
from app.core.engine.ranking import expected_fpts, player_value
from nba_fantasy_shared.models.league import RankingSettings
from nba_fantasy_shared.models.scoring import ScoringSettings
from tests.factories import managers, override, record, small_league, valuation


def proj_record(pid, pts):
    return record(pid, f"Test Player{pid}").model_copy(update={"projection": {"pts": pts}})


def test_projection_blends_with_last_season_and_scales_ceiling():
    scoring = ScoringSettings()
    rec = proj_record(1, pts=40.0)
    proj = 40.0 * scoring.base.pts
    v = valuation(1, avg=proj / 2, best=proj, gp=65)          # last season was half the projection
    avg, ceiling = expected_fpts(rec, v, RankingSettings(projection_weight=0.75), scoring)
    expected = 0.75 * (proj + v.bonus_fpts_per_game) + 0.25 * v.avg_fpts
    assert avg == pytest.approx(expected)
    assert ceiling == pytest.approx(v.weekly_best_avg * expected / v.avg_fpts)
    # weight 0 = last season only; no scoring = projection ignored
    assert expected_fpts(rec, v, RankingSettings(projection_weight=0.0), scoring)[0] == pytest.approx(v.avg_fpts)
    assert expected_fpts(rec, v, RankingSettings(), None)[0] == v.avg_fpts


def test_projection_without_history_counts_at_full_confidence():
    scoring = ScoringSettings()
    value, blended, conf, *_ = player_value(proj_record(2, pts=30.0), override(2, ["SF"]), None, RankingSettings(), scoring)
    assert conf == 1.0 and value > 0


def test_fewer_priced_bench_slots_raise_the_price_of_value():
    league = small_league()
    ms = managers(3, budget=league.budget_per_manager)
    values = [100.0 - i for i in range(80)]
    pool = dict(enumerate(values))
    deep = league.model_copy(update={"ranking": RankingSettings(priced_bench_slots=99)})
    shallow = league.model_copy(update={"ranking": RankingSettings(priced_bench_slots=0)})
    r_deep = market_rate(deep, ms, [], values, pool)
    r_shallow = market_rate(shallow, ms, [], values, pool)
    assert r_shallow.replacement > r_deep.replacement
    assert r_shallow.dollars_per_var > r_deep.dollars_per_var


def test_tiers_break_on_a_relative_drop_from_the_tier_top():
    from app.core.engine.ranking import tiers

    t = tiers({1: 100.0, 2: 96.0, 3: 93.0, 4: 90.0, 5: 50.0})
    assert t == {1: 1, 2: 1, 3: 2, 4: 2, 5: 3}


def test_age_penalty_only_hits_the_last_season_share_when_projected():
    scoring = ScoringSettings()
    old = record(3, "Old Player", age=41.0).model_copy(update={"projection": {"pts": 40.0}})
    v = valuation(3, avg=10.0, best=20.0, gp=65)
    r = RankingSettings(projection_weight=0.75)
    *_, age, _ = player_value(old, override(3, ["SF"]), v, r, scoring)
    assert age == pytest.approx(1 - 0.25 * 0.25)            # max 25 % penalty × 25 % last-season share
    *_, age_unprojected, _ = player_value(record(4, "Old Other", age=41.0), override(4, ["SF"]), v, r, scoring)
    assert age_unprojected == pytest.approx(0.75)
