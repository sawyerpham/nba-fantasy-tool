"""Week plan for a Lock-In matchup: which game fills each starting slot, what to lock, and in which slot.

Every starting slot ends the week with exactly one game: the one locked into it, else its occupant's last game
(a DNP last game scores 0). Moving a player between starting slots is free; moving one to the bench forfeits his
unlocked game. The plan maximizes the week's expected fantasy points:

  locked      L = the locked score; he stays in his slot.
  lock now    X = his latest game, when he sits in a starting slot, is unlocked and his next game hasn't started
                  (bench players can't lock, and the window closes at his next tip).
  wait        W = the value of his remaining games played optimally: going backwards from his last game,
                  V_last = p·μ_last (a DNP last game counts 0), V_k = p·E[max(X_k, V_k+1)] + (1-p)·V_k+1,
                  each game X_k ~ Normal(Sleeper's projection μ_k, σ_k = μ_k × his swing).
  value       = L, else max(X, W). LOCK when X ≥ W, else PASS.

Seating: locked players keep their slots; everyone else, highest value first, takes a slot he can play, sliding
already-seated multi-position players to other slots when that makes room (augmenting paths). Highest-value-first
with augmenting paths is optimal for this kind of slot filling (a transversal matroid), and it is what puts a
PG/SG's lock in the SG slot when two better PGs still have games: they claim the PG slots first.
Players left without a slot don't count this week.

swing = one game's spread as a share of its mean: the player's own game-to-game variation under the league's scoring
(std / mean of last season's games) pulled toward the league's, which is what real games show (swing_of); a game's
mean is Sleeper's projection scaled by PROJ_SCALE (the projections run high).
ponytail: games are independent normals and the plan ignores the option of swapping several later players
through one slot; good enough to rank lock/pass, revisit if the calls look off in practice.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace

from ..core.engine import roster

MIN_SWING, MAX_SWING, MIN_GAMES_FOR_SWING = 0.12, 0.6, 15
# One source for how far a game lands from its projection, fit by backtest_week.py on 2,048 played games (weeks 1-3,
# 2026-27). Sleeper's projections ran 7.5 % high in each of the three weeks, and around the corrected mean a game's
# spread was 0.45 of it. Last season's own std / mean predicts only part of that (steady players came in wilder than
# their record, wild ones steadier), so it is pulled 60 % of the way to 0.45. Expected FP once ran ~140 against real
# weeks of 105-122 because the projections were taken at face value; halving the swing hid that and left every win
# chance too sure of itself (real margins 1.39x wider than predicted).
# ponytail: three flat numbers from three weeks; rerun the backtest to retune as the season goes on.
PROJ_SCALE = 0.925
SWING_CENTER, SWING_SHRINK = 0.45, 0.4
# Chance he plays a game, by Sleeper injury status: next game / later games this week.
# ponytail: flat guesses; tune from what actually happens once the season runs.
PLAY_CHANCE = {"healthy": (0.97, 0.97), "day_to_day": (0.6, 0.9), "out_short_term": (0.0, 0.3),
               "out_long_term": (0.0, 0.0), "out_season": (0.0, 0.0)}
# The second night of a back-to-back: rest days land there (RotoWire: passing on a good early game backfires when he
# sits later, and an unlocked player's final game counts even at zero). His chance to play it is scaled by this.
# ponytail: one flat factor for everyone; stars rest more than role players, tune per player if it matters.
B2B_PLAY = 0.85


def play_chance(g: "Game", injury: str, first: bool) -> float:
    """Chance he plays game g: his injury status (next game / later ones), lower on a back-to-back's second night."""
    if g.started:   # it has tipped: he's in it (a live game counted in plan_week)
        return 1.0
    nxt, later = PLAY_CHANCE.get(injury, PLAY_CHANCE["healthy"])
    return (nxt if first else later) * (B2B_PLAY if g.b2b else 1.0)


@dataclass
class Game:
    """One game of a player's week: projection, actual points, tip-off, whether it is in progress or over, minutes and clock, and whether his team played the night before."""
    date: str
    proj: float | None          # Sleeper projection in league FP; None = no projection (the plan counts PROJ_SCALE of it: _mu)
    fp: float | None = None     # actual FP once played
    started: bool = False       # tipped off (in progress or final)
    live: bool = False          # in progress right now
    tip: str | None = None      # tip-off, UTC ISO
    final: bool = False         # game over
    min: float | None = None    # minutes played so far
    proj_min: float | None = None   # Sleeper's projected minutes
    period: int = 0             # live game clock (ESPN): quarter and seconds left in it
    clock: float = 0.0
    b2b: bool = False           # his team played the day before (second night of a back-to-back)


@dataclass
class PlanPlayer:
    """One player in the week plan: his slot, games, locked score, value of waiting, the LOCK / PASS call, win chances and the open-slot and lock-slot options."""
    sid: str
    name: str
    eligibility: list[str]
    slot: str                   # where he sits now: a starting slot, "BN" or "IR"
    games: list[Game]
    swing: float = SWING_CENTER
    injury: str = "healthy"
    locked: float | None = None # locked score, if he's locked this week
    # filled by plan_week
    x: float | None = None      # his latest game's score (counting now; lockable once that game is final)
    x_final: bool = False       # that game is over: only then can it be locked (no LOCK / PASS call before)
    w: float = 0.0              # value of waiting
    w_var: float = 0.0          # ...and the variance of what waiting ends up with (wait_moments)
    value: float = 0.0
    seat: str | None = None
    action: str = ""            # LOCKED / LOCK / PASS / BENCH (not seated) / DONE
    why: str = ""
    win_lock: float | None = None   # chance to win the week if he locks now / if he waits (decide_by_win_chance)
    win_wait: float | None = None
    slot_w: float | None = None     # a lockable starter's slot left open: what it can still get (open_slot)
    slot_var: float = 0.0           # ...and its variance
    slot_from: list = field(default_factory=list)   # [(date, player name)]: whose game it would take each day
    lock_at: list = field(default_factory=list)     # where to lock him: lock_slots, best first


