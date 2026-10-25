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


def test_a_counted_latest_game_is_guessed_locked_when_locking_beats_waiting(fixture_world):
    from app.lockin.service import team_plan

    s = make_session(fixture_world)
    g = lambda d, fp=None, proj=10.0, st="pre": {"date": d, "proj": proj, "fp": fp, "state": st, "tip": None, "min": None}   # noqa: E731
    pl = lambda sid, games: {"player_id": None, "name": sid, "team": "DEN", "pos": ["PG"], "injury": "healthy",   # noqa: E731
                             "injury_note": "", "retired": False, "games": games}
    view = {"today": "2026-10-21", "dates": [], "roster_positions": ["PG", "PG"], "reserve_slots": 0,
            "matchups": [[{"roster_id": 1, "players_points": {"hot": 18.6, "cold": 4.0}}]],
            "players": {"hot": pl("hot", [g("2026-10-20", 18.6, st="post"), g("2026-10-23")]),
                        "cold": pl("cold", [g("2026-10-20", 4.0, st="post"), g("2026-10-23")])},
            "teams": [{"roster_id": 1, "name": "rival", "is_user": False, "players": ["hot", "cold"], "starters": ["hot", "cold"], "reserve": []}]}
    out = {p["sid"]: p for p in team_plan(s, view, roster_id=1)["players"]}
    assert out["hot"]["lock_status"] == "guess" and out["hot"]["locked"] == 18.6   # 18.6 beats ~10 from his next game
    assert out["cold"]["lock_status"] == "maybe" and out["cold"]["locked"] is None  # 4 doesn't: he'd wait
    assert team_plan(s, view, roster_id=1)["points"] == 18.6
    view["players"]["hot"]["games"][0]["state"] = "in"   # still playing: can't be locked yet, so no guess
    assert {p["sid"]: p["lock_status"] for p in team_plan(s, view, roster_id=1)["players"]}["hot"] == "maybe"
    view["players"]["hot"]["games"][0]["state"] = "post"
    view["teams"][0]["is_user"] = True   # your own team: no guessing, you know what you locked
    assert team_plan(s, view)["points"] == 0


def test_news_merges_my_players_newest_first_and_flags_injuries():
    from app.lockin.service import season_news

    note = lambda t, d, ms: {"published": ms, "metadata": {"title": t, "description": d}}   # noqa: E731 - Sleeper's shape
    feeds = {"a": [note("Al Pha - Questionable", "Pha (ankle) is questionable Monday.", 1_792_000_000_000),
                   note("", "", 1_792_900_000_000)],                                          # untitled: skipped
             "b": [note("Bo Ta - Resting Monday", "Ta (rest) won't play Monday.", 1_792_100_000_000)],
             "c": [note("Cy Ga - Suffers torn Achilles", "Ga suffered a season-ending Achilles tear, Shams Charania reports.", 1_792_200_000_000)],
             "f": [note("Ben Simmons - Suffers torn Achilles", "Simmons tore his right Achilles.", 1_792_300_000_000)]}
    fetch = lambda url, ttl: feeds[url.split("/")[-2]]   # noqa: E731

    view = {"teams": [{"is_user": True, "name": "me", "user": "meuser", "players": ["a", "b"]},
                      {"is_user": False, "name": "rival", "user": "rivaluser", "players": ["c"]}],
            "players": {"a": {"name": "Al Pha", "player_id": 1}, "b": {"name": "Bo Ta", "player_id": 2}, "c": {"name": "Cy Ga", "player_id": 3},
                        "f": {"name": "Ben Simmons", "player_id": 4, "team": "SAC"}}}
    n = season_news(view, fetch, free=["f", "c", "zz"])   # c is rostered, zz unknown: neither is a free agent
    assert [(x["headline"], x["injury"]) for x in n["mine"]] == [("Bo Ta - Resting Monday", False), ("Al Pha - Questionable", True)]
    assert [(x["headline"], x["injury"], x["user"]) for x in n["league"]] == [("Cy Ga - Suffers torn Achilles", True, "rivaluser")]
    assert [(x["name"], x["team"], x["owner"]) for x in n["free"]] == [("Ben Simmons", "SAC", None)]
    assert n["mine"][0]["published"].startswith("2026-")


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

    assert waivers(None, None, {"teams": [], "waiver": None}) == {"error": "Couldn't receive Sleeper waiver and FAAB data.", "claims": []}


