"""Season week view: Sleeper schedule/rosters/matchups/projections/box scores + ESPN tips -> one week's data."""

from datetime import date

from app.lockin.service import actual_fp, current_week, week_view
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
                               "settings": {"wins": 1, "losses": 0, "fpts": 50, "fpts_decimal": 25},
                               "metadata": {"p_nick_999": " The Joker ", "p_nick_123": "traded away", "allow_pn": "on"}}],
        "league/L1/users": [{"user_id": "u1", "display_name": "me", "avatar": "abc", "metadata": {"team_name": "Joker Fans"}}],
        "league/L1/matchups/1": [{"roster_id": 1, "matchup_id": 1, "points": 31.5}, {"roster_id": 2, "matchup_id": 1, "points": 20}],
        "scoreboard?dates=20261020": {"events": [{"date": "2026-10-21T02:00Z", "status": {"type": {"state": "post", "shortDetail": "Final"}},
                                                  "competitions": [{"competitors": [{"homeAway": "home", "team": {"abbreviation": "DEN"}},
                                                                                    {"homeAway": "away", "team": {"abbreviation": "LAL"}}]}]}]},
    }
    fetch = lambda url, ttl: next((v for k, v in canned.items() if k in url), None)

    w = week_view(s, fetch, today=date(2026, 10, 21))
    assert w["week"] == 1 and w["dates"] == ["2026-10-20", "2026-10-22"]
    team = w["teams"][0]
    assert team["name"] == "Joker Fans" and team["user"] == "me" and team["avatar"] == "https://sleepercdn.com/avatars/thumbs/abc"
    assert w["players"]["999"]["nick"] == "The Joker" and "123" not in w["players"]   # only nicknames of players he has
    assert team["is_user"] and team["fpts"] == 50.25 and team["wins"] == 1
    assert [len(m) for m in w["matchups"]] == [2]
    g1, g2 = w["players"]["999"]["games"]
    assert g1["opp"] == "LAL" and g1["state"] == "post" and g1["min"] == 36.0
    assert g1["fp"] == round(actual_fp(box, s.league.scoring), 2) and g1["fp"] > 20   # scored with the league formula
    assert g2["opp"] == "PHX" and g2["fp"] is None and g2["proj"] > 0 and g2["tip"] is None

    from app.lockin import service as season
    real = season.today_ct
    season.today_ct = lambda *_: date(2026, 10, 20)   # live mode: today's only game is over -> the lineup moves to the next game day
    try:
        assert week_view(s, fetch)["day"] == "2026-10-22"
    finally:
        season.today_ct = real
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
    from app.lockin.service import detect_lock

    games = [{"date": "2026-10-20", "fp": 18.5}, {"date": "2026-10-22", "fp": 11.0}, {"date": "2026-10-24", "fp": None}]
    assert detect_lock(18.5, games, None) == ("locked", "2026-10-20")    # counts an earlier game: locked
    assert detect_lock(11.0, games, None) == ("maybe", "2026-10-22")     # counts his latest: can't tell yet
    assert detect_lock(0, games, None) == ("no", None)
    assert detect_lock(11.0, games, "2026-10-20") == ("locked", "2026-10-20")   # your answer wins
    assert detect_lock(18.5, games, "") == ("no", None)


def test_lock_answers_are_saved_per_league_and_week(tmp_path):
    from app.lockin.service import read_locks, write_lock
    from nba_fantasy_shared.storage import JsonStore

    store = JsonStore(tmp_path)
    write_lock(store, "lg", 1, "999", "2026-10-20")
    write_lock(store, "lg", 1, "111", "")
    assert read_locks(store, "lg", 1) == {"999": "2026-10-20", "111": ""} and read_locks(store, "lg", 2) == {}
    write_lock(store, "lg", 1, "999", None)
    assert read_locks(store, "lg", 1) == {"111": ""}


def test_roster_rules_flag_a_healthy_player_on_ir_and_open_ir_spots(fixture_world):
    from app.lockin.service import team_plan

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