@dataclass
class WeekPlan:
    """The week plan for one team: every player, the expected score and the slot counts."""
    players: list[PlanPlayer]
    expected: float             # expected FP of all slots
    slots: dict[str, int] = field(default_factory=dict)


def swing_of(per_game_fpts: list[float]) -> float:
    """How much one game can swing a player's night, as a share of its mean: last season's std / mean of his per-game
    fantasy points, pulled toward the league's (SWING_CENTER; that alone with too few games)."""
    games = [f for f in per_game_fpts if f is not None]
    m = sum(games) / len(games) if games else 0.0   # float math: statistics.mean/pstdev run exact fractions, ~400 calls a page
    if len(games) < MIN_GAMES_FOR_SWING or m <= 0:
        return SWING_CENTER
    own = min(MAX_SWING, max(MIN_SWING, math.sqrt(sum((f - m) ** 2 for f in games) / len(games)) / m))
    return SWING_CENTER + SWING_SHRINK * (own - SWING_CENTER)


def _mu(g: "Game") -> float:
    """The mean of a game still to come: Sleeper's projection, scaled down (it runs high: PROJ_SCALE)."""
    return max(0.0, (g.proj or 0.0) * PROJ_SCALE)


def _phi(z: float) -> float:
    """The standard normal density at z."""
    return math.exp(-z * z / 2) / math.sqrt(2 * math.pi)


def _cdf(z: float) -> float:
    """The standard normal cumulative distribution at z."""
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expected_max(mu: float, sigma: float, v: float) -> float:
    """E[max(X, v)] for X ~ Normal(mu, sigma)."""
    if sigma <= 0:
        return max(mu, v)
    d = (mu - v) / sigma
    return v + (mu - v) * _cdf(d) + sigma * _phi(d)


def open_slot(p: PlanPlayer, players: list[PlanPlayer]) -> tuple[float, list[tuple[str, str]], float]:
    """(value, whose game each look is, variance): what his slot is worth left open (not locking him): one look at every remaining tip, his games or a bench
    player's who fits the slot and isn't seated in the plan, earliest first, with the option to keep the best one
    (wait_value). Same-day looks count too: start the 6:30 bench player, and if his game flops swap in the 9:00 one.
    Tips CLOSE_TIPS_MIN or less apart are one look (no time to judge the first): the bigger projection.
    That's why locking a decent game can be wrong with a deep bench: it gives up every one of those chances.
    ponytail: two open slots can both count the same bench player; fine while one lock is decided at a time."""
    pool = [p] + [q for q in players if q is not p and q.seat is None and q.slot != "IR" and q.locked is None
                  and q.injury not in OUT and p.seat in roster.candidate_slots(q.eligibility)]
    looks: list[tuple[Game, PlanPlayer]] = []
    for g, q in sorted(((g, q) for q in pool for g in q.games if not g.started), key=lambda gq: (gq[0].date, _minutes(gq[0].tip))):
        prev = looks[-1][0] if looks else None
        if prev and prev.date == g.date and (g.tip == prev.tip or _minutes(g.tip) - _minutes(prev.tip) <= CLOSE_TIPS_MIN):
            if (g.proj or 0) > (prev.proj or 0):
                looks[-1] = (g, q)
        else:
            looks.append((g, q))
    mean, var = wait_moments([g for g, _ in looks], p.swing, "healthy")
    return mean, [(g.date, q.name) for g, q in looks], var


def game_dist(g: Game, swing: float) -> tuple[float, float]:
    """(mean, spread) of a game that isn't over. Before the tip: Sleeper's scaled projection and swing × it. In
    progress: where it is headed (live_estimate), and the whole game's spread shrunk by the square root of the share
    left, since points pile up minute by minute. Fit by backtest_live.py on 2,843 player games: the miss at 12 / 24 /
    36 / 42 minutes was 0.87 / 0.70 / 0.51 / 0.36 of the pre-game miss; √share left is 0.87 / 0.71 / 0.50 / 0.35."""
    mu = _mu(g)
    if not g.live:
        return mu, mu * swing
    est = live_estimate(g) if g.fp is not None else mu
    return est, (mu or est) * swing * math.sqrt(_share_left(g))


def _above(mu: float, sigma: float, v: float) -> tuple[float, float, float]:
    """For X ~ Normal(mu, sigma): P(X > v), E[X; X > v] and E[X²; X > v] (the part of X that beats v)."""
    if sigma <= 0:
        hit = 1.0 if mu > v else 0.0
        return hit, hit * mu, hit * mu * mu
    d = (mu - v) / sigma
    c, f = _cdf(d), _phi(d)
    return c, mu * c + sigma * f, (mu * mu + sigma * sigma) * c + (mu + v) * sigma * f


