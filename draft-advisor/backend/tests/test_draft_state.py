"""Draft state machine: keepers, nomination rotation, picks, undo, and the reservation rule end to end."""

import pytest

from app.engine.draft_state import DraftEngine, DraftError, KeeperAssignment
from nba_fantasy_shared.models.league import KeeperSettings
from tests.factories import NOW, default_world, fresh_draft, managers, override, record, small_league


def engine(num_managers=3, budget=50, **league_kw) -> DraftEngine:
    players, overrides, _ = default_world()
    lg = small_league(num_managers=num_managers, budget=budget, **league_kw)
    return DraftEngine(lg, managers(num_managers, budget), fresh_draft(), players, overrides, now=lambda: NOW)


# ------------------------------------------------------------------ start / keepers

def test_start_sets_live_default_order_and_keeper_picks():
    e = engine()
    picks = e.start([KeeperAssignment("m1", 1, 20), KeeperAssignment("m2", 2, 15)])
    assert e.draft.status == "live" and e.draft.nomination_order == ["m1", "m2", "m3"]
    assert [(p.pick_number, p.player_id, p.manager_id, p.price, p.slot, p.is_keeper) for p in picks] == [
        (1, 1, "m1", 20, "C", True), (2, 2, "m2", 15, "PG", True)]
    assert e.budget("m1").remaining == 30 and e.budget("m1").open_mandatory == 5
    assert not e.is_available(1) and e.is_available(3)
    assert e.next_nominator() == "m1"


def test_default_max_one_keeper_per_manager_is_enforced():
    e = engine()
    with pytest.raises(DraftError, match="more than 1 keeper"):
        e.start([KeeperAssignment("m1", 1, 10), KeeperAssignment("m1", 2, 10)])
    assert e.draft.status == "setup" and e.draft.picks == []


@pytest.mark.parametrize("max_keepers, kept", [(2, 2), (3, 3)])
def test_managers_may_keep_more_than_one_when_the_setting_allows(max_keepers, kept):
    e = engine(keeper=KeeperSettings(enabled=True, max_per_manager=max_keepers))
    assignments = [KeeperAssignment("m1", pid, 5) for pid in range(1, kept + 1)]
    e.start(assignments)
    own = e.picks_for("m1")
    assert len(own) == kept and all(p.is_keeper for p in own)
    assert e.budget("m1").remaining == 50 - 5 * kept and e.budget("m1").open_mandatory == 6 - kept
    with pytest.raises(DraftError, match=f"more than {max_keepers}"):
        engine(keeper=KeeperSettings(enabled=True, max_per_manager=max_keepers)).start(
            [KeeperAssignment("m1", pid, 5) for pid in range(1, max_keepers + 2)])


def test_keepers_disabled_rejects_keepers_and_keeper_cost_obeys_reservation():
    with pytest.raises(DraftError, match="disabled"):
        engine(keeper=KeeperSettings(enabled=False)).start([KeeperAssignment("m1", 1, 5)])
    e = engine()
    with pytest.raises(DraftError, match="exceeds max bid"):
        e.start([KeeperAssignment("m1", 1, 46)])  # 50 - 5 reserved = 45 max
    assert e.draft.status == "setup"


def test_cannot_start_twice_or_act_before_start():
    e = engine()
    with pytest.raises(DraftError, match="not live"):
        e.pick(1, "m1", 5)
    e.start()
    with pytest.raises(DraftError, match="already live"):
        e.start()


# ------------------------------------------------------------------ nomination

def test_fixed_rotation_advances_per_pick_regardless_of_winner():
    e = engine()
    e.start()
    seen = []
    for pid, winner in [(1, "m3"), (2, "m3"), (3, "m1"), (4, "m2")]:
        seen.append(e.next_nominator())
        e.pick(pid, winner, 2)
    assert seen == ["m1", "m2", "m3", "m1"]
    assert e.next_nominator() == "m2"


