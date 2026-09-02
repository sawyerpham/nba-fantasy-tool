"""League settings, managers, ranking knobs, and the Sleeper platform objects."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from .players import InjuryStatus, SlotType
from .scoring import ScoringSettings

GameMode = Literal["lock_in", "standard"]
DraftType = Literal["auction", "snake"]
NominationOrder = Literal["fixed_rotation", "snake"]
ScoringFormat = Literal["h2h_points"]


class RosterSlotSpec(BaseModel):
    slot: SlotType
    count: int = Field(ge=0)


def default_roster_slots() -> list[RosterSlotSpec]:
    # Decision 3: 7 starters (PG SG SF PF C UTIL UTIL), 8 bench, 2 IR.
    return [
        RosterSlotSpec(slot="PG", count=1),
        RosterSlotSpec(slot="SG", count=1),
        RosterSlotSpec(slot="SF", count=1),
        RosterSlotSpec(slot="PF", count=1),
        RosterSlotSpec(slot="C", count=1),
        RosterSlotSpec(slot="UTIL", count=2),
        RosterSlotSpec(slot="BN", count=8),
        RosterSlotSpec(slot="IR", count=2),
    ]


class KeeperSettings(BaseModel):
    enabled: bool = True
    max_per_manager: int = 1
    deadline: date | None = None


def default_injury_multipliers() -> dict[str, float]:
    return {
        "healthy": 1.0,
        "day_to_day": 0.95,
        "out_short_term": 0.85,
        "out_long_term": 0.6,
        "out_season": 0.0,
    }


def default_sleeper_injury_map() -> dict[str, InjuryStatus]:
    # Decision 9: Sleeper carries no duration, "Out" seeds as short term.
    return {"DTD": "day_to_day", "Out": "out_short_term", "IR": "out_long_term"}


class RankingSettings(BaseModel):
    weight_avg: float = 0.6
    weight_ceiling: float = 0.4
    injury_multipliers: dict[str, float] = Field(default_factory=default_injury_multipliers)
    sleeper_injury_map: dict[str, InjuryStatus] = Field(default_factory=default_sleeper_injury_map)
    age_penalty_start: int = 31
    age_penalty_per_year: float = 0.03
    age_penalty_max: float = 0.25
    min_games_full_confidence: int = 20
    hide_unrosterable: bool = True


class ManagerBehavior(BaseModel):
    spend_pace: Literal["early", "even", "late"] = "even"
    aggression: float = 1.0


class Manager(BaseModel):
    manager_id: str
    name: str
    is_user: bool = False
    budget_total: int = 200
    behavior: ManagerBehavior = Field(default_factory=ManagerBehavior)
    sleeper_user_id: str | None = None
    sleeper_roster_id: int | None = None


class LeagueSettings(BaseModel):
    league_id: str
    name: str
    platform: Literal["sleeper"] = "sleeper"
    sleeper_league_id: str | None = None
    roster_season: str = "2026-27"
    stats_season: str = "2025-26"
    game_mode: GameMode = "lock_in"
    scoring_format: ScoringFormat = "h2h_points"
    draft_type: DraftType = "auction"
    nomination_order_type: NominationOrder = "fixed_rotation"
    num_managers: int = 12
    roster_slots: list[RosterSlotSpec] = Field(default_factory=default_roster_slots)
    budget_per_manager: int = 200
    min_bid: int = 1
    bid_increment: int = 1
    keeper: KeeperSettings = Field(default_factory=KeeperSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    ranking: RankingSettings = Field(default_factory=RankingSettings)

    @model_validator(mode="after")
    def _check_budget(self) -> "LeagueSettings":
        if self.min_bid < 1:
            raise ValueError("min_bid must be at least 1")
        if self.budget_per_manager < self.min_bid * self.mandatory_slot_count():
            raise ValueError("budget_per_manager cannot fill every mandatory slot at min_bid")
        return self

    def mandatory_slot_count(self) -> int:
        """Slots that must be filled by draft's end (everything except IR). Decision 10."""
        return sum(s.count for s in self.roster_slots if s.slot != "IR")

    def total_slot_count(self) -> int:
        return sum(s.count for s in self.roster_slots)


class PlatformState(BaseModel):
    """Normalized Sleeper /v1/state/nba."""

    season: str
    season_type: str
    previous_season: str | None = None
    season_start_date: date | None = None
    week: int | None = None
    league_season: str | None = None


class PlatformLeague(BaseModel):
    """Normalized Sleeper /v1/league/{id}. Structure verified on a public league."""

    league_id: str
    name: str
    sport: str
    season: str
    status: str
    total_rosters: int
    roster_positions: list[str]
    settings: dict[str, int | float | None]
    scoring_settings: dict[str, float]
    draft_id: str | None = None
    previous_league_id: str | None = None