def wait_moments(remaining: list[Game], swing: float, injury: str) -> tuple[float, float]:
    """(mean, variance) of what his remaining games end up with under the optimal lock rule (see module doc): going
    backwards, a game he plays is locked when it beats the value of the games after it, else the wait goes on; a game
    he misses passes the wait on, and missing the final one leaves 0 (Sleeper counts an unlocked player's final game,
    even a zero). The variance is the real mix, not value × swing: a questionable player's 60 % of a 20 is far less
    certain than a healthy player's 12. One game: mean p·μ, variance p·(σ² + μ²) − (p·μ)²."""
    v = m2 = 0.0   # mean and second moment of the games after this one
    for i in range(len(remaining) - 1, -1, -1):
        (mu, sigma), p = game_dist(remaining[i], swing), play_chance(remaining[i], injury, i == 0)
        v, m2 = _then(mu, sigma, p, v, m2, last=i == len(remaining) - 1)
    return v, max(0.0, m2 - v * v)


def _then(mu: float, sigma: float, p: float, v: float, m2: float, last: bool) -> tuple[float, float]:
    """One game ~ Normal(mu, sigma), played with chance p, ahead of games worth (mean v, second moment m2): the mean
    and second moment of the two together. Played, it is locked when it beats v, else the wait goes on; `last` = there
    is nothing after it, so it counts whatever it is. Missed, the wait goes on."""
    if last:
        e1, e2 = mu, mu * mu + sigma * sigma
    else:
        c, a, b = _above(mu, sigma, v)
        e1, e2 = a + (1 - c) * v, b + (1 - c) * m2
    return p * e1 + (1 - p) * v, p * e2 + (1 - p) * m2


def wait_value(remaining: list[Game], swing: float, injury: str) -> float:
    """Value of his remaining games played with the optimal lock rule: wait_moments' mean."""
    return wait_moments(remaining, swing, injury)[0]


def lock_slots(p: PlanPlayer, players: list[PlanPlayer], slot_counts: dict[str, int]) -> list[dict]:
    """Where to lock him (a lock freezes him in that slot for the week): for every starting slot he can play, the value
    the rest of the lineup can still reach with him locked there (everyone else seated around him by value, sliding
    multi-position players: seat_players), and how many other players could use that slot. Best first.
    [{slot, team: value of the other slots, others: other unlocked players who can play it, open: free slots left}]"""
    saved = {id(q): (q.seat, q.slot) for q in players}
    locked = [q for q in players if q.locked is not None and q.slot in slot_counts]
    others = sorted((q for q in players if q is not p and q.locked is None and q.slot != "IR" and q.value > 0),
                    key=lambda q: -q.value)
    out = []
    for s in roster.candidate_slots(p.eligibility):
        if s not in slot_counts or sum(q.slot == s for q in locked) >= slot_counts[s]:
            continue
        p.slot = s
        seats = seat_players(others, slot_counts, locked + [p])
        out.append({"slot": s, "team": round(sum(q.value for ss in seats.values() for q in ss if q in others), 2),
                    "others": sum(1 for q in others if s in roster.candidate_slots(q.eligibility)),
                    "open": slot_counts[s] - 1 - sum(q.slot == s for q in locked)})
        p.slot = saved[id(p)][1]
    for q in players:
        q.seat, q.slot = saved[id(q)]
    return sorted(out, key=lambda o: (-o["team"], o["slot"] != p.slot))   # a tie: where he already sits (no move)


def seat_players(order: list[PlanPlayer], slot_counts: dict[str, int], pinned=()) -> dict[str, list[PlanPlayer]]:
    """Pinned players keep their current slot; then each player in `order` takes a slot he can play, sliding
    already-seated (unpinned) multi-position players elsewhere when that makes room. Sets .seat."""
    seats: dict[str, list[PlanPlayer]] = {s: [] for s in slot_counts}
    fixed = {id(p) for p in pinned}
    for p in pinned:
        p.seat = p.slot
        seats[p.slot].append(p)

    def place(p: PlanPlayer, seen: set[str]) -> bool:
        """Seat one player in the first slot he can play (his current slot first), sliding other players along a chain when that is needed; False when no seat is possible."""
        slots = roster.candidate_slots(p.eligibility)
        if p.slot in slots:   # his current slot first: fewest moves for the same result
            slots = [p.slot] + [x for x in slots if x != p.slot]
        for slot in slots:
            if slot not in seats or slot in seen:
                continue
            seen.add(slot)
            if len(seats[slot]) < slot_counts[slot]:
                seats[slot].append(p)
                p.seat = slot
                return True
            for q in list(seats[slot]):
                if id(q) in fixed:
                    continue
                seats[slot].remove(q)
                if place(q, seen):
                    seats[slot].append(p)
                    p.seat = slot
                    return True
                seats[slot].append(q)
                q.seat = slot
        return False

    for p in order:
        p.seat = None
        place(p, set())
    return seats