def test_snake_nomination_reverses_each_round():
    e = engine(nomination_order_type="snake")
    e.start()
    seen = []
    for pid in range(1, 8):
        seen.append(e.next_nominator())
        e.pick(pid, "m1" if pid % 2 else "m2", 1)
    assert seen == ["m1", "m2", "m3", "m3", "m2", "m1", "m1"]


def test_nominate_validates_turn_and_availability():
    e = engine()
    e.start()
    nom = e.nominate(5)
    assert nom.player_id == 5 and nom.nominated_by == "m1"
    with pytest.raises(DraftError, match="m1's turn"):
        e.nominate(6, manager_id="m2")
    assert e.nominate(6, manager_id="m2", force=True).nominated_by == "m2"
    e.pick(6, "m3", 3)
    assert e.draft.picks[-1].nominated_by == "m2"
    assert e.draft.current_nomination is None
    with pytest.raises(DraftError, match="not available"):
        e.nominate(6)


def test_rotation_skips_managers_who_cannot_draft():
    e = engine()
    e.start()
    for pid in (1, 2, 3, 4, 5, 6):
        e.pick(pid, "m2", 1)  # m2 fills all 6 mandatory slots
    assert not e.can_draft("m2")
    assert e.next_nominator() == "m1"
    e.pick(7, "m1", 1)
    assert e.next_nominator() == "m3"  # m2 skipped
    e.pick(8, "m3", 1)
    assert e.next_nominator() == "m1"


def test_reorder_mid_draft_keeps_the_current_nominator_and_make_next_skips_ahead():
    e = engine()
    e.start()
    e.pick(1, "m1", 5)  # m1 nominated -> m2 is next
    assert e.next_nominator() == "m2"
    e.set_nomination_order(["m3", "m2", "m1"])  # reorder on the fly: m2 still nominates next
    assert e.next_nominator() == "m2"
    e.pick(2, "m2", 5)
    assert e.next_nominator() == "m1"  # then the new rotation continues: m3 m2 m1 -> after m2 comes m1
    e.set_next_nominator("m3")  # the room skipped ahead
    assert e.next_nominator() == "m3"
    e.pick(3, "m3", 5)
    assert e.next_nominator() == "m2"
    with pytest.raises(DraftError, match="unknown manager"):
        e.set_next_nominator("m9")
    for pid in (4, 5, 6, 7, 8):
        e.pick(pid, "m1", 1)  # fill m1 (6 slots incl. pick 1)
    with pytest.raises(DraftError, match="cannot draft"):
        e.set_next_nominator("m1")


def test_reorder_before_start_sets_first_nominator():
    e = engine()
    e.set_nomination_order(["m2", "m3", "m1"])
    e.start()
    assert e.next_nominator() == "m2"


def test_set_nomination_order_must_cover_every_manager_once():
    e = engine()
    with pytest.raises(DraftError):
        e.set_nomination_order(["m1", "m2"])
    e.set_nomination_order(["m3", "m1", "m2"])
    e.start()
    assert e.next_nominator() == "m3"


# ------------------------------------------------------------------ picks

def test_pick_validations():
    e = engine()
    e.start()
    with pytest.raises(DraftError, match="unknown manager"):
        e.pick(1, "m9", 5)
    with pytest.raises(DraftError, match="unknown player"):
        e.pick(999, "m1", 5)
    with pytest.raises(DraftError, match="below the minimum"):
        e.pick(1, "m1", 0)
    with pytest.raises(DraftError, match=r"exceeds max bid \$45.*5 other mandatory"):
        e.pick(1, "m1", 46)
    e.pick(1, "m1", 45)
    with pytest.raises(DraftError, match="already drafted"):
        e.pick(1, "m2", 5)
    with pytest.raises(DraftError, match="no open C"):
        e.pick(6, "m1", 1, slot="C")  # C already used by player 1
    p = e.pick(6, "m1", 1)  # C/PF player: C full -> UTIL
    assert p.slot == "UTIL"


