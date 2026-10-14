"""Fit for my team: one 0-100 score per available player, shown in the rankings' Fit column and explained in
the player profile.

    fit = 100 × value ÷ best value left (rosterable)
          × role:  1 if he fills an open starting spot, 0.6 bench only, 0 no spot
          × price: the call on him (live only): BUY 1, STAR ONLY 0.85, TOO PRICEY 0.4, CAN'T 0

The profile also lists 'worth knowing' notes (injury, missed weeks, age, schedule, projection trend, tier,
alternatives). They are context only and never change the score, so the card and the column always agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from .ranking import tiers

BENCH_FIT = 0.6          # a bench player rarely scores under Lock-In
PRICE_FIT = {"buy": 1.0, "star": 0.85, "pricey": 0.4, "cannot": 0.0}
CALL_LABEL = {"buy": "BUY", "star": "STAR ONLY", "pricey": "TOO PRICEY", "cannot": "CAN'T"}
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


def _score(r, best: float, call) -> tuple[int, str, str, str]:
    """(score, quality line, role line, price line); `call` is the spending guide's TargetAdvice, None before the draft."""
    pct = round(100 * r.value / best)
    quality = f"Quality: {pct}% of the best player left (value {r.value:.1f})."
    if r.assignable_slot is None:
        role_f, role = 0.0, "Role: no open spot on your roster he can fill (×0)."
    elif r.assignable_slot == "BN":
        role_f, role = BENCH_FIT, f"Role: bench only, your {'/'.join(r.eligibility) or 'matching'} starting spots are full (×{BENCH_FIT})."
    else:
        role_f, role = 1.0, f"Role: starts for you at {r.assignable_slot} (×1)."
    if call is None:
        price_f, price_line = 1.0, "Price: not counted until the draft is live."
    else:
        price_f = PRICE_FIT[call.verdict]
        detail = ("you can't bid on him" if call.verdict == "cannot" else
                  f"market price ${call.recommended}, comfort limit ${call.stretch}, walk-away ${call.walk_away}")
        price_line = f"Price: call {CALL_LABEL[call.verdict]} ({detail}) (×{price_f})."
    return round(pct * role_f * price_f), quality, role, price_line


def fit_scores(session, manager_id: str, rows, calls: dict) -> dict[int, dict]:
    """The Fit column: {player_id: {score, why}} for the listed rows."""
    best = _best_value(session, manager_id)
    out = {}
    for r in rows:
        score, *lines = _score(r, best, calls.get(r.player_id))
        out[r.player_id] = {"score": score, "why": " ".join(lines)}
    return out


def team_fit(session, manager_id: str, player_id: int) -> TeamFit:
    """The profile card: the same score as the Fit column, its three parts, and context notes."""
    my_picks = session.engine.picks_for(manager_id)
    rows = session.rank(my_picks, session.available_ids())
    p = next((r for r in rows if r.player_id == player_id), None)
    if p is None:
        raise ValueError(f"player {player_id} is not available")
    call = session.spending_guide(manager_id, player_id).focus if session.draft.status == "live" else None
    score, quality, role, price_line = _score(p, _best_value(session, manager_id), call)
    verdict = verdict_for(score)

    # Headline: the score plus whatever pulled it down most (or why it is high).
    v = call.verdict if call else None
    drags = [t for t, bad in (("bench only", p.assignable_slot == "BN"), ("no open spot", p.assignable_slot is None),
                             ("you can't bid on him", v == "cannot" and p.assignable_slot is not None),
                             ("too pricey", v == "pricey"), ("star only at his price", v == "star")) if bad]
    why = ", ".join(drags) if drags else f"starts at {p.assignable_slot}" + (", call BUY" if v == "buy" else "")
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
        notes.append(f"Missed time: played in {round(p.availability * 100)}% of fantasy weeks over the last 3 seasons ({p.games_played} games last season).")
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
