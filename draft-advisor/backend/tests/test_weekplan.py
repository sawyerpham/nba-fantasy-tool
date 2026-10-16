"""Week plan: lock-now vs wait values, optimal seating, and which slot a lock goes into."""

import pytest

from app.engine.weekplan import Game, PlanPlayer, expected_max, plan_week, swing_of, wait_value

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
    from app.engine.weekplan import plan_today

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
    from app.engine.weekplan import plan_today

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
    from app.engine.weekplan import live_estimate

    half = Game("2026-10-21", 16.0, fp=10.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    est = live_estimate(half)                       # halftime, on pace: about double
    assert 18 < est < 22
    cold = Game("2026-10-21", 16.0, fp=2.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    assert live_estimate(cold) < est - 5            # a cold half drags the estimate down
    done = Game("2026-10-21", 16.0, fp=25.0, started=True, final=True, min=36.0)
    assert live_estimate(done) == 25.0 and live_estimate(Game("2026-10-21", 16.0)) is None


def test_six_pm_player_starts_over_a_645_one_and_the_live_game_decides_the_swap():
    from app.engine.weekplan import plan_today

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
