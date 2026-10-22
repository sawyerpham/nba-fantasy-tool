"""Week plan: lock-now vs wait values, optimal seating, and which slot a lock goes into."""

import pytest

from app.lockin.weekplan import Game, PlanPlayer, expected_max, plan_week, swing_of, wait_value

SLOTS = {"PG": 2, "SG": 2}


def pp(sid, elig, slot, games, **kw):
    return PlanPlayer(sid=sid, name=sid, eligibility=elig, slot=slot, games=games, **kw)


def future(*projs):
    return [Game(date=f"2026-10-2{i + 2}", proj=p) for i, p in enumerate(projs)]


def test_expected_max_and_wait_value_math():
    assert expected_max(0, 1, 0) == pytest.approx(0.3989, abs=1e-4)
    assert expected_max(10, 0, 12) == 12
    assert wait_value(future(20), 0.3, "healthy") == pytest.approx(0.97 * 20)          # last game: just its projection
    two = wait_value(future(20, 20), 0.3, "healthy")
    assert two > 20                                                                      # two chances beat one
    assert wait_value(future(20, 20), 0.3, "out_long_term") == 0                        # never plays: worth 0
    assert wait_value(future(20), 0.3, "day_to_day") == pytest.approx(0.6 * 20)         # GTD last game: a DNP counts 0


def test_pg_sg_locks_in_the_sg_slot_so_both_great_pgs_still_fit():
    pg1 = pp("pg1", ["PG"], "BN", future(20, 20))
    pg2 = pp("pg2", ["PG"], "BN", future(20, 20))
    combo = pp("combo", ["PG", "SG"], "PG", [Game("2026-10-21", 15, fp=19.0, started=True)])   # done for the week
    sg = pp("sg", ["SG"], "SG", future(8))
    plan = plan_week([pg1, pg2, combo, sg], SLOTS)
    assert combo.x == 19.0 and combo.action == "LOCK" and combo.seat == "SG"
    assert "PG → SG" in combo.why
    assert {pg1.seat, pg2.seat} == {"PG"} and sg.seat == "SG"
    assert plan.expected == pytest.approx(pg1.w + pg2.w + 19 + sg.w, abs=0.2)


def test_great_player_bad_game_passes_and_keeps_his_value_from_later_games():
    star = pp("star", ["PG"], "PG", [Game("2026-10-21", 20, fp=9.0, started=True)] + future(20, 20))
    plan_week([star], SLOTS)
    assert star.x == 9.0 and star.action == "PASS" and star.value == star.w > 20


def test_bench_players_cant_lock_and_the_window_closes_at_his_next_tip():
    bench = pp("bn", ["PG"], "BN", [Game("2026-10-21", 15, fp=30.0, started=True)] + future(15))
    closed = pp("closed", ["SG"], "SG", [Game("2026-10-21", 15, fp=30.0, started=True), Game("2026-10-22", 15, started=True)] + future(15))
    plan_week([bench, closed], SLOTS)
    assert bench.x is None and closed.x is None


def test_locked_players_keep_their_slot_and_others_fill_around_them():
    locked = pp("locked", ["PG", "SG"], "PG", [], locked=25.0)
    a = pp("a", ["PG"], "BN", future(18, 18))
    b = pp("b", ["PG"], "BN", future(10))
    plan = plan_week([locked, a, b], SLOTS)
    assert locked.action == "LOCKED" and locked.seat == "PG"
    assert a.seat == "PG" and b.seat is None and b.action == "BENCH"     # only one PG slot was left
    assert plan.expected == pytest.approx(25 + a.w, abs=0.2)


def test_swing_comes_from_his_own_games():
    assert swing_of([10.0] * 20) == 0.12                                  # perfectly steady: the floor
    assert swing_of([5.0, 25.0] * 10) == 0.6                              # wild: the ceiling
    assert swing_of([10.0] * 5) == 0.3                                    # too few games: the default