def test_timeline_hands_the_slot_to_a_later_player_at_his_check_in():
    from app.lockin.service import week_timeline
    from app.lockin.weekplan import Game, PlanPlayer, plan_week

    shai = PlanPlayer(sid="s", name="s", eligibility=["PG"], slot="PG", games=[Game("2026-10-20", 15, tip="2026-10-21T01:30:00Z")])
    reav = PlanPlayer(sid="r", name="r", eligibility=["PG"], slot="BN", games=[Game("2026-10-21", 12, tip="2026-10-22T02:00:00Z")])
    plan_week([shai, reav], {"PG": 1})
    view = {"tz": "America/Chicago", "dates": ["2026-10-20", "2026-10-21"], "day": "2026-10-20"}
    segs = week_timeline([shai, reav], {"PG": 1}, view, None)["segments"]
    assert [(x["seats"]["PG"], x["to"][:16]) for x in segs] == [
        (["s"], "2026-10-21T20:45"),    # Shai (Tue 8:30 PM) holds the slot until the check 15 min before Reaves's Wed tip ...
        (["r"], "2026-10-26T00:00")]    # ... then the slot goes to the player who still has a game (Shai can be locked)
    assert shai.slot == "PG" and not shai.games[0].started   # the simulation leaves the real state alone


def test_timeline_does_a_nights_swaps_at_one_check_in_and_never_moves_a_player_mid_game():
    from app.lockin.service import week_timeline
    from app.lockin.weekplan import Game, PlanPlayer, plan_week

    def guy(sid, slot, tip):   # Wed 10/21 (CDT = UTC-5)
        return PlanPlayer(sid=sid, name=sid, eligibility=["C"], slot=slot, games=[Game("2026-10-21", 20, tip=tip)])
    six, six30, seven = guy("6:00", "C", "2026-10-21T23:00:00Z"), guy("6:30", "C", "2026-10-21T23:30:00Z"), guy("7:00", "C", "2026-10-22T00:00:00Z")
    nine, nine30 = guy("9:00", "BN", "2026-10-22T02:00:00Z"), guy("9:30", "BN", "2026-10-22T02:30:00Z")
    ps = [six, six30, seven, nine, nine30]
    plan_week(ps, {"C": 3})
    view = {"tz": "America/Chicago", "dates": ["2026-10-21"], "day": "2026-10-21"}
    segs = week_timeline(ps, {"C": 3}, view, None)["segments"]
    assert [(sorted(x["seats"]["C"]), x["to"][:16]) for x in segs] == [
        (["6:00", "6:30", "7:00"], "2026-10-21T20:45"),   # the early games start; one check at 8:45 PM ...
        (["7:00", "9:00", "9:30"], "2026-10-26T00:00")]   # ... swaps in the 9:00 AND 9:30 games; 7:00 is still playing


def test_lead_stats_points_first_then_what_is_worth_fantasy_points(fixture_world):
    from app.lockin.service import lead_stats

    s = make_session(fixture_world)
    lead = lead_stats({"pts": 20, "reb": 10, "ast": 1, "stl": 0, "blk": 3, "tpm": 0}, s.league.scoring)
    assert lead[0] == ["PTS", 20] and ["BLK", 3] in lead and ["REB", 10] in lead
    assert not any(label in ("STL", "3PM", "AST") for label, _ in lead)   # zeros and a lone assist aren't worth showing


def test_team_ranks_offense_from_its_box_scores_and_defense_from_its_opponents():
    from app.lockin.service import team_ranks

    def row(team, opp, game="g1", **st):
        return {"player_id": f"TEAM_{team}", "team": team, "opponent": opp, "game_id": game, "stats": st}
    rows = [row("MEM", "BOS", pts=120, reb=50, to=20), row("BOS", "MEM", pts=100, reb=40, to=10),
            row("MEM", "DEN", pts=110, reb=50, to=18), row("DEN", "MEM", pts=130, reb=45, to=12),
            row("DEN", "BOS", pts=105, reb=35, to=15), row("BOS", "DEN", pts=115, reb=40, to=14),
            {"player_id": "123", "team": "MEM", "opponent": "BOS", "game_id": "g1", "stats": {"pts": 40}},   # a player row
            row("MEM", "LAL", game="live", pts=30, reb=9, to=2)]   # in progress (not in done): ignored
    done = {"g1"}
    r = team_ranks(rows, "MEM", done)
    assert r["games"] == 2 and r["teams"] == 3
    assert r["offense"]["pts"] == {"v": 115.0, "rank": 2}                 # DEN 117.5 scores more
    assert r["offense"]["reb"]["rank"] == 1 and r["offense"]["to"]["rank"] == 3   # most turnovers: last
    assert r["defense"]["pts"] == {"v": 115.0, "rank": 3}                 # allows the most (BOS 107.5, DEN 112.5)
    assert team_ranks(rows, "BOS", done)["offense"]["reb"]["rank"] == 2 == team_ranks(rows, "DEN", done)["offense"]["reb"]["rank"]  # a tie
    assert team_ranks(rows, "LAL", done) is None


