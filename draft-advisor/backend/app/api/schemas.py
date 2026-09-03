"""Request bodies for the API. Responses reuse the shared Pydantic models and engine dataclasses."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nba_fantasy_shared.models.draft import KeeperRecord
from nba_fantasy_shared.models.league import LeagueSettings, Manager, ManagerBehavior
from nba_fantasy_shared.models.players import InjuryStatus, Position, SlotType


class PullRequest(BaseModel):
    sources: list[str] = Field(default_factory=lambda: ["nba_api", "sleeper"])
    force_sleeper: bool = False
    skip_game_logs: bool = False


class OverridePatch(BaseModel):
    eligibility: list[Position] | None = None
    injury_status: InjuryStatus | None = None
    injury_note: str | None = None
    notes: str | None = None


class OverrideReset(BaseModel):
    fields: list[Literal["eligibility", "injury"]]


class CreateLeague(BaseModel):
    league_id: str
    name: str
    settings: LeagueSettings | None = None
    managers: list[Manager] | None = None


class ManagerPatch(BaseModel):
    name: str | None = None
    is_user: bool | None = None
    budget_total: int | None = None
    behavior: ManagerBehavior | None = None
    sleeper_user_id: str | None = None
    sleeper_roster_id: int | None = None


class KeeperIn(BaseModel):
    manager_id: str
    player_id: int
    cost: int


class StartDraft(BaseModel):
    keepers: list[KeeperIn] = Field(default_factory=list)


class KeeperCandidateIn(BaseModel):
    manager_id: str
    player_id: int
    last_price: int = Field(ge=0)
    keeper_price: int | None = Field(default=None, ge=1)


class KeeperEvaluateIn(BaseModel):
    candidates: list[KeeperCandidateIn]


class NominateIn(BaseModel):
    player_id: int
    manager_id: str | None = None
    force: bool = False


class PickIn(BaseModel):
    player_id: int
    manager_id: str
    price: int
    slot: SlotType | None = None


class ReassignIn(BaseModel):
    pick_number: int
    slot: SlotType


class NominationOrderIn(BaseModel):
    order: list[str]


class KeeperHistoryIn(BaseModel):
    records: list[KeeperRecord]


class SleeperPreviewIn(BaseModel):
    sleeper_league_id: str


SleeperApplyField = Literal["name", "scoring", "roster_slots", "num_managers", "keepers"]


class SleeperApplyIn(BaseModel):
    sleeper_league_id: str
    apply: list[SleeperApplyField]
