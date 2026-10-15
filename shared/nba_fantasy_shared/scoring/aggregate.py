"""Season aggregation of per-game fantasy points into a PlayerValuation, plus the value blend.

avg_fpts         mean FP per game played (season-long value, realized bonus frequency included)
weekly_best_avg  mean of the best game in each fantasy week (Mon-Sun) the player played: what Lock-In scores
best_game_fpts   single best game (kept for display / the 'best_game' ceiling option)
top_quarter_avg  mean of the top 25 % of games
availability     weeks with a game / weeks in the league season
confidence       min(1, games_played / min_games) so a tiny sample cannot out-rank a full season (decision 5)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Iterable, Mapping

from ..models.league import RankingSettings
from ..models.players import GameLine, PlayerValuation
from ..models.scoring import ScoringSettings
from .formula import score_game

STAT_KEYS: tuple[str, ...] = ("pts", "reb", "ast", "stl", "blk", "tov", "fgm", "fga", "ftm", "fta", "fg3m", "minutes")


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_index(day: date, season_start: date) -> int:
    return (day - season_start).days // 7


def season_span(logs: Mapping[int, Iterable[GameLine]]) -> tuple[date | None, int]:
    """(Monday of the first game league-wide, number of fantasy weeks through the last game)."""
    dates = [g.game_date for lines in logs.values() for g in lines]
    if not dates:
        return None, 0
    start = monday_of(min(dates))
    return start, week_index(max(dates), start) + 1


def valuate(
    player_id: int,
    stats_season: str,
    lines: Iterable[GameLine],
    settings: ScoringSettings,
    season_start: date | None = None,
    season_weeks: int | None = None,
) -> PlayerValuation:
    ordered = sorted(lines, key=lambda g: (g.game_date, g.game_id))
    scores = [score_game(g, settings) for g in ordered]
    per_game = [round(s.fpts, 2) for s in scores]
    games = len(per_game)
    bonus_counts = {rule.id: 0 for rule in settings.bonuses}
    for s in scores:
        for rule_id in s.bonuses_hit:
            bonus_counts[rule_id] += 1
    teams: list[str] = []
    for g in ordered:
        if g.team_abbr not in teams:
            teams.append(g.team_abbr)

    weekly: dict[int, float] = defaultdict(float)
    if games:
        start = season_start or monday_of(ordered[0].game_date)
        for g, fp in zip(ordered, per_game):
            idx = week_index(g.game_date, start)
            weekly[idx] = max(weekly[idx], fp)
        if season_weeks is None:
            season_weeks = week_index(ordered[-1].game_date, start) + 1
    weeks_played = len(weekly)
    season_weeks = season_weeks or 0
    top_n = max(1, games // 4) if games else 0
    top_quarter = sorted(per_game, reverse=True)[:top_n] if games else []
    stat_averages = {
        key: round(sum(getattr(g, key) for g in ordered) / games, 2) if games else 0.0 for key in STAT_KEYS
    }

    return PlayerValuation(
        player_id=player_id,
        stats_season=stats_season,
        games_played=games,
        per_game_fpts=per_game,
        avg_fpts=round(sum(per_game) / games, 2) if games else 0.0,
        best_game_fpts=max(per_game) if games else 0.0,
        weekly_best_avg=round(sum(weekly.values()) / weeks_played, 2) if weeks_played else 0.0,
        top_quarter_avg=round(sum(top_quarter) / len(top_quarter), 2) if top_quarter else 0.0,
        total_fpts=round(sum(per_game), 2),
        weeks_played=weeks_played,
        season_weeks=season_weeks,
        availability=round(weeks_played / season_weeks, 3) if season_weeks else 0.0,
        stat_averages=stat_averages,
        bonus_fpts_per_game=round(sum(s.bonus_points for s in scores) / games, 2) if games else 0.0,
        bonus_counts=bonus_counts,
        minutes_avg=round(sum(g.minutes for g in ordered) / games, 1) if games else 0.0,
        teams_played_for=teams,
    )


def valuate_all(
    logs: Mapping[int, Iterable[GameLine]],
    settings: ScoringSettings,
    stats_season: str,
    player_ids: Iterable[int] | None = None,
) -> dict[int, PlayerValuation]:
    materialized = {pid: list(lines) for pid, lines in logs.items()}
    season_start, season_weeks = season_span(materialized)
    ids = list(player_ids) if player_ids is not None else list(materialized.keys())
    return {
        pid: valuate(pid, stats_season, materialized.get(pid, []), settings, season_start, season_weeks or None)
        for pid in ids
    }


def confidence_factor(games_played: int, min_games: int) -> float:
    if min_games <= 0:
        return 1.0
    return max(0.0, min(1.0, games_played / min_games))


def ceiling_value(valuation: PlayerValuation, ranking: RankingSettings) -> float:
    if ranking.ceiling_metric == "best_game":
        return valuation.best_game_fpts
    if ranking.ceiling_metric == "top_quarter":
        return valuation.top_quarter_avg
    return valuation.weekly_best_avg


# A player with no games last season (rookie, season-long injury) tells us nothing about how often he plays,
# so he gets the typical availability of players who did play (median of 8+ FP/G players, 2025-26) instead of 0.
NO_GAMES_AVAILABILITY = 0.88


def availability_factor(valuation: PlayerValuation, ranking: RankingSettings) -> float:
    w = max(0.0, min(1.0, ranking.availability_weight))
    if w == 0 or valuation.season_weeks == 0:
        return 1.0
    # No games last season: a veteran's 3-season blend (missed season = 0) still applies; only a player with no
    # earlier NBA seasons (rookie) falls back to the typical availability.
    no_history = valuation.games_played == 0 and len(valuation.availability_seasons) <= 1
    availability = NO_GAMES_AVAILABILITY if no_history else valuation.availability
    return 1.0 - w * (1.0 - availability)


def blended_value(valuation: PlayerValuation, ranking: RankingSettings) -> float:
    """Weighted FP/G + ceiling blend scaled by games-played confidence and (optionally) availability.
    Injury, age and eligibility modifiers are applied on top of this by the draft engine's ranker."""
    raw = ranking.weight_avg * valuation.avg_fpts + ranking.weight_ceiling * ceiling_value(valuation, ranking)
    return raw * confidence_factor(valuation.games_played, ranking.min_games_full_confidence) * availability_factor(valuation, ranking)


