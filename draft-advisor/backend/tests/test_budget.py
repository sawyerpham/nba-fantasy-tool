from datetime import datetime, timezone

import pytest

from app.core.engine.budget import discretionary_dollars, manager_budget, max_bid, validate_bid
from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, Manager

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def league(**kw) -> LeagueSettings:
    return LeagueSettings(league_id="L", name="Test", **kw)


def pick(n: int, manager_id: str, price: int, slot: str = "BN", player_id: int | None = None) -> Pick:
    return Pick(pick_number=n, player_id=player_id or 1000 + n, manager_id=manager_id, price=price, slot=slot, timestamp=NOW)


def test_default_league_has_15_mandatory_and_2_ir_slots():
    lg = league()
    assert lg.mandatory_slot_count() == 15
    assert lg.total_slot_count() == 17


@pytest.mark.parametrize(
    "remaining, open_mandatory, min_bid, expected",
    [
        (200, 15, 1, 186),  # fresh: 200 - 14 reserved
        (16, 15, 1, 2),     # nearly broke: can bid $2 and still fill 14 slots at $1
        (15, 15, 1, 1),     # exactly enough for $1 each
        (14, 15, 1, 0),     # cannot fill roster (should be unreachable if validation holds)
        (37, 1, 1, 37),     # last slot: everything is spendable
        (37, 0, 1, 0),      # no open mandatory slot: no bid at all
        (100, 5, 2, 92),    # min bid $2 reserves $8
    ],
)
def test_max_bid_reserves_min_bid_for_every_other_open_slot(remaining, open_mandatory, min_bid, expected):
    assert max_bid(remaining, open_mandatory, min_bid) == expected


def test_discretionary_dollars_is_money_above_the_bare_minimum():
    assert discretionary_dollars(200, 15, 1) == 185
    assert discretionary_dollars(15, 15, 1) == 0
    assert discretionary_dollars(10, 15, 1) == 0


def test_manager_budget_ignores_ir_picks_for_mandatory_count_but_counts_their_cost():
    lg = league()
    m = Manager(manager_id="m1", name="Me", is_user=True, budget_total=200)
    picks = [pick(1, "m1", 60, "UTIL"), pick(2, "m1", 5, "IR"), pick(3, "m2", 40, "BN")]
    b = manager_budget(lg, m, picks)
    assert b.spent == 65
    assert b.remaining == 135
    assert b.filled_mandatory == 1
    assert b.open_mandatory == 14
    assert b.reserved == 13
    assert b.max_bid == 122
    assert b.discretionary == 121


def test_validate_bid_rejects_bids_that_would_strand_the_roster():
    lg = league()
    m = Manager(manager_id="m1", name="Me", budget_total=200)
    b = manager_budget(lg, m, [])
    assert validate_bid(186, b, lg.min_bid) is None
    err = validate_bid(187, b, lg.min_bid)
    assert err is not None and "exceeds the cap $186" in err and "14 other mandatory slot" in err
    assert "below the minimum" in validate_bid(0, b, lg.min_bid)


def test_validate_bid_when_roster_is_full():
    lg = league()
    m = Manager(manager_id="m1", name="Me", budget_total=200)
    picks = [pick(i, "m1", 1) for i in range(1, 16)]
    b = manager_budget(lg, m, picks)
    assert b.open_mandatory == 0 and b.max_bid == 0
    assert "no open roster slot" in validate_bid(1, b, lg.min_bid)


def test_sequence_of_max_bids_always_leaves_the_roster_fillable():
    """Bidding max every time must still end with every mandatory slot filled and budget >= 0."""
    lg = league()
    m = Manager(manager_id="m1", name="Me", budget_total=200)
    picks: list[Pick] = []
    for n in range(1, 16):
        b = manager_budget(lg, m, picks)
        assert b.max_bid >= lg.min_bid
        picks.append(pick(n, "m1", b.max_bid))
    final = manager_budget(lg, m, picks)
    assert final.open_mandatory == 0
    assert final.remaining == 0


def test_league_rejects_budget_that_cannot_fill_mandatory_slots():
    with pytest.raises(ValueError):
        league(budget_per_manager=14)