def plan_week(players: list[PlanPlayer], slot_counts: dict[str, int]) -> WeekPlan:
    """Plan the week: seat the players in the starting slots (his current slot first, fewest moves) and value each unlocked slot by what waiting on its games is worth; a played, final game gets a LOCK / PASS call."""
    starting = set(slot_counts)
    for p in players:
        played = [g for g in p.games if g.fp is not None]
        remaining = [g for g in p.games if not g.started]
        live = next((g for g in p.games if g.live), None)
        if live and p.locked is None and p.slot in starting:
            # a starter's game in progress counts where it's headed (no stats yet: its projection), not his points so far
            remaining = [live] + remaining
        p.x, p.x_final = None, False
        if p.locked is None and p.slot in starting and played:
            last = played[-1]
            later_started = any(g.started for g in p.games if g.date > last.date)
            if not later_started:
                p.x, p.x_final = last.fp, not last.live   # a played game not in progress is over
        p.w, p.w_var = wait_moments(remaining, p.swing, p.injury) if p.locked is None else (0.0, 0.0)
        p.value = p.locked if p.locked is not None else max(p.x or 0.0, p.w)

    for p in players:
        p.seat = None
    pinned = [p for p in players if p.locked is not None and p.slot in slot_counts]   # locked players keep their slots
    order = sorted((p for p in players if p.locked is None and p.slot != "IR" and p.value > 0), key=lambda p: -p.value)
    seats = seat_players(order, slot_counts, pinned)

    for p in players:   # a lockable starter: locking him closes his slot, so waiting is worth what the open slot gets
        # only a final game is lockable; a game in progress keeps his own value (w: its projected finish counted)
        p.slot_w, p.slot_from, p.slot_var = (open_slot(p, players) if p.seat and p.x is not None and p.x_final and p.locked is None
                                             else (None, [], 0.0))
    for p in players:
        if p.locked is not None:
            p.action, p.why = "LOCKED", f"locked {p.locked:.1f}"
        elif p.seat is None:
            p.action = "DONE" if p.value <= 0 else "BENCH"
            p.why = "no games left" if p.value <= 0 else "his games aren't worth a slot this week"
        elif p.x is not None and not p.x_final:   # his game is still going: nothing to lock yet
            p.action, p.why = "LIVE", "his game isn't over: it can only be locked once it's final"
        elif p.x is not None and p.x >= p.slot_w:
            p.action = "LOCK"
            move = f" (move him {p.slot} → {p.seat} first)" if p.seat != p.slot else ""
            p.why = f"{p.x:.1f} beats keeping the slot open (~{p.slot_w:.1f}): lock in the {p.seat} slot{move}"
        elif p.x is not None:
            p.action, p.why = "PASS", f"the {p.seat} slot's games still to come are worth ~{p.slot_w:.1f}, more than {p.x:.1f}"
        else:
            p.action, p.why = "WAIT", f"{p.seat} slot: his games are worth ~{p.w:.1f}"
    expected = sum(p.value for s in seats.values() for p in s)
    return WeekPlan(players=players, expected=round(expected, 2), slots=dict(slot_counts))


# Every unlocked slot is a free chance at a pop-off on any day: start everyone who plays today, as long as that
# doesn't cost a game worth keeping. Seating order:
#   pinned  - locked players, and anyone whose game is in progress (he can't be moved), in their current slot;
#   1       - players whose call is LOCK (they must stay in the lineup to lock);
#   2       - players who play later today, best projection for today's game first;
#   3       - no game today: by next game, earliest tip first (set now for the coming games); then current
#             starters hold any slot still free.
# Benching a player with a played, unlocked game forfeits that game; only LOCK players have one worth keeping,
# and they come first. The moves are the differences from the current Sleeper lineup.

@dataclass
class TodayLineup:
    """Today's lineup: the seat of each player, the moves from the current Sleeper lineup and the swap-watch and GTD lines."""
    seats: dict[str, list[str]]          # slot -> player ids
    moves: list[dict]                    # {sid, name, from, to, by}: `by` = tip-off the move must beat (UTC ISO)
    watch: list[dict]                    # swap-watch and GTD lines (see today_watch)


def sits_out(p: PlanPlayer, g: Game | None) -> bool:
    """Ruled OUT and hasn't played a minute of this game: he scores exactly 0 in it."""
    return p.injury in OUT and g is not None and not (g.min or g.fp)


def _today(p: PlanPlayer, today: str) -> Game | None:
    """The player's game on `today`, if any."""
    return next((g for g in p.games if g.date == today), None)


def _by_tip(ps: list[PlanPlayer], game) -> list[PlanPlayer]:
    """Start order by game(p): earliest tip first. If the early game goes badly you swap the later player in before
    his tip (see today_watch); starting the later one first gives that chance away. Tips CLOSE_TIPS_MIN or less
    apart are one group (no time to judge the first game): the bigger projection starts, unless within CLOSE_PROJ."""
    from functools import cmp_to_key
    tips = [game(q).tip for q in ps]

    def first(a: PlanPlayer, b: PlanPlayer) -> int:   # -1: a starts ahead of b
        """Order two players by seating priority: -1 when `a` starts ahead of `b` (earlier tip group first, then the bigger projection; a near tie goes to the earlier tip)."""
        A, B = game(a), game(b)
        ga, gb = _tip_group(A.tip, tips), _tip_group(B.tip, tips)
        if ga != gb:
            return -1 if ga < gb else 1
        pa, pb = A.proj or 0, B.proj or 0
        if abs(pa - pb) <= CLOSE_PROJ:   # a near tie: the earlier tip (a little more to go on)
            return -1 if _minutes(A.tip) < _minutes(B.tip) else 1
        return -1 if pa > pb else 1
    return sorted(ps, key=cmp_to_key(first))