def test_today_starts_whoever_plays_today_and_keeps_lock_candidates():
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    star = pp("star", ["PG"], "PG", [Game("2026-10-20", 20, fp=9.0, started=True), Game("2026-10-23", 20)])   # bad game, plays Fri
    hot = pp("hot", ["PG", "SG"], "SG", [Game("2026-10-20", 12, fp=30.0, started=True)] + future(12))       # lockable 30
    flier = pp("flier", ["PG"], "BN", [Game(today, 11, tip="2026-10-22T00:00Z")])                         # plays tonight
    sg = pp("sg", ["SG"], "SG", [Game("2026-10-24", 10)])
    players = [star, hot, flier, sg]
    one_each = {"PG": 1, "SG": 1}
    plan_week(players, one_each)
    assert hot.action == "LOCK" and star.action == "PASS" and star.seat == "PG" and hot.seat == "SG"
    t = plan_today(players, one_each, today)
    assert t.seats == {"PG": ["flier"], "SG": ["hot"]}            # tonight's game gets the PG slot; the lock stays in
    moved = {m["sid"]: (m["from"], m["to"]) for m in t.moves}
    assert moved["flier"] == ("BN", "PG") and moved["star"] == ("PG", "BN") and moved["flier"] and "hot" not in moved
    assert star.seat == "PG"                                       # the week plan's seats are left alone


def test_today_never_moves_a_player_mid_game_and_flags_swaps_and_gtd():
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    live = pp("live", ["PG"], "PG", [Game(today, 15, started=True, live=True)] + future(15))
    early = pp("early", ["SG"], "SG", [Game(today, 14, tip="2026-10-21T23:00Z")] + future(14), injury="day_to_day")
    late = pp("late", ["SG"], "BN", [Game(today, 12, tip="2026-10-22T02:00Z")])
    players = [live, early, late]
    one_each = {"PG": 1, "SG": 1}
    plan_week(players, one_each)
    t = plan_today(players, one_each, today)
    assert "live" in t.seats["PG"]                                                    # in progress: stays put
    kinds = {w["kind"] for w in t.watch}
    assert {"gtd", "swap"} <= kinds
    swap = next(w for w in t.watch if w["kind"] == "swap")
    assert swap["name"] == "early" and swap["backup"] == "late" and swap["by"] == "2026-10-22T02:00Z" and swap["bar"] > 0


