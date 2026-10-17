"""Roster slots, greedy assignment, eligibility, and same-team stacking."""

from datetime import datetime, timezone

from app.core.engine import roster
from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, RosterSlotSpec
from tests.factories import default_world, small_league

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def pick(n, slot, player_id=None, manager="m1", price=1):
    return Pick(pick_number=n, player_id=player_id or 100 + n, manager_id=manager, price=price, slot=slot, timestamp=NOW)


def test_candidate_slots_most_specific_first():
    assert roster.candidate_slots(["PG", "SG"]) == ["PG", "SG", "G", "UTIL", "BN"]
    assert roster.candidate_slots(["C"]) == ["C", "UTIL", "BN"]
    assert roster.candidate_slots(["SF", "PF"]) == ["SF", "PF", "F", "UTIL", "BN"]
    assert roster.candidate_slots([]) == ["UTIL", "BN"]  # eligibility not set yet: generic slots only


def test_default_league_capacity_is_17_slots_15_mandatory():
    lg = LeagueSettings(league_id="L", name="L")
    caps = roster.slot_capacity(lg)
    assert caps == {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "UTIL": 2, "BN": 8, "IR": 2}
    assert roster.open_mandatory_count(lg, []) == 15
    assert sum(caps.values()) == 17


def test_greedy_assignment_fills_position_then_util_then_bench_never_ir():
    lg = LeagueSettings(league_id="L", name="L")
    picks: list[Pick] = []
    expected = ["PG", "SG", "UTIL", "UTIL"] + ["BN"] * 8
    for i, slot in enumerate(expected, 1):
        assigned = roster.assign_slot(lg, picks, ["PG", "SG"])
        assert assigned == slot, (i, assigned)
        picks.append(pick(i, assigned))
    assert roster.assign_slot(lg, picks, ["PG", "SG"]) is None   # SF/PF/C still open but a guard cannot fill them
    assert roster.assign_slot(lg, picks, ["C"]) == "C"
    assert roster.open_slots(lg, picks)["IR"] == 2                # IR untouched and never assigned
    assert roster.open_mandatory_count(lg, picks) == 3


def test_is_rosterable_false_when_only_non_fitting_position_slots_remain():
    lg = small_league()  # PG SG C UTIL BN BN
    picks = [pick(1, "PG"), pick(2, "SG"), pick(3, "UTIL"), pick(4, "BN"), pick(5, "BN")]
    assert roster.open_slots(lg, picks) == {"PG": 0, "SG": 0, "C": 1, "UTIL": 0, "BN": 0, "IR": 1}
    assert roster.is_rosterable(lg, picks, ["C", "PF"])
    assert not roster.is_rosterable(lg, picks, ["PG"])
    assert not roster.is_rosterable(lg, picks, [])


def test_validate_slot_messages():
    lg = small_league()
    assert "cannot be drafted into" in roster.validate_slot(lg, [], ["C"], "IR")
    assert "league has no" in roster.validate_slot(lg, [], ["PG"], "G")
    assert "not eligible" in roster.validate_slot(lg, [], ["PG"], "C")
    assert "no open PG" in roster.validate_slot(lg, [pick(1, "PG")], ["PG"], "PG")
    assert roster.validate_slot(lg, [], ["PG"], "PG") is None
    assert roster.validate_slot(lg, [], [], "BN") is None


def test_flex_slots_accept_the_right_positions():
    lg = LeagueSettings(league_id="L", name="L", roster_slots=[RosterSlotSpec(slot="G", count=1), RosterSlotSpec(slot="F", count=1),
                                                             RosterSlotSpec(slot="BN", count=1)], budget_per_manager=10)
    assert roster.assign_slot(lg, [], ["PG"]) == "G"
    assert roster.assign_slot(lg, [], ["PF"]) == "F"
    assert roster.assign_slot(lg, [], ["C"]) == "BN"


def test_team_stack_and_stack_if_added():
    players, _, _ = default_world()
    picks = [pick(1, "C", player_id=1), pick(2, "PG", player_id=2), pick(3, "UTIL", player_id=3)]  # DEN, DEN, LAL
    stack = roster.team_stack(players, picks)
    assert stack == {"DEN": 2, "LAL": 1}
    assert roster.stack_if_added(stack, "DEN") == 3
    assert roster.stack_if_added(stack, "LAL") == 2
    assert roster.stack_if_added(stack, "BOS") == 1
    assert roster.stack_if_added(stack, None) == 0


def test_stack_ignores_picks_for_unknown_players():
    players, _, _ = default_world()
    assert roster.team_stack(players, [pick(1, "BN", player_id=999)]) == {}