def plan_today(players: list[PlanPlayer], slot_counts: dict[str, int], today: str, now: str | None = None) -> TodayLineup:
    """Plan today's lineup: pin locked and in-progress players, then seat everyone who plays today (LOCK players first, then by projection), then players by next tip, with moves from the current Sleeper lineup.
    A SWAP call joins the lineup only from its check-in (`now` ≥ the backup's tip - CHECK_LEAD_MIN): until then the starter's game can still turn."""
    # in progress = can't move, except an OUT player who hasn't played a minute: he scores 0, so he's benched right away.
    # A starter whose game today has begun keeps his slot after it too: only a swap call (today_watch) benches him for a
    # later player, so the swap windows and the lineup are one decision.
    playing = {id(p) for p in players if _today(p, today) and _today(p, today).started and not sits_out(p, _today(p, today))}
    live_today = {id(p) for p in players if id(p) in playing and _today(p, today).live}
    pinned = [p for p in players if p.slot in slot_counts and (p.locked is not None or id(p) in playing)]
    free = [p for p in players if p not in pinned and id(p) not in live_today and p.slot != "IR" and p.locked is None]
    tier1 = [p for p in free if p.action == "LOCK"]
    plays = [p for p in free if p not in tier1 and _today(p, today) and not _today(p, today).started and p.injury not in OUT]
    tier2 = _by_tip(plays, lambda p: _today(p, today))
    # No game today: the slots left go by each player's next game, the same way (earliest tip first), so today's
    # lineup is already set for the coming games and nobody waits for game day to be moved in. Then current
    # starters with no next game (or ruled OUT) hold whatever is still free.
    def nxt(p: PlanPlayer) -> Game | None:
        """A player's next game after today that hasn't started."""
        return next((g for g in p.games if g.date > today and not g.started), None)
    rest = [p for p in free if p not in tier1 and p not in tier2]
    # ...except a starter who already played this week, today included (unlocked): benching him gives up locking that game, and on a
    # day neither plays nothing is gained, so he holds his slot (anyone who plays today can still take it, above).
    # When a later player needs one of their slots, the one who sits is whoever's latest game is worth least
    # (given_up: a game in progress counts at its projected finish).
    held = sorted((p for p in rest if p.slot in slot_counts and any(g.date < today or g.started for g in p.games)
                   and p.injury not in OUT), key=lambda p: -given_up(p))
    tier3 = held + _by_tip([p for p in rest if p not in held and nxt(p) and p.injury not in OUT], nxt)
    tier3 += sorted((p for p in rest if p not in tier3 and p.slot in slot_counts), key=lambda p: -p.value)
    plan_seat = {id(p): p.seat for p in players}
    for p in players:   # today's seating starts empty: nobody keeps a week-plan seat he isn't given today
        p.seat = None
    order = tier1 + tier2 + tier3
    seats = seat_players(order, slot_counts, pinned)
    today_seat = {id(p): p.seat for p in players}
    watch = today_watch(players, today, today_seat, slot_counts, pinned)
    # A SWAP call (a starter's game in progress headed below a later bench player's) or a PENDING one (no live score
    # yet: the starter the swap is worth most against): the lineup makes it at its check-in, so the arrows and the
    # timeline show it then, not just the swap window. The starter sits; the backup is seated first (others slide to fit).
    by_sid = {p.sid: p for p in players}
    swaps = {}   # starter sid -> backup; one backup per starter
    for w in watch:
        gs = _today(by_sid[w["sid"]], today) if w["kind"] == "swap" else None
        # due at the backup's check-in, or sooner once the starter's game is over (nothing left to wait for: one visit a night)
        if (w["kind"] == "swap" and w["decision"] in ("SWAP", "PENDING") and w["sid"] not in swaps and now
                and (_minutes(now) >= _minutes(w["by"]) - CHECK_LEAD_MIN or (gs.started and not gs.live))):
            swaps[w["sid"]] = by_sid[w["backup_sid"]]
    if swaps:
        sat = {id(by_sid[s]) for s in swaps}
        backups = list(swaps.values())
        for p in players:
            p.seat = None
        seats = seat_players(backups + [p for p in order if id(p) not in sat and p not in backups], slot_counts,
                             [p for p in pinned if id(p) not in sat])
        today_seat = {id(p): p.seat for p in players}
    for p in players:   # leave the week plan's seats on the players
        p.seat = plan_seat[id(p)]

    moves = []
    for p in players:
        to = today_seat[id(p)] or ("IR" if p.slot == "IR" else "BN")
        if to != p.slot and not (p.slot not in slot_counts and to == "BN"):
            g = _today(p, today)
            moves.append({"sid": p.sid, "name": p.name, "from": p.slot, "to": to,
                          "by": g.tip if g and not g.started else None})
    moves.sort(key=lambda m: (m["by"] or "~", m["to"] == "BN"))
    return TodayLineup(seats={s: [p.sid for p in ps] for s, ps in seats.items()}, moves=moves, watch=watch)


GAME_SECONDS, QUARTER_SECONDS, OT_SECONDS = 48 * 60, 12 * 60, 5 * 60
# Fit by backtest_live.py on 1,782 player games (weeks 1-3, 2026-27): tonight's rate barely predicts the rest of his
# game (MAE best at 60-80 vs 10), and projected minutes × share left ran ~0.7 min high (Sleeper's minutes run high,
# starters sit late); 0.9 takes the +0.3-0.5 FP bias to ~0. Rerun the backtest to retune as the season goes on.
PRIOR_MINUTES, MINUTES_LEFT_SCALE = 60.0, 0.9
CLOSE_TIPS_MIN = 15  # tips this close count as the same time (bigger projection starts; no swap check between them)
CLOSE_PROJ = 1.0     # ...unless the projections are this close: then the earlier tip
CHECK_LEAD_MIN = 15  # check-ins sit this long before the tip they're for: a SWAP call is made then, not before
OUT = ("out_short_term", "out_long_term", "out_season")


def _minutes(iso: str | None) -> float:
    """An ISO timestamp as minutes since the epoch (infinity when missing)."""
    from datetime import datetime
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() / 60 if iso else float("inf")


