"""DraftSession: one league's settings, managers, draft state and player data, wired to the engine.

The session owns the in-memory state the API serves; `to_export()` produces the versioned document
that is both the on-disk league file and the Fantasy Tracker import (DESIGN.md 1.8).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Mapping

from nba_fantasy_shared.models.draft import DraftState, KeeperHistory
from nba_fantasy_shared.models.export import DraftExport, ExportedPlayer, KeeperBlock
from nba_fantasy_shared.models.league import LeagueSettings, Manager
from nba_fantasy_shared.models.players import PlayerOverrides, PlayerRecord, PlayerValuation
from nba_fantasy_shared.providers.base import utcnow

from . import roster
from .bidding import BidRecommendation, market_rate, recommend_bid
from .budget import ManagerBudget
from .draft_state import DraftEngine, DraftError, KeeperAssignment
from .ranking import RankedPlayer, pool_values, rank_players
from .spending import SpendingGuide, spending_guide


@dataclass
class ManagerSummary:
    manager_id: str
    name: str
    is_user: bool
    budget: ManagerBudget
    open_slots: dict[str, int]
    picks: list[dict]
    stack: dict[str, int]
    is_next_nominator: bool
    behavior: dict
    tendency: dict | None = None   # how they spent in last season's Sleeper auction


@dataclass
class DraftSession:
    league: LeagueSettings
    managers: list[Manager]
    draft: DraftState
    keeper_history: KeeperHistory
    players: dict[int, PlayerRecord]
    overrides: dict[int, PlayerOverrides]
    valuations: dict[int, PlayerValuation]
    now: Callable[[], datetime] = utcnow
    sleeper_details: dict | None = None   # cached Sleeper league details (see services/sleeper_league.py)
    sleeper_history: list[dict] = field(default_factory=list)   # extra leagues, for draft habits only
    _pool_values: dict[int, float] | None = field(default=None, init=False, repr=False)
    _opening_rate: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.engine = DraftEngine(self.league, self.managers, self.draft, self.players, self.overrides, now=self.now)

    # ------------------------------------------------------------------ invalidation

    def invalidate(self) -> None:
        """Call after any override, valuation, or league-settings change."""
        self._pool_values = None
        self._opening_rate = None
        self.engine.league = self.league
        self.engine.managers = self.managers

    def set_league(self, league: LeagueSettings) -> None:
        self.league = league
        self.invalidate()

    def set_override(self, override: PlayerOverrides) -> None:
        self.overrides[override.player_id] = override
        self.invalidate()

    def set_valuations(self, valuations: Mapping[int, PlayerValuation]) -> None:
        self.valuations = dict(valuations)
        self.invalidate()

    # ------------------------------------------------------------------ queries

    def user_manager_id(self) -> str:
        user = self.engine.user_manager()
        if user is None:
            raise DraftError("no manager is marked is_user")
        return user.manager_id

    def pool_values(self) -> dict[int, float]:
        if self._pool_values is None:
            self._pool_values = pool_values(self.players, self.overrides, self.valuations, self.league.ranking, self.league.scoring)
        return self._pool_values

    def available_ids(self) -> list[int]:
        drafted = self.engine.drafted_ids()
        return [pid for pid in self.players if pid not in drafted]

    def rankings(self, manager_id: str | None = None, limit: int | None = None) -> list[RankedPlayer]:
        manager_id = manager_id or self.user_manager_id()
        rows = rank_players(
            self.league, self.players, self.overrides, self.valuations,
            self.engine.picks_for(manager_id), self.available_ids(),
        )
        if self.league.ranking.hide_unrosterable:
            rows = [r for r in rows if r.rosterable]
        return rows[:limit] if limit else rows

    def recommend(self, player_id: int, manager_id: str | None = None) -> BidRecommendation:
        manager_id = manager_id or self.user_manager_id()
        if not self.engine.is_available(player_id):
            raise DraftError(f"player {player_id} is not available")
        rows = rank_players(
            self.league, self.players, self.overrides, self.valuations,
            self.engine.picks_for(manager_id), self.available_ids(),
        )
        target = next(r for r in rows if r.player_id == player_id)
        return recommend_bid(
            self.league, self.managers, self.draft.picks, manager_id, target, rows, self.pool_values(),
            self.engine.progress(),
        )

    def opening_rate(self) -> float:
        """$/VAR with full budgets and nobody drafted: the baseline the spending guide measures inflation against."""
        if self._opening_rate is None:
            rows = rank_players(self.league, self.players, self.overrides, self.valuations, [], list(self.players))
            self._opening_rate = market_rate(
                self.league, self.managers, [], (r.value for r in rows), self.pool_values()
            ).dollars_per_var
        return self._opening_rate

    def spending_guide(self, manager_id: str | None = None, player_id: int | None = None) -> SpendingGuide:
        manager_id = manager_id or self.user_manager_id()
        rows = rank_players(
            self.league, self.players, self.overrides, self.valuations,
            self.engine.picks_for(manager_id), self.available_ids(),
        )
        return spending_guide(
            self.league, self.managers, self.draft.picks, manager_id, rows, self.pool_values(),
            self.engine.progress(), self.opening_rate(), focus_player_id=player_id,
        )

    def manager_summaries(self) -> list[ManagerSummary]:
        from ..services.sleeper_league import draft_habits, tendencies

        nominator = self.engine.next_nominator()
        habits = tendencies(self.sleeper_details)
        drafts = draft_habits([self.sleeper_details, *self.sleeper_history]) if self.sleeper_details else {}
        by_sleeper = {r.sleeper_id: pid for pid, r in self.players.items() if r.sleeper_id}

        def tendency(m) -> dict | None:
            if not habits and not drafts:
                return None
            t = dict(habits.get(m.sleeper_user_id) or {"style": "new", "top_buys": []})
            d = drafts.get(m.sleeper_user_id) or {}
            t["favorite_teams"] = d.get("favorite_teams", [])
            t["lean"] = d.get("lean")
            # our player id -> where they drafted him before ("2025 tobedecided.: $51")
            t["drafted_before"] = {str(by_sleeper[s]): how for s, how in d.get("drafted", {}).items() if s in by_sleeper}
            return t
        out = []
        for m in self.managers:
            picks = self.engine.picks_for(m.manager_id)
            out.append(
                ManagerSummary(
                    manager_id=m.manager_id,
                    name=m.name,
                    is_user=m.is_user,
                    budget=self.engine.budget(m.manager_id),
                    open_slots=self.engine.open_slots(m.manager_id),
                    picks=[
                        {**p.model_dump(mode="json"),
                         "player_name": self.players[p.player_id].full_name if p.player_id in self.players else str(p.player_id),
                         "team_abbr": self.players[p.player_id].team_abbr if p.player_id in self.players else None}
                        for p in picks
                    ],
                    stack=dict(roster.team_stack(self.players, picks)),
                    is_next_nominator=(m.manager_id == nominator),
                    behavior=m.behavior.model_dump(),
                    tendency=tendency(m),
                )
            )
        return out

    # ------------------------------------------------------------------ commands (delegated)

    def start(self, keepers: list[KeeperAssignment]) -> None:
        self.engine.start(keepers)
        self.sync_keeper_history()

    def sync_keeper_history(self) -> None:
        """This season's keeper rows in the history mirror the keeper picks in the draft."""
        season = self.league.roster_season
        self.keeper_history.records = [
            r for r in self.keeper_history.records if r.season != season
        ] + self.engine.keeper_records(season)

    def edit_pick(self, pick_number: int, manager_id: str | None = None, price: int | None = None, slot: str | None = None):
        pick = self.engine.edit_pick(pick_number, manager_id, price, slot)
        if pick.is_keeper:
            self.sync_keeper_history()
        return pick

    def remove_pick(self, pick_number: int):
        pick = self.engine.remove_pick(pick_number)
        if pick.is_keeper:
            self.sync_keeper_history()
        return pick

    # ------------------------------------------------------------------ export / import

    def to_export(self) -> DraftExport:
        drafted = self.engine.drafted_ids()
        players = {
            str(pid): ExportedPlayer(
                record=self.players[pid], overrides=self.overrides.get(pid), valuation=self.valuations.get(pid)
            )
            for pid in sorted(drafted)
            if pid in self.players
        }
        return DraftExport(
            generated_at=self.now(),
            league=self.league,
            managers=self.managers,
            draft=self.draft,
            keepers=KeeperBlock(
                current=[p for p in self.draft.picks if p.is_keeper],
                history=list(self.keeper_history.records),
            ),
            players=players,
        )

    @classmethod
    def from_export(
        cls,
        doc: DraftExport,
        players: Mapping[int, PlayerRecord],
        overrides: Mapping[int, PlayerOverrides],
        valuations: Mapping[int, PlayerValuation],
        now: Callable[[], datetime] = utcnow,
    ) -> "DraftSession":
        merged_players = dict(players)
        merged_overrides = dict(overrides)
        merged_valuations = dict(valuations)
        # Drafted players snapshotted in the document win over missing pool entries (pool may have re-pulled).
        for key, exported in doc.players.items():
            pid = int(key)
            merged_players.setdefault(pid, exported.record)
            if exported.overrides is not None:
                merged_overrides.setdefault(pid, exported.overrides)
            if exported.valuation is not None:
                merged_valuations.setdefault(pid, exported.valuation)
        return cls(
            league=doc.league,
            managers=list(doc.managers),
            draft=doc.draft,
            keeper_history=KeeperHistory(records=list(doc.keepers.history)),
            players=merged_players,
            overrides=merged_overrides,
            valuations=merged_valuations,
            now=now,
        )
