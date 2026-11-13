
import pytest

from app.lockin.weekplan import PROJ_SCALE, Game, PlanPlayer, expected_max, plan_week, swing_of, wait_value

SLOTS = {"PG": 2, "SG": 2}


def pp(sid, elig, slot, games, **kw):
    """A PlanPlayer with the given eligibility, slot and games."""
    return PlanPlayer(sid=sid, name=sid, eligibility=elig, slot=slot, games=games, **kw)


def future(*projs):
    """One future game per projection, on consecutive days."""
    return [Game(date=f"2026-10-2{i + 2}", proj=p) for i, p in enumerate(projs)]


def test_expected_max_and_wait_value_math():
    """Expected max and wait value math."""
    assert expected_max(0, 1, 0) == pytest.approx(0.3989, abs=1e-4)
    assert expected_max(10, 0, 12) == 12
    assert wait_value(future(20), 0.3, "healthy") == pytest.approx(0.97 * 20 * PROJ_SCALE)   # last game: just its (scaled) projection
    two = wait_value(future(20, 20), 0.3, "healthy")
    assert two > 20 * PROJ_SCALE                                                         # two chances beat one
    assert wait_value(future(20, 20), 0.3, "out_long_term") == 0                        # never plays: worth 0
    assert wait_value(future(20), 0.3, "day_to_day") == pytest.approx(0.6 * 20 * PROJ_SCALE)   # GTD last game: a DNP counts 0


def test_pg_sg_locks_in_the_sg_slot_so_both_great_pgs_still_fit():
    """Pg sg locks in the sg slot so both great pgs still fit."""
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
    """Great player bad game passes and keeps his value from later games."""
    star = pp("star", ["PG"], "PG", [Game("2026-10-21", 20, fp=9.0, started=True)] + future(20, 20))
    plan_week([star], SLOTS)
    assert star.x == 9.0 and star.action == "PASS" and star.value == star.w > 20


def test_bench_players_cant_lock_and_the_window_closes_at_his_next_tip():
    """Bench players cant lock and the window closes at his next tip."""
    bench = pp("bn", ["PG"], "BN", [Game("2026-10-21", 15, fp=30.0, started=True)] + future(15))
    closed = pp("closed", ["SG"], "SG", [Game("2026-10-21", 15, fp=30.0, started=True), Game("2026-10-22", 15, started=True)] + future(15))
    plan_week([bench, closed], SLOTS)
    assert bench.x is None and closed.x is None


def test_locked_players_keep_their_slot_and_others_fill_around_them():
    """Locked players keep their slot and others fill around them."""
    locked = pp("locked", ["PG", "SG"], "PG", [], locked=25.0)
    a = pp("a", ["PG"], "BN", future(18, 18))
    b = pp("b", ["PG"], "BN", future(10))
    plan = plan_week([locked, a, b], SLOTS)
    assert locked.action == "LOCKED" and locked.seat == "PG"
    assert a.seat == "PG" and b.seat is None and b.action == "BENCH"     # only one PG slot was left
    assert plan.expected == pytest.approx(25 + a.w, abs=0.2)


def test_swing_comes_from_his_own_games():
    """Swing comes from his own games."""
    from app.lockin.weekplan import SWING_CENTER, SWING_SHRINK
    pulled = lambda own: SWING_CENTER + SWING_SHRINK * (own - SWING_CENTER)   # his own spread, pulled toward the league's
    assert swing_of([10.0] * 20) == pytest.approx(pulled(0.12))           # perfectly steady: the floor
    assert swing_of([5.0, 25.0] * 10) == pytest.approx(pulled(0.6))       # wild: the ceiling
    assert swing_of([8.0, 12.0] * 10) == pytest.approx(pulled(0.2))       # his own std / mean in between
    assert swing_of([10.0] * 5) == SWING_CENTER                           # too few games: the league's