def _tip_group(tip: str | None, tips: list[str | None]) -> float:
    """The start of his tip's group: groups open at the earliest tip and hold every tip within CLOSE_TIPS_MIN of
    that opening tip (6:00, 6:10 together; 6:20 opens the next group)."""
    start = None
    for t in sorted(_minutes(x) for x in tips):
        if start is None or t - start > CLOSE_TIPS_MIN:
            start = t
        if t >= _minutes(tip):
            return start
    return _minutes(tip)
ALARM_LEAD_MIN = 5   # the swap check fires this many minutes before the later player's tip


def live_estimate(g: Game) -> float | None:
    """Where his game will likely finish: points so far + his scoring rate × the minutes he has left. The rate is
    his rate tonight shrunk toward his projected rate (as if he'd played PRIOR_MINUTES more at it), so a hot or cold
    first few minutes don't swing the call; minutes left = his projected minutes × the share of the game left, cut by
    MINUTES_LEFT_SCALE. In overtime the share left is the rest of that period."""
    if g.fp is None:
        return None
    if g.final or not g.live:
        return g.fp
    played = g.min or 0.0
    proj_rate = (g.proj or 0.0) / g.proj_min if g.proj_min else 0.0
    rate = (g.fp + proj_rate * PRIOR_MINUTES) / (played + PRIOR_MINUTES)
    left = max(0.0, (g.proj_min or played) * _share_left(g) * MINUTES_LEFT_SCALE)
    return g.fp + rate * left


def given_up(p: PlanPlayer) -> float:
    """What benching him now gives up: his latest game, a game in progress at its projected finish (live_estimate, by
    ESPN's clock now). Only that game: his later games stay usable in any slot, so they don't decide who sits."""
    last = next((g for g in reversed(p.games) if g.fp is not None), None)
    if last is None:
        return p.value
    return live_estimate(replace(last, live=True)) if not last.final and last.period else last.fp


def _share_left(g: Game) -> float:
    """What is left of a live game, as a share of regulation: in overtime, the rest of that 5-minute period (a player
    still on the floor is still scoring; 0 here would freeze his game as if it were final)."""
    if g.period > 4:
        return min(OT_SECONDS, max(0.0, g.clock)) / GAME_SECONDS
    elapsed = min(GAME_SECONDS, (max(1, g.period) - 1) * QUARTER_SECONDS + (QUARTER_SECONDS - g.clock)) if g.period else 0
    return 1 - elapsed / GAME_SECONDS


def beat_chance(score: float, games: list[Game], swing: float, injury: str) -> float:
    """Chance at least one of his unfinished games beats `score`. Each game ~ Normal(game_dist), played at his
    play_chance (injury, back-to-backs); a live game centres on his pace, its spread shrinking with the time left.
    ponytail: games taken as independent, so it runs a little high when hot / cold streaks carry over."""
    miss = 1.0
    for i, g in enumerate(games):
        (mu, sd), p = game_dist(g, swing), play_chance(g, injury, i == 0)
        hit = (1.0 if mu > score else 0.0) if sd <= 0 else 1 - _cdf((score - mu) / sd)
        miss *= 1 - p * hit
    return 1 - miss


def swap_call(s: PlanPlayer, b: PlanPlayer, today: str) -> dict:
    """Keep S (his game tonight is the slot's chance; pass on it if his later games are worth more) or swap B in
    (S's game tonight is forfeited, the slot gets B's game, S still has his later games). Both sides are valued the
    same way (_then): tonight's game, with S's later games behind it as the fallback, so a game still in progress
    keeps the upside it has left just as B's game does. gain = swap − keep, whatever state S's game is in."""
    gs, gb = _today(s, today), _today(b, today)
    later = [g for g in s.games if g.date > today and not g.started]
    bar, bar_var = wait_moments(later, s.swing, s.injury)      # what S's later games are worth
    bar_m2 = bar_var + bar * bar
    (mu_b, sd_b), p_b = game_dist(gb, b.swing), play_chance(gb, b.injury, True)
    swap, swap_m2 = _then(mu_b, sd_b, p_b, bar, bar_m2, last=not later)
    # a game the timeline's check treats as over but that isn't final yet: judge it at its projected finish
    now = replace(gs, live=True) if gs.started and not gs.final and gs.period else gs
    if not gs.started:                                         # not started: judge it at the alarm
        est = None
        keep, keep_m2 = _then(*game_dist(gs, s.swing), play_chance(gs, s.injury, True), bar, bar_m2, last=not later)
    elif now.live and now.fp is not None and not sits_out(s, gs):   # under way: where it is headed, and the spread it has left
        (est, sd_s) = game_dist(now, s.swing)
        keep, keep_m2 = _then(est, sd_s, 1.0, bar, bar_m2, last=not later)
    elif now.live and s.injury not in OUT:                     # tipped, no stats yet: no score to judge
        est = None
        keep, keep_m2 = _then(*game_dist(now, s.swing), 1.0, bar, bar_m2, last=not later)
    else:                                                      # over (or under way without him: he scores 0): a known score
        est = gs.fp or 0.0
        keep, keep_m2 = (est, est * est) if est >= bar else (bar, bar_m2)
    out = {"swap": round(swap, 1), "bar": round(bar, 1), "keep_if": round(swap, 1),   # keep_if: the finish S must be headed for
           "gain": round(swap - keep, 2), "swap_var": max(0.0, swap_m2 - swap * swap), "keep_var": max(0.0, keep_m2 - keep * keep)}
    if est is None:
        return {"decision": "PENDING", "est": None, "keep": None, **out}
    # his game is under way: headed past the backup's own projection, the swap is off (whatever the option math says)
    return {"decision": "SWAP" if swap > keep and est <= mu_b else "KEEP", "est": round(est, 1), "keep": round(keep, 1), **out}


