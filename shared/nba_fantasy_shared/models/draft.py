from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .players import SlotType


class Pick(BaseModel):
    """One draft pick (or keeper): who took which player, at what price, in which roster slot."""
    pick_number: int
    player_id: int
    manager_id: str
    price: int
    slot: SlotType
    is_keeper: bool = False
    nominated_by: str | None = None
    timestamp: datetime


class CurrentNomination(BaseModel):
    """The player currently on the block and who nominated him."""
    player_id: int
    nominated_by: str
    opened_at: datetime


class DraftState(BaseModel):
    """Auction draft state: status (setup / live / complete), nomination order and pointer, the current nomination and every pick."""
    status: Literal["setup", "live", "complete"] = "setup"
    nomination_order: list[str] = Field(default_factory=list)
    nomination_pointer: int = 0
    current_nomination: CurrentNomination | None = None
    picks: list[Pick] = Field(default_factory=list)


class KeeperCost(BaseModel):
    """What a keeper costs: an auction amount, or a draft round / pick."""
    type: Literal["auction", "draft"]
    amount: int | None = None
    round: int | None = None
    pick: int | None = None


class KeeperRecord(BaseModel):
    """A past season's keeper: which manager kept which player at what cost."""
    season: str
    manager_id: str
    player_id: int
    player_name: str
    cost: KeeperCost


class KeeperHistory(BaseModel):
    """All recorded keepers from prior seasons."""
    records: list[KeeperRecord] = Field(default_factory=list)
