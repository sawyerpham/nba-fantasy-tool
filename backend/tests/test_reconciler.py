"""Synthetic inputs that exercise every reconciliation stage without fixtures."""

from datetime import date, datetime, timezone

from nba_fantasy_shared.models.players import FantasyAttributes, PlayerBio, PlayerRef
from nba_fantasy_shared.reconcile import ReconcileInputs, normalize_name, reconcile

NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def nba(pid: int, name: str, team: str | None, birthdate: date | None = None) -> PlayerBio:
    first, last = name.split(" ", 1)
    return PlayerBio(source="nba_api", source_id=str(pid), full_name=name, first_name=first, last_name=last,
                     normalized_name=normalize_name(name), team_abbr=team, team_id=1 if team else None,
                     birthdate=birthdate, age=25.0, fetched_at=NOW)


def sleeper(sid: str, name: str, team: str | None, status: str = "ACT", active: bool = True,
            birthdate: date | None = None) -> PlayerBio:
    first, last = name.split(" ", 1)
    return PlayerBio(source="sleeper", source_id=sid, full_name=name, first_name=first, last_name=last,
                     normalized_name=normalize_name(name), team_abbr=team, roster_status=status, is_active=active,
                     birthdate=birthdate, age=26.0, height_in=80, fetched_at=NOW)


def ref(pid: int, name: str, active: bool = True) -> PlayerRef:
    first, last = name.split(" ", 1)
    return PlayerRef(player_id=pid, full_name=name, first_name=first, last_name=last, is_active=active)


def fa(sid: str, *positions: str) -> FantasyAttributes:
    return FantasyAttributes(sleeper_id=sid, fantasy_positions=list(positions))


def run(nba_pool, sleeper_all, static=(), fantasy=None, lookup=None):
    inputs = ReconcileInputs(roster_season="2026-27", nba_pool=list(nba_pool), sleeper_all=list(sleeper_all),
                             fantasy=fantasy or {}, nba_static=list(static))
    records, report = reconcile(inputs, birthdate_lookup=lookup)
    return {r.player_id: r for r in records}, report


def test_stage1_name_and_team_match_merges_bio_and_attaches_fantasy():
    recs, report = run([nba(203999, "Nikola Jokić", "DEN")],
                       [sleeper("1658", "Nikola Jokić", "DEN", birthdate=date(1995, 2, 19))],
                       fantasy={"1658": fa("1658", "C")})
    r = recs[203999]
    assert r.match_method == "name_team" and r.sleeper_id == "1658" and r.has_stats
    assert r.fantasy.fantasy_positions == ["C"]
    assert r.bio.birthdate == date(1995, 2, 19) and r.bio.height_in == 80 and r.bio.age == 26.0
    assert report.counts == {"name_team": 1} and not report.unmatched_nba and not report.unmatched_sleeper


def test_stage2_name_only_records_team_conflict_and_sleeper_wins():
    recs, report = run([nba(1, "Jonathan Kuminga", "ATL")], [sleeper("10", "Jonathan Kuminga", "MIN")])
    r = recs[1]
    assert r.match_method == "name_only" and r.team_abbr == "MIN"
    assert r.team_conflict == {"nba_api": "ATL", "sleeper": "MIN"}
    assert report.team_conflicts[0]["name"] == "Jonathan Kuminga"


def test_stage2_unsigned_per_sleeper_keeps_nba_team_and_flags():
    recs, report = run([nba(2, "Seth Curry", "GSW")], [sleeper("11", "Seth Curry", None, status="FA", active=True)])
    r = recs[2]
    assert r.match_method == "name_only" and r.team_abbr == "GSW" and r.unsigned_per_sleeper
    assert report.unsigned_per_sleeper[0]["sleeper_status"] == "FA"


def test_stage3_birthdate_tiebreak_resolves_collision_using_lookup():
    lookup_calls = []

    def lookup(pid: int):
        lookup_calls.append(pid)
        return date(2001, 8, 7)

    recs, report = run(
        [nba(3, "Jameer Nelson Jr.", "PHI")],
        [sleeper("20", "Jameer Nelson", None, status="FA", birthdate=date(2001, 8, 7)),
         sleeper("21", "Jameer Nelson", None, status="RET", active=False, birthdate=date(1982, 2, 9))],
    )
    assert recs[3].match_method == "nba_only"  # no lookup -> unresolved
    assert report.collisions[0]["resolved"] is False

    recs, report = run(
        [nba(3, "Jameer Nelson Jr.", "PHI")],
        [sleeper("20", "Jameer Nelson", None, status="FA", birthdate=date(2001, 8, 7)),
         sleeper("21", "Jameer Nelson", None, status="RET", active=False, birthdate=date(1982, 2, 9))],
        lookup=lookup,
    )
    assert recs[3].match_method == "birthdate" and recs[3].sleeper_id == "20"
    assert lookup_calls == [3]
    assert report.collisions[0]["resolved"] is True


def test_stage4_sleeper_only_player_recovered_from_static_list_keeps_nba_id():
    recs, report = run([], [sleeper("30", "Lonnie Walker", "DEN")], static=[ref(1629022, "Lonnie Walker IV", active=False)])
    r = recs[1629022]
    assert r.match_method == "static_list" and r.sleeper_id == "30" and r.has_stats and r.team_abbr == "DEN"
    assert report.counts == {"static_list": 1}


def test_stage4_static_collision_uses_birthdate_lookup():
    def lookup(pid: int):
        return {41: date(2000, 1, 1), 42: date(1990, 1, 1)}[pid]

    recs, report = run([], [sleeper("31", "Chris Smith", "LAL", birthdate=date(1990, 1, 1))],
                       static=[ref(41, "Chris Smith"), ref(42, "Chris Smith", active=False)], lookup=lookup)
    assert 42 in recs and recs[42].match_method == "static_list"
    assert report.collisions[0]["stage"] == "static_list" and report.collisions[0]["resolved"]


def test_stage5_sleeper_only_gets_synthetic_negative_id_and_no_stats():
    recs, report = run([], [sleeper("4460", "Josh Oduro", "NOP", status="TWO-WAY")])
    r = recs[-4460]
    assert r.match_method == "sleeper_only" and not r.has_stats and r.sleeper_id == "4460"
    assert report.unmatched_sleeper[0]["reason"] == "not_in_nba_static_list"


def test_stage5_nba_only_is_listed_not_dropped():
    recs, report = run([nba(5, "Nate Bittle", "TOR")], [])
    assert recs[5].match_method == "nba_only" and recs[5].fantasy is None and recs[5].has_stats
    assert report.unmatched_nba == [{"player_id": 5, "name": "Nate Bittle", "team": "TOR", "reason": "no_sleeper_name_match"}]


def test_unrostered_sleeper_players_are_not_added_as_records():
    recs, report = run([], [sleeper("50", "Kyle Lowry", None, status="RET", active=False)])
    assert recs == {} and report.sleeper_rostered_size == 0 and report.sleeper_all_size == 1


def test_each_sleeper_player_matches_at_most_once():
    recs, report = run([nba(1, "Jaylin Williams", "OKC"), nba(2, "Jaylin Williams", "MIA")],
                       [sleeper("60", "Jaylin Williams", "OKC")])
    assert recs[1].sleeper_id == "60" and recs[1].match_method == "name_team"
    assert recs[2].match_method == "nba_only" and recs[2].sleeper_id is None
