"""Request bodies for the API. Responses reuse the shared Pydantic models and engine dataclasses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nba_fantasy_shared.models.draft import KeeperRecord
from nba_fantasy_shared.models.league import LeagueSettings, Manager, ManagerBehavior
from nba_fantasy_shared.models.players import SlotType


class PullRequest(BaseModel):
    """Body of POST /data/pull: which sources to pull and the force-Sleeper and skip-game-logs switches."""
    sources: list[str] = Field(default_factory=lambda: ["nba_api", "sleeper"])
    force_sleeper: bool = False
    skip_game_logs: bool = False


class OverridePatch(BaseModel):
    """Body for patching a player's overrides (his notes)."""
    notes: str | None = None


class CreateLeague(BaseModel):
    """Body to create a league, optionally with settings and managers."""
    league_id: str
    name: str
    settings: LeagueSettings | None = None
    managers: list[Manager] | None = None


class ManagerPatch(BaseModel):
    """Partial update of a manager (every field optional)."""
    name: str | None = None
    is_user: bool | None = None
    budget_total: int | None = None
    behavior: ManagerBehavior | None = None
    sleeper_user_id: str | None = None
    sleeper_roster_id: int | None = None


class KeeperIn(BaseModel):
    """A keeper to set when starting the draft: manager, player and cost."""
    manager_id: str
    player_id: int
    cost: int


class StartDraft(BaseModel):
    """Body to start the draft with its keepers."""
    keepers: list[KeeperIn] = Field(default_factory=list)


class KeeperCandidateIn(BaseModel):
    """One keeper candidate to evaluate: last year's price and an optional hand-edited keeper price."""
    manager_id: str
    player_id: int
    last_price: int = Field(ge=0)
    keeper_price: int | None = Field(default=None, ge=1)


class KeeperEvaluateIn(BaseModel):
    """Body to evaluate a batch of keeper candidates."""
    candidates: list[KeeperCandidateIn]


class NominateIn(BaseModel):
    """Body to nominate a player (optionally for a manager, with `force`)."""
    player_id: int
    manager_id: str | None = None
    force: bool = False


class PickIn(BaseModel):
    """Body to record a pick: player, winning manager, price and optional slot."""
    player_id: int
    manager_id: str
    price: int
    slot: SlotType | None = None


class ReassignIn(BaseModel):
    """Body to move a recorded pick to another roster slot."""
    pick_number: int
    slot: SlotType


class EditPickIn(BaseModel):
    """Body to edit a recorded pick (manager, price or slot; every field optional)."""
    manager_id: str | None = None
    price: int | None = None
    slot: SlotType | None = None


class NominationOrderIn(BaseModel):
    """Body to set the nomination order."""
    order: list[str]


class NextNominatorIn(BaseModel):
    """Body to make a manager the next nominator."""
    manager_id: str


class KeeperHistoryIn(BaseModel):
    """Body to replace the keeper history."""
    records: list[KeeperRecord]


class SleeperPreviewIn(BaseModel):
    """Body to preview a Sleeper league's settings."""
    sleeper_league_id: str


SleeperApplyField = Literal["name", "scoring", "roster_slots", "num_managers", "keepers"]


class SleeperApplyIn(BaseModel):
    """Body to apply chosen fields (name, scoring, roster slots, manager count, keepers) from a Sleeper league."""
    sleeper_league_id: str
    apply: list[SleeperApplyField]
