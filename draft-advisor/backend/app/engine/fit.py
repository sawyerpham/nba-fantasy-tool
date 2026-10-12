"""Fit for my team: one 0-100 score per available player, shown in the rankings' Fit column and explained in
the player profile.

    fit = 100 × value ÷ best value left (rosterable)
          × role:  1 if he fills an open starting spot, 0.6 bench only, 0 no spot
          × price: 1 within my stretch price, 0.85 past it, 0.4 past my walk-away, 0 above my max bid (live only)

The profile also lists 'worth knowing' notes (injury, missed weeks, age, schedule, projection trend, tier,
alternatives). They are context only and never change the score, so the card and the column always agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .ranking import tiers

BENCH_FIT = 0.6          # a bench player rarely scores under Lock-In
PRICE_FIT = {"ok": 1.0, "stretch": 0.85, "past walk-away": 0.4, "can't afford": 0.0}
INJURY_LABEL = {"day_to_day": "Day-to-day", "out_short_term": "Out short term", "out_long_term": "Out long term", "out_season": "Out for the season"}


def verdict_for(score: int) -> str:
    return "strong" if score >= 70 else "decent" if score >= 45 else "weak"


@dataclass
class TeamFit:
    player_id: int
    score: int
    verdict: str                                   # strong | decent | weak (same colours as the Fit column)
    headline: str
    score_lines: list[str] = field(default_factory=list)   # the three parts of the score
    notes: list[str] = field(default_factory=list)          # context, not in the score
    reasons: list[str] = field(default_factory=list)        # score_lines + notes (for Copy for Claude)


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _best_value(session, manager_id: str) -> float:
    rows = session.rank(session.engine.picks_for(manager_id), session.available_ids())
    return max((r.value for r in rows if r.rosterable), default=0.0) or 1.0


def _bands(session, manager_id: str, rows) -> tuple[int, int, int] | None:
    """(stretch, walk-away, max bid) for me right now; None before the draft.

    ponytail: one stretch / walk-away pair (from a starter target) for every player; per-slot bands if bench
    prices ever matter.
    """
    if session.draft.status != "live":
        return None
    starter = next((r for r in rows if r.assignable_slot not in (None, "BN")), None)
    focus = session.spending_guide(manager_id, starter.player_id).focus if starter else None
    return (focus.stretch, focus.walk_away, session.engine.budget(manager_id).max_bid) if focus else None


def _score(r, best: float, bands, price: int | None) -> tuple[int, str, str, str]:
    """(score, quality line, role line, price line)."""
    pct = round(100 * r.value / best)
    quality = f"Quality: {pct}% of the best player left (value {r.value:.1f})."
    if r.assignable_slot is None:
        role_f, role = 0.0, "Role: no open spot on your roster he can fill (×0)."
    elif r.assignable_slot == "BN":
        role_f, role = BENCH_FIT, f"Role: bench only, your {'/'.join(r.eligibility) or 'matching'} starting spots are full (×{BENCH_FIT})."
    else:
        role_f, role = 1.0, f"Role: starts for you at {r.assignable_slot} (×1)."
    band = "ok"
    if bands is None or price is None:
        price_line = "Price: not counted until the draft is live."
    else:
        stretch, walk, cap = bands
        band = "can't afford" if price > cap else "past walk-away" if price > walk else "stretch" if price > stretch else "ok"
        what = {"ok": "fits your budget", "stretch": "is past your stretch price", "past walk-away": "is past your walk-away",
                "can't afford": "is more than you can bid"}[band]
        price_line = f"Price: ${price} {what} (stretch ${stretch}, walk-away ${walk}) (×{PRICE_FIT[band]})."
    return round(pct * role_f * PRICE_FIT[band]), quality, role, price_line


def fit_scores(session, manager_id: str, rows, prices: dict[int, int]) -> dict[int, dict]:
    """The Fit column: {player_id: {score, why}} for the listed rows."""
    best = _best_value(session, manager_id)
    bands = _bands(session, manager_id, rows) if prices else None
    out = {}
    for r in rows:
        score, *lines = _score(r, best, bands, prices.get(r.player_id))
        out[r.player_id] = {"score": score, "why": " ".join(lines)}
    return out


def team_fit(session, manager_id: str, player_id: int) -> TeamFit:
    """The profile card: the same score as the Fit column, its three parts, and context notes."""
    my_picks = session.engine.picks_for(manager_id)
    rows = session.rank(my_picks, session.available_ids())
    p = next((r for r in rows if r.player_id == player_id), None)
    if p is None:
        raise ValueError(f"player {player_id} is not available")
    price = None
    if session.draft.status == "live":
        rec = session.recommend(player_id, manager_id)
        price = rec.recommended_max if rec.can_bid else round(rec.fair_value)
    score, quality, role, price_line = _score(p, _best_value(session, manager_id), _bands(session, manager_id, rows), price)
    verdict = verdict_for(score)

    # Headline: the score plus whatever pulled it down most (or why it is high).
    drags = [t for t, bad in (("bench only", p.assignable_slot == "BN"), ("no open spot", p.assignable_slot is None),
                             ("can't afford him", "more than you can bid" in price_line),
                             ("past your walk-away", "past your walk-away" in price_line),
                             ("past your stretch price", "past your stretch" in price_line)) if bad]
    why = ", ".join(drags) if drags else f"starts at {p.assignable_slot}" + (", price fits" if "fits your budget" in price_line else "")
    headline = f"Fit {score} · {verdict}: {why}"

    notes: list[str] = []
    if p.assignable_slot not in (None, "BN"):
        same = [r for r in rows if r.assignable_slot == p.assignable_slot]
        k = next(i for i, r in enumerate(same, 1) if r.player_id == player_id)
        if k == 1:
            notes.append(f"Best {p.assignable_slot} option left for you.")
        elif k <= 3:
            notes.append(f"{_ordinal(k).capitalize()}-best {p.assignable_slot} option left (behind {', '.join(r.full_name for r in same[:k - 1])}).")
    tier = tiers(session.pool_values())
    t = tier.get(player_id)
    left, size = Counter(tier.get(r.player_id) for r in rows)[t], Counter(tier.values())[t]
    if t is not None and size >= 3 and left <= 2:
        notes.append(f"{'Last player' if left == 1 else 'One of the last 2'} in tier T{t}: the next tier is a step down.")
    if p.injury_status != "healthy":
        notes.append(f"{INJURY_LABEL.get(p.injury_status, p.injury_status)}{f': {p.injury_note}' if p.injury_note else ''}.")
    if p.games_played and p.availability < 0.75:
        notes.append(f"Missed time: played in {round(p.availability * 100)}% of fantasy weeks last season ({p.games_played} games).")
    if p.age and p.age >= 33:
        notes.append(f"Age {int(p.age)}: more rest days and decline risk.")

    from ..services.sleeper_league import fantasy_weeks

    _, playoffs = fantasy_weeks(session.sleeper_details, session.schedule_games)
    games = session.schedule_games.get(p.team_abbr or "", {})
    po = "/".join(str(games.get(str(w), 0)) for w in playoffs) if playoffs and games else ""
    po_text = f" ({po} games in playoff weeks {playoffs[0]}-{playoffs[-1]})" if po else ""
    if p.schedule_factor >= 1.03:
        notes.append(f"Good Lock-In schedule{po_text}.")
    elif p.schedule_factor <= 0.97:
        notes.append(f"Weak Lock-In schedule{po_text}.")
    mates = [session.players[pk.player_id].full_name for pk in my_picks
             if pk.player_id in session.players and session.players[pk.player_id].team_abbr == p.team_abbr and p.team_abbr]
    if mates:
        notes.append(f"Same NBA team as your {', '.join(mates)}.")

    lines = [quality, role, price_line]
    return TeamFit(player_id, score, verdict, headline, lines, notes, lines + notes)
