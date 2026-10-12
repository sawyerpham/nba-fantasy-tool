"""'Is he good for my team?': a short, rule-based read on one available player for one manager.

Every line comes from numbers the app already has (open slots, the alternatives at the same slot, tiers,
the bid guide's price call, injury / missed weeks / age, the Lock-In schedule, the projection trend), so the
message is instant and never invents a fact. Each rule adds or subtracts points; the total picks the verdict.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import roster
from .ranking import tiers

INJURY_LABEL = {"day_to_day": "Day-to-day", "out_short_term": "Out short term", "out_long_term": "Out long term", "out_season": "Out for the season"}
VERDICTS = ((3.0, "great"), (1.5, "good"), (0.0, "okay"))   # below 0: poor
LABEL = {"great": "Great fit", "good": "Good fit", "okay": "Okay fit", "poor": "Poor fit"}


@dataclass
class TeamFit:
    player_id: int
    verdict: str                     # great | good | okay | poor
    headline: str
    reasons: list[str] = field(default_factory=list)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def team_fit(session, manager_id: str, player_id: int) -> TeamFit:
    my_picks = session.engine.picks_for(manager_id)
    rows = session.rank(my_picks, session.available_ids())
    p = next((r for r in rows if r.player_id == player_id), None)
    if p is None:
        raise ValueError(f"player {player_id} is not available")
    if p.assignable_slot is None:
        return TeamFit(player_id, "poor", f"{LABEL['poor']}: no open spot he can fill", ["Every slot he is eligible for is full on your roster."])

    notes: list[tuple[float, str, str]] = []   # (points, short tag for the headline, full reason)
    add = lambda pts, tag, why: notes.append((pts, tag, why))

    # 1. Where he'd play for me.
    slot = p.assignable_slot
    open_ = roster.open_slots(session.league, my_picks)
    if slot == "BN":
        add(-2, "bench only", f"Bench only: your {'/'.join(p.eligibility) or 'matching'} starting spots are full, and a bench player rarely scores under Lock-In.")
    else:
        last = " last" if open_.get(slot, 0) == 1 else ""
        add(1, f"fills your{last} open {slot} spot", f"Fills your{last} open {slot} starting spot.")
        if p.scarcity >= 0.15:
            add(0.5, "scarce position", f"Scarce position: the best {slot} left once every team has its starters is weaker than at other spots.")

    # 2. How he compares with what's left for that slot, and whether his tier is running out.
    if slot != "BN":
        same = [r for r in rows if r.assignable_slot == slot]
        k = next(i for i, r in enumerate(same, 1) if r.player_id == player_id)
        if k == 1:
            add(1, f"best {slot} left", f"Best {slot} option left for you.")
        elif k <= 3:
            add(0.5, f"{_ordinal(k)}-best {slot} left", f"{_ordinal(k).capitalize()}-best {slot} option left (behind {', '.join(r.full_name for r in same[:k - 1])}).")
    tier = tiers(session.pool_values())
    t = tier.get(player_id)
    left = Counter(tier.get(r.player_id) for r in rows)[t]
    size = Counter(tier.values())[t]
    if t is not None and size >= 3 and left <= 2:
        add(0.5, f"last of tier T{t}", f"{'Last player' if left == 1 else 'One of the last 2'} in tier T{t}: after that the next tier is a step down.")

    # 3. Price for me (bid guide), only once the draft is live.
    if session.draft.status == "live":
        f = session.spending_guide(manager_id, player_id).focus
        if f is not None:
            if f.verdict in ("go", "fits", "fair-only"):
                add(1, f"price works up to ${f.suggested}", f"Price works: go up to ${f.suggested} (market ~${f.recommended}).")
            elif f.verdict == "stretch":
                add(0, "a stretch on price", f"Stretch: the market ~${f.recommended} thins out your other starters (walk away at ${f.walk_away}).")
            elif f.verdict == "pass":
                add(-2, "too pricey for you", f"Too pricey for you: market ~${f.recommended}, your walk-away is ${f.walk_away}.")
            elif f.verdict == "cannot":
                add(-3, "you can't afford him", f"You can't afford him: your max bid is ${f.all_in}.")

    # 4. Risk.
    if p.injury_status != "healthy":
        add(-1, INJURY_LABEL.get(p.injury_status, p.injury_status).lower(), f"{INJURY_LABEL.get(p.injury_status, p.injury_status)}{f': {p.injury_note}' if p.injury_note else ''}.")
    if p.games_played and p.availability < 0.75:
        add(-1, "missed time last year", f"Missed time: played in {round(p.availability * 100)}% of fantasy weeks last season ({p.games_played} games).")
    if p.age and p.age >= 33:
        add(-0.5, f"age {int(p.age)}", f"Age {int(p.age)}: more rest days and decline risk.")

    # 5. Lock-In schedule (playoff weeks shown when the league has them).
    from ..services.sleeper_league import fantasy_weeks

    _, playoffs = fantasy_weeks(session.sleeper_details, session.schedule_games)
    games = session.schedule_games.get(p.team_abbr or "", {})
    po = "/".join(str(games.get(str(w), 0)) for w in playoffs) if playoffs and games else ""
    po_text = f" ({po} games in playoff weeks {playoffs[0]}-{playoffs[-1]})" if po else ""
    if p.schedule_factor >= 1.03:
        add(0.5, "good schedule", f"Good Lock-In schedule{po_text}.")
    elif p.schedule_factor <= 0.97:
        add(-0.5, "weak schedule", f"Weak Lock-In schedule{po_text}.")

    # 6. Role trend: Sleeper's projection vs last season.
    if p.proj_fpts is not None and p.last_fpts:
        diff = p.proj_fpts - p.last_fpts
        if diff >= 1:
            add(0.5, "growing role", f"Projected {diff:+.1f} FP/G over last season (bigger role).")
        elif diff <= -1:
            add(-0.5, "shrinking role", f"Projected {diff:+.1f} FP/G under last season (smaller role).")

    # 7. Same NBA team as players I already have (context only: Lock-In picks one game per slot anyway).
    mates = [session.players[pk.player_id].full_name for pk in my_picks
             if pk.player_id in session.players and session.players[pk.player_id].team_abbr == p.team_abbr and p.team_abbr]
    if mates:
        add(0, "", f"Same NBA team as your {', '.join(mates)}.")

    score = sum(n[0] for n in notes)
    verdict = next((v for cut, v in VERDICTS if score >= cut), "poor")
    # The headline leads with the points that moved the verdict most; on a tie, the warning first.
    tags = [tag for pts, tag, _ in sorted(notes, key=lambda n: (-abs(n[0]), n[0])) if tag][:2]
    return TeamFit(player_id, verdict, f"{LABEL[verdict]}: {', '.join(tags)}" if tags else LABEL[verdict],
                   [why for _, _, why in notes])


# Fit column: quality × where he'd play for me × whether the price works for me.
BENCH_FIT = 0.6          # a bench player rarely scores under Lock-In
PRICE_FIT = {"ok": 1.0, "stretch": 0.85, "past walk-away": 0.4, "can't afford": 0.0}


def fit_scores(session, manager_id: str, rows, prices: dict[int, int]) -> dict[int, dict]:
    """0-100 per listed player: 100 × value ÷ best value left, × slot factor, × price factor (live draft only).

    ponytail: price bands use one stretch / walk-away pair (from a starter target) for every player; per-slot
    bands if bench prices ever matter.
    """
    best = max((r.value for r in rows), default=0.0) or 1.0
    bands = None
    if session.draft.status == "live" and prices:
        starter = next((r for r in rows if r.assignable_slot not in (None, "BN")), None)
        focus = session.spending_guide(manager_id, starter.player_id).focus if starter else None
        if focus is not None:
            bands = (focus.stretch, focus.walk_away, session.engine.budget(manager_id).max_bid)
    out = {}
    for r in rows:
        slot = 0.0 if r.assignable_slot is None else BENCH_FIT if r.assignable_slot == "BN" else 1.0
        why = [f"value {r.value:.1f} = {round(100 * r.value / best)}% of the best left",
               "no open spot" if slot == 0 else "bench only ×0.6" if slot < 1 else f"starts at {r.assignable_slot}"]
        price_band = "ok"
        if bands and r.player_id in prices:
            stretch, walk, cap = bands
            p = prices[r.player_id]
            price_band = "can't afford" if p > cap else "past walk-away" if p > walk else "stretch" if p > stretch else "ok"
            why.append(f"${p} {'fits your budget' if price_band == 'ok' else price_band} (stretch ${stretch}, walk-away ${walk})")
        score = round(100 * r.value / best * slot * PRICE_FIT[price_band])
        out[r.player_id] = {"score": score, "why": " · ".join(why)}
    return out
