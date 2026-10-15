"""Bid recommendation: fair value, competition pressure, and the reservation cap."""

import pytest

from app.engine.bidding import competitor_weight, recommend_bid, replacement_value
from app.engine.draft_state import DraftEngine
from app.engine.ranking import pool_values, rank_players
from nba_fantasy_shared.models.league import ManagerBehavior
from tests.factories import NOW, default_world, fresh_draft, managers, small_league


def setup(num_managers=3, budget=50, behaviors=None, **league_kw):
    players, overrides, valuations = default_world()
    lg = small_league(num_managers=num_managers, budget=budget, **league_kw)
    mgrs = managers(num_managers, budget, behaviors=behaviors)
    e = DraftEngine(lg, mgrs, fresh_draft(), players, overrides, now=lambda: NOW)
    e.start()
    return lg, mgrs, e, players, overrides, valuations


def recommend(lg, mgrs, e, players, overrides, valuations, pid, me="m1"):
    available = [p for p in players if e.is_available(p)]
    rows = rank_players(lg, players, overrides, valuations, e.picks_for(me), available)
    target = next(r for r in rows if r.player_id == pid)
    return recommend_bid(lg, mgrs, e.draft.picks, me, target, rows, pool_values(players, overrides, valuations, lg.ranking), e.progress())


def test_replacement_value_is_the_nth_best():
    assert replacement_value([10, 50, 30, 20], 2) == 30
    assert replacement_value([10, 50, 30, 20], 4) == 10
    assert replacement_value([10, 50], 5) == 0.0   # fewer players than slots
    assert replacement_value([], 3) == 0.0


@pytest.mark.parametrize("pace, progress, expected", [("early", 0.1, 1.3), ("early", 0.6, 0.8), ("late", 0.1, 0.8),
                                                      ("late", 0.6, 1.3), ("even", 0.1, 1.0)])
def test_competitor_weight_by_pace_and_progress(pace, progress, expected):
    assert competitor_weight(ManagerBehavior(spend_pace=pace), progress) == pytest.approx(expected)
    assert competitor_weight(ManagerBehavior(spend_pace=pace, aggression=1.5), progress) == pytest.approx(expected * 1.5)


def test_fair_value_hand_computed_at_draft_start():
    lg, mgrs, e, players, overrides, valuations = setup()
    values = pool_values(players, overrides, valuations, lg.ranking)
    ordered = sorted(values.values(), reverse=True)
    rosterable_n = 6 * 3
    replacement = ordered[rosterable_n - 1] if rosterable_n <= len(ordered) else 0.0
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)
    assert rec.replacement_value == pytest.approx(replacement, abs=0.01)      # 12 players < 18 slots -> 0
    assert rec.free_dollars == 3 * (50 - 6)                                    # $44 discretionary each
    assert rec.var == pytest.approx(values[1] - replacement, abs=0.01)
    var_pool = sum(max(0.0, v - replacement) for v in ordered[:18])
    assert rec.var_pool == pytest.approx(var_pool, abs=0.01)
    assert rec.fair_value == pytest.approx(1 + rec.var * rec.free_dollars / var_pool, abs=0.01)
    assert rec.can_bid and rec.my_max_bid == 45
    assert rec.competition_pressure == 2.0  # both other managers can afford it, even pace
    assert rec.recommended_max == max(1, min(45, round(rec.fair_value * (1 + 0.15 * 2.0 / 2))))  # +15 % when everyone is in


def test_pressure_is_normalized_by_number_of_other_managers():
    few = setup(num_managers=3)
    many = setup(num_managers=12, budget=200)
    rec_few = recommend(*few, pid=1)
    rec_many = recommend(*many, pid=1)
    assert rec_few.competition_pressure == 2.0 and rec_many.competition_pressure == 11.0
    for rec in (rec_few, rec_many):  # everyone in, even pace -> exactly +15 % over fair value (before caps)
        assert rec.recommended_max == max(1, min(rec.my_max_bid, round(rec.fair_value * 1.15)))
    assert any("Replacement level" in line for line in rec.rationale) and any(line.startswith("Max $") for line in rec.rationale)