def _minus_minutes(iso: str | None, minutes: int) -> str | None:
    """An ISO timestamp minus some minutes (None when missing)."""
    from datetime import datetime, timedelta, timezone
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(minutes=minutes)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def today_watch(players: list[PlanPlayer], today: str, seat: dict[int, str | None], slot_counts: dict[str, int] | None = None,
                pinned=()) -> list[dict]:
    """For every starter who plays today, the best bench player who could take his slot and tips LATER (any gap,
    even 45 minutes): an alarm ALARM_LEAD_MIN before that tip, and the call KEEP / SWAP from the live score of the
    starter's game (PENDING until it starts). Also questionable (GTD) starters with a backup who plays today."""
    lines, candidates = [], {}
    starters = [p for p in players if seat.get(id(p)) and p.locked is None and _today(p, today)]
    bench = [p for p in players if not seat.get(id(p)) and p.slot != "IR" and p.locked is None
             and _today(p, today) and not _today(p, today).started and p.injury not in OUT]
    for p in players:   # in the lineup now, plays today, ruled OUT before tip: start someone else right away
        g = _today(p, today)
        if p.slot not in ("BN", "IR") and g and (not g.started or sits_out(p, g)) and p.injury in OUT:
            # who today's lineup moves into his spot (a bench player who plays tonight), else the best one who fits
            fits = [b for b in players if b is not p and b.slot in ("BN",) and seat.get(id(b)) and _today(b, today)]                 or [b for b in bench if p.slot in roster.candidate_slots(b.eligibility)]
            backup = max(fits, key=lambda b: _today(b, today).proj or 0, default=None)
            lines.append({"kind": "out", "sid": p.sid, "name": p.name, "slot": p.slot, "by": g.tip, "alarm": "now",
                          "backup": backup.name if backup else None,
                          "text": f"{p.name} is OUT tonight: bench him" + (f" and start {backup.name} at {p.slot} now." if backup else " (nobody on the bench who plays tonight fits).")})
    seated = [p for p in players if seat.get(id(p))]

    def can_replace(s: PlanPlayer, b: PlanPlayer) -> bool:
        """Can b take s's place: straight into his slot, or with other movable starters sliding along (Reaves PG/SG
        to PG so an SG/SF fits at SG)?"""
        if seat[id(s)] in roster.candidate_slots(b.eligibility):
            return True
        if not slot_counts:
            return False
        was = {id(p): p.seat for p in players}
        rest = [p for p in seated if p is not s]
        seat_players([b] + [p for p in rest if p not in pinned], slot_counts, [p for p in pinned if p is not s])
        ok = b.seat is not None and all(p.seat for p in rest)
        for p in players:
            p.seat = was[id(p)]
        return ok

    for s in starters:
        gs, slot = _today(s, today), seat[id(s)]
        fits = [b for b in bench if slot in roster.candidate_slots(b.eligibility)]
        if s.injury == "day_to_day" and fits and not gs.started:
            backup = max(fits, key=lambda b: _today(b, today).proj or 0)
            lines.append({"kind": "gtd", "sid": s.sid, "name": s.name, "slot": slot, "by": gs.tip,
                          "alarm": _minus_minutes(gs.tip, 30), "backup": backup.name, "backup_tip": _today(backup, today).tip,
                          "text": f"{s.name} is questionable: check before his tip. If he's out, start {backup.name} at {slot}."})
        for b in (b for b in bench if can_replace(s, b)):   # every bench player tipping later (by more than CLOSE_TIPS_MIN)
            if _minutes(_today(b, today).tip) - _minutes(gs.tip) <= CLOSE_TIPS_MIN:
                continue
            candidates.setdefault(b.sid, (b, []))[1].append((s, slot, swap_call(s, b, today)))

    # One alarm per later player: at his tip - ALARM_LEAD_MIN, swap him in (if that's worth it) for the starter whose
    # game is headed lowest (his projected finish: benching him gives up only tonight's game, his later ones stay
    # usable), or keep everyone. PENDING until at least one of those starters' games has begun.
    # A starter goes to one backup: earliest tip first (his alarm rings first), then the bigger swap; a later backup
    # whose every starter is taken gets no line.
    claimed = set()
    for b, opts in sorted(candidates.values(), key=lambda c: (_minutes(_today(c[0], today).tip), -max(o[2]["swap"] for o in c[1]))):
        opts = [o for o in opts if o[0].sid not in claimed]
        if not opts:
            continue
        tip = _today(b, today).tip
        live = [o for o in opts if o[2]["decision"] != "PENDING"]
        best = min((o for o in live if o[2]["decision"] == "SWAP"), key=lambda o: o[2]["est"], default=None) \
            or max(live, key=lambda o: o[2]["swap"] - o[2]["keep"], default=None)
        if best and best[2]["decision"] == "SWAP":
            s, slot, call = best
            text = (f"SWAP: {s.name} is headed for ~{call['est']} (keep is worth {call['keep']}). Bench him and start "
                    f"{b.name} at {slot} before {b.name}'s tip (worth ~{call['swap']}).")
            decision = "SWAP"
        elif live and len(live) == len(opts):
            s, slot, call = best
            text = f"KEEP everyone: no starter is headed below what {b.name}'s game is worth ({', '.join(f'{o[0].name} ~{o[2]['est']}' for o in live)})."
            decision = "KEEP"
        else:
            s, slot, call = max((o for o in opts if o[2]["decision"] == "PENDING"), key=lambda o: o[2]["gain"])
            lines_ = ", ".join(f"{o[0].name} {o[2]['keep_if']}+" for o in sorted(opts, key=lambda o: o[2]["keep_if"]))
            text = (f"{ALARM_LEAD_MIN} min before {b.name}'s tip the site reads the games of the starters he could replace "
                    f"and swaps him in for whoever is furthest below his keep line ({lines_}).")
            decision = "PENDING"
        if decision != "KEEP":
            claimed.add(s.sid)
        lines.append({"kind": "swap", "sid": s.sid, "name": s.name, "slot": slot, "backup": b.name, "backup_sid": b.sid,
                      "by": tip, "alarm": _minus_minutes(tip, ALARM_LEAD_MIN), "text": text, **call, "decision": decision,
                      "options": [{"sid": o[0].sid, "name": o[0].name, "slot": o[1], **o[2]} for o in opts]})
    return lines


