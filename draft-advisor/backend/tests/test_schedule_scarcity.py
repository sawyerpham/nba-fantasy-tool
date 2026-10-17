"""Lock-In schedule factor and position scarcity."""

from nba_fantasy_shared.models.league import LeagueSettings, RosterSlotSpec
from nba_fantasy_shared.providers.nba_api_provider import games_per_week

from app.core.engine.ranking import scarcity_bonus, schedule_factors
from app.core.services.sleeper_league import fantasy_weeks


def test_games_per_week_counts_regular_season_games_with_known_teams():
    game = lambda gid, week, home, away: {"gameId": gid, "weekNumber": week, "homeTeam": {"teamTricode": home}, "awayTeam": {"teamTricode": away}}
    sched = {"leagueSchedule": {"gameDates": [{"games": [
        game("0012600001", 0, "NYK", "BOS"),     # preseason
        game("0022600001", 1, "NYK", "BOS"),
        game("0022600002", 1, "NYK", "LAL"),
        game("0022600003", 8, None, None),       # NBA Cup knockout, teams not known yet
    ]}]}}
    assert games_per_week(sched) == {"NYK": {"1": 2}, "BOS": {"1": 1}, "LAL": {"1": 1}}


def test_more_games_and_playoff_weeks_lift_the_schedule_factor():
    games = {"A": {"1": 4, "2": 4}, "B": {"1": 2, "2": 2}, "C": {"1": 3, "2": 3, "3": 0}}
    f = schedule_factors(games, weeks=[1, 2, 3])
    assert f["A"] > f["C"] > f["B"]
    assert abs(sum(f.values()) / 3 - 1) < 1e-9
    # Same total games, but D has its 4-game week in the playoffs.
    late = schedule_factors({"D": {"1": 2, "2": 4}, "E": {"1": 4, "2": 2}}, weeks=[1, 2], playoff_weeks=[2])
    assert late["D"] > late["E"]


def test_fantasy_weeks_follow_the_sleeper_playoff_settings():
    games = {"A": {str(w): 3 for w in range(1, 26)}}
    details = {"seasons": [{"league": {"settings": {"start_week": 1, "playoff_week_start": 19, "playoff_teams": 6}}}]}
    weeks, playoffs = fantasy_weeks(details, games)
    assert playoffs == [19, 20, 21] and weeks == list(range(1, 22))
    assert fantasy_weeks(None, games) == (list(range(1, 26)), [])


def test_scarce_position_gets_a_bonus_and_deep_position_a_penalty():
    league = LeagueSettings(league_id="t", name="t", num_managers=1,
                            roster_slots=[RosterSlotSpec(slot="PG", count=1), RosterSlotSpec(slot="C", count=1), RosterSlotSpec(slot="BN", count=1)])
    # One starter per position; the best PG left over (9) is far better than the best C left over (2).
    values = {1: 20.0, 2: 10.0, 3: 9.0, 4: 2.0}
    elig = {1: ["PG"], 2: ["C"], 3: ["PG"], 4: ["C"]}
    bonus = scarcity_bonus(values, elig, league)
    assert bonus[2] > 0 > bonus[1]
    assert abs(bonus[2] - 3.5) < 1e-9 and abs(bonus[1] + 3.5) < 1e-9   # mean replacement 5.5: C 2 → +3.5, PG 9 → −3.5
    league.ranking.scarcity_weight = 0
    assert scarcity_bonus(values, elig, league) == {}