# Availability over three seasons, most recent first: one injured season no longer prices a player like a
# chronically injured one, while a player who misses time every year stays penalized.
AVAILABILITY_SEASON_WEIGHTS = (0.5, 0.3, 0.2)


def season_week_shares(game_dates: dict[int, list[str]]) -> dict[int, float]:
    """Share of the season's fantasy weeks (Mon-Sun) in which each player played at least one game."""
    all_dates = [date.fromisoformat(d) for ds in game_dates.values() for d in ds]
    if not all_dates:
        return {}
    start = monday_of(min(all_dates))
    weeks = week_index(max(all_dates), start) + 1
    return {pid: round(len({week_index(date.fromisoformat(d), start) for d in ds}) / weeks, 3) for pid, ds in game_dates.items()}


LOST_SEASON = 0.5    # a season under this share of weeks counts as lost (one big injury)
DURABLE = 0.8        # ...and is a one-off when his other seasons average at least this


def forgiveness(age: float | None) -> float:
    """How much of a one-off lost season to forgive: all of it under 30, half at 32, a quarter from 34."""
    return 1.0 if age is None else min(1.0, max(0.25, (35 - age) / 6))


def blend_availability(shares: list[float | None], age: float | None = None) -> float:
    """Weighted mean of the seasons that count (None = before his NBA career / unknown), weights renormalized.
    With his age: one lost season from an otherwise durable player is pulled toward his usual share by
    forgiveness(age); two lost seasons, or a weak record otherwise, is a pattern and stays as it is."""
    lost = [i for i, s in enumerate(shares) if s is not None and s < LOST_SEASON]
    others = [s for i, s in enumerate(shares) if s is not None and i not in lost]
    if age is not None and len(lost) == 1 and others and round(sum(others) / len(others), 3) >= DURABLE:
        usual = sum(others) / len(others)
        shares = list(shares)
        shares[lost[0]] += forgiveness(age) * (usual - shares[lost[0]])
    pairs = [(w, s) for w, s in zip(AVAILABILITY_SEASON_WEIGHTS, shares) if s is not None]
    total = sum(w for w, _ in pairs)
    return round(sum(w * s for w, s in pairs) / total, 3) if total else 0.0