def test_news_merges_my_players_newest_first_and_skips_clips():
    from app.lockin.service import season_news

    feeds = {"1": [{"type": "Rotowire", "headline": "Pha (ankle) is questionable", "published": "2026-10-20T10:00:00Z"},
                   {"type": "Media", "headline": "Al Pha dunks", "published": "2026-10-21T10:00:00Z"}],
             "2": [{"type": "Rotowire", "headline": "Ta scored 30", "published": "2026-10-21T09:00:00Z"}],
             "3": [{"type": "Rotowire", "headline": "Ga (knee) is out", "published": "2026-10-21T11:00:00Z"}]}

    def fetch(url, ttl):
        if "teams/" in url:
            return {"athletes": [{"id": "1", "displayName": "Al Pha"}, {"id": "2", "displayName": "Bo Ta"}, {"id": "3", "displayName": "Cy Ga"}]}
        return {"feed": feeds[url.split("playerId=")[1].split("&")[0]]}

    view = {"teams": [{"is_user": True, "name": "me", "players": ["a", "b"]}, {"is_user": False, "name": "rival", "players": ["c"]}],
            "players": {"a": {"name": "Al Pha", "team": "MIA", "player_id": 1}, "b": {"name": "Bo Ta", "team": "MIA", "player_id": 2},
                        "c": {"name": "Cy Ga", "team": "MIA", "player_id": 3}}}
    n = season_news(view, fetch)
    assert [x["headline"] for x in n["mine"]] == ["Ta scored 30", "Pha (ankle) is questionable"]   # newest first, no clip
    assert [(x["headline"], x["owner"]) for x in n["league"]] == [("Ga (knee) is out", "rival")]   # other teams' players


def test_acquisitions_draft_price_then_moves_in_order():
    from types import SimpleNamespace
    from app.lockin.service import acquisitions

    def fetch(url, ttl):
        if url.endswith("/league/L"):
            return {"draft_id": "D"}
        if "/draft/D/picks" in url:
            return [{"player_id": "9", "roster_id": 1, "is_keeper": False, "metadata": {"amount": "24"}}]
        if url.endswith("/transactions/1"):
            return [{"type": "waiver", "status": "complete", "adds": {"9": 2}, "drops": None, "settings": {"waiver_bid": 7}, "status_updated": 30},
                    {"type": "free_agent", "status": "complete", "adds": None, "drops": {"9": 1}, "status_updated": 20},
                    {"type": "waiver", "status": "failed", "adds": {"9": 3}, "settings": {"waiver_bid": 9}, "status_updated": 25}]
        return []

    session = SimpleNamespace(league=SimpleNamespace(sleeper_league_id="L"))
    view = {"week": 1, "teams": [{"roster_id": 1, "name": "me"}, {"roster_id": 2, "name": "rival"}, {"roster_id": 3, "name": "other"}]}
    assert [(a["kind"], a["team"], a["price"]) for a in acquisitions(session, fetch, view, "9")] == [
        ("drafted", "me", 24), ("dropped", "me", None), ("claimed", "rival", 7)]   # failed claim skipped


def test_waivers_say_so_when_sleeper_sent_no_waiver_settings():
    from app.lockin.service import waivers

    assert waivers(None, {"teams": [], "waiver": None}) == {"error": "Couldn't receive Sleeper waiver and FAAB data.", "claims": []}


def test_timeline_changes_at_each_tip_so_a_later_player_can_take_the_slot():
    from app.lockin.service import week_timeline
    from app.lockin.weekplan import Game, PlanPlayer, plan_week

    shai = PlanPlayer(sid="s", name="s", eligibility=["PG"], slot="PG", games=[Game("2026-10-20", 15, tip="2026-10-21T01:30:00Z")])
    reav = PlanPlayer(sid="r", name="r", eligibility=["PG"], slot="BN", games=[Game("2026-10-21", 12, tip="2026-10-22T02:00:00Z")])
    plan_week([shai, reav], {"PG": 1})
    view = {"tz": "America/Chicago", "dates": ["2026-10-20", "2026-10-21"], "day": "2026-10-20"}
    segs = week_timeline([shai, reav], {"PG": 1}, view, None)["segments"]
    assert [(x["seats"]["PG"], x["to"][:16]) for x in segs] == [
        (["s"], "2026-10-20T20:30"),    # Shai starts until his 8:30 PM CT tip ...
        (["r"], "2026-10-26T00:00")]    # ... then the slot goes to the player who still has a game (Shai can be locked)
    assert shai.slot == "PG" and not shai.games[0].started   # the simulation leaves the real state alone
