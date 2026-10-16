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
from dataclasses import dataclass, field
from statistics import mean, pstdev

from . import roster

DEFAULT_SWING, MIN_SWING, MAX_SWING, MIN_GAMES_FOR_SWING = 0.3, 0.12, 0.6, 15
# Chance he plays a game, by Sleeper injury status: next game / later games this week.
# ponytail: flat guesses; tune from what actually happens once the season runs.
PLAY_CHANCE = {"healthy": (0.97, 0.97), "day_to_day": (0.6, 0.9), "out_short_term": (0.0, 0.3),
               "out_long_term": (0.0, 0.0), "out_season": (0.0, 0.0)}


@dataclass
class Game:
    date: str
    proj: float | None          # Sleeper projection in league FP; None = no projection
    fp: float | None = None     # actual FP once played
    started: bool = False       # tipped off (in progress or final)


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


def wait_value(remaining: list[Game], swing: float, injury: str) -> float:
    """Value of his remaining games played with the optimal lock rule (see module doc)."""
    nxt, later = PLAY_CHANCE.get(injury, PLAY_CHANCE["healthy"])
    v = 0.0
    for i in range(len(remaining) - 1, -1, -1):
        mu = max(0.0, remaining[i].proj or 0.0)
        p = nxt if i == 0 else later
        v = p * (mu if i == len(remaining) - 1 else expected_max(mu, mu * swing, v)) + (1 - p) * v
    return v


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

    seats: dict[str, list[PlanPlayer]] = {s: [] for s in slot_counts}
    for p in players:   # locked players keep their slots
        p.seat = None
        if p.locked is not None and p.slot in seats:
            p.seat = p.slot
            seats[p.slot].append(p)

    def place(p: PlanPlayer, seen: set[str]) -> bool:
        for slot in roster.candidate_slots(p.eligibility):
            if slot not in seats or slot in seen:
                continue
            seen.add(slot)
            if len(seats[slot]) < slot_counts[slot]:
                seats[slot].append(p); p.seat = slot
                return True
            for q in list(seats[slot]):
                if q.locked is None and place_from(q, slot, seen):
                    seats[slot].append(p); p.seat = slot
                    return True
        return False

    def place_from(q: PlanPlayer, old: str, seen: set[str]) -> bool:
        seats[old].remove(q)
        if place(q, seen):
            return True
        seats[old].append(q); q.seat = old
        return False

    for p in sorted((p for p in players if p.locked is None and p.slot != "IR"), key=lambda p: -p.value):
        if p.value > 0:
            place(p, set())

    for p in players:
        if p.locked is not None:
            p.action, p.why = "LOCKED", f"locked {p.locked:.1f}"
        elif p.seat is None:
            p.action = "DONE" if p.value <= 0 else "BENCH"
            p.why = "no games left" if p.value <= 0 else "his games aren't worth a slot this week"
        elif p.x is not None and p.x >= p.w:
            p.action = "LOCK"
            move = f" (move him {p.slot} → {p.seat} first)" if p.seat != p.slot else ""
            p.why = f"{p.x:.1f} beats waiting (~{p.w:.1f}): lock in the {p.seat} slot{move}"
        elif p.x is not None:
            p.action, p.why = "PASS", f"his remaining games are worth ~{p.w:.1f}, more than {p.x:.1f}"
        else:
            p.action, p.why = "WAIT", f"{p.seat} slot: his games are worth ~{p.w:.1f}"
    expected = sum(p.value for s in seats.values() for p in s)
    return WeekPlan(players=players, expected=round(expected, 1), slots=dict(slot_counts))
