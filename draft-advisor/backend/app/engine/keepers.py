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
        rows = session.rank(session.engine.picks_for(c.manager_id), session.available_ids())
        row = next((r for r in rows if r.player_id == c.player_id), None)
        surplus = round(rec.fair_value - price, 2)
        verdict = verdict_for(surplus, rec.fair_value)
        affordable = price <= rec.my_max_bid
        if not affordable:
            note = f"${price} exceeds this manager's cap ${rec.my_max_bid} (reservation rule)"
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


# ---- keeper outlook for a player you could buy now (profile "Keeper next year")
# next price = the escalation rule applied to his market price now (what you'd likely pay)
# next worth = fair value of his healthy value a year older, at this year's draft-start $ per point (after keepers):
#              current injury removed, the age penalty for next year's age (31+ loses 3 %/year)
# call       = verdict_for(next worth - next price): the same GOOD / EVEN / BAD keep as the keeper menu
# good_up_to = the highest price now that still makes him a GOOD keep next year (None if no price does)
# stash      = he is out now (hurts this season) but a GOOD keep next year
# ponytail: next year's projection is this year's; young players who improve are flagged, not modelled.
OUT_NOW = ("out_short_term", "out_long_term", "out_season")


def keeper_outlook(session, row, buy_price: int) -> dict:
    from .bidding import market_rate, replacement_value
    from .ranking import age_multiplier, player_value

    lg = session.league
    rec = session.players[row.player_id]
    override = session.overrides.get(row.player_id)
    healthy = override.model_copy(update={"injury_status": "healthy"}) if override else None
    value = player_value(rec, healthy, session.valuations.get(row.player_id), lg.ranking, lg.scoring,
                         session.schedule().get(rec.team_abbr or "", 1.0))[0]
    if rec.bio.age:
        value *= age_multiplier(rec.bio.age + 1, lg.ranking) / age_multiplier(rec.bio.age, lg.ranking)
    value += session._scarcity.get(row.player_id, 0.0)
    pool = session.pool_values()
    mandatory = lg.mandatory_slot_count()
    bench = sum(s.count for s in lg.roster_slots if s.slot == "BN")
    priced = mandatory - bench + min(bench, lg.ranking.priced_bench_slots)
    replacement = replacement_value(pool.values(), priced * len(session.managers))
    keepers = [p for p in session.draft.picks if p.is_keeper]
    kept = {p.player_id for p in keepers}
    rate = market_rate(lg, session.managers, keepers, (v for pid, v in pool.items() if pid not in kept), pool).dollars_per_var
    worth = round(lg.min_bid + max(0.0, value - replacement) * rate)
    rule = lg.keeper.escalation
    next_price = rule.price(buy_price)
    surplus = worth - next_price
    verdict = verdict_for(surplus, worth)
    good_up_to = max((b for b in range(lg.min_bid, worth + 1) if verdict_for(worth - rule.price(b), worth) == "good"), default=None)
    stash = verdict == "good" and (override.injury_status if override else "healthy") in OUT_NOW
    young = bool(rec.bio.age and rec.bio.age <= 23)
    return {"buy_price": buy_price, "next_price": next_price, "next_worth": worth, "surplus": surplus,
            "verdict": verdict, "good_up_to": good_up_to, "stash": stash, "young": young}
