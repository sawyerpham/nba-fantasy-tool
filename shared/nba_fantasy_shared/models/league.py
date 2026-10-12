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


class KeeperEscalation(BaseModel):
    """Next-year keeper price = last price + increase_per_step × floor(last price / step_dollars).

    League rule (2026-09-03): +$1 per full $5 of last year's price, so $17 -> $20.
    """

    enabled: bool = True
    step_dollars: int = Field(default=5, ge=1)
    increase_per_step: int = Field(default=1, ge=0)

    def price(self, last_price: int) -> int:
        if not self.enabled:
            return max(1, int(last_price))
        last = max(0, int(last_price))
        return max(1, last + self.increase_per_step * (last // self.step_dollars))


class KeeperSettings(BaseModel):
    enabled: bool = True
    max_per_manager: int = 1
    deadline: date | None = None
    escalation: KeeperEscalation = Field(default_factory=KeeperEscalation)


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


CeilingMetric = Literal["weekly_best", "best_game", "top_quarter"]


class RankingSettings(BaseModel):
    """value = (weight_avg × FP/G + weight_ceiling × ceiling) × games confidence × injury × age × availability.

    ceiling defaults to the average of each week's best game (what Lock-In scores); 'best_game' is the single
    best game (noisy: one outlier night can lift a role player over a star), 'top_quarter' the mean of the
    top 25 % of games.
    """

    weight_avg: float = 0.5
    weight_ceiling: float = 0.5
    ceiling_metric: CeilingMetric = "weekly_best"
    availability_weight: float = 0.0                   # 0 = ignore missed weeks; 1 = scale fully by weeks played
    injury_multipliers: dict[str, float] = Field(default_factory=default_injury_multipliers)
    sleeper_injury_map: dict[str, InjuryStatus] = Field(default_factory=default_sleeper_injury_map)
    age_penalty_start: int = 31
    age_penalty_per_year: float = 0.03
    age_penalty_max: float = 0.25
    min_games_full_confidence: int = 20
    hide_unrosterable: bool = True
    # Share of FP/G taken from Sleeper's season projection (role, minutes, new team); the rest is last season.
    # 1 = projection only (user's call, 2026-10-11); players Sleeper does not project still use last season.
    projection_weight: float = 1.0
    # Bench spots per team that get real auction money; the rest are treated as $1 fills. Calibrated to
    # the league's 2025 auction (stars $90–105, #84 ≈ $6, 55 picks at $1).
    priced_bench_slots: int = 2


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
    sleeper_draft_id: str | None = None   # live-sync override (e.g. a Sleeper mock draft); default: the league's draft
    # Other Sleeper leagues with the same people (any format), pulled only to learn how each manager drafts.
    sleeper_history_league_ids: list[str] = Field(default_factory=list)
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
