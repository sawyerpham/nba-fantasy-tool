"""Auction bid recommendation (DESIGN.md section 3).

rosterable_n   = managers × mandatory slots
replacement    = value of the rosterable_n-th best player in the whole pool (drafted + available)
VAR(p)         = max(0, value(p) - replacement)
free_dollars   = Σ_m (budget_remaining_m - min_bid × open_mandatory_m)      # discretionary money
VAR_pool       = Σ VAR over the top (Σ_m open_mandatory_m) available players
fair_value(p)  = min_bid + VAR(p) × free_dollars / VAR_pool
my_max_bid     = budget_remaining_me - min_bid × (open_mandatory_me - 1)     # reservation rule
recommended    = clamp(fair_value × (1 + 0.15 × pressure / other_managers), min_bid, my_max_bid)

Fair value is additionally capped at the largest legal bid any manager can make right now.
Competition pressure sums the weights of other managers who can afford fair value and have a slot the
player fits, weighted by their behaviour modifiers relative to draft progress.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, Manager, ManagerBehavior

from . import roster
from .budget import ManagerBudget, manager_budget
from .ranking import RankedPlayer

EARLY_PHASE_END = 0.4
# Recommended max = fair × (1 + PRESSURE_SCALE × pressure / other managers): +15 % when every other
# manager can afford the player at even pace, scaled by their behaviour weights, ~0 when nobody can.
PRESSURE_SCALE = 0.15


@dataclass
class Competitor:
    manager_id: str
    name: str
    max_bid: int
    weight: float


@dataclass
class BidRecommendation:
    player_id: int
    can_bid: bool
    fair_value: float
    recommended_max: int
    my_max_bid: int
    my_budget_remaining: int
    my_open_mandatory: int
    replacement_value: float
    var: float
    free_dollars: int
    var_pool: float
    dollars_per_var: float
    competition_pressure: float
    competitors: list[Competitor] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)


def competitor_weight(behavior: ManagerBehavior, progress: float) -> float:
    early = progress < EARLY_PHASE_END
    if behavior.spend_pace == "early":
        base = 1.3 if early else 0.8
    elif behavior.spend_pace == "late":
        base = 0.8 if early else 1.3
    else:
        base = 1.0
    return base * behavior.aggression


def replacement_value(pool_values: Iterable[float], rosterable_n: int) -> float:
    ordered = sorted(pool_values, reverse=True)
    if not ordered or rosterable_n <= 0:
        return 0.0
    if rosterable_n > len(ordered):
        return 0.0
    return ordered[rosterable_n - 1]


def recommend_bid(
    league: LeagueSettings,
    managers: list[Manager],
    picks: list[Pick],
    my_manager_id: str,
    target: RankedPlayer,
    available: list[RankedPlayer],
    pool_values: Mapping[int, float],
    progress: float,
) -> BidRecommendation:
    min_bid = league.min_bid
    budgets: dict[str, ManagerBudget] = {m.manager_id: manager_budget(league, m, picks) for m in managers}
    me = budgets[my_manager_id]

    rosterable_n = league.mandatory_slot_count() * len(managers)
    replacement = replacement_value(pool_values.values(), rosterable_n)
    var = max(0.0, target.value - replacement)

    free_dollars = sum(b.discretionary for b in budgets.values())
    open_total = sum(b.open_mandatory for b in budgets.values())
    top_available = sorted((p.value for p in available), reverse=True)[: max(0, open_total)]
    var_pool = sum(max(0.0, v - replacement) for v in top_available)
    dollars_per_var = free_dollars / var_pool if var_pool > 0 else 0.0
    uncapped_fair_value = min_bid + var * dollars_per_var
    # Nobody can pay more than the largest legal bid in the room (reservation rule applied to everyone).
    market_cap = max((b.max_bid for b in budgets.values()), default=min_bid)
    fair_value = min(uncapped_fair_value, float(max(market_cap, min_bid)))

    rationale: list[str] = []
    rationale.append(
        f"Replacement level is {replacement:.2f} value (the {rosterable_n}th best player league-wide); "
        f"{target.full_name} is {var:.2f} above it."
    )
    rationale.append(
        f"League has ${free_dollars} discretionary dollars for {open_total} open mandatory slots "
        f"(${dollars_per_var:.2f} per point of value above replacement)."
    )
    rationale.append(f"Fair value: ${min_bid} + {var:.2f} × ${dollars_per_var:.2f} = ${uncapped_fair_value:.2f}.")
    if fair_value < uncapped_fair_value:
        rationale.append(f"Capped at ${fair_value:.0f}: the most any manager can legally bid right now.")

    competitors: list[Competitor] = []
    for m in managers:
        if m.manager_id == my_manager_id:
            continue
        b = budgets[m.manager_id]
        if b.open_mandatory <= 0 or b.max_bid < max(min_bid, round(fair_value)):
            continue
        if not roster.is_rosterable(league, [p for p in picks if p.manager_id == m.manager_id], target.eligibility):
            continue
        competitors.append(Competitor(m.manager_id, m.name, b.max_bid, round(competitor_weight(m.behavior, progress), 2)))
    pressure = round(sum(c.weight for c in competitors), 2)
    if competitors:
        rationale.append(
            f"{len(competitors)} other manager(s) can afford fair value and have a fitting slot "
            f"(pressure {pressure:.2f}): " + ", ".join(f"{c.name} ≤${c.max_bid}×{c.weight}" for c in competitors) + "."
        )
    else:
        rationale.append("No other manager can both afford fair value and fit this player; bid near the minimum.")

    if not target.rosterable:
        rationale.append("You have no open slot this player fits.")
        return BidRecommendation(
            player_id=target.player_id, can_bid=False, fair_value=round(fair_value, 2), recommended_max=0,
            my_max_bid=me.max_bid, my_budget_remaining=me.remaining, my_open_mandatory=me.open_mandatory,
            replacement_value=round(replacement, 2), var=round(var, 2), free_dollars=free_dollars,
            var_pool=round(var_pool, 2), dollars_per_var=round(dollars_per_var, 2), competition_pressure=pressure,
            competitors=competitors, rationale=rationale,
        )
    if me.max_bid < min_bid:
        rationale.append(f"Your max bid is ${me.max_bid}: ${me.remaining} remaining with {me.open_mandatory} mandatory slots to fill.")
        return BidRecommendation(
            player_id=target.player_id, can_bid=False, fair_value=round(fair_value, 2), recommended_max=0,
            my_max_bid=me.max_bid, my_budget_remaining=me.remaining, my_open_mandatory=me.open_mandatory,
            replacement_value=round(replacement, 2), var=round(var, 2), free_dollars=free_dollars,
            var_pool=round(var_pool, 2), dollars_per_var=round(dollars_per_var, 2), competition_pressure=pressure,
            competitors=competitors, rationale=rationale,
        )

    others = max(1, len(managers) - 1)
    pressure_fraction = pressure / others
    adjusted = fair_value * (1 + PRESSURE_SCALE * pressure_fraction)
    recommended = int(round(adjusted))
    recommended = max(min_bid, min(recommended, me.max_bid))
    rationale.append(
        f"Recommended max ${recommended} = ${fair_value:.2f} × (1 + {PRESSURE_SCALE:.2f} × {pressure:.2f}/{others}) "
        f"capped at your max bid ${me.max_bid} (${me.remaining} remaining − ${me.reserved} reserved for "
        f"{max(0, me.open_mandatory - 1)} other mandatory slot(s))."
    )
    return BidRecommendation(
        player_id=target.player_id, can_bid=True, fair_value=round(fair_value, 2), recommended_max=recommended,
        my_max_bid=me.max_bid, my_budget_remaining=me.remaining, my_open_mandatory=me.open_mandatory,
        replacement_value=round(replacement, 2), var=round(var, 2), free_dollars=free_dollars,
        var_pool=round(var_pool, 2), dollars_per_var=round(dollars_per_var, 2), competition_pressure=pressure,
        competitors=competitors, rationale=rationale,
    )
