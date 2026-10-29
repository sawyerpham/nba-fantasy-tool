"""Versioned export document. The on-disk league file uses exactly this shape."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from .draft import DraftState, KeeperRecord, Pick
from .league import LeagueSettings, Manager
from .players import PlayerOverrides, PlayerRecord, PlayerValuation

SCHEMA_VERSION = 1


class ExportedPlayer(BaseModel):
    """One player in the export: his record plus any overrides and valuation."""
    record: PlayerRecord
    overrides: PlayerOverrides | None = None
    valuation: PlayerValuation | None = None


class KeeperBlock(BaseModel):
    """The keeper block of an export: this season's keeper picks and the keeper history."""
    current: list[Pick] = Field(default_factory=list)
    history: list[KeeperRecord] = Field(default_factory=list)


class DraftExport(BaseModel):
    """The whole versioned export document: league settings, managers, draft state, keepers and every player."""
    schema_version: int = SCHEMA_VERSION
    generated_by: str = "draft-advisor"
    generated_at: datetime
    league: LeagueSettings
    managers: list[Manager]
    draft: DraftState
    keepers: KeeperBlock
    players: dict[str, ExportedPlayer] = Field(default_factory=dict)