def test_recommendation_never_exceeds_max_bid_reservation():
    lg, mgrs, e, players, overrides, valuations = setup()
    # m1 spends heavily: $43 on player 3 -> $7 left, 5 slots open -> max bid 3
    e.pick(3, "m1", 43)
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)
    assert rec.my_budget_remaining == 7 and rec.my_open_mandatory == 5 and rec.my_max_bid == 3
    assert rec.fair_value > 3
    assert rec.recommended_max == 3
    assert "limited to your cap $3" in rec.rationale[-1]


def test_recommendation_is_at_least_min_bid_for_below_replacement_players():
    lg, mgrs, e, players, overrides, valuations = setup(num_managers=2)
    # 2 managers × 6 slots = 12 rosterable = whole pool: the lowest-valued player IS replacement level
    values = pool_values(players, overrides, valuations, lg.ranking)
    worst = min(values, key=values.get)
    assert worst == 12  # Lou Rookie: 3 games -> confidence 0.15
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=worst)
    assert rec.var == 0.0 and rec.fair_value == 1.0 and rec.recommended_max == 1 and rec.can_bid


def test_fair_value_is_capped_at_the_largest_legal_bid_in_the_room():
    lg, mgrs, e, players, overrides, valuations = setup()
    for pid in range(3, 11):
        e.pick(pid, "m1" if pid % 2 else "m2", 1)  # few players left, lots of money: uncapped fair value explodes
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)
    assert rec.fair_value == 45.0  # m3 (untouched) can bid at most 50 - 5 = 45
    assert any("Capped at $45" in line for line in rec.rationale)
    assert rec.recommended_max <= rec.my_max_bid


def test_cannot_bid_without_a_fitting_slot_or_money():
    lg, mgrs, e, players, overrides, valuations = setup()
    for pid, slot in [(2, "PG"), (5, "SG"), (3, "UTIL"), (7, "BN"), (8, "BN")]:
        e.pick(pid, "m1", 1, slot=slot)
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=4)  # PG only, my PG/UTIL/BN are full
    assert not rec.can_bid and rec.recommended_max == 0 and "no open slot" in rec.rationale[-1]
    rec_c = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)  # C fits my last slot
    assert rec_c.can_bid and rec_c.my_max_bid == 45


def test_competitors_exclude_managers_who_cannot_afford_or_fit():
    lg, mgrs, e, players, overrides, valuations = setup()
    e.pick(3, "m2", 44)  # m2: $6 left, 5 open -> max bid 2
    for pid, slot in [(2, "PG"), (5, "SG"), (7, "UTIL"), (8, "BN"), (11, "BN")]:
        e.pick(pid, "m3", 1, slot=slot)  # m3 has only C open
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=4)  # PG, expensive
    assert rec.fair_value > 2
    assert [c.manager_id for c in rec.competitors] == []  # m2 broke, m3 has no PG-fitting slot
    assert rec.competition_pressure == 0.0
    rec_c = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)  # C: m3 can fit it
    assert [c.manager_id for c in rec_c.competitors] == ["m3"]


def test_early_spenders_add_more_pressure_early_and_less_late():
    behaviors = {1: ManagerBehavior(spend_pace="early"), 2: ManagerBehavior(spend_pace="late")}
    lg, mgrs, e, players, overrides, valuations = setup(behaviors=behaviors)
    early = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)
    weights = {c.manager_id: c.weight for c in early.competitors}
    assert weights == {"m2": 1.3, "m3": 0.8}
    # advance the draft past 40%: 8 of 18 picks
    for pid in range(3, 11):
        e.pick(pid, "m1" if pid % 2 else "m2", 1)
    late = recommend(lg, mgrs, e, players, overrides, valuations, pid=1)
    assert e.progress() > 0.4
    assert {c.manager_id: c.weight for c in late.competitors} == {"m2": 0.8, "m3": 1.3}


def test_more_free_dollars_means_higher_fair_value():
    poor = setup(budget=20)
    rich = setup(budget=200)
    assert recommend(*rich, pid=1).fair_value > recommend(*poor, pid=1).fair_value
    assert recommend(*poor, pid=1).recommended_max <= 20 - 5


def test_user_manager_cannot_be_own_competitor():
    lg, mgrs, e, players, overrides, valuations = setup()
    rec = recommend(lg, mgrs, e, players, overrides, valuations, pid=1, me="m2")
    assert "m2" not in {c.manager_id for c in rec.competitors} and len(rec.competitors) == 2