def test_today_starts_whoever_plays_today_and_keeps_lock_candidates():
    """Today starts whoever plays today and keeps lock candidates."""
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
    """Today never moves a player mid game and flags swaps and gtd."""
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

    late.injury = "out_short_term"   # ruled OUT: never offered as anyone's backup
    plan_week(players, one_each)
    assert not [w for w in plan_today(players, one_each, today).watch if w.get("backup") == "late"]


def test_live_estimate_projects_the_rest_of_his_game():
    """Live estimate projects the rest of his game."""
    from app.lockin.weekplan import live_estimate

    half = Game("2026-10-21", 16.0, fp=10.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    est = live_estimate(half)                       # halftime, on pace: a bit under double (fewer minutes left)
    assert 16 < est < 20
    cold = Game("2026-10-21", 16.0, fp=2.0, started=True, live=True, min=17.0, proj_min=34.0, period=3, clock=720.0)
    assert live_estimate(cold) < est - 5            # a cold half drags the estimate down
    done = Game("2026-10-21", 16.0, fp=25.0, started=True, final=True, min=36.0)
    assert live_estimate(done) == 25.0 and live_estimate(Game("2026-10-21", 16.0)) is None


def test_six_pm_player_starts_over_a_645_one_and_the_live_game_decides_the_swap():
    """Six pm player starts over a 645 one and the live game decides the swap."""
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


def test_a_live_starter_headed_past_the_backups_projection_keeps_his_slot():
    """Okongwu live, headed for a bit more than Sharpe's pre-game 12: the swap is off, even where the option math
    (Sharpe's game plus the chance to pass on it for Okongwu's later games) would still say swap."""
    from app.lockin.weekplan import swap_call

    today = "2026-10-21"
    ok = pp("okongwu", ["C"], "C", [Game(today, 11, fp=7.0, started=True, live=True, tip="2026-10-21T23:00Z",
                                         min=16, proj_min=32, period=2, clock=0)] + future(11, 11))
    sharpe = pp("sharpe", ["C"], "BN", [Game(today, 12, tip="2026-10-21T23:30Z", proj_min=30)])
    call = swap_call(ok, sharpe, today)
    assert 12 < call["est"] < call["swap"] and call["decision"] == "KEEP", call
    ok.games[0].fp = 1.0                                                   # ice cold: headed well below 12
    assert swap_call(ok, sharpe, today)["decision"] == "SWAP"


def test_the_starter_headed_lowest_tonight_sits_for_the_later_player_not_the_one_with_weaker_later_games():
    """The starter headed lowest tonight sits for the later player not the one with weaker later games."""
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
    t = plan_today(players, pf, today, now="2026-10-22T00:30Z")
    w = next(x for x in t.watch if x["kind"] == "swap")
    assert (w["decision"], w["name"], w["backup"]) == ("SWAP", "wiggins", "sabonis")
    assert t.moves == []   # hours before Sabonis's tip: the call can still turn, so the lineup waits for the check-in
    # at the check-in, the lineup makes the swap while Wiggins is still playing (Sabonis tips before his game ends)
    t = plan_today(players, pf, today, now="2026-10-22T02:15Z")
    assert sorted(t.seats["PF"]) == ["grant", "sabonis"]
    assert {m["sid"]: (m["from"], m["to"]) for m in t.moves} == {"wiggins": ("PF", "BN"), "sabonis": ("BN", "PF")}

    for g in wig.games[:1] + grant.games[:1]:   # the timeline's check after their games: free to move, same scores
        g.live = False
    plan_week(players, pf)
    assert sorted(plan_today(players, pf, today, now="2026-10-22T02:15Z").seats["PF"]) == ["grant", "sabonis"]


def test_a_finished_week_auto_locks_the_last_game_of_every_unlocked_starter():
    """A finished week shows the lineup it had (Sleeper's matchup, not today's roster), and a starter nobody locked
    counts his last game: 0 when he sat it out. Sleeper's final count wins over your answers."""
    from app.lockin.service import _plan_players

    g = lambda d, fp: {"date": d, "fp": fp, "proj": 10.0, "tip": None, "state": "post", "b2b": False}   # noqa: E731
    view = {"dates": ["2026-10-26", "2026-11-01"], "today": "2026-11-02", "now": None, "roster_positions": ["PG", "C", "BN"],
            "players": {s: {"player_id": None, "name": s, "pos": ["PG", "C"], "injury": "healthy", "games": gs}
                        for s, gs in (("a", [g("2026-10-26", 20.0), g("2026-11-01", 8.0)]),
                                      ("b", [g("2026-10-26", 12.0), g("2026-11-01", None)]),
                                      ("c", [g("2026-10-26", 30.0)]))},
            "matchups": [[{"roster_id": 1, "starters": ["a", "b"], "players": ["a", "b", "c"], "players_points": {}}]]}
    team = {"roster_id": 1, "is_user": True, "starters": ["c", "a"], "players": ["a", "c"], "reserve": []}   # today's lineup
    session = type("S", (), {"valuations": {}})()
    players, locks, _ = _plan_players(session, view, team, {})
    by = {p.sid: p for p in players}
    assert (by["a"].slot, by["b"].slot, by["c"].slot) == ("PG", "C", "BN")   # the week's lineup, dropped b included
    assert (by["a"].locked, by["b"].locked, by["c"].locked) == (8.0, 0.0, None)   # last games; b sat his out
    view["matchups"][0][0]["players_points"] = {"a": 20.0}
    players, _, _ = _plan_players(session, view, team, {"a": "2026-11-01"})
    assert next(p for p in players if p.sid == "a").locked == 20.0           # Sleeper's final count beats your answer


def test_an_out_starter_sitting_out_his_live_game_is_benched_now():
    """An OUT starter whose game has tipped without him scores 0: he isn't pinned, he's benched now for the best later player."""
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    wat = pp("watson", ["SF"], "SF", [Game(today, 8, started=True, live=True, tip="2026-10-21T23:00Z", period=1, clock=0)] + future(8))
    wat.injury = "out_short_term"
    wig = pp("wiggins", ["SF"], "BN", [Game(today, 8, tip="2026-10-22T02:00Z")])
    gri = pp("grimes", ["SF"], "BN", [Game(today, 6, tip="2026-10-22T02:00Z")])
    players, sf = [wat, wig, gri], {"SF": 1}
    plan_week(players, sf)
    t = plan_today(players, sf, today)
    assert {m["sid"]: m["to"] for m in t.moves} == {"watson": "BN", "wiggins": "SF"}
    assert [w["kind"] for w in t.watch] == ["out"]


def test_every_later_bench_player_is_watched_and_targets_the_starter_the_swap_is_worth_most_against():
    """No minimum gain: a later bench player is watched against every earlier starter he fits, each starter goes to one
    backup, and before any live score the arrows (from the check-in) go to the starter the swap is worth most against."""
    from app.lockin.weekplan import plan_today

    today = "2026-10-21"
    # a projects more tonight but has good games to come: benching him costs little. b's game tonight is his last.
    a = pp("a", ["SG"], "SG", [Game(today, 12, tip="2026-10-21T23:00Z")] + future(12, 12))
    b = pp("b", ["SG"], "SG", [Game(today, 9, tip="2026-10-21T23:00Z")])
    g = pp("grimes", ["SG"], "BN", [Game(today, 6.5, tip="2026-10-22T02:00Z")])
    players, sg = [a, b, g], {"SG": 2}
    plan_week(players, sg)
    t = plan_today(players, sg, today, now="2026-10-21T22:00Z")
    w = next(x for x in t.watch if x["kind"] == "swap")
    assert (w["backup"], w["name"], w["decision"]) == ("grimes", "a", "PENDING") and t.moves == []
    t = plan_today(players, sg, today, now="2026-10-22T01:45Z")   # the check-in: the arrow goes to a
    assert {m["sid"]: m["to"] for m in t.moves} == {"a": "BN", "grimes": "SG"}


def test_a_day_without_games_seats_by_next_tip():
    """A day without games seats by next tip."""
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
    """Tips within 15 minutes start the bigger projection and get no swap check."""
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
    """Lock or wait by the chance to win your scenario."""
    from app.lockin.weekplan import decide_by_win_chance

    # everyone else locked at 100; the great player's unlocked game is 15; his last game is projected 20
    def team():
        """A team with a locked player, a star with one played and one future game, and fillers for the swap tests."""
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


def test_a_starter_the_plan_benches_still_gets_a_win_chance_for_locking():
    """A starter the plan benches (a better player takes his slot) can still lock his final game: win % re-planned."""
    from app.lockin.weekplan import bench_lock_chance, decide_by_win_chance

    one = {"C": 1}
    starter = pp("starter", ["C"], "C", [Game("2026-10-24", 10, fp=10.0, started=True, final=True), Game("2026-10-26", 11)])
    better = pp("better", ["C"], "BN", future(14))
    players = [starter, better]
    plan_week(players, one)
    assert starter.seat is None and starter.x == 10.0 and starter.x_final   # benched by the plan, yet lockable
    plan_chance = decide_by_win_chance(players, (12.0, 4.0))
    locked = bench_lock_chance(starter, players, one, "C", (12.0, 4.0))
    assert 0 < locked < plan_chance                    # a sure 10 vs their ~12 loses more often than the 14-proj player
    assert starter.seat is None and starter.locked is None and better.seat == "C"   # the originals are untouched


def test_late_scratch_alarms_now_and_close_projections_go_to_the_earlier_tip():
    """Late scratch alarms now and close projections go to the earlier tip."""
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
    """An idle starter who already played keeps his slot for the lock."""
    from app.lockin.weekplan import plan_today

    s = pp("s", ["PG"], "PG", [Game("2026-10-20", 15, tip="2026-10-21T01:30:00Z"), Game("2026-10-22", 15, tip="2026-10-23T01:30:00Z")])
    h = pp("h", ["PG"], "BN", [Game("2026-10-22", 11, tip="2026-10-22T23:00:00Z")])   # tips first on the 22nd
    plan_week([s, h], {"PG": 1})
    assert plan_today([s, h], {"PG": 1}, "2026-10-21").moves == []   # nobody plays the 21st: s keeps the PG slot
    moves = {m["sid"]: m["to"] for m in plan_today([s, h], {"PG": 1}, "2026-10-22").moves}
    assert moves == {"h": "PG", "s": "BN"}                             # on game day the earlier tip starts (rule 1)


def test_beat_chance_is_one_minus_every_game_missing():
    """Beat chance is one minus every game missing."""
    from app.lockin.weekplan import beat_chance
    assert beat_chance(17.5, [], 0.3, "healthy") == 0                            # no games left: can't beat it
    one = beat_chance(14.6 * PROJ_SCALE, future(14.6), 0.3, "healthy")
    assert one == pytest.approx(0.97 * 0.5)                                       # projection = score: a coin flip if he plays
    two = beat_chance(17.5, future(13.7, 14.6), 0.3, "healthy")
    assert 0.15 < two < 0.4 and two > beat_chance(17.5, future(14.6), 0.3, "healthy")
    assert beat_chance(17.5, future(13.7, 14.6), 0.3, "out_long_term") == 0


def test_safe_locks_every_game_risky_waits_on_every_later_one():
    """Safe locks every game risky waits on every later one."""
    from app.lockin.weekplan import scenario_total

    a = pp("a", ["PG"], "PG", [], x=17.5, x_final=True, w=15.5, w_var=20.0, swing=0.3, seat="PG")   # can lock 17.5 or wait ~15.5
    done = pp("done", ["PG"], "PG", [], x=9.0, x_final=True, w=0.0, swing=0.3, seat="PG")   # no games left: locks either way
    assert scenario_total([a, done], True) == (26.5, 0.0)                  # certain
    mean, var = scenario_total([a, done], False)
    assert mean == 24.5 and var > 0                                        # waits on a's later games, with their spread


def test_an_open_slot_counts_spare_bench_players_games_not_just_his_own():
    """An open slot counts spare bench players games not just his own."""
    from app.lockin.weekplan import open_slot

    # Jaquez can lock 9.7; his own later game is only ~7. A spare forward on the bench plays a 12-proj game Friday:
    # left open, his slot can take that, so it's worth more than his own games alone.
    jaq = pp("jaquez", ["SG", "SF"], "SF", [Game("2026-10-23", 7.0)], seat="SF")
    spare = pp("spare", ["SF", "PF"], "BN", [Game("2026-10-23", 12.0), Game("2026-10-24", 8.0)])
    c_only = pp("big", ["C"], "BN", [Game("2026-10-23", 20.0)])                      # can't play SF: no help
    starter = pp("coward", ["SG", "SF"], "SF", [Game("2026-10-24", 15.0)], seat="SF")  # has his own slot: no help
    w, src, _ = open_slot(jaq, [jaq, spare, c_only, starter])
    assert src == [("2026-10-23", "spare"), ("2026-10-24", "spare")] and w > 12 * PROJ_SCALE


def test_an_open_slot_gets_an_early_bench_look_before_his_own_later_game_that_day():
    """Sharpe at 6:30 then Kessler at 9:00 the same night: the slot can watch Sharpe's game and still go to Kessler's,
    so leaving it open is worth more than Kessler's game alone (and close tips are one look)."""
    from app.lockin.weekplan import open_slot

    kes = pp("kessler", ["C"], "C", [Game("2026-11-04", 11.0, tip="2026-11-05T03:00Z")], seat="C")
    sharpe = pp("sharpe", ["C"], "BN", [Game("2026-11-04", 7.0, tip="2026-11-05T00:30Z")])
    alone, _, _ = open_slot(kes, [kes])
    w, src, _ = open_slot(kes, [kes, sharpe])
    assert src == [("2026-11-04", "sharpe"), ("2026-11-04", "kessler")] and w > alone
    sharpe.games[0].tip = "2026-11-05T02:50Z"                      # 10 min before his: no time to judge, one look
    assert open_slot(kes, [kes, sharpe])[1] == [("2026-11-04", "kessler")]


def test_a_back_to_backs_second_night_is_worth_less_to_wait_on():
    """A back to backs second night is worth less to wait on."""
    # RotoWire: rest days land on back-to-backs, and an unlocked player's final game counts even at zero
    rested = wait_value([Game("2026-10-24", 15.0, b2b=True)], 0.3, "healthy")
    fresh = wait_value([Game("2026-10-24", 15.0)], 0.3, "healthy")
    assert rested < fresh and rested == pytest.approx(15.0 * PROJ_SCALE * 0.97 * 0.85)   # sitting the final game leaves 0


def test_lock_a_pf_c_player_at_pf_when_the_centers_need_the_c_slots():
    """Lock a pf c player at pf when the centers need the c slots."""
    from app.lockin.weekplan import lock_slots

    # Sabonis can lock at PF or C; two C-only players need both C slots, while a forward could take the PF slot
    sab = pp("sabonis", ["PF", "C"], "PF", [], x=14.9, value=15.0, seat="PF")
    c1 = pp("kessler", ["C"], "C", [], value=13.0, seat="C")
    c2 = pp("okongwu", ["C"], "BN", [], value=11.0)
    f = pp("watson", ["SF", "PF"], "BN", [], value=9.0)
    slots = {"PF": 1, "C": 2}
    best = lock_slots(sab, [sab, c1, c2, f], slots)
    assert [o["slot"] for o in best] == ["PF", "C"]       # at C he'd push Okongwu out (11) for Watson's PF (9)
    assert best[0]["team"] - best[1]["team"] == pytest.approx(2.0)
    assert sab.slot == "PF" and c2.slot == "BN"           # the lineup it tried is undone


def test_a_game_still_in_progress_gets_no_lock_call():
    """A game still in progress gets no lock call."""
    # a big night that isn't over yet: nothing to lock until it's final
    live = pp("a", ["PG"], "PG", [Game("2026-10-23", 10.0, fp=25.0, started=True, live=True, period=3, clock=300),
                                    Game("2026-10-25", 10.0)])
    plan_week([live], {"PG": 1})
    assert live.x == 25.0 and not live.x_final and live.action == "LIVE"
    live.games[0] = Game("2026-10-23", 10.0, fp=25.0, started=True, final=True)
    plan_week([live], {"PG": 1})
    assert live.x_final and live.action == "LOCK"   # once final: 25 beats waiting on a 10-proj game


def test_a_starters_game_in_progress_counts_where_its_headed_not_his_points_so_far():
    """A starters game in progress counts where its headed not his points so far."""
    today = "2026-10-24"
    tipped = pp("harden", ["PG"], "PG", [Game(today, 10.7, started=True, live=True)])            # just tipped, no stats yet
    cold = pp("wiggins", ["PF"], "PF", [Game(today, 8.1, fp=3.0, started=True, live=True, min=20, proj_min=32,
                                             period=3, clock=550)])
    benched = pp("watson", ["PF"], "BN", [Game(today, 8.2, started=True, live=True)])            # on the bench: can't count
    plan = plan_week([tipped, cold, benched], {"PG": 1, "PF": 1})
    assert tipped.value == pytest.approx(10.7 * PROJ_SCALE) and tipped.seat == "PG"
    assert 3.0 < cold.value < 8.1 and cold.seat == "PF"
    assert benched.value == 0
    assert plan.expected == pytest.approx(tipped.value + cold.value, abs=0.1)


def test_win_chance_counts_a_live_game_at_its_projected_finish():
    """Win chance counts a live game at its projected finish."""
    from app.lockin.weekplan import slot_spread

    today = "2026-10-24"
    live = pp("sharpe", ["C"], "C", [Game(today, 10.4, fp=6.0, started=True, live=True, min=15, proj_min=26,
                                         period=3, clock=600)])                  # no games after tonight
    plan_week([live], {"C": 1})
    mean, _ = slot_spread(live, lock=False)
    assert live.slot_w is None and mean == pytest.approx(live.value) and mean > 6.0   # not 0 for a slot with nothing left


def test_one_games_variance_is_the_mix_of_playing_and_sitting():
    """A game he may miss: mean p·μ, variance p·(σ² + μ²) − (p·μ)², so a questionable player's slot is the less
    certain one, not the more certain (value × swing said the opposite)."""
    from app.lockin.weekplan import wait_moments

    mu, sigma = 20 * PROJ_SCALE, 20 * PROJ_SCALE * 0.3
    for injury, p in (("healthy", 0.97), ("day_to_day", 0.6)):
        mean, var = wait_moments(future(20), 0.3, injury)
        assert mean == pytest.approx(p * mu) and var == pytest.approx(p * (sigma ** 2 + mu ** 2) - (p * mu) ** 2)
    assert wait_moments(future(20), 0.3, "day_to_day")[1] > 2 * wait_moments(future(20), 0.3, "healthy")[1]
    assert wait_moments(future(20), 0.3, "out_long_term") == (0.0, 0.0)   # never plays: a certain 0


def test_wait_moments_match_the_lock_rule_played_out():
    """The mean and variance of three games under the lock rule, against the same rule simulated 40,000 times."""
    import random

    from app.lockin.weekplan import play_chance, wait_moments

    games, swing, injury = [Game("2026-10-22", 14.0), Game("2026-10-23", 18.0, b2b=True), Game("2026-10-25", 16.0)], 0.45, "healthy"
    bar = [wait_value(games[i + 1:], swing, injury) for i in range(len(games))]   # what the games after each are worth
    rng, runs, got = random.Random(7), 40_000, []
    for _ in range(runs):
        banked = 0.0
        for i, g in enumerate(games):
            if rng.random() >= play_chance(g, injury, i == 0):
                continue
            x = rng.gauss(g.proj * PROJ_SCALE, g.proj * PROJ_SCALE * swing)
            if i == len(games) - 1 or x > bar[i]:
                banked = x
                break
        got.append(banked)
    mean = sum(got) / runs
    var = sum((x - mean) ** 2 for x in got) / runs
    m, v = wait_moments(games, swing, injury)
    assert m == pytest.approx(mean, rel=0.01) and v == pytest.approx(var, rel=0.03)


def test_a_live_games_spread_shrinks_with_the_square_root_of_the_share_left():
    """Half a game left keeps 71 % of the pre-game spread, not half of it; the mean is where the game is headed."""
    from app.lockin.weekplan import game_dist, live_estimate

    before = game_dist(Game("2026-10-24", 20.0), 0.4)
    assert before == pytest.approx((20 * PROJ_SCALE, 20 * PROJ_SCALE * 0.4))
    half = Game("2026-10-24", 20.0, fp=9.0, started=True, live=True, min=17, proj_min=34, period=3, clock=720)
    mu, sd = game_dist(half, 0.4)
    assert mu == live_estimate(half) and sd == pytest.approx(before[1] * 0.5 ** 0.5)
    late = Game("2026-10-24", 20.0, fp=16.0, started=True, live=True, min=30, proj_min=34, period=4, clock=360)
    assert game_dist(late, 0.4)[1] == pytest.approx(before[1] * 0.125 ** 0.5)


def test_overtime_is_still_a_live_game():
    """In overtime he is still scoring: the estimate sits above his points so far and the spread isn't zero."""
    from app.lockin.weekplan import beat_chance, game_dist, live_estimate

    ot = Game("2026-10-24", 20.0, fp=24.0, started=True, live=True, min=38, proj_min=34, period=5, clock=240)
    assert live_estimate(ot) > 24.0 and game_dist(ot, 0.4)[1] > 0
    assert 0 < beat_chance(25.0, [ot], 0.4, "healthy") < 1       # a 25 he hasn't reached yet is neither sure nor out
    assert game_dist(Game("2026-10-24", 20.0, fp=24.0, started=True, live=True, min=43, proj_min=34, period=5, clock=0), 0.4)[1] == 0


def test_swap_and_keep_are_valued_the_same_way():
    """Two identical games tonight are a wash, and a game in progress keeps the upside it has left."""
    from app.lockin.weekplan import swap_call

    today, later = "2026-10-24", "2026-10-26"
    s = pp("starter", ["PG"], "PG", [Game(today, 14.0, tip="2026-10-24T23:00Z"), Game(later, 12.0)], swing=0.4)
    b = pp("backup", ["PG"], "BN", [Game(today, 14.0, tip="2026-10-25T02:00Z")], swing=0.4)
    call = swap_call(s, b, today)
    assert call["decision"] == "PENDING" and call["gain"] == 0          # same game, same fallback: nothing to gain
    b.games[0].proj = 17.0
    assert swap_call(s, b, today)["gain"] > 0                             # the better game is the gain, on one baseline

    # under way and headed for ~his later games' value: keeping is worth more than either number alone, because the
    # game can still beat the fallback (it used to count max(pace, bar), a point, against a swap priced with upside)
    s.games[0] = Game(today, 14.0, fp=5.5, started=True, live=True, min=17, proj_min=34, period=3, clock=720, tip="2026-10-24T23:00Z")
    live = swap_call(s, b, today)
    assert live["keep"] > max(live["est"], live["bar"]) and live["keep_var"] > 0
    assert live["gain"] == pytest.approx(live["swap"] - live["keep"], abs=0.11)   # gain and the call share a baseline
    s.games[0] = Game(today, 14.0, fp=11.0, started=True, final=True, tip="2026-10-24T23:00Z")
    over = swap_call(s, b, today)
    assert over["keep"] == pytest.approx(max(11.0, over["bar"]), abs=0.05)   # final: a known score, no upside left
