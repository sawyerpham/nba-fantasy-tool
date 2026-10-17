"""Normalization against real captured responses (tests/fixtures, pulled 2026-09-02)."""

import json
from datetime import date

from nba_fantasy_shared.providers.nba_api_provider import (
    bio_from_playerindex_row,
    detail_from_responses,
    game_line_from_row,
    parse_game_date,
    parse_height,
    parse_matchup,
    season_from_season_id,
    sort_game_lines,
)
from nba_fantasy_shared.providers.sleeper_provider import (
    bio_from_sleeper_entry,
    fantasy_attributes_from_entry,
    is_placeholder,
    is_rostered,
    platform_league_from_json,
    platform_state_from_json,
)

JOKIC = 203999


def load(fixtures_dir, rel):
    with (fixtures_dir / rel).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_parsers():
    assert parse_height("6-11") == 83 and parse_height("83") == 83 and parse_height(None) is None
    assert parse_matchup("DEN @ SAS") == ("DEN", "SAS", False)
    assert parse_matchup("DEN vs. SAS") == ("DEN", "SAS", True)
    assert parse_game_date("Apr 12, 2026") == date(2026, 4, 12)
    assert parse_game_date("2026-04-12T00:00:00") == date(2026, 4, 12)
    assert season_from_season_id("22025") == "2025-26"


def test_per_player_and_batch_rows_normalize_to_identical_game_lines(fixtures_dir):
    per_player = [game_line_from_row(r) for r in load(fixtures_dir, "nba/playergamelog_203999_2025-26.json")]
    batch = [game_line_from_row(r) for r in load(fixtures_dir, "nba/playergamelogs_2025-26.json") if r["PLAYER_ID"] == JOKIC]
    assert len(per_player) == 65 == len(batch)
    a = {g.game_id: g for g in per_player}
    b = {g.game_id: g for g in batch}
    assert a.keys() == b.keys()
    for gid, ga in a.items():
        gb = b[gid]
        assert (ga.game_date, ga.team_abbr, ga.opponent_abbr, ga.home, ga.win) == (gb.game_date, gb.team_abbr, gb.opponent_abbr, gb.home, gb.win)
        for stat in ("pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta", "fg3m", "fg3a", "oreb", "dreb", "pf", "plus_minus"):
            assert getattr(ga, stat) == getattr(gb, stat), (gid, stat)
        assert abs(ga.minutes - gb.minutes) < 1.0  # per-player MIN is a rounded int, batch MIN is float
    ordered = sort_game_lines(per_player)
    assert ordered[0].game_date == date(2025, 10, 23) and ordered[-1].game_date == date(2026, 4, 12)
    assert all(g.season == "2025-26" and g.player_id == JOKIC for g in ordered)


def test_playerindex_row_to_bio(fixtures_dir):
    rows = {r["PERSON_ID"]: r for r in load(fixtures_dir, "nba/playerindex_2026-27.json")}
    bio = bio_from_playerindex_row(rows[JOKIC])
    assert bio.source == "nba_api" and bio.source_id == "203999"
    assert bio.full_name == "Nikola Jokić" and bio.normalized_name == "nikola jokic"
    assert bio.team_abbr == "DEN" and bio.team_id == 1610612743
    assert bio.height_in == 83 and bio.weight_lbs == 284
    assert (bio.draft_year, bio.draft_round, bio.draft_number) == (2014, 2, 41)
    assert bio.position_raw in {"C", "C-F", "F-C"}


def test_sleeper_entry_to_bio_and_fantasy_attributes(fixtures_dir):
    payload = load(fixtures_dir, "sleeper/players_nba.json")
    jokic = payload["1658"]
    bio = bio_from_sleeper_entry(jokic)
    assert bio.source == "sleeper" and bio.source_id == "1658" and bio.team_abbr == "DEN"
    assert bio.birthdate == date(1995, 2, 19) and bio.age == 31.0 and bio.height_in == 83 and bio.weight_lbs == 284
    assert bio.roster_status == "ACT" and bio.is_active
    fa = fantasy_attributes_from_entry(jokic)
    assert fa.fantasy_positions == ["C"]
    assert fa.fantasy_positions_alt == ["C", "PF"]  # metadata variant kept for reference only (decision 7)
    assert fa.injury_status_raw is None and fa.search_rank == 2 and fa.news_updated is not None

    butler = next(e for e in payload.values() if e.get("last_name") == "Butler")
    fb = fantasy_attributes_from_entry(butler)
    assert fb.injury_status_raw == "Out" and fb.injury_body_part == "Knee" and fb.injury_notes == "Surgery"


def test_sleeper_placeholders_are_filtered(fixtures_dir):
    payload = load(fixtures_dir, "sleeper/players_nba.json")
    defs = [e for e in payload.values() if e.get("position") == "DEF"]
    dups = [e for e in payload.values() if e.get("status") == "DUP"]
    assert defs and dups, "fixture must carry one DEF and one DUP placeholder"
    assert all(is_placeholder(e) and not is_rostered(e) for e in defs + dups)
    assert is_rostered(payload["1658"])
    assert not is_rostered(payload["1041"])  # Seth Curry: FA, no team
    assert sum(1 for e in payload.values() if is_rostered(e)) == 20


def test_detail_from_responses_with_and_without_career(fixtures_dir):
    jokic = detail_from_responses(JOKIC, load(fixtures_dir, "nba/commonplayerinfo_203999.json"),
                                  load(fixtures_dir, "nba/playercareerstats_203999.json"))
    assert jokic.birthdate == date(1995, 2, 19) and jokic.season_exp == 11 and jokic.height_in == 83
    assert len(jokic.season_totals) == 11 and jokic.season_totals[-1].season == "2025-26"
    assert jokic.season_totals[-1].gp == 65 and jokic.season_totals[-1].team_abbr == "DEN"

    rookie = detail_from_responses(1642392, load(fixtures_dir, "nba/commonplayerinfo_1642392.json"),
                                   load(fixtures_dir, "nba/playercareerstats_1642392.json"))
    assert rookie.birthdate == date(2001, 8, 7) and rookie.season_totals == []


def test_platform_state_and_league(fixtures_dir):
    state = platform_state_from_json(load(fixtures_dir, "sleeper/state_nba.json"))
    assert state.season == "2026" and state.season_type == "off" and state.previous_season == "2025"
    assert state.season_start_date == date(2026, 10, 20)

    league = platform_league_from_json(load(fixtures_dir, "sleeper/league_289646328504385536.json"))
    assert league.sport == "nfl" and league.total_rosters == 12 and league.status == "complete"
    assert "BN" in league.roster_positions and league.settings["num_teams"] == 12
    assert isinstance(league.scoring_settings["rec_td"], float)
