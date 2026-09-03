"""Spending guide: money picture, inflation, slot plan, and how far to go on a player."""

import pytest

from app.engine.bidding import market_rate
from app.engine.draft_state import DraftEngine, KeeperAssignment
from app.engine.ranking import pool_values, rank_players
from app.engine.spending import ordinal, spending_guide
from tests.factories import NOW, default_world, fresh_draft, managers, small_league


def setup(keepers=None):
    players, overrides, valuations = default_world()
    lg = small_league()
    mgrs = managers(3, 50)
    e = DraftEngine(lg, mgrs, fresh_draft(), players, overrides, now=lambda: NOW)
    e.start(keepers or [])
    return lg, mgrs, e, players, overrides, valuations


def guide(lg, mgrs, e, players, overrides, valuations, me="m1", focus=None):
    pv = pool_values(players, overrides, valuations, lg.ranking)
    opening_rows = rank_players(lg, players, overrides, valuations, [], list(players))
    opening = market_rate(lg, mgrs, [], (r.value for r in opening_rows), pv).dollars_per_var
    available = [p for p in players if e.is_available(p)]
    rows = rank_players(lg, players, overrides, valuations, e.picks_for(me), available)
    return spending_guide(lg, mgrs, e.draft.picks, me, rows, pv, e.progress(), opening, focus_player_id=focus)


def pick(e, pid, mgr, price):
    e.nominate(pid)
    e.pick(pid, mgr, price)


def test_ordinal():
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 101)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "101st"]


def test_opening_picture_at_draft_start():
    world = setup()
    g = guide(*world)
    me = g.me
    assert (me.remaining, me.open_mandatory, me.open_starters, me.open_bench, me.max_bid) == (50, 6, 4, 2, 45)
    assert me.per_slot == pytest.approx(50 / 6, abs=0.1)
    assert g.money_rank == 1 and g.per_slot_rank == 1 and g.num_managers == 3
    assert g.room_remaining == 150 and g.room_open_mandatory == 18 and g.room_open_starters == 12
    assert g.room_per_slot == pytest.approx(150 / 18, abs=0.1)
    assert g.inflation == pytest.approx(1.0) and g.current_dollars_per_var == g.opening_dollars_per_var > 0
    assert g.allowance == 12  # ($50 - 2 bench at $1) / 4 starter slots
    assert not g.can_outbid_me
    assert g.advice[0] == "$50 for 6 slots ($8/slot): 1st most money of 3, 1st per open slot."
    assert g.advice[1] == "Prices are near the opening rate."
    assert g.advice[-1] == "Nobody can outbid your max of $45."
    assert [m.manager_id for m in g.managers] == ["m1", "m2", "m3"]


def test_plan_covers_each_open_starter_slot_without_reusing_a_player():
    g = guide(*setup())
    assert [e.slot for e in g.plan] == ["PG", "SG", "C", "UTIL"]
    assert g.plan[0].best_name == "Bo Guard" and g.plan[2].best_name == "Ace Center" and g.plan[3].best_name == "Cy Wing"
    ids = [e.best_id for e in g.plan] + [e.fit_id for e in g.plan if e.fit_id is not None]
    assert len(ids) == len(set(ids))
    assert all(e.fit_price <= g.allowance for e in g.plan if e.fit_id is not None)
    assert all(e.best_price >= e.fit_price for e in g.plan)
    assert g.bench_total == 2
    assert g.plan_best_total == sum(e.best_price for e in g.plan) + 2
    assert g.plan_fit_total == sum(e.fit_price for e in g.plan) + 2
    assert g.slack_best == 50 - g.plan_best_total and g.slack_fit == 50 - g.plan_fit_total
    # the best at every slot costs more than $50 in this tiny room, and the advice says so
    assert g.slack_best < 0 and g.slack_fit >= 0
    assert any(line.startswith(f"The best available at every open starter slot costs ${g.plan_best_total}, ") for line in g.advice)


def test_targets_are_affordable_and_ranked_by_value():
    g = guide(*setup())
    assert [t.name for t in g.targets] == ["Ace Center", "Bo Guard", "Cy Wing", "Dee Point", "Ed Two"]
    assert all(1 <= t.suggested <= 45 for t in g.targets)
    assert [t.tier for t in g.targets] == ["top", "top", "top", "starter", "starter"]
    assert all(t.left_after == 50 - t.suggested for t in g.targets)
    assert all(t.verdict in {"go", "fair-only", "fits", "stretch", "pass"} for t in g.targets)
    assert all(t.room_per_starter == 12.0 for t in g.targets)  # ($150 - 6 bench) / 12 open starter slots


def test_everyone_equal_at_the_start_a_star_is_a_stretch_and_a_mid_player_fits():
    g = guide(*setup(), focus=1)
    f = g.focus
    # $50 - $2 bench - 3 other starters × 0.8 × $12 = $19 stretch; × 0.5 = $30 walk-away
    assert (f.stretch, f.walk_away, f.all_in) == (19, 30, 45)
    assert f.rivals_above_market == 2 and f.stretch < f.recommended <= f.walk_away
    assert f.verdict == "stretch" and f.suggested == f.recommended
    assert f.text.startswith(f"Ace Center is worth the market max ${f.recommended} only as your star: you'd have ${50 - f.recommended} for 5 slots")
    assert f.per_starter_after == pytest.approx((50 - f.recommended - 2) / 3, abs=0.1)
    dee = next(t for t in g.targets if t.name == "Dee Point")
    assert dee.verdict == "fits" and dee.suggested == dee.recommended <= 19


