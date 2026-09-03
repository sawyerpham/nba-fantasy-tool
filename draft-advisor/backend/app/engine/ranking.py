"""Rank available players for one manager.

value = (w_avg × FP/G + w_ceiling × ceiling) × confidence(games) × availability × injury multiplier × age multiplier
ceiling = average of each week's best game by default (Lock-In), or the single best game / top-quarter average.
Players who cannot fill any of the manager's open slots sink to the bottom (or are hidden by the UI).
Everything is pure: re-running after a pick, an override edit, or a settings change re-sorts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, RankingSettings
from nba_fantasy_shared.models.players import PlayerOverrides, PlayerRecord, PlayerValuation
from nba_fantasy_shared.scoring import availability_factor, ceiling_value, confidence_factor

from . import roster


@dataclass
class RankedPlayer:
    player_id: int
    full_name: str
    team_abbr: str | None
    eligibility: list[str]
    eligibility_source: str
    injury_status: str
    injury_note: str
    age: float | None
    games_played: int
    avg_fpts: float
    best_game_fpts: float
    weekly_best_avg: float
    top_quarter_avg: float
    total_fpts: float
    availability: float
    weeks_played: int
    ceiling: float
    ceiling_metric: str
    blended: float
    confidence: float
    availability_factor: float
    injury_multiplier: float
    age_multiplier: float
    value: float
    rosterable: bool
    assignable_slot: str | None
    stack_if_added: int
    has_stats: bool
    match_method: str
    sleeper_status: str | None
    unsigned_per_sleeper: bool
    team_conflict: dict[str, str] | None
    rank: int = 0
    bonus_counts: dict[str, int] = field(default_factory=dict)


def injury_multiplier(status: str, ranking: RankingSettings) -> float:
    return float(ranking.injury_multipliers.get(status, 1.0))


def age_multiplier(age: float | None, ranking: RankingSettings) -> float:
    if age is None:
        return 1.0
    years_over = max(0.0, age - ranking.age_penalty_start)
    penalty = min(ranking.age_penalty_max, years_over * ranking.age_penalty_per_year)
    return 1.0 - penalty


def player_value(
    record: PlayerRecord,
    override: PlayerOverrides | None,
    valuation: PlayerValuation | None,
    ranking: RankingSettings,
) -> tuple[float, float, float, float, float, float]:
    """Returns (value, blended, confidence, injury_mult, age_mult, availability_mult)."""
    if valuation is None:
        blended, confidence, avail = 0.0, 0.0, 1.0
    else:
        blended = ranking.weight_avg * valuation.avg_fpts + ranking.weight_ceiling * ceiling_value(valuation, ranking)
        confidence = confidence_factor(valuation.games_played, ranking.min_games_full_confidence)
        avail = availability_factor(valuation, ranking)
    inj = injury_multiplier(override.injury_status if override else "healthy", ranking)
    age = age_multiplier(record.bio.age, ranking)
    return blended * confidence * avail * inj * age, blended, confidence, inj, age, avail


def pool_values(
    players: Mapping[int, PlayerRecord],
    overrides: Mapping[int, PlayerOverrides],
    valuations: Mapping[int, PlayerValuation],
    ranking: RankingSettings,
) -> dict[int, float]:
    """Roster-independent value of every player in the pool (drafted or not)."""
    return {
        pid: player_value(rec, overrides.get(pid), valuations.get(pid), ranking)[0]
        for pid, rec in players.items()
    }


def rank_players(
    league: LeagueSettings,
    players: Mapping[int, PlayerRecord],
    overrides: Mapping[int, PlayerOverrides],
    valuations: Mapping[int, PlayerValuation],
    my_picks: Iterable[Pick],
    available_ids: Iterable[int],
) -> list[RankedPlayer]:
    my_picks = list(my_picks)
    stack = roster.team_stack(players, my_picks)
    ranking = league.ranking
    rows: list[RankedPlayer] = []
    for pid in available_ids:
        rec = players.get(pid)
        if rec is None:
            continue
        override = overrides.get(pid)
        valuation = valuations.get(pid)
        value, blended, confidence, inj, age_mult, avail = player_value(rec, override, valuation, ranking)
        eligibility = list(override.eligibility) if override else []
        slot = roster.assign_slot(league, my_picks, eligibility)
        rows.append(
            RankedPlayer(
                player_id=pid,
                full_name=rec.full_name,
                team_abbr=rec.team_abbr,
                eligibility=eligibility,
                eligibility_source=override.eligibility_source if override else "none",
                injury_status=override.injury_status if override else "healthy",
                injury_note=override.injury_note if override else "",
                age=rec.bio.age,
                games_played=valuation.games_played if valuation else 0,
                avg_fpts=valuation.avg_fpts if valuation else 0.0,
                best_game_fpts=valuation.best_game_fpts if valuation else 0.0,
                weekly_best_avg=valuation.weekly_best_avg if valuation else 0.0,
                top_quarter_avg=valuation.top_quarter_avg if valuation else 0.0,
                total_fpts=valuation.total_fpts if valuation else 0.0,
                availability=valuation.availability if valuation else 0.0,
                weeks_played=valuation.weeks_played if valuation else 0,
                ceiling=round(ceiling_value(valuation, ranking), 2) if valuation else 0.0,
                ceiling_metric=ranking.ceiling_metric,
                blended=round(blended, 2),
                confidence=round(confidence, 3),
                availability_factor=round(avail, 3),
                injury_multiplier=inj,
                age_multiplier=round(age_mult, 3),
                value=round(value, 2),
                rosterable=slot is not None,
                assignable_slot=slot,
                stack_if_added=roster.stack_if_added(stack, rec.team_abbr),
                has_stats=rec.has_stats,
                match_method=rec.match_method,
                sleeper_status=rec.sleeper_status,
                unsigned_per_sleeper=rec.unsigned_per_sleeper,
                team_conflict=rec.team_conflict,
                bonus_counts=dict(valuation.bonus_counts) if valuation else {},
            )
        )
    rows.sort(key=lambda r: (not r.rosterable, -r.value, -r.avg_fpts, r.full_name))
    for i, row in enumerate(rows, 1):
        row.rank = i
    return rows
