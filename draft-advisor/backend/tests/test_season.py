"""Season week view: Sleeper schedule/rosters/matchups/projections/box scores + ESPN tips -> one week's data."""

from datetime import date

from app.services.season import actual_fp, current_week, week_view
from tests.test_session import JOKIC, fixture_world, make_session  # noqa: F401 - fixture_world is a pytest fixture


def test_week_view_joins_schedule_projections_scores_and_tips(fixture_world):
    s = make_session(fixture_world, sleeper_league_id="L1")
    rec = s.players[JOKIC]
    s.players[JOKIC] = rec = rec.model_copy(update={"sleeper_id": "999", "team_abbr": "DEN"})
    s.managers[0] = s.managers[0].model_copy(update={"sleeper_roster_id": 1})
    box = {"pts": 40, "reb": 12, "ast": 10, "stl": 1, "blk": 1, "to": 3, "fgm": 15, "fga": 25, "ftm": 8, "fta": 9, "tpm": 2, "sp": 2160}
    canned = {
        "schedule/nba/regular/2026": [{"date": "2026-10-20", "week": 1, "home": {"team": "DEN"}, "away": {"team": "LAL"}},
                                      {"date": "2026-10-22", "week": 1, "home": {"team": "PHX"}, "away": {"team": "DEN"}},
                                      {"date": "2026-10-27", "week": 2, "home": {"team": "DEN"}, "away": {"team": "UTA"}}],
        "projections/nba/2026/1": [{"player_id": "999", "date": "2026-10-22", "stats": {"pts": 28, "reb": 12, "ast": 10}}],
        "stats/nba/2026/1": [{"player_id": "999", "date": "2026-10-20", "stats": box}],
        "league/L1/rosters": [{"roster_id": 1, "owner_id": "u1", "players": ["999"], "starters": ["999"],
                               "settings": {"wins": 1, "losses": 0, "fpts": 50, "fpts_decimal": 25}}],
        "league/L1/users": [{"user_id": "u1", "display_name": "spham5"}],
        "league/L1/matchups/1": [{"roster_id": 1, "matchup_id": 1, "points": 31.5}, {"roster_id": 2, "matchup_id": 1, "points": 20}],
        "scoreboard?dates=20261020": {"events": [{"date": "2026-10-21T02:00Z", "status": {"type": {"state": "post", "shortDetail": "Final"}},
                                                  "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": "DEN"}},
                                                                                    {"homeAway": "away", "team": {"abbreviation": "LAL"}}]}]}]},
    }
    fetch = lambda url, ttl: next((v for k, v in canned.items() if k in url), None)

    w = week_view(s, fetch, today=date(2026, 10, 21))
    assert w["week"] == 1 and w["dates"] == ["2026-10-20", "2026-10-22"]
    team = w["teams"][0]
    assert team["name"] == "spham5" and team["is_user"] and team["fpts"] == 50.25 and team["wins"] == 1
    assert [len(m) for m in w["matchups"]] == [2]
    g1, g2 = w["players"]["999"]["games"]
    assert g1["opp"] == "LAL" and g1["state"] == "post" and g1["min"] == 36.0
    assert g1["fp"] == round(actual_fp(box, s.league.scoring), 2) and g1["fp"] > 20   # scored with the league formula
    assert g2["opp"] == "PHX" and g2["fp"] is None and g2["proj"] > 0 and g2["tip"] is None

    from app.services import season
    season.RETIRED.add("999")   # a retired player never has games, even with a team and a schedule
    try:
        p = week_view(s, fetch, today=date(2026, 10, 21))["players"]["999"]
        assert p["retired"] and p["games"] == []
    finally:
        season.RETIRED.discard("999")


def test_current_week_is_the_monday_to_sunday_span_holding_today():
    weeks = {1: ["2026-10-20", "2026-10-25"], 2: ["2026-10-26", "2026-11-01"]}
    assert current_week(weeks, date(2026, 10, 16)) == 1    # preseason: week 1
    assert current_week(weeks, date(2026, 10, 25)) == 1    # Sunday still week 1
    assert current_week(weeks, date(2026, 10, 26)) == 2
    assert current_week(weeks, date(2027, 6, 1)) == 2      # after the season: the last week


def test_lock_detection_and_your_answers():
    from app.services.season import detect_lock

    games = [{"date": "2026-10-20", "fp": 18.5}, {"date": "2026-10-22", "fp": 11.0}, {"date": "2026-10-24", "fp": None}]
    assert detect_lock(18.5, games, None) == ("locked", "2026-10-20")    # counts an earlier game: locked
    assert detect_lock(11.0, games, None) == ("maybe", "2026-10-22")     # counts his latest: can't tell yet
    assert detect_lock(0, games, None) == ("no", None)
    assert detect_lock(11.0, games, "2026-10-20") == ("locked", "2026-10-20")   # your answer wins
    assert detect_lock(18.5, games, "") == ("no", None)


def test_lock_answers_are_saved_per_league_and_week(tmp_path):
    from app.services.season import read_locks, write_lock
    from nba_fantasy_shared.storage import JsonStore

    store = JsonStore(tmp_path)
    write_lock(store, "lg", 1, "999", "2026-10-20")
    write_lock(store, "lg", 1, "111", "")
    assert read_locks(store, "lg", 1) == {"999": "2026-10-20", "111": ""} and read_locks(store, "lg", 2) == {}
    write_lock(store, "lg", 1, "999", None)
    assert read_locks(store, "lg", 1) == {"111": ""}


def test_roster_rules_flag_a_healthy_player_on_ir_and_open_ir_spots(fixture_world):
    from app.services.season import team_plan

    s = make_session(fixture_world)
    positions = ["PG", "SG", "BN"]
    pl = lambda sid, inj="healthy": {"player_id": None, "name": sid, "team": "DEN", "pos": ["PG"], "injury": inj,
                                     "injury_note": "", "retired": False, "games": []}
    view = {"today": "2026-10-16", "dates": [], "roster_positions": positions, "reserve_slots": 2, "matchups": [],
            "players": {"a": pl("a"), "b": pl("b"), "c": pl("c", "out_long_term"), "back": pl("back")},
            "teams": [{"roster_id": 1, "name": "me", "is_user": True, "players": ["a", "b", "c", "back"],
                       "starters": ["a", "b"], "reserve": ["back"]}]}
    r = team_plan(s, view)["roster"]
    assert r["illegal"] == ["back"]                  # 3 active + a healthy player on IR = 4 > 3 spots
    assert r["ir_open"] == 1 and r["ir_candidates"] == ["c"]