def test_pick_fails_when_no_slot_fits():
    e = engine()
    e.start()
    for pid, slot in [(2, "PG"), (4, "UTIL"), (7, "BN"), (11, "BN")]:
        e.pick(pid, "m1", 1, slot=slot)
    e.pick(5, "m1", 1, slot="SG")
    assert e.open_slots("m1") == {"PG": 0, "SG": 0, "C": 1, "UTIL": 0, "BN": 0, "IR": 1}
    with pytest.raises(DraftError, match="no open slot that fits PG"):
        e.pick(12, "m1", 1)
    assert e.pick(1, "m1", 1).slot == "C"


def test_reservation_rule_holds_for_every_manager_through_a_full_draft():
    """Each manager always bids its max; nobody ever gets stuck unable to fill a mandatory slot."""
    e = engine()
    for pid in range(13, 21):  # 3 managers × 6 slots need 18 players; the default world has 12
        e.players[pid] = record(pid, f"Spare {pid}", "UTA")
        e.overrides[pid] = override(pid, ["PG", "SG", "SF", "PF", "C"])
    e.start([KeeperAssignment("m1", 1, 20)])
    pid = 2
    while True:
        nominator = e.next_nominator()
        if nominator is None:
            break
        b = e.budget(nominator)
        assert b.max_bid >= e.league.min_bid
        e.pick(pid, nominator, b.max_bid)
        pid += 1
    for m in ("m1", "m2", "m3"):
        b = e.budget(m)
        assert b.open_mandatory == 0 and b.remaining == 0 and len(e.picks_for(m)) == 6
    assert e.draft.status == "live" and e.progress() == 1.0
    e.complete()
    assert e.draft.status == "complete"


def test_bid_increment_enforced_when_greater_than_one():
    e = engine(bid_increment=5)
    e.start()
    with pytest.raises(DraftError, match="multiple"):
        e.pick(1, "m1", 7)
    assert e.pick(1, "m1", 6).price == 6


# ------------------------------------------------------------------ undo / reassign / reset

def test_undo_restores_availability_budget_and_pointer_but_not_keepers():
    e = engine()
    e.start([KeeperAssignment("m1", 1, 20)])
    e.pick(2, "m2", 10)
    e.pick(3, "m3", 8)
    assert e.draft.nomination_pointer == 2
    undone = e.undo()
    assert undone.player_id == 3 and e.is_available(3) and e.budget("m3").remaining == 50
    assert e.draft.nomination_pointer == 1 and e.next_nominator() == "m2"
    e.undo()
    with pytest.raises(DraftError, match="keepers are set at draft start"):
        e.undo()
    e.reset()
    assert e.draft.status == "setup" and e.draft.picks == [] and e.is_available(1)


def test_reassign_slot():
    e = engine()
    e.start()
    p = e.pick(2, "m1", 5)  # PG/SG -> PG
    assert p.slot == "PG"
    assert e.reassign_slot(p.pick_number, "BN").slot == "BN"
    assert e.open_slots("m1")["PG"] == 1
    with pytest.raises(DraftError, match="not eligible"):
        e.reassign_slot(p.pick_number, "C")
    with pytest.raises(DraftError, match="cannot be drafted into"):
        e.reassign_slot(p.pick_number, "IR")


def test_progress_and_keeper_records():
    e = engine()
    e.start([KeeperAssignment("m2", 2, 9)])
    assert e.progress() == 0.0
    e.pick(1, "m1", 5)
    assert e.progress() == pytest.approx(1 / 17)
    recs = e.keeper_records("2026-27")
    assert len(recs) == 1 and recs[0].manager_id == "m2" and recs[0].player_name == "Bo Guard"
    assert recs[0].cost.type == "auction" and recs[0].cost.amount == 9
