"""Player-side models: identity, bio, fantasy attributes, overrides, stats."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

Position = Literal["PG", "SG", "SF", "PF", "C"]
ALL_POSITIONS: tuple[Position, ...] = ("PG", "SG", "SF", "PF", "C")

SlotType = Literal["PG", "SG", "SF", "PF", "C", "G", "F", "UTIL", "BN", "IR"]
InjuryStatus = Literal["healthy", "day_to_day", "out_short_term", "out_long_term", "out_season"]
Source = Literal["nba_api", "sleeper", "manual", "none"]
MatchMethod = Literal["name_team", "name_only", "birthdate", "static_list", "sleeper_only", "nba_only"]

_ALL = frozenset(ALL_POSITIONS)
SLOT_ACCEPTS: dict[str, frozenset[str]] = {
    "PG": frozenset({"PG"}),
    "SG": frozenset({"SG"}),
    "SF": frozenset({"SF"}),
    "PF": frozenset({"PF"}),
    "C": frozenset({"C"}),
    "G": frozenset({"PG", "SG"}),
    "F": frozenset({"SF", "PF"}),
    "UTIL": _ALL,
    "BN": _ALL,
    "IR": _ALL,
}


class PlayerRef(BaseModel):
    """A player as listed in nba_api's bundled static data (no network)."""

    player_id: int
    full_name: str
    first_name: str
    last_name: str
    is_active: bool


class TeamRef(BaseModel):
    team_id: int
    abbreviation: str
    full_name: str
    nickname: str
    city: str


class PlayerBio(BaseModel):
    """What ONE provider knows about a player. Both providers emit this shape."""

    source: Source
    source_id: str
    full_name: str
    first_name: str
    last_name: str
    normalized_name: str
    team_abbr: str | None = None
    team_id: int | None = None
    roster_status: str | None = None
    is_active: bool | None = None
    position_raw: str | None = None
    height_in: int | None = None
    weight_lbs: int | None = None
    birthdate: date | None = None
    age: float | None = None
    years_exp: int | None = None
    draft_year: int | None = None
    draft_round: int | None = None
    draft_number: int | None = None
    country: str | None = None
    college: str | None = None
    fetched_at: datetime


class FantasyAttributes(BaseModel):
    """Sleeper-only facts, keyed by Sleeper player id."""

    sleeper_id: str
    fantasy_positions: list[Position] = Field(default_factory=list)
    position: str | None = None          # Sleeper's main position (what its positional ranks use)
    fantasy_positions_alt: list[Position] | None = None
    injury_status_raw: str | None = None
    injury_body_part: str | None = None
    injury_notes: str | None = None
    injury_start_date: date | None = None
    search_rank: int | None = None
    news_updated: datetime | None = None
    team_changed_at: datetime | None = None
    depth_chart_position: str | None = None
    depth_chart_order: int | None = None


class PlayerRecord(BaseModel):
    """The merged record the engine and API see (output of the reconciler)."""

    player_id: int
    sleeper_id: str | None = None
    full_name: str
    first_name: str
    last_name: str
    normalized_name: str
    team_abbr: str | None = None
    team_conflict: dict[str, str] | None = None
    unsigned_per_sleeper: bool = False
    sleeper_status: str | None = None  # "ACT" | "TWO-WAY" | "FA" | "RET" ... as Sleeper reports it
    bio: PlayerBio
    fantasy: FantasyAttributes | None = None
    match_method: MatchMethod
    has_stats: bool = True
    projection: dict[str, float] | None = None  # Sleeper season projection, per-game stats (attached at load)


class PlayerOverrides(BaseModel):
    """Per-player draft attributes: eligibility and injury seeded from Sleeper on every pull, plus the user's notes."""

    player_id: int
    eligibility: list[Position] = Field(default_factory=list)
    eligibility_source: Source = "none"
    injury_status: InjuryStatus = "healthy"
    injury_source: Source = "none"
    injury_note: str = ""
    injury_sleeper_raw: str | None = None
    seeded_at: datetime | None = None
    notes: str = ""
    updated_at: datetime


class GameLine(BaseModel):
    """One row per game played, normalized from nba_api."""

    player_id: int
    season: str
    game_id: str
    game_date: date
    team_abbr: str
    opponent_abbr: str
    home: bool
    win: bool | None = None
    minutes: float
    pts: int
    reb: int
    ast: int
    stl: int
    blk: int
    tov: int
    fgm: int
    fga: int
    ftm: int
    fta: int
    fg3m: int
    fg3a: int
    oreb: int
    dreb: int
    pf: int
    plus_minus: int


class PlayerValuation(BaseModel):
    """Derived from GameLine[] + ScoringSettings; recomputed whenever scoring changes.

    All *_fpts fields are fantasy points under the configured scoring (base values + per-game bonuses).
    """

    player_id: int
    stats_season: str
    games_played: int
    per_game_fpts: list[float]
    avg_fpts: float                     # FP per game played
    best_game_fpts: float               # single best game
    weekly_best_avg: float = 0.0        # mean of the best game in each fantasy week played (Lock-In estimator)
    top_quarter_avg: float = 0.0        # mean of the top 25 % of games
    total_fpts: float = 0.0             # season total
    weeks_played: int = 0               # fantasy weeks (Mon-Sun) with at least one game
    season_weeks: int = 0               # fantasy weeks in the league season
    availability: float = 0.0           # weeks_played / season_weeks
    stat_averages: dict[str, float] = Field(default_factory=dict)   # pts, reb, ast, ... per game
    bonus_fpts_per_game: float = 0.0    # FP from bonus rules, per game
    bonus_counts: dict[str, int]
    minutes_avg: float
    teams_played_for: list[str]


class SeasonTotals(BaseModel):
    """One row per season from PlayerCareerStats (regular season)."""

    season: str
    team_id: int
    team_abbr: str
    age: float | None = None
    gp: int
    gs: int
    minutes: int
    pts: int
    reb: int
    ast: int
    stl: int
    blk: int
    tov: int
    fgm: int
    fga: int
    fg3m: int
    fg3a: int
    ftm: int
    fta: int


class PlayerDetail(BaseModel):
    """On-demand sidebar data: exact bio plus per-season history."""

    player_id: int
    birthdate: date | None = None
    season_exp: int | None = None
    position_raw: str | None = None
    height_in: int | None = None
    weight_lbs: int | None = None
    school: str | None = None
    country: str | None = None
    draft_year: int | None = None
    draft_round: int | None = None
    draft_number: int | None = None
    season_totals: list[SeasonTotals] = Field(default_factory=list)
    fetched_at: datetime


class ReconcileReport(BaseModel):
    run_at: datetime
    roster_season: str
    nba_pool_size: int
    sleeper_all_size: int
    sleeper_rostered_size: int
    counts: dict[str, int]
    team_conflicts: list[dict] = Field(default_factory=list)
    unsigned_per_sleeper: list[dict] = Field(default_factory=list)
    collisions: list[dict] = Field(default_factory=list)
    unmatched_nba: list[dict] = Field(default_factory=list)
    unmatched_sleeper: list[dict] = Field(default_factory=list)
