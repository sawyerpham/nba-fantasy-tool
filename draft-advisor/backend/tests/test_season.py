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


def test_current_week_is_the_monday_to_sunday_span_holding_today():
    weeks = {1: ["2026-10-20", "2026-10-25"], 2: ["2026-10-26", "2026-11-01"]}
    assert current_week(weeks, date(2026, 10, 16)) == 1    # preseason: week 1
    assert current_week(weeks, date(2026, 10, 25)) == 1    # Sunday still week 1
    assert current_week(weeks, date(2026, 10, 26)) == 2
    assert current_week(weeks, date(2027, 6, 1)) == 2      # after the season: the last week
