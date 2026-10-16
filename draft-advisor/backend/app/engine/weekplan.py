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
    live: bool = False          # in progress right now
    tip: str | None = None      # tip-off, UTC ISO
    final: bool = False         # game over
    min: float | None = None    # minutes played so far
    proj_min: float | None = None   # Sleeper's projected minutes
    period: int = 0             # live game clock (ESPN): quarter and seconds left in it
    clock: float = 0.0


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
    # Earliest tip first: start the 6:00 player over the 6:45 one. If the early game goes badly you swap the later
    # player in before his tip (see today_watch); starting the later one first gives that chance away.
    tier2 = sorted((p for p in free if p not in tier1 and _today(p, today) and not _today(p, today).started),
                   key=lambda p: (_today(p, today).tip or "~", -(_today(p, today).proj or 0)))
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


GAME_SECONDS, QUARTER_SECONDS, PRIOR_MINUTES = 48 * 60, 12 * 60, 10.0
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
    elapsed = min(GAME_SECONDS, (max(1, g.period) - 1) * QUARTER_SECONDS + (QUARTER_SECONDS - g.clock)) if g.period else 0
    left = max(0.0, (g.proj_min or played) * (1 - elapsed / GAME_SECONDS))
    if g.period > 4:   # overtime: whatever he plays now is a bonus
        left = 0.0
    return g.fp + rate * left


def swap_call(s: PlanPlayer, b: PlanPlayer, today: str) -> dict:
    """Keep S (his game tonight is the slot's chance; pass on it if his later games are worth more) or swap B in
    (S's game tonight is forfeited, the slot gets B's game, S still has his later games)."""
    gs, gb = _today(s, today), _today(b, today)
    later = [g for g in s.games if g.date > today and not g.started]
    bar = wait_value(later, s.swing, s.injury)                 # what S's later games are worth
    nxt = PLAY_CHANCE.get(b.injury, PLAY_CHANCE["healthy"])[0]
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
    for s in starters:
        gs, slot = _today(s, today), seat[id(s)]
        fits = [b for b in bench if slot in roster.candidate_slots(b.eligibility)]
        if s.injury == "day_to_day" and fits and not gs.started:
            backup = max(fits, key=lambda b: _today(b, today).proj or 0)
            lines.append({"kind": "gtd", "sid": s.sid, "name": s.name, "slot": slot, "by": gs.tip,
                          "alarm": _minus_minutes(gs.tip, 30), "backup": backup.name, "backup_tip": _today(backup, today).tip,
                          "text": f"{s.name} is questionable: check before his tip. If he's out, start {backup.name} at {slot}."})
        for b in fits:   # every later bench player who could take this slot is a candidate swap
            if (_today(b, today).tip or "") <= (gs.tip or ""):
                continue
            call = swap_call(s, b, today)
            if call["swap"] - call["bar"] >= MIN_SWAP_GAIN:   # his game must beat just waiting on S's later games
                candidates.setdefault(b.sid, (b, []))[1].append((s, slot, call))

    # One alarm per later player: at his tip - ALARM_LEAD_MIN, swap him in for the starter furthest below his keep
    # line (most to gain), or keep everyone. PENDING until at least one of those starters' games has begun.
    for b, opts in candidates.values():
        tip = _today(b, today).tip
        live = [o for o in opts if o[2]["decision"] != "PENDING"]
        best = max(live, key=lambda o: o[2]["swap"] - o[2]["keep"], default=None)
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
