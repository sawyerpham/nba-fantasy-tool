"""Ranking modifiers (injury, age, confidence) and roster-driven re-sorting."""

import pytest

from app.core.engine.ranking import age_multiplier, injury_multiplier, player_value, pool_values, rank_players
from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import RankingSettings
from tests.factories import NOW, default_world, override, record, small_league, valuation


def pick(n, pid, slot, manager="m1"):
    return Pick(pick_number=n, player_id=pid, manager_id=manager, price=1, slot=slot, timestamp=NOW)


@pytest.mark.parametrize("status, expected", [("healthy", 1.0), ("day_to_day", 0.95), ("out_short_term", 0.85),
                                              ("out_long_term", 0.6), ("out_season", 0.0)])
def test_injury_multipliers_default(status, expected):
    assert injury_multiplier(status, RankingSettings()) == expected


def test_injury_multipliers_are_editable():
    custom = RankingSettings(injury_multipliers={"healthy": 1.0, "out_season": 0.5})
    assert injury_multiplier("out_season", custom) == 0.5
    assert injury_multiplier("unknown_status", custom) == 1.0


@pytest.mark.parametrize("age, expected", [(None, 1.0), (22.0, 1.0), (31.0, 1.0), (33.0, 0.94), (36.0, 0.85), (45.0, 0.75)])
def test_age_penalty_starts_at_31_three_percent_per_year_capped_at_25(age, expected):
    assert age_multiplier(age, RankingSettings()) == pytest.approx(expected)


def test_player_value_composition():
    rec = record(1, "Test Player", "DEN", age=34.0)
    v = valuation(1, avg=50.0, best=80.0, gp=65)
    r = RankingSettings()
    value, blended, conf, inj, age, avail = player_value(rec, override(1, ["C"]), v, r)
    assert blended == pytest.approx(65.0) and conf == 1.0 and inj == 1.0 and age == pytest.approx(0.91) and avail == 1.0
    assert value == pytest.approx(65.0 * 0.91)
    value_out, *_ = player_value(rec, override(1, ["C"], injury="out_long_term"), v, r)
    assert value_out == pytest.approx(65.0 * 0.91 * 0.6)
    value_avail, *_ = player_value(rec, override(1, ["C"]), valuation(1, 50.0, 80.0, weeks=10), RankingSettings(availability_weight=1.0))
    assert value_avail == pytest.approx(65.0 * 0.91 * 0.4)
    assert player_value(rec, override(1, ["C"]), None, r)[0] == 0.0  # no stats -> zero value
    small = valuation(1, avg=60.0, best=95.0, gp=3)
    assert player_value(rec, override(1, ["C"]), small, r)[0] < value  # 3-game sample cannot out-rank a full season


def test_rank_order_and_flags():
    players, overrides, valuations = default_world()
    lg = small_league()
    rows = rank_players(lg, players, overrides, valuations, my_picks=[], available_ids=list(players))
    names = [r.full_name for r in rows]
    assert names[:3] == ["Ace Center", "Bo Guard", "Cy Wing"]
    assert names.index("Lou Rookie") > names.index("Gus Bench")  # 3 games, confidence 0.15
    rookie = next(r for r in rows if r.full_name == "Lou Rookie")
    assert rookie.confidence == 0.15 and rookie.value == pytest.approx((0.5 * 30 + 0.5 * 70) * 0.15, abs=0.01)
    assert rookie.ceiling_metric == "weekly_best" and rookie.ceiling == 70.0 and rookie.total_fpts == pytest.approx(90.0)
    fay = next(r for r in rows if r.full_name == "Fay Big")
    assert fay.injury_multiplier == 0.95 and fay.injury_status == "day_to_day"
    hal = next(r for r in rows if r.full_name == "Hal Bench")
    assert hal.age_multiplier == pytest.approx(0.88)
    assert all(r.rosterable for r in rows) and [r.rank for r in rows] == list(range(1, 13))


def test_unrosterable_players_sink_as_roster_fills():
    players, overrides, valuations = default_world()
    lg = small_league()
    # my roster: PG, SG, UTIL, BN, BN filled -> only C open
    my_picks = [pick(1, 2, "PG"), pick(2, 5, "SG"), pick(3, 3, "UTIL"), pick(4, 7, "BN"), pick(5, 8, "BN")]
    available = [pid for pid in players if pid not in {2, 5, 3, 7, 8}]
    rows = rank_players(lg, players, overrides, valuations, my_picks, available)
    rosterable = [r.full_name for r in rows if r.rosterable]
    assert rosterable == ["Ace Center", "Fay Big", "Ike Bench"]  # every C-eligible player, by value
    assert rows[0].assignable_slot == "C"
    dee = next(r for r in rows if r.full_name == "Dee Point")
    assert not dee.rosterable and dee.rank > len(rosterable)
    assert dee.value > rows[2].value  # higher value but sunk below every rosterable player


def test_stack_if_added_reflects_my_roster():
    players, overrides, valuations = default_world()
    lg = small_league()
    rows = rank_players(lg, players, overrides, valuations, [pick(1, 1, "C")], [2, 3])
    by_name = {r.full_name: r for r in rows}
    assert by_name["Bo Guard"].stack_if_added == 2   # DEN, same as Ace Center
    assert by_name["Cy Wing"].stack_if_added == 1    # LAL


def test_override_edit_changes_ranking_immediately():
    players, overrides, valuations = default_world()
    lg = small_league()
    before = rank_players(lg, players, overrides, valuations, [], list(players))
    assert before[0].full_name == "Ace Center"
    overrides[1] = override(1, ["C"], injury="out_season", source="manual")
    after = rank_players(lg, players, overrides, valuations, [], list(players))
    assert after[0].full_name == "Bo Guard"
    ace = next(r for r in after if r.full_name == "Ace Center")
    assert ace.value == 0.0 and ace.injury_status == "out_season"
    overrides[4] = override(4, ["PG", "SF"], source="manual")  # eligibility edit
    assert next(r for r in rank_players(lg, players, overrides, valuations, [], [4]) if r.player_id == 4).eligibility == ["PG", "SF"]


def test_pool_values_cover_every_player_including_no_stats():
    players, overrides, valuations = default_world()
    players[99] = record(99, "No Stats", "UTA", has_stats=False)
    values = pool_values(players, overrides, valuations, RankingSettings())
    assert set(values) == set(players) and values[99] == 0.0 and values[1] > values[2] > 0


def test_no_games_last_season_is_not_treated_as_never_available():
    from nba_fantasy_shared.scoring.aggregate import NO_GAMES_AVAILABILITY, availability_factor

    r = RankingSettings(availability_weight=0.3)
    missed_all = valuation(1, 0.0, 0.0, gp=0, weeks=0)
    assert availability_factor(missed_all, r) == 1 - 0.3 * (1 - NO_GAMES_AVAILABILITY)
    # a veteran who missed last season keeps his 3-season blend (0.5 × 0 + 0.3 × 0.7 + 0.2 × 0.85 = 0.38)
    vet = missed_all.model_copy(update={"availability": 0.38, "availability_seasons": {"2025-26": 0.0, "2024-25": 0.7, "2023-24": 0.85}})
    assert availability_factor(vet, r) == pytest.approx(1 - 0.3 * (1 - 0.38))
