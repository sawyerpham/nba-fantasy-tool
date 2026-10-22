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

swing = the player's own game-to-game variation under the league's scoring (std / mean of last season's games),
clamped to [MIN_SWING, MAX_SWING]; DEFAULT_SWING when he has too few games (rookies).
ponytail: games are independent normals and the plan ignores the option of swapping several later players
through one slot; good enough to rank lock/pass, revisit if the calls look off in practice.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from statistics import mean, pstdev

from ..core.engine import roster

DEFAULT_SWING, MIN_SWING, MAX_SWING, MIN_GAMES_FOR_SWING = 0.3, 0.12, 0.6, 15
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
    nxt, later = PLAY_CHANCE.get(injury, PLAY_CHANCE["healthy"])
    return (nxt if first else later) * (B2B_PLAY if g.b2b else 1.0)


@dataclass
class Game:
    date: str
    proj: float | None          # Sleeper projection in league FP; None = no projection
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
    sid: str
    name: str
    eligibility: list[str]
    slot: str                   # where he sits now: a starting slot, "BN" or "IR"
    games: list[Game]
    swing: float = DEFAULT_SWING
    injury: str = "healthy"
    locked: float | None = None # locked score, if he's locked this week
    # filled by plan_week
    x: float | None = None      # lockable now
    w: float = 0.0              # value of waiting
    value: float = 0.0
    seat: str | None = None
    action: str = ""            # LOCKED / LOCK / PASS / BENCH (not seated) / DONE
    why: str = ""
    win_lock: float | None = None   # chance to win the week if he locks now / if he waits (decide_by_win_chance)
    win_wait: float | None = None
    slot_w: float | None = None     # a lockable starter's slot left open: what it can still get (open_slot)
    slot_from: list = field(default_factory=list)   # [(date, player name)]: whose game it would take each day


@dataclass
class WeekPlan:
    players: list[PlanPlayer]
    expected: float             # expected FP of all slots
    slots: dict[str, int] = field(default_factory=dict)


def swing_of(per_game_fpts: list[float]) -> float:
    games = [f for f in per_game_fpts if f is not None]
    if len(games) < MIN_GAMES_FOR_SWING or mean(games) <= 0:
        return DEFAULT_SWING
    return min(MAX_SWING, max(MIN_SWING, pstdev(games) / mean(games)))


def _phi(z: float) -> float:
    return math.exp(-z * z / 2) / math.sqrt(2 * math.pi)


def _cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def expected_max(mu: float, sigma: float, v: float) -> float:
    """E[max(X, v)] for X ~ Normal(mu, sigma)."""
    if sigma <= 0:
        return max(mu, v)
    d = (mu - v) / sigma
    return v + (mu - v) * _cdf(d) + sigma * _phi(d)


def open_slot(p: PlanPlayer, players: list[PlanPlayer]) -> tuple[float, list[tuple[str, str]]]:
    """What his slot is worth left open (not locking him): each remaining day it can take the best game from him or a
    bench player who fits the slot and isn't seated in the plan, with the option to lock the best one (wait_value).
    That's why locking a decent game can be wrong with a deep bench: it gives up every one of those chances.
    ponytail: two open slots can both count the same bench player; fine while one lock is decided at a time."""
    pool = [p] + [q for q in players if q is not p and q.seat is None and q.slot != "IR" and q.locked is None
                  and q.injury not in OUT and p.seat in roster.candidate_slots(q.eligibility)]
    best: dict[str, tuple[Game, PlanPlayer]] = {}
    for q in pool:
        for g in q.games:
            if not g.started and (g.date not in best or (g.proj or 0) > (best[g.date][0].proj or 0)):
                best[g.date] = (g, q)
    days = [best[d] for d in sorted(best)]
    return wait_value([g for g, _ in days], p.swing, "healthy"), [(g.date, q.name) for g, q in days]


def wait_value(remaining: list[Game], swing: float, injury: str) -> float:
    """Value of his remaining games played with the optimal lock rule (see module doc). Sitting out the final game
    leaves 0 (v starts at 0: Sleeper counts an unlocked player's final game, even a zero)."""
    v = 0.0
    for i in range(len(remaining) - 1, -1, -1):
        mu = max(0.0, remaining[i].proj or 0.0)
        p = play_chance(remaining[i], injury, i == 0)
        v = p * (mu if i == len(remaining) - 1 else expected_max(mu, mu * swing, v)) + (1 - p) * v
    return v


def seat_players(order: list[PlanPlayer], slot_counts: dict[str, int], pinned=()) -> dict[str, list[PlanPlayer]]:
    """Pinned players keep their current slot; then each player in `order` takes a slot he can play, sliding
    already-seated (unpinned) multi-position players elsewhere when that makes room. Sets .seat."""
    seats: dict[str, list[PlanPlayer]] = {s: [] for s in slot_counts}
    fixed = {id(p) for p in pinned}
    for p in pinned:
        p.seat = p.slot
        seats[p.slot].append(p)

    def place(p: PlanPlayer, seen: set[str]) -> bool:
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
    starting = set(slot_counts)
    for p in players:
        played = [g for g in p.games if g.fp is not None]
        remaining = [g for g in p.games if not g.started]
        p.x = None
        if p.locked is None and p.slot in starting and played:
            last = played[-1]
            later_started = any(g.started for g in p.games if g.date > last.date)
            if not later_started:
                p.x = last.fp
        p.w = wait_value(remaining, p.swing, p.injury) if p.locked is None else 0.0
        p.value = p.locked if p.locked is not None else max(p.x or 0.0, p.w)

    for p in players:
        p.seat = None
    pinned = [p for p in players if p.locked is not None and p.slot in slot_counts]   # locked players keep their slots
    order = sorted((p for p in players if p.locked is None and p.slot != "IR" and p.value > 0), key=lambda p: -p.value)
    seats = seat_players(order, slot_counts, pinned)

    for p in players:   # a lockable starter: locking him closes his slot, so waiting is worth what the open slot gets
        p.slot_w, p.slot_from = open_slot(p, players) if p.seat and p.x is not None and p.locked is None else (None, [])
    for p in players:
        if p.locked is not None:
            p.action, p.why = "LOCKED", f"locked {p.locked:.1f}"
        elif p.seat is None:
            p.action = "DONE" if p.value <= 0 else "BENCH"
            p.why = "no games left" if p.value <= 0 else "his games aren't worth a slot this week"
        elif p.x is not None and p.x >= p.slot_w:
            p.action = "LOCK"
            move = f" (move him {p.slot} → {p.seat} first)" if p.seat != p.slot else ""
            p.why = f"{p.x:.1f} beats keeping the slot open (~{p.slot_w:.1f}): lock in the {p.seat} slot{move}"
        elif p.x is not None:
            p.action, p.why = "PASS", f"the {p.seat} slot's games still to come are worth ~{p.slot_w:.1f}, more than {p.x:.1f}"
        else:
            p.action, p.why = "WAIT", f"{p.seat} slot: his games are worth ~{p.w:.1f}"
    expected = sum(p.value for s in seats.values() for p in s)
    return WeekPlan(players=players, expected=round(expected, 1), slots=dict(slot_counts))


# ---- today's lineup ------------------------------------------------------------------------------------------
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
    seats: dict[str, list[str]]          # slot -> player ids
    moves: list[dict]                    # {sid, name, from, to, by}: `by` = tip-off the move must beat (UTC ISO)
    watch: list[dict]                    # swap-watch and GTD lines (see today_watch)


def _today(p: PlanPlayer, today: str) -> Game | None:
    return next((g for g in p.games if g.date == today), None)


def _by_tip(ps: list[PlanPlayer], game) -> list[PlanPlayer]:
    """Start order by game(p): earliest tip first. If the early game goes badly you swap the later player in before
    his tip (see today_watch); starting the later one first gives that chance away. Tips CLOSE_TIPS_MIN or less
    apart are one group (no time to judge the first game): the bigger projection starts, unless within CLOSE_PROJ."""
    from functools import cmp_to_key
    tips = [game(q).tip for q in ps]

    def first(a: PlanPlayer, b: PlanPlayer) -> int:   # -1: a starts ahead of b
        A, B = game(a), game(b)
        ga, gb = _tip_group(A.tip, tips), _tip_group(B.tip, tips)
        if ga != gb:
            return -1 if ga < gb else 1
        pa, pb = A.proj or 0, B.proj or 0
        if abs(pa - pb) <= CLOSE_PROJ:   # a near tie: the earlier tip (a little more to go on)
            return -1 if _minutes(A.tip) < _minutes(B.tip) else 1
        return -1 if pa > pb else 1
    return sorted(ps, key=cmp_to_key(first))


def plan_today(players: list[PlanPlayer], slot_counts: dict[str, int], today: str) -> TodayLineup:
    live_today = {id(p) for p in players if _today(p, today) and _today(p, today).live}
    pinned = [p for p in players if p.slot in slot_counts and (p.locked is not None or id(p) in live_today)]
    free = [p for p in players if p not in pinned and id(p) not in live_today and p.slot != "IR" and p.locked is None]
    tier1 = [p for p in free if p.action == "LOCK"]
    plays = [p for p in free if p not in tier1 and _today(p, today) and not _today(p, today).started and p.injury not in OUT]
    tier2 = _by_tip(plays, lambda p: _today(p, today))
    # No game today: the slots left go by each player's next game, the same way (earliest tip first), so today's
    # lineup is already set for the coming games and nobody waits for game day to be moved in. Then current
    # starters with no next game (or ruled OUT) hold whatever is still free.
    def nxt(p: PlanPlayer) -> Game | None:
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
    seats = seat_players(tier1 + tier2 + tier3, slot_counts, pinned)
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
    return TodayLineup(seats={s: [p.sid for p in ps] for s, ps in seats.items()}, moves=moves,
                       watch=today_watch(players, today, today_seat))


GAME_SECONDS, QUARTER_SECONDS, PRIOR_MINUTES = 48 * 60, 12 * 60, 10.0
CLOSE_TIPS_MIN = 15  # tips this close count as the same time (bigger projection starts; no swap check between them)
CLOSE_PROJ = 1.0     # ...unless the projections are this close: then the earlier tip
OUT = ("out_short_term", "out_long_term", "out_season")


def _minutes(iso: str | None) -> float:
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
MIN_SWAP_GAIN = 0.5  # only watch a swap that could add at least this much (FP) over keeping the starter


def live_estimate(g: Game) -> float | None:
    """Where his game will likely finish: points so far + his scoring rate × the minutes he has left. The rate is
    his rate tonight shrunk toward his projected rate (as if he'd played PRIOR_MINUTES more at it), so a hot or cold
    first few minutes don't swing the call; minutes left = his projected minutes × the share of the game left."""
    if g.fp is None:
        return None
    if g.final or not g.live:
        return g.fp
    played = g.min or 0.0
    proj_rate = (g.proj or 0.0) / g.proj_min if g.proj_min else 0.0
    rate = (g.fp + proj_rate * PRIOR_MINUTES) / (played + PRIOR_MINUTES)
    left = max(0.0, (g.proj_min or played) * _share_left(g))
    return g.fp + rate * left


def given_up(p: PlanPlayer) -> float:
    """What benching him now gives up: his latest game, a game in progress at its projected finish (live_estimate, by
    ESPN's clock now). Only that game: his later games stay usable in any slot, so they don't decide who sits."""
    last = next((g for g in reversed(p.games) if g.fp is not None), None)
    if last is None:
        return p.value
    return live_estimate(replace(last, live=True)) if not last.final and last.period else last.fp


def _share_left(g: Game) -> float:
    """Share of a live game still to play (0 in overtime: whatever he plays then is a bonus)."""
    if g.period > 4:
        return 0.0
    elapsed = min(GAME_SECONDS, (max(1, g.period) - 1) * QUARTER_SECONDS + (QUARTER_SECONDS - g.clock)) if g.period else 0
    return 1 - elapsed / GAME_SECONDS


def beat_chance(score: float, games: list[Game], swing: float, injury: str) -> float:
    """Chance at least one of his unfinished games beats `score`. Each game ~ Normal(proj, proj × swing), played at his
    play_chance (injury, back-to-backs); a live game centres on his pace, its spread shrinking with the time left.
    ponytail: games taken as independent, so it runs a little high when hot / cold streaks carry over."""
    miss = 1.0
    for i, g in enumerate(games):
        if g.live:
            mu = live_estimate(g) if g.fp is not None else max(0.0, g.proj or 0.0)
            sd, p = mu * swing * _share_left(g), 1.0
        else:
            mu = max(0.0, g.proj or 0.0)
            sd, p = mu * swing, play_chance(g, injury, i == 0)
        hit = (1.0 if mu > score else 0.0) if sd <= 0 else 1 - _cdf((score - mu) / sd)
        miss *= 1 - p * hit
    return 1 - miss


def swap_call(s: PlanPlayer, b: PlanPlayer, today: str) -> dict:
    """Keep S (his game tonight is the slot's chance; pass on it if his later games are worth more) or swap B in
    (S's game tonight is forfeited, the slot gets B's game, S still has his later games)."""
    gs, gb = _today(s, today), _today(b, today)
    later = [g for g in s.games if g.date > today and not g.started]
    bar = wait_value(later, s.swing, s.injury)                 # what S's later games are worth
    nxt = play_chance(gb, b.injury, True)
    mu_b = max(0.0, gb.proj or 0.0)
    swap = nxt * expected_max(mu_b, mu_b * b.swing, bar) + (1 - nxt) * bar
    est = live_estimate(gs)
    # keep_if: the finish S must be headed for to beat swapping (below his later-games bar, any finish loses to it)
    keep_if = round(swap, 1)
    if est is None:                                            # not started: judge it at the alarm
        return {"decision": "PENDING", "est": None, "keep": None, "swap": round(swap, 1), "bar": round(bar, 1), "keep_if": keep_if}
    keep = max(est, bar)
    return {"decision": "SWAP" if swap > keep else "KEEP", "est": round(est, 1), "keep": round(keep, 1),
            "swap": round(swap, 1), "bar": round(bar, 1), "keep_if": keep_if}


def _minus_minutes(iso: str | None, minutes: int) -> str | None:
    from datetime import datetime, timedelta, timezone
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")) - timedelta(minutes=minutes)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def today_watch(players: list[PlanPlayer], today: str, seat: dict[int, str | None]) -> list[dict]:
    """For every starter who plays today, the best bench player who could take his slot and tips LATER (any gap,
    even 45 minutes): an alarm ALARM_LEAD_MIN before that tip, and the call KEEP / SWAP from the live score of the
    starter's game (PENDING until it starts). Also questionable (GTD) starters with a backup who plays today."""
    lines, candidates = [], {}
    starters = [p for p in players if seat.get(id(p)) and p.locked is None and _today(p, today)]
    bench = [p for p in players if not seat.get(id(p)) and p.slot != "IR" and p.locked is None
             and _today(p, today) and not _today(p, today).started]
    for p in players:   # in the lineup now, plays today, ruled OUT before tip: start someone else right away
        g = _today(p, today)
        if p.slot not in ("BN", "IR") and p.injury in OUT and g and not g.started:
            # who today's lineup moves into his spot (a bench player who plays tonight), else the best one who fits
            fits = [b for b in players if b is not p and b.slot in ("BN",) and seat.get(id(b)) and _today(b, today)]                 or [b for b in bench if p.slot in roster.candidate_slots(b.eligibility)]
            backup = max(fits, key=lambda b: _today(b, today).proj or 0, default=None)
            lines.append({"kind": "out", "sid": p.sid, "name": p.name, "slot": p.slot, "by": g.tip, "alarm": "now",
                          "backup": backup.name if backup else None,
                          "text": f"{p.name} is OUT tonight: bench him" + (f" and start {backup.name} at {p.slot} now." if backup else " (nobody on the bench who plays tonight fits).")})
    for s in starters:
        gs, slot = _today(s, today), seat[id(s)]
        fits = [b for b in bench if slot in roster.candidate_slots(b.eligibility)]
        if s.injury == "day_to_day" and fits and not gs.started:
            backup = max(fits, key=lambda b: _today(b, today).proj or 0)
            lines.append({"kind": "gtd", "sid": s.sid, "name": s.name, "slot": slot, "by": gs.tip,
                          "alarm": _minus_minutes(gs.tip, 30), "backup": backup.name, "backup_tip": _today(backup, today).tip,
                          "text": f"{s.name} is questionable: check before his tip. If he's out, start {backup.name} at {slot}."})
        for b in fits:   # every bench player tipping later (by more than CLOSE_TIPS_MIN) is a candidate swap
            if _minutes(_today(b, today).tip) - _minutes(gs.tip) <= CLOSE_TIPS_MIN:
                continue
            call = swap_call(s, b, today)
            if call["swap"] - call["bar"] >= MIN_SWAP_GAIN:   # his game must beat just waiting on S's later games
                candidates.setdefault(b.sid, (b, []))[1].append((s, slot, call))

    # One alarm per later player: at his tip - ALARM_LEAD_MIN, swap him in (if that's worth it) for the starter whose
    # game is headed lowest (his projected finish: benching him gives up only tonight's game, his later ones stay
    # usable), or keep everyone. PENDING until at least one of those starters' games has begun.
    for b, opts in candidates.values():
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
            s, slot, call = min(opts, key=lambda o: o[2]["keep_if"])
            lines_ = ", ".join(f"{o[0].name} {o[2]['keep_if']}+" for o in sorted(opts, key=lambda o: o[2]["keep_if"]))
            text = (f"{ALARM_LEAD_MIN} min before {b.name}'s tip the site reads the games of the starters he could replace "
                    f"and swaps him in for whoever is furthest below his keep line ({lines_}).")
            decision = "PENDING"
        lines.append({"kind": "swap", "sid": s.sid, "name": s.name, "slot": slot, "backup": b.name, "backup_sid": b.sid,
                      "by": tip, "alarm": _minus_minutes(tip, ALARM_LEAD_MIN), "text": text, **call, "decision": decision,
                      "options": [{"name": o[0].name, "slot": o[1], **o[2]} for o in opts]})
    return lines


# ---- win chance -----------------------------------------------------------------------------------------
# The decision rule for locks, passes and swaps: the choice with the higher chance to win the week, not the higher
# expected points. Each team's final = its counted/locked points (certain) + every other slot's value, which is
# uncertain while it still waits on games (spread = value × the player's swing × SPREAD). Chance to win =
# Φ((my total − their total) / √(my spread² + their spread²)). Example: everyone else locked, you need 13 more:
# locking 15 wins unless they beat their estimate by 2; waiting on a 20-proj game wins unless it lands under 13,
# and the site shows both chances side by side.
SPREAD = 0.8   # ponytail: a slot's spread ≈ one game's swing, shrunk a bit for the option of locking the best game


def slot_spread(p: PlanPlayer, lock: bool) -> tuple[float, float]:
    """(expected FP, variance) a seated player adds to his team's final: certain once locked (or locking now)."""
    if p.locked is not None:
        return p.locked, 0.0
    if lock and p.x is not None:
        return p.x, 0.0
    w = p.slot_w if p.slot_w is not None else p.w   # waiting on a lockable game: the open slot's value (open_slot)
    return w, (w * p.swing * SPREAD) ** 2


def team_total(players: list[PlanPlayer], skip: PlanPlayer | None = None) -> tuple[float, float]:
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
        m, v = slot_spread(p, lock=p.x is not None and (lock_all or p.w <= 0))
        mean, var = mean + m, var + v
    return mean, var


def win_chance(mine: tuple[float, float], theirs: tuple[float, float]) -> float:
    sd = math.sqrt(mine[1] + theirs[1])
    if sd == 0:
        return 1.0 if mine[0] > theirs[0] else 0.5 if mine[0] == theirs[0] else 0.0
    return _cdf((mine[0] - theirs[0]) / sd)


def decide_by_win_chance(players: list[PlanPlayer], theirs: tuple[float, float]) -> float:
    """Re-decide every lockable seated player (LOCK vs PASS) by the chance to win, and return the team's chance."""
    for p in players:
        if p.seat is None or p.locked is not None or p.x is None:
            continue
        mean, var = team_total(players, skip=p)
        p.win_lock = win_chance((mean + p.x, var), theirs)
        w = p.slot_w if p.slot_w is not None else p.w   # waiting = keeping his slot open (open_slot)
        p.win_wait = win_chance((mean + w, var + (w * p.swing * SPREAD) ** 2), theirs) if w > 0 else 0.0
        p.action = "LOCK" if p.win_lock >= p.win_wait else "PASS"
        p.why = (f"Lock {p.x:.1f}: {p.win_lock:.0%} to win · keep the slot open (~{w:.1f} from games still to come): {p.win_wait:.0%}"
                 + (f" · lock in the {p.seat} slot" if p.action == "LOCK" else ""))
    return win_chance(team_total(players), theirs)


def swap_win_chance(players: list[PlanPlayer], starter_sid: str, call: dict, backup_swing: float,
                    theirs: tuple[float, float]) -> tuple[float, float] | None:
    """(win chance keeping the starter, win chance swapping the later player in) for one watch line."""
    s = next((p for p in players if p.sid == starter_sid), None)
    if s is None or call.get("keep") is None:
        return None
    mean, var = team_total(players, skip=s)
    keep_var = 0.0 if call["est"] is not None and call["keep"] == call["est"] else (call["keep"] * s.swing * SPREAD) ** 2
    keep = win_chance((mean + call["keep"], var + keep_var), theirs)
    swap = win_chance((mean + call["swap"], var + (call["swap"] * backup_swing * SPREAD) ** 2), theirs)
    return keep, swap
