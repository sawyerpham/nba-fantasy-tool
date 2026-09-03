"""Keeper pricing and keep/don't-keep verdicts (proposal P18, approved 2026-09-03).

keeper price = league escalation rule applied to last year's price (e.g. $17 -> $20)
surplus      = fair value at draft start - keeper price
verdict      = good when the surplus is at least max($2, 10 % of fair value),
               bad when the deficit is at least that much, even otherwise
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .draft_state import DraftError
from .ranking import rank_players

GOOD_MIN_DOLLARS = 2
GOOD_MIN_FRACTION = 0.10


@dataclass
class KeeperCandidate:
    manager_id: str
    player_id: int
    last_price: int
    keeper_price: int | None = None  # explicit override of the computed price


@dataclass
class KeeperEvaluation:
    manager_id: str
    player_id: int
    full_name: str
    team_abbr: str | None
    last_price: int
    keeper_price: int
    computed_price: int
    fair_value: float
    recommended_max: int
    surplus: float
    verdict: str            # good | even | bad
    rank: int | None
    value: float
    max_bid: int
    affordable: bool
    note: str


def verdict_for(surplus: float, fair_value: float) -> str:
    threshold = max(GOOD_MIN_DOLLARS, GOOD_MIN_FRACTION * fair_value)
    if surplus >= threshold:
        return "good"
    if surplus <= -threshold:
        return "bad"
    return "even"


def evaluate_keepers(session, candidates: Iterable[KeeperCandidate]) -> list[KeeperEvaluation]:
    rule = session.league.keeper.escalation
    out: list[KeeperEvaluation] = []
    for c in candidates:
        record = session.players.get(c.player_id)
        if record is None:
            raise DraftError(f"unknown player {c.player_id}")
        computed = rule.price(c.last_price)
        price = c.keeper_price if c.keeper_price is not None else computed
        rec = session.recommend(c.player_id, c.manager_id)
        rows = rank_players(session.league, session.players, session.overrides, session.valuations,
                            session.engine.picks_for(c.manager_id), session.available_ids())
        row = next((r for r in rows if r.player_id == c.player_id), None)
        surplus = round(rec.fair_value - price, 2)
        verdict = verdict_for(surplus, rec.fair_value)
        affordable = price <= rec.my_max_bid
        if not affordable:
            note = f"${price} exceeds this manager's max bid ${rec.my_max_bid} (reservation rule)"
        elif verdict == "good":
            note = f"keep: ${price} is ${surplus:.0f} under the ${rec.fair_value:.0f} fair value"
        elif verdict == "bad":
            note = f"let go: ${price} is ${-surplus:.0f} over the ${rec.fair_value:.0f} fair value; you could buy similar value cheaper"
        else:
            note = f"even: ${price} is about the ${rec.fair_value:.0f} fair value"
        out.append(KeeperEvaluation(
            manager_id=c.manager_id, player_id=c.player_id, full_name=record.full_name, team_abbr=record.team_abbr,
            last_price=c.last_price, keeper_price=price, computed_price=computed, fair_value=rec.fair_value,
            recommended_max=rec.recommended_max, surplus=surplus, verdict=verdict,
            rank=row.rank if row else None, value=row.value if row else 0.0, max_bid=rec.my_max_bid,
            affordable=affordable, note=note,
        ))
    return out