def test_live_estimate_projects_the_rest_of_his_game():
    from app.lockin.weekplan import live_estimate

    half = Game("2026-10-21", 16.0, fp=10.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    est = live_estimate(half)                       # halftime, on pace: about double
    assert 18 < est < 22
    cold = Game("2026-10-21", 16.0, fp=2.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    assert live_estimate(cold) < est - 5            # a cold half drags the estimate down
    done = Game("2026-10-21", 16.0, fp=25.0, started=True, final=True, min=36.0)
    assert live_estimate(done) == 25.0 and live_estimate(Game("2026-10-21", 16.0)) is None


def test_six_pm_player_starts_over_a_645_one_and_the_live_game_decides_the_swap():
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    early = pp("early", ["SG"], "BN", [Game(today, 10, tip="2026-10-21T23:00Z", proj_min=30)] + future(10))
    late = pp("late", ["SG"], "BN", [Game(today, 12, tip="2026-10-21T23:45Z", proj_min=30)])
    one = {"SG": 1}
    players = [early, late]
    plan_week(players, one)
    t = plan_today(players, one, today)
    assert t.seats == {"SG": ["early"]}                                   # earlier tip first, despite the lower projection
    w = next(x for x in t.watch if x["kind"] == "swap")
    assert w["decision"] == "PENDING" and w["backup"] == "late" and w["alarm"] == "2026-10-21T23:40Z"

    # 6:40: early is ice cold in the 2nd quarter -> SWAP; on fire -> KEEP
    for fp_now, want in ((1.0, "SWAP"), (14.0, "KEEP")):
        early.games[0] = Game(today, 10, fp=fp_now, started=True, live=True, tip="2026-10-21T23:00Z", min=10, proj_min=30, period=2, clock=600)
        early.slot = "SG"
        plan_week(players, one)
        w = next(x for x in plan_today(players, one, today).watch if x["kind"] == "swap")
        assert w["decision"] == want, (fp_now, w)


def test_the_starter_headed_lowest_tonight_sits_for_the_later_player_not_the_one_with_weaker_later_games():
    from app.lockin.weekplan import plan_today

    # Wiggins: 4.1 with 6 min left in Q4 but good later games; Grant: 6.0 late in Q3, weak later games.
    # Benching either gives up only tonight's game, so the one headed lower (Wiggins) sits for Sabonis.
    today = "2026-10-21"
    wig = pp("wiggins", ["SF", "PF"], "PF", [Game(today, 8.5, fp=4.1, started=True, live=True, tip="2026-10-21T23:30Z",
                                                  min=30, proj_min=32, period=4, clock=360)] + future(8.3, 8.0))
    grant = pp("grant", ["SF", "PF"], "PF", [Game(today, 5.4, fp=6.0, started=True, live=True, tip="2026-10-22T00:00Z",
                                                  min=22, proj_min=30, period=3, clock=78)] + future(5.6, 6.2))
    sab = pp("sabonis", ["PF", "C"], "BN", [Game(today, 13.7, tip="2026-10-22T02:30Z", proj_min=34)] + future(14.0))
    players, pf = [wig, grant, sab], {"PF": 2}
    plan_week(players, pf)
    w = next(x for x in plan_today(players, pf, today).watch if x["kind"] == "swap")
    assert (w["decision"], w["name"], w["backup"]) == ("SWAP", "wiggins", "sabonis")

    for g in wig.games[:1] + grant.games[:1]:   # the timeline's check after their games: free to move, same scores
        g.live = False
    plan_week(players, pf)
    assert sorted(plan_today(players, pf, today).seats["PF"]) == ["grant", "sabonis"]


def test_a_day_without_games_seats_by_next_tip():
    from app.lockin.weekplan import plan_today

    a = pp("a", ["C"], "C", [Game("2026-10-21", 10, tip="2026-10-21T23:00:00Z")])   # no game on the 20th
    b = pp("b", ["C"], "BN", [Game("2026-10-21", 14, tip="2026-10-21T23:30:00Z")])  # bigger, but tips later
    plan_week([a, b], {"C": 1})
    assert b.seat == "C"                                       # the week plan prefers b ...
    assert plan_today([a, b], {"C": 1}, "2026-10-20").moves == []   # ... but a plays first: he keeps the slot

    c = pp("c", ["C"], "BN", [Game("2026-10-21", 9, tip="2026-10-21T22:00:00Z")])   # on the bench, plays first
    moves = {m["sid"]: m["to"] for m in plan_today([a, c], {"C": 1}, "2026-10-20").moves}
    assert moves == {"c": "C", "a": "BN"}                      # set now, not on c's game day


def test_tips_within_15_minutes_start_the_bigger_projection_and_get_no_swap_check():
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    six = pp("six", ["SG"], "BN", [Game(today, 9, tip="2026-10-21T23:00Z")])
    six10 = pp("six10", ["SG"], "BN", [Game(today, 14, tip="2026-10-21T23:10Z")])     # 10 min later, projects more
    seven = pp("seven", ["SG"], "BN", [Game(today, 20, tip="2026-10-22T00:00Z")])     # an hour later
    one = {"SG": 1}
    players = [six, six10, seven]
    plan_week(players, one)
    t = plan_today(players, one, today)
    assert t.seats == {"SG": ["six10"]}                       # 6:00 and 6:10 are one group: the bigger projection starts
    swap = [w for w in t.watch if w["kind"] == "swap"]
    assert [w["backup"] for w in swap] == ["seven"]           # the 7:00 player is watched; the 6:00 one isn't (too close)


def test_lock_or_wait_by_the_chance_to_win_your_scenario():
    from app.lockin.weekplan import decide_by_win_chance

    # everyone else locked at 100; the great player's unlocked game is 15; his last game is projected 20
    def team():
        done = pp("done", ["PG"], "PG", [], locked=100.0)
        star = pp("star", ["SG"], "SG", [Game("2026-10-24", 18, fp=15.0, started=True), Game("2026-10-25", 20)])
        plan_week([done, star], SLOTS)
        return done, star
    done, star = team()
    decide_by_win_chance([done, star], (113.0, 0.0))      # they finish at 113 for sure: locking 15 (115) wins
    assert star.action == "LOCK" and star.win_lock == 1.0 and star.win_wait < 1.0
    done, star = team()
    decide_by_win_chance([done, star], (120.0, 0.0))      # they finish at 120: 115 can't win, the 20-proj game can
    assert star.action == "PASS" and star.win_lock == 0.0 and star.win_wait > 0.2
    done, star = team()
    decide_by_win_chance([done, star], (113.0, 64.0))     # their total is uncertain (±8): both chances in between
    assert 0 < star.win_lock < 1 and 0 < star.win_wait < 1 and "to win" in star.why


def test_late_scratch_alarms_now_and_close_projections_go_to_the_earlier_tip():
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    scratched = pp("scr", ["SG"], "SG", [Game(today, 15, tip="2026-10-22T00:00Z")], injury="out_short_term")
    sub = pp("sub", ["SG"], "BN", [Game(today, 9, tip="2026-10-22T01:00Z")])
    players = [scratched, sub]
    plan_week(players, {"SG": 1})
    t = plan_today(players, {"SG": 1}, today)
    out = next(w for w in t.watch if w["kind"] == "out")
    assert out["name"] == "scr" and out["backup"] == "sub" and out["alarm"] == "now"
    assert t.seats == {"SG": ["sub"]}                                 # an OUT player never gets the slot

    a = pp("a", ["SG"], "BN", [Game(today, 12.0, tip="2026-10-21T23:00Z")])
    b = pp("b", ["SG"], "BN", [Game(today, 12.8, tip="2026-10-21T23:10Z")])   # 10 min later, only 0.8 more
    plan_week([a, b], {"SG": 1})
    assert plan_today([a, b], {"SG": 1}, today).seats == {"SG": ["a"]}   # near tie: the earlier tip


def test_an_idle_starter_who_already_played_keeps_his_slot_for_the_lock():
    from app.lockin.weekplan import plan_today

    s = pp("s", ["PG"], "PG", [Game("2026-10-20", 15, tip="2026-10-21T01:30:00Z"), Game("2026-10-22", 15, tip="2026-10-23T01:30:00Z")])
    h = pp("h", ["PG"], "BN", [Game("2026-10-22", 11, tip="2026-10-22T23:00:00Z")])   # tips first on the 22nd
    plan_week([s, h], {"PG": 1})
    assert plan_today([s, h], {"PG": 1}, "2026-10-21").moves == []   # nobody plays the 21st: s keeps the PG slot
    moves = {m["sid"]: m["to"] for m in plan_today([s, h], {"PG": 1}, "2026-10-22").moves}
    assert moves == {"h": "PG", "s": "BN"}                             # on game day the earlier tip starts (rule 1)


def test_beat_chance_is_one_minus_every_game_missing():
    from app.lockin.weekplan import beat_chance
    assert beat_chance(17.5, [], 0.3, "healthy") == 0                            # no games left: can't beat it
    one = beat_chance(14.6, future(14.6), 0.3, "healthy")
    assert one == pytest.approx(0.97 * 0.5)                                       # projection = score: a coin flip if he plays
    two = beat_chance(17.5, future(13.7, 14.6), 0.3, "healthy")
    assert 0.25 < two < 0.4 and two > beat_chance(17.5, future(14.6), 0.3, "healthy")
    assert beat_chance(17.5, future(13.7, 14.6), 0.3, "out_long_term") == 0


def test_safe_locks_every_game_risky_waits_on_every_later_one():
    from app.lockin.weekplan import scenario_total

    a = pp("a", ["PG"], "PG", [], x=17.5, w=15.5, swing=0.3, seat="PG")   # can lock 17.5 or wait ~15.5
    done = pp("done", ["PG"], "PG", [], x=9.0, w=0.0, swing=0.3, seat="PG")   # no games left: locks either way
    assert scenario_total([a, done], True) == (26.5, 0.0)                  # certain
    mean, var = scenario_total([a, done], False)
    assert mean == 24.5 and var > 0                                        # waits on a's later games, with their spread
