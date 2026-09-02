"""Draft state and keeper history."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .players import SlotType


class Pick(BaseModel):
    pick_number: int
    player_id: int
    manager_id: str
    price: int
    slot: SlotType
    is_keeper: bool = False
    nominated_by: str | None = None
    timestamp: datetime


class CurrentNomination(BaseModel):
    player_id: int
    nominated_by: str
    opened_at: datetime


class DraftState(BaseModel):
    status: Literal["setup", "live", "complete"] = "setup"
    nomination_order: list[str] = Field(default_factory=list)
    nomination_pointer: int = 0
    current_nomination: CurrentNomination | None = None
    picks: list[Pick] = Field(default_factory=list)


class KeeperCost(BaseModel):
    type: Literal["auction", "draft"]
    amount: int | None = None
    round: int | None = None
    pick: int | None = None


class KeeperRecord(BaseModel):
    season: str
    manager_id: str
    player_id: int
    player_name: str
    cost: KeeperCost


class KeeperHistory(BaseModel):
    records: list[KeeperRecord] = Field(default_factory=list)
