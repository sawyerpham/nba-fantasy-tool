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
    live: bool = False          # in progress right now (the player can't be moved)
    tip: str | None = None      # tip-off, UTC ISO


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


def seat_players(order: list[PlanPlayer], slot_counts: dict[str, int], pinned=()) -> dict[str, list[PlanPlayer]]:
    """Pinned players keep their current slot; then each player in `order` takes a slot he can play, sliding
    already-seated (unpinned) multi-position players elsewhere when that makes room. Sets .seat."""
    seats: dict[str, list[PlanPlayer]] = {s: [] for s in slot_counts}
    fixed = {id(p) for p in pinned}
    for p in pinned:
        p.seat = p.slot
        seats[p.slot].append(p)

    def place(p: PlanPlayer, seen: set[str]) -> bool:
        for slot in roster.candidate_slots(p.eligibility):
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


# ---- today's lineup ------------------------------------------------------------------------------------------
# Every unlocked slot is a free chance at a pop-off on any day: start everyone who plays today, as long as that
# doesn't cost a game worth keeping. Seating order:
#   pinned  - locked players, and anyone whose game is in progress (he can't be moved), in their current slot;
#   1       - players whose call is LOCK (they must stay in the lineup to lock);
#   2       - players who play later today, best projection for today's game first;
#   3       - everyone else, by week value (an empty slot and a non-playing starter score the same today).
# Benching a player with a played, unlocked game forfeits that game; only LOCK players have one worth keeping,
# and they come first. The moves are the differences from the current Sleeper lineup.

@dataclass
class TodayLineup:
    seats: dict[str, list[str]]          # slot -> player ids
    moves: list[dict]                    # {sid, name, from, to, by}: `by` = tip-off the move must beat (UTC ISO)
    watch: list[dict]                    # swap-watch and GTD lines (see today_watch)


def _today(p: PlanPlayer, today: str) -> Game | None:
    return next((g for g in p.games if g.date == today), None)


def plan_today(players: list[PlanPlayer], slot_counts: dict[str, int], today: str) -> TodayLineup:
    live_today = {id(p) for p in players if _today(p, today) and _today(p, today).live}
    pinned = [p for p in players if p.slot in slot_counts and (p.locked is not None or id(p) in live_today)]
    free = [p for p in players if p not in pinned and id(p) not in live_today and p.slot != "IR" and p.locked is None]
    tier1 = [p for p in free if p.action == "LOCK"]
    tier2 = sorted((p for p in free if p not in tier1 and _today(p, today) and not _today(p, today).started),
                   key=lambda p: -(_today(p, today).proj or 0))
    tier3 = sorted((p for p in free if p not in tier1 and p not in tier2 and p.value > 0), key=lambda p: -p.value)
    plan_seat = {id(p): p.seat for p in players}
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


def today_watch(players: list[PlanPlayer], today: str, seat: dict[int, str | None]) -> list[dict]:
    """Starters who play today before a bench player who could take their slot: if the starter's game comes in
    under the bar (what his later games are worth), bench him and start the later player before that tip-off.
    Also questionable (GTD) starters with a backup who plays today."""
    lines = []
    starters = [p for p in players if seat.get(id(p)) and p.locked is None and _today(p, today) and not _today(p, today).started]
    bench = [p for p in players if not seat.get(id(p)) and p.slot != "IR" and p.locked is None
             and _today(p, today) and not _today(p, today).started]
    for s in starters:
        gs, slot = _today(s, today), seat[id(s)]
        fits = [b for b in bench if slot in roster.candidate_slots(b.eligibility)]
        if s.injury == "day_to_day" and fits:
            backup = max(fits, key=lambda b: _today(b, today).proj or 0)
            lines.append({"kind": "gtd", "sid": s.sid, "name": s.name, "slot": slot, "by": gs.tip,
                          "backup": backup.name, "backup_tip": _today(backup, today).tip,
                          "text": f"{s.name} is questionable: check before his tip. If he's out, start {backup.name} at {slot}."})
        later = [b for b in fits if (_today(b, today).tip or "") > (gs.tip or "")]
        if later:
            b = max(later, key=lambda b: _today(b, today).proj or 0)
            after = [g for g in s.games if g.date > today and not g.started]
            bar = wait_value(after, s.swing, s.injury)
            text = (f"If {s.name} scores under {bar:.1f}, bench him and start {b.name} at {slot} before {b.name}'s tip."
                    if after else f"Today is {s.name}'s last game: lock him if he scores well, or start {b.name} at {slot} (plays later).")
            lines.append({"kind": "swap", "sid": s.sid, "name": s.name, "slot": slot, "bar": round(bar, 1),
                          "backup": b.name, "by": _today(b, today).tip, "text": text})
    return lines
