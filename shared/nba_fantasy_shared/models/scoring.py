"""Scoring settings. Every value is editable; defaults come from SPEC.md."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from .players import Source


class BaseScoring(BaseModel):
    pts: float = 0.25
    reb: float = 0.4
    ast: float = 0.5
    stl: float = 0.75
    blk: float = 0.75
    tov: float = -0.5
    fgm: float = 0.25
    fga: float = -0.1
    ftm: float = 0.05
    fg3m: float = 0.3


class BonusRule(BaseModel):
    id: str
    kind: Literal["stat_threshold", "triple_double"]
    stat: Literal["pts", "reb", "ast", "stl", "blk"] | None = None
    threshold: int | None = None
    bonus: float


def default_bonuses() -> list[BonusRule]:
    return [
        BonusRule(id="triple_double", kind="triple_double", bonus=2.0),
        BonusRule(id="pts_40", kind="stat_threshold", stat="pts", threshold=40, bonus=4.0),
        BonusRule(id="pts_50", kind="stat_threshold", stat="pts", threshold=50, bonus=1.0),
        BonusRule(id="ast_15", kind="stat_threshold", stat="ast", threshold=15, bonus=4.0),
        BonusRule(id="reb_20", kind="stat_threshold", stat="reb", threshold=20, bonus=4.0),
    ]


class ScoringSettings(BaseModel):
    base: BaseScoring = Field(default_factory=BaseScoring)
    bonuses: list[BonusRule] = Field(default_factory=default_bonuses)
    source: Source = "manual"

    def scoring_hash(self) -> str:
        """Stable hash of everything that affects fantasy-point values (not `source`)."""
        payload = {"base": self.base.model_dump(), "bonuses": [b.model_dump() for b in self.bonuses]}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
