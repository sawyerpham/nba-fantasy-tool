"""Auction budget arithmetic with the mandatory-slot reservation (DESIGN.md decision 10).

Every manager must be able to fill all mandatory (non-IR) roster slots by draft's end, so at any
moment the most they may bid is what is left after reserving `min_bid` for every OTHER open
mandatory slot. IR slots never count toward the reservation and are never drafted into.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, Manager


@dataclass(frozen=True)
class ManagerBudget:
    manager_id: str
    budget_total: int
    spent: int
    remaining: int
    filled_mandatory: int
    open_mandatory: int
    reserved: int          # dollars that must stay untouched for the other open mandatory slots
    max_bid: int           # remaining - reserved, floored at 0; 0 when no mandatory slot is open
    discretionary: int     # remaining - min_bid * open_mandatory: money above the bare minimum


def max_bid(remaining: int, open_mandatory: int, min_bid: int) -> int:
    """Largest legal bid: after paying it, the manager can still put `min_bid` on every other open slot."""
    if open_mandatory <= 0:
        return 0
    return max(0, remaining - min_bid * (open_mandatory - 1))


def reserved_for_others(open_mandatory: int, min_bid: int) -> int:
    return max(0, min_bid * (open_mandatory - 1))


def discretionary_dollars(remaining: int, open_mandatory: int, min_bid: int) -> int:
    return max(0, remaining - min_bid * max(0, open_mandatory))


def manager_budget(league: LeagueSettings, manager: Manager, picks: Iterable[Pick]) -> ManagerBudget:
    own = [p for p in picks if p.manager_id == manager.manager_id]
    spent = sum(p.price for p in own)
    remaining = manager.budget_total - spent
    filled = sum(1 for p in own if p.slot != "IR")
    open_mandatory = max(0, league.mandatory_slot_count() - filled)
    return ManagerBudget(
        manager_id=manager.manager_id,
        budget_total=manager.budget_total,
        spent=spent,
        remaining=remaining,
        filled_mandatory=filled,
        open_mandatory=open_mandatory,
        reserved=reserved_for_others(open_mandatory, league.min_bid),
        max_bid=max_bid(remaining, open_mandatory, league.min_bid),
        discretionary=discretionary_dollars(remaining, open_mandatory, league.min_bid),
    )


def validate_bid(price: int, budget: ManagerBudget, min_bid: int) -> str | None:
    """Returns an error message, or None when the bid is legal."""
    if budget.open_mandatory <= 0:
        return f"{budget.manager_id} has no open roster slot to draft into"
    if price < min_bid:
        return f"bid ${price} is below the minimum bid ${min_bid}"
    if price > budget.max_bid:
        return (
            f"bid ${price} exceeds max bid ${budget.max_bid}: ${budget.remaining} remaining minus "
            f"${budget.reserved} reserved for {budget.open_mandatory - 1} other mandatory slot(s)"
        )
    return None
