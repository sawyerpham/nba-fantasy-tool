"""Live auction draft state machine: keepers, fixed-rotation (or snake) nomination, picks, undo.

Every pick is validated against the budget reservation rule (decision 10): a manager may never pay
more than `budget_remaining - min_bid * (open_mandatory_slots - 1)`, so all 15 mandatory slots stay
fillable. IR slots are never drafted into and never count toward the reservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Mapping

from nba_fantasy_shared.models.draft import CurrentNomination, DraftState, KeeperRecord, KeeperCost, Pick
from nba_fantasy_shared.models.league import LeagueSettings, Manager
from nba_fantasy_shared.models.players import PlayerOverrides, PlayerRecord
from nba_fantasy_shared.providers.base import utcnow

from . import roster
from .budget import ManagerBudget, manager_budget, validate_bid


class DraftError(ValueError):
    """A rule violation the UI should show; never a bug."""


@dataclass(frozen=True)
class KeeperAssignment:
    manager_id: str
    player_id: int
    cost: int


class DraftEngine:
    def __init__(
        self,
        league: LeagueSettings,
        managers: list[Manager],
        draft: DraftState,
        players: Mapping[int, PlayerRecord],
        overrides: Mapping[int, PlayerOverrides],
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.league = league
        self.managers = managers
        self.draft = draft
        self.players = players
        self.overrides = overrides
        self._now = now
        if len({m.manager_id for m in managers}) != len(managers):
            raise DraftError("manager ids must be unique")

    # ------------------------------------------------------------------ lookups

    def manager(self, manager_id: str) -> Manager:
        for m in self.managers:
            if m.manager_id == manager_id:
                return m
        raise DraftError(f"unknown manager {manager_id}")

    def user_manager(self) -> Manager | None:
        return next((m for m in self.managers if m.is_user), None)

    def picks_for(self, manager_id: str) -> list[Pick]:
        return [p for p in self.draft.picks if p.manager_id == manager_id]

    def drafted_ids(self) -> set[int]:
        return {p.player_id for p in self.draft.picks}

    def is_available(self, player_id: int) -> bool:
        return player_id in self.players and player_id not in self.drafted_ids()

    def eligibility(self, player_id: int) -> list[str]:
        override = self.overrides.get(player_id)
        return list(override.eligibility) if override else []

    def budget(self, manager_id: str) -> ManagerBudget:
        return manager_budget(self.league, self.manager(manager_id), self.draft.picks)

    def open_slots(self, manager_id: str) -> dict[str, int]:
        return roster.open_slots(self.league, self.picks_for(manager_id))

    def can_draft(self, manager_id: str) -> bool:
        b = self.budget(manager_id)
        return b.open_mandatory > 0 and b.max_bid >= self.league.min_bid

    def stack(self, manager_id: str) -> dict[str, int]:
        return dict(roster.team_stack(self.players, self.picks_for(manager_id)))

    def non_keeper_picks(self) -> list[Pick]:
        return [p for p in self.draft.picks if not p.is_keeper]

    def total_draftable_slots(self) -> int:
        return self.league.mandatory_slot_count() * len(self.managers)

    def progress(self) -> float:
        """Fraction of draftable (non-keeper) slots filled so far, 0..1."""
        keepers = sum(1 for p in self.draft.picks if p.is_keeper)
        remaining_total = self.total_draftable_slots() - keepers
        if remaining_total <= 0:
            return 1.0
        return min(1.0, len(self.non_keeper_picks()) / remaining_total)

    # ------------------------------------------------------------------ nomination order

    def set_nomination_order(self, order: list[str]) -> None:
        ids = {m.manager_id for m in self.managers}
        if sorted(order) != sorted(ids):
            raise DraftError("nomination order must list every manager exactly once")
        self.draft.nomination_order = list(order)

    def _nominator_at(self, index: int) -> str:
        order = self.draft.nomination_order
        n = len(order)
        rnd, pos = divmod(index, n)
        if self.league.nomination_order_type == "snake" and rnd % 2 == 1:
            pos = n - 1 - pos
        return order[pos]

    def next_nominator(self) -> str | None:
        """Manager who nominates next; skips managers who can no longer draft."""
        if self.draft.status != "live" or not self.draft.nomination_order:
            return None
        n = len(self.draft.nomination_order)
        for step in range(n):
            candidate = self._nominator_at(self.draft.nomination_pointer + step)
            if self.can_draft(candidate):
                if step:
                    self.draft.nomination_pointer += step
                return candidate
        return None

    # ------------------------------------------------------------------ commands

    def start(self, keepers: Iterable[KeeperAssignment] = ()) -> list[Pick]:
        if self.draft.status != "setup":
            raise DraftError(f"draft already {self.draft.status}")
        if not self.draft.nomination_order:
            self.draft.nomination_order = [m.manager_id for m in self.managers]
        else:
            self.set_nomination_order(self.draft.nomination_order)
        keepers = list(keepers)
        if keepers and not self.league.keeper.enabled:
            raise DraftError("league has keepers disabled")
        per_manager: dict[str, int] = {}
        for k in keepers:
            per_manager[k.manager_id] = per_manager.get(k.manager_id, 0) + 1
            if per_manager[k.manager_id] > self.league.keeper.max_per_manager:
                raise DraftError(
                    f"{k.manager_id} has more than {self.league.keeper.max_per_manager} keeper(s)"
                )
        self.draft.picks = []
        self.draft.nomination_pointer = 0
        self.draft.current_nomination = None
        self.draft.status = "live"
        try:
            for k in keepers:
                self._record_pick(k.player_id, k.manager_id, k.cost, slot=None, is_keeper=True, nominated_by=None)
        except DraftError:
            self.draft.picks = []
            self.draft.status = "setup"
            raise
        return list(self.draft.picks)

    def nominate(self, player_id: int, manager_id: str | None = None, force: bool = False) -> CurrentNomination:
        self._require_live()
        if not self.is_available(player_id):
            raise DraftError(f"player {player_id} is not available")
        expected = self.next_nominator()
        if expected is None:
            raise DraftError("no manager can draft any more players")
        nominator = manager_id or expected
        if nominator != expected and not force:
            raise DraftError(f"it is {expected}'s turn to nominate, not {nominator}'s")
        self.manager(nominator)
        self.draft.current_nomination = CurrentNomination(player_id=player_id, nominated_by=nominator, opened_at=self._now())
        return self.draft.current_nomination

    def pick(self, player_id: int, manager_id: str, price: int, slot: str | None = None) -> Pick:
        self._require_live()
        current = self.draft.current_nomination
        nominated_by = current.nominated_by if current and current.player_id == player_id else self.next_nominator()
        pick = self._record_pick(player_id, manager_id, price, slot, is_keeper=False, nominated_by=nominated_by)
        self.draft.current_nomination = None
        self.draft.nomination_pointer += 1
        return pick

    def undo(self) -> Pick:
        self._require_live()
        if not self.draft.picks:
            raise DraftError("nothing to undo")
        last = self.draft.picks[-1]
        if last.is_keeper:
            raise DraftError("keepers are set at draft start; reset the draft to change them")
        self.draft.picks.pop()
        self.draft.nomination_pointer = max(0, self.draft.nomination_pointer - 1)
        self.draft.current_nomination = None
        return last

    def reassign_slot(self, pick_number: int, slot: str) -> Pick:
        pick = next((p for p in self.draft.picks if p.pick_number == pick_number), None)
        if pick is None:
            raise DraftError(f"no pick #{pick_number}")
        others = [p for p in self.picks_for(pick.manager_id) if p.pick_number != pick_number]
        error = roster.validate_slot(self.league, others, self.eligibility(pick.player_id), slot)
        if error:
            raise DraftError(error)
        pick.slot = slot  # type: ignore[assignment]
        return pick

    def complete(self) -> None:
        self._require_live()
        self.draft.current_nomination = None
        self.draft.status = "complete"

    def reset(self) -> None:
        self.draft.picks = []
        self.draft.nomination_pointer = 0
        self.draft.current_nomination = None
        self.draft.status = "setup"

    def keeper_records(self, season: str) -> list[KeeperRecord]:
        """Current keepers as history rows for `season` (Phase 2 reads these)."""
        out = []
        for p in self.draft.picks:
            if p.is_keeper:
                rec = self.players.get(p.player_id)
                out.append(KeeperRecord(season=season, manager_id=p.manager_id, player_id=p.player_id,
                                        player_name=rec.full_name if rec else str(p.player_id),
                                        cost=KeeperCost(type="auction", amount=p.price)))
        return out

    # ------------------------------------------------------------------ internals

    def _require_live(self) -> None:
        if self.draft.status != "live":
            raise DraftError(f"draft is {self.draft.status}, not live")

    def _record_pick(
        self, player_id: int, manager_id: str, price: int, slot: str | None, is_keeper: bool, nominated_by: str | None
    ) -> Pick:
        manager = self.manager(manager_id)
        if player_id not in self.players:
            raise DraftError(f"unknown player {player_id}")
        if not self.is_available(player_id):
            raise DraftError(f"player {player_id} is already drafted")
        budget = manager_budget(self.league, manager, self.draft.picks)
        error = validate_bid(price, budget, self.league.min_bid)
        if error:
            raise DraftError(error)
        if self.league.bid_increment > 1 and (price - self.league.min_bid) % self.league.bid_increment:
            raise DraftError(f"bid ${price} is not a multiple of the ${self.league.bid_increment} increment")
        own = self.picks_for(manager_id)
        eligibility = self.eligibility(player_id)
        if slot is None:
            slot = roster.assign_slot(self.league, own, eligibility)
            if slot is None:
                raise DraftError(f"{manager_id} has no open slot that fits {', '.join(eligibility) or 'this player'}")
        else:
            error = roster.validate_slot(self.league, own, eligibility, slot)
            if error:
                raise DraftError(error)
        pick = Pick(
            pick_number=len(self.draft.picks) + 1,
            player_id=player_id,
            manager_id=manager_id,
            price=price,
            slot=slot,  # type: ignore[arg-type]
            is_keeper=is_keeper,
            nominated_by=nominated_by,
            timestamp=self._now(),
        )
        self.draft.picks.append(pick)
        return pick
