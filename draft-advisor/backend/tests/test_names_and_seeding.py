from datetime import datetime, timezone

import pytest

from nba_fantasy_shared.models.players import FantasyAttributes, PlayerBio, PlayerOverrides, PlayerRecord
from nba_fantasy_shared.reconcile import normalize_name, seed_overrides

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 3, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Lonnie Walker IV", "Lonnie Walker"),
        ("Patrick Baldwin Jr.", "Patrick Baldwin"),
        ("Nikola Jokić", "nikola jokic"),
        ("A.J. Lawson", "aj lawson"),
        ("Jameer Nelson Jr.", "Jameer Nelson"),
        ("  Moussa   Diabaté ", "moussa diabate"),
    ],
)
def test_normalize_name_pairs(a, b):
    assert normalize_name(a) == normalize_name(b)


def test_normalize_name_empty():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


def bio(pid: str = "1", source: str = "nba_api") -> PlayerBio:
    return PlayerBio(source=source, source_id=pid, full_name="Test Player", first_name="Test", last_name="Player",
                     normalized_name="test player", fetched_at=NOW)


def record(player_id: int, fantasy: FantasyAttributes | None) -> PlayerRecord:
    return PlayerRecord(player_id=player_id, sleeper_id=fantasy.sleeper_id if fantasy else None, full_name="Test Player",
                        first_name="Test", last_name="Player", normalized_name="test player", bio=bio(),
                        fantasy=fantasy, match_method="name_team" if fantasy else "nba_only")


def test_seed_sets_eligibility_and_injury_from_sleeper_with_source_tracking():
    fa = FantasyAttributes(sleeper_id="9", fantasy_positions=["PG", "SG"], injury_status_raw="Out",
                           injury_body_part="Knee", injury_notes="Surgery")
    out = seed_overrides([record(1, fa)], {}, now=NOW)
    o = out[1]
    assert o.eligibility == ["PG", "SG"] and o.eligibility_source == "sleeper"
    assert o.injury_status == "out_short_term" and o.injury_source == "sleeper"
    assert o.injury_note == "Knee — Surgery" and o.injury_sleeper_raw == "Out"
    assert o.seeded_at == NOW


def test_seed_maps_dtd_ir_and_none():
    for raw, expected in [("DTD", "day_to_day"), ("IR", "out_long_term"), (None, "healthy")]:
        fa = FantasyAttributes(sleeper_id="9", fantasy_positions=["C"], injury_status_raw=raw)
        assert seed_overrides([record(1, fa)], {}, now=NOW)[1].injury_status == expected


def test_seed_always_takes_sleeper_and_keeps_the_users_notes():
    existing = {
        1: PlayerOverrides(player_id=1, eligibility=["C"], eligibility_source="manual",
                           injury_status="healthy", injury_source="sleeper", updated_at=NOW, notes="keep me"),
        2: PlayerOverrides(player_id=2, eligibility=["PG"], eligibility_source="sleeper",
                           injury_status="out_season", injury_source="manual", injury_note="ACL", updated_at=NOW),
    }
    fa1 = FantasyAttributes(sleeper_id="1", fantasy_positions=["PF", "SF"], injury_status_raw="DTD", injury_body_part="Ankle")
    fa2 = FantasyAttributes(sleeper_id="2", fantasy_positions=["PG", "SG"], injury_status_raw=None)
    out = seed_overrides([record(1, fa1), record(2, fa2)], existing, now=LATER)
    # old manual values (from before manual editing was removed) are replaced by Sleeper's
    assert out[1].eligibility == ["PF", "SF"] and out[1].eligibility_source == "sleeper"
    assert out[1].injury_status == "day_to_day" and out[1].injury_note == "Ankle" and out[1].notes == "keep me"
    assert out[2].eligibility == ["PG", "SG"] and out[2].eligibility_source == "sleeper"
    assert out[2].injury_status == "healthy" and out[2].injury_source == "sleeper" and out[2].injury_note == ""
    assert out[2].injury_sleeper_raw is None  # raw value still recorded for display


def test_seed_leaves_players_without_sleeper_data_untouched():
    existing = {3: PlayerOverrides(player_id=3, eligibility=["SF"], eligibility_source="manual", updated_at=NOW)}
    out = seed_overrides([record(3, None), record(4, None)], existing, now=LATER)
    assert out[3].eligibility == ["SF"] and out[3].updated_at == NOW
    assert out[4].eligibility == [] and out[4].eligibility_source == "none" and out[4].injury_source == "none"


def test_seed_keeps_overrides_for_players_missing_from_the_pool():
    existing = {99: PlayerOverrides(player_id=99, eligibility=["C"], eligibility_source="manual", updated_at=NOW)}
    out = seed_overrides([record(1, None)], existing, now=LATER)
    assert 99 in out and out[99].eligibility == ["C"]


def test_seed_custom_injury_map():
    fa = FantasyAttributes(sleeper_id="9", fantasy_positions=["C"], injury_status_raw="Out")
    out = seed_overrides([record(1, fa)], {}, injury_map={"Out": "out_long_term"}, now=NOW)
    assert out[1].injury_status == "out_long_term"


def test_preseason_short_term_tags_and_rest_seed_as_healthy_but_out_still_counts():
    from nba_fantasy_shared.models.players import FantasyAttributes

    def fa(raw, part=None):
        return FantasyAttributes(sleeper_id="1", fantasy_positions=["PG"], injury_status_raw=raw, injury_body_part=part)

    pre = lambda f: seed_overrides([record(1, f)], {}, now=NOW, ignore_short_term=True)[1]
    assert pre(fa("DTD", "Ankle")).injury_status == "healthy" and pre(fa("DTD", "Ankle")).injury_sleeper_raw == "DTD"
    assert pre(fa("GTD")).injury_status == "healthy"
    assert pre(fa("Out", "Knee")).injury_status == "out_short_term"
    in_season = seed_overrides([record(1, fa("DTD", "Ankle"))], {}, now=NOW)[1]
    assert in_season.injury_status == "day_to_day"
    assert seed_overrides([record(1, fa("DTD", "Rest"))], {}, now=NOW)[1].injury_status == "healthy"