# The decision rule for locks, passes and swaps: the choice with the higher chance to win the week, not the higher
# expected points. Each team's final = its counted/locked points (certain) + every other slot's value, which is
# uncertain while it still waits on games (its variance: wait_moments). Chance to win =
# Φ((my total − their total) / √(my spread² + their spread²)). Example: everyone else locked, you need 13 more:
# locking 15 wins unless they beat their estimate by 2; waiting on a 20-proj game wins unless it lands under 13,
# and the site shows both chances side by side.

def slot_spread(p: PlanPlayer, lock: bool) -> tuple[float, float]:
    """(expected FP, variance) a seated player adds to his team's final: certain once locked (or locking now)."""
    if p.locked is not None:
        return p.locked, 0.0
    if lock and p.x is not None:
        return p.x, 0.0
    # waiting on a lockable game: the open slot's value (open_slot)
    return (p.slot_w, p.slot_var) if p.slot_w is not None else (p.w, p.w_var)


def team_total(players: list[PlanPlayer], skip: PlanPlayer | None = None) -> tuple[float, float]:
    """A team's expected total and variance across its seated players (optionally leaving one out)."""
    mean = var = 0.0
    for p in players:
        if p.seat is None or p is skip:
            continue
        m, v = slot_spread(p, lock=p.action == "LOCK")
        mean, var = mean + m, var + v
    return mean, var


def scenario_total(players: list[PlanPlayer], lock_all: bool) -> tuple[float, float]:
    """The team's final (mean, variance) if you lock every game you can now (safe) or wait on every player who still
    has games to come (risky; a player with nothing left to play still locks what he has)."""
    mean = var = 0.0
    for p in players:
        if p.seat is None:
            continue
        m, v = slot_spread(p, lock=p.x is not None and p.x_final and (lock_all or p.w <= 0))
        mean, var = mean + m, var + v
    return mean, var


def win_chance(mine: tuple[float, float], theirs: tuple[float, float]) -> float:
    """Chance to win the week: the normal CDF of the difference of totals over the combined spread."""
    sd = math.sqrt(mine[1] + theirs[1])
    if sd == 0:
        return 1.0 if mine[0] > theirs[0] else 0.5 if mine[0] == theirs[0] else 0.0
    return _cdf((mine[0] - theirs[0]) / sd)


def decide_by_win_chance(players: list[PlanPlayer], theirs: tuple[float, float]) -> float:
    """Re-decide every lockable seated player (LOCK vs PASS) by the chance to win, and return the team's chance."""
    for p in players:
        if p.seat is None or p.locked is not None or p.x is None or not p.x_final:   # only a final game can be locked
            continue
        mean, var = team_total(players, skip=p)
        p.win_lock = win_chance((mean + p.x, var), theirs)
        w, w_var = slot_spread(p, lock=False)   # waiting = keeping his slot open (open_slot)
        p.win_wait = win_chance((mean + w, var + w_var), theirs) if w > 0 else 0.0
        p.action = "LOCK" if p.win_lock >= p.win_wait else "PASS"
        p.why = (f"Lock {p.x:.1f}: {p.win_lock:.0%} to win · keep the slot open (~{w:.1f} from games still to come): {p.win_wait:.0%}"
                 + (f" · lock in the {p.seat} slot" if p.action == "LOCK" else ""))
    return win_chance(team_total(players), theirs)


def bench_lock_chance(p: PlanPlayer, players: list[PlanPlayer], slot_counts: dict[str, int], slot: str,
                      theirs: tuple[float, float]) -> float:
    """Chance to win if a starter the plan benches locks his final game in `slot` anyway (Sleeper allows it while he
    sits in a starting slot): the week re-planned on copies with him locked there, decided by win chance."""
    clones = copy.deepcopy(players)
    c = clones[players.index(p)]
    c.locked, c.slot = c.x, slot
    plan_week(clones, slot_counts)
    return decide_by_win_chance(clones, theirs)


def swap_win_chance(players: list[PlanPlayer], starter_sid: str, call: dict, theirs: tuple[float, float]) -> tuple[float, float] | None:
    """(win chance keeping the starter, win chance swapping the later player in) for one watch line."""
    s = next((p for p in players if p.sid == starter_sid), None)
    if s is None or call.get("keep") is None:
        return None
    mean, var = team_total(players, skip=s)
    keep = win_chance((mean + call["keep"], var + call["keep_var"]), theirs)
    swap = win_chance((mean + call["swap"], var + call["swap_var"]), theirs)
    return keep, swap