def test_go_with_an_overpay_ceiling_when_rich_and_a_bidding_war_is_likely():
    lg, mgrs, e, players, overrides, valuations = setup()
    pick(e, 10, "m2", 30)   # rivals blow $30 each on spares: $20 left, max bid $16
    pick(e, 11, "m3", 30)
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=1)
    assert g.money_rank == 1 and [m.remaining for m in g.managers] == [50, 20, 20]
    assert g.inflation < 1.0  # money left the room faster than talent did
    f = g.focus
    assert f.player_id == 1 and f.slot == "C" and f.tier == "top" and f.rivals_at_fair == 2 and f.rivals_above_market == 2
    assert f.verdict == "go" and f.recommended < f.suggested == min(f.stretch, round(f.recommended * 1.25))
    assert f.text.startswith(f"Go for Ace Center: pay up to ${f.suggested} (market max ${f.recommended}, fair ${round(f.fair_value)}). 2 rivals can also reach")
    assert f.left_after == 50 - f.suggested and f.per_starter_after == pytest.approx((50 - f.suggested - 2) / 3, abs=0.1)


def test_go_at_market_when_few_rivals_can_go_past_it():
    lg, mgrs, e, players, overrides, valuations = setup()
    pick(e, 10, "m2", 40)   # m2: $10 left, max bid $6 -> cannot reach the market max; m3 still can
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=1)
    f = g.focus
    assert f.rivals_at_fair >= 1 and f.rivals_above_market == 1
    assert f.verdict == "go" and f.suggested == f.recommended
    assert f.text.startswith(f"Go for Ace Center: pay up to ${f.suggested} (fair ${round(f.fair_value)}). Only 1 rival can go past that")


def test_fair_only_when_nobody_else_can_pay_fair_value():
    lg, mgrs, e, players, overrides, valuations = setup()
    pick(e, 10, "m2", 45)   # $5 left with 5 open slots: max bid $1
    pick(e, 11, "m3", 45)
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=1)
    f = g.focus
    assert f.rivals_at_fair == 0 and f.verdict == "fair-only"
    assert f.suggested == round(f.fair_value) and f.suggested <= f.recommended
    assert f.text.startswith(f"Nobody else can pay fair value (${f.suggested}) for Ace Center. Bid to ${f.suggested} and stop")
    assert not g.can_outbid_me and g.advice[-1] == "Nobody can outbid your max of $45."


def test_pass_when_the_market_max_would_gut_the_other_starter_slots():
    lg, mgrs, e, players, overrides, valuations = setup()
    pick(e, 3, "m1", 20)   # I paid $20 for Cy Wing: $30 left, 3 starter slots + 2 bench
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=1)
    f = g.focus
    assert f.verdict == "pass" and f.suggested == f.walk_away < f.recommended
    assert f.text.startswith(f"Walk away from Ace Center at ${f.walk_away}: the market max is ${f.recommended}, but paying it leaves")
    assert "under half the room's" in f.text and f.text.endswith("2 rivals can outbid you anyway.")


def test_bench_slot_is_capped_at_the_market_max():
    lg, mgrs, e, players, overrides, valuations = setup()
    for pid, price in ((2, 5), (5, 5), (1, 5), (3, 5)):  # PG, SG, C, UTIL filled: only bench left
        pick(e, pid, "m1", price)
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=4)
    f = g.focus
    assert f.slot == "BN" and f.verdict == "fits" and f.suggested == min(f.recommended, g.me.max_bid)
    assert f.text.startswith("Bench slot: pay up to $")
    assert g.advice[2].startswith("Only bench slots left: $")


def test_cheap_keeper_inflates_prices():
    lg, mgrs, e, players, overrides, valuations = setup([KeeperAssignment("m2", 1, 1)])  # Ace Center kept for $1
    g = guide(lg, mgrs, e, players, overrides, valuations)
    assert g.inflation > 1.05 and g.current_dollars_per_var > g.opening_dollars_per_var
    assert g.advice[1].startswith(f"Prices are running {g.inflation:.2f}× the opening rate")
    assert all(t.player_id != 1 for t in g.targets) and all(pl.best_id != 1 for pl in g.plan)


def test_can_outbid_lists_richer_managers_by_max_bid():
    lg, mgrs, e, players, overrides, valuations = setup()
    pick(e, 1, "m1", 30)   # I spend $30 on Ace: $20 left, 5 slots, max bid $16
    g = guide(lg, mgrs, e, players, overrides, valuations)
    assert g.money_rank == 3 and g.me.max_bid == 16
    assert [m.manager_id for m in g.can_outbid_me] == ["m2", "m3"]
    assert g.advice[-1] == "2 managers can outbid your max of $16: Manager 2 $45, Manager 3 $45."
    assert [pl.slot for pl in g.plan] == ["PG", "SG", "UTIL"]  # C is filled


def test_roster_full():
    lg, mgrs, e, players, overrides, valuations = setup()
    for pid in (2, 5, 1, 3, 7, 8):  # PG, SG, C, UTIL, BN, BN at $1 each
        pick(e, pid, "m1", 1)
    g = guide(lg, mgrs, e, players, overrides, valuations, focus=4)
    assert g.me.open_mandatory == 0 and g.per_slot_rank == 0 and g.me.per_slot == 0.0
    assert g.advice[0] == "Roster full: $44 unspent." and g.plan == [] and g.targets == []
    assert g.focus.verdict == "cannot" and g.focus.suggested == 0