def test_next_waiver_run_is_the_coming_saturday_or_sunday_at_2_am():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.lockin.service import next_waiver_run

    ct = ZoneInfo("America/Chicago")
    at = lambda *a: datetime(*a, tzinfo=ct)
    assert next_waiver_run(at(2026, 10, 21, 15, 0), [5, 6], 2) == at(2026, 10, 24, 2, 0)    # Wed -> Sat 2 AM
    assert next_waiver_run(at(2026, 10, 24, 1, 59), [5, 6], 2) == at(2026, 10, 24, 2, 0)    # Sat just before the run
    assert next_waiver_run(at(2026, 10, 24, 18, 0), [5, 6], 2) == at(2026, 10, 25, 2, 0)    # Sat evening -> Sun 2 AM
    assert next_waiver_run(at(2026, 10, 25, 2, 0), [5, 6], 2) == at(2026, 10, 31, 2, 0)     # Sun's run just went -> next Sat
    assert next_waiver_run(at(2026, 10, 24, 18, 0), [2], 0) == at(2026, 10, 28, 0, 0)   # a league set to Wed midnight


def test_season_averages_count_finished_games_in_league_scoring(fixture_world):
    from app.lockin.service import season_averages

    s = make_session(fixture_world)
    box = {"pts": 20, "reb": 10, "ast": 4, "stl": 1, "blk": 1, "to": 2, "tpm": 2, "sp": 1800}
    rows = [{"player_id": "7", "game_id": "g1", "stats": box},
            {"player_id": "7", "game_id": "g2", "stats": {**box, "pts": 10, "reb": 6}},
            {"player_id": "7", "game_id": "live", "stats": {**box, "pts": 2}},        # in progress: not counted
            {"player_id": "7", "game_id": "g3", "stats": {"pts": 0}},                 # DNP (no minutes)
            {"player_id": "8", "game_id": "g1", "stats": box}]                        # not asked for
    a = season_averages(rows, {"7"}, {"g1", "g2", "g3"}, s.league.scoring)
    assert set(a) == {"7"} and a["7"]["gp"] == 2 and a["7"]["pts"] == 15.0 and a["7"]["reb"] == 8.0
    assert a["7"]["fp"] == round((actual_fp(box, s.league.scoring) + actual_fp({**box, "pts": 10, "reb": 6}, s.league.scoring)) / 2, 1)


def test_game_card_shows_both_teams_before_the_tip_with_their_ranks(fixture_world):
    from app.lockin.service import game_detail

    s = make_session(fixture_world)
    team = lambda abbr, name, ha, rec: {"homeAway": ha, "team": {"abbreviation": abbr, "displayName": name,
                                                                "logos": [{"href": f"https://logo/{abbr}.png"}]},
                                       "record": [{"type": "total", "summary": rec}]}
    canned = {
        "summary?event=9": {"header": {"competitions": [{"date": "2026-10-25T22:00Z", "status": {"type": {"state": "pre"}},
                                                         "competitors": [team("UTAH", "Utah Jazz", "home", "1-1"), team("LAL", "Los Angeles Lakers", "away", "2-0")]}]}},
        "schedule/nba/regular/2026": [{"date": "2026-10-21", "week": 1, "status": "complete", "game_id": "g1",
                                       "home": {"team": "UTA"}, "away": {"team": "LAL"}}],
        "stats/nba/2026/1": [{"player_id": "TEAM_UTA", "team": "UTA", "opponent": "LAL", "game_id": "g1", "stats": {"pts": 100}},
                             {"player_id": "TEAM_LAL", "team": "LAL", "opponent": "UTA", "game_id": "g1", "stats": {"pts": 110}}],
    }
    g = game_detail(s, lambda url, ttl: next((v for k, v in canned.items() if k in url), None), "9")
    away, home = g["teams"]
    assert g["state"] == "pre" and (away["abbr"], home["abbr"]) == ("LAL", "UTA")      # ESPN's UTAH -> UTA, away first
    assert home["name"] == "Utah Jazz" and home["record"] == "1-1" and home["logo"] == "https://logo/UTAH.png"
    assert home["players"] == [] and home["ranks"]["offense"]["pts"]["rank"] == 2 and away["ranks"]["offense"]["pts"]["rank"] == 1


def test_sleeper_injuries_tag_every_hurt_player_red_or_yellow():
    from app.lockin.service import sleeper_injuries

    feed = {"1": {"full_name": "Zach Edey", "team": "MEM", "injury_status": "Out", "injury_body_part": "Ankle"},
            "2": {"full_name": "Cedric Coward", "team": "MEM", "injury_status": "GTD", "injury_body_part": "Wrist"},
            "3": {"full_name": "Healthy Guy", "team": "MEM", "injury_status": None},
            "4": {"full_name": "Free Agent", "team": None, "injury_status": "Out"},
            "5": {"full_name": "Long Term", "team": "BKN", "injury_status": "IR"}}
    hurt = sleeper_injuries(lambda url, ttl: feed)
    assert set(hurt) == {"1", "2", "5"}                                   # healthy and teamless players left out
    assert (hurt["1"]["group"], hurt["2"]["group"], hurt["5"]["group"]) == ("out", "q", "out")
    assert hurt["1"]["body"] == "Ankle" and hurt["2"]["team"] == "MEM"
    assert sleeper_injuries(lambda url, ttl: (_ for _ in ()).throw(OSError("down"))) == {}   # Sleeper down: no colours, no crash
