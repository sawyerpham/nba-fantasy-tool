"""Season aggregation of per-game fantasy points into a PlayerValuation, plus the value blend.

avg_fpts       mean of per-game fantasy points (season-long value, realized bonus frequency included)
best_game_fpts max single game (Lock-In ceiling: one game per week counts)
confidence     min(1, games_played / min_games) so a tiny sample cannot out-rank a full season (decision 5)
"""

from __future__ import annotations

from typing import Iterable, Mapping

from ..models.league import RankingSettings
from ..models.players import GameLine, PlayerValuation
from ..models.scoring import ScoringSettings
from .formula import score_game


def valuate(player_id: int, stats_season: str, lines: Iterable[GameLine], settings: ScoringSettings) -> PlayerValuation:
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
    return PlayerValuation(
        player_id=player_id,
        stats_season=stats_season,
        games_played=games,
        per_game_fpts=per_game,
        avg_fpts=round(sum(per_game) / games, 2) if games else 0.0,
        best_game_fpts=max(per_game) if games else 0.0,
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
    ids = list(player_ids) if player_ids is not None else list(logs.keys())
    return {pid: valuate(pid, stats_season, logs.get(pid, []), settings) for pid in ids}


def confidence_factor(games_played: int, min_games: int) -> float:
    if min_games <= 0:
        return 1.0
    return max(0.0, min(1.0, games_played / min_games))


def blended_value(valuation: PlayerValuation, ranking: RankingSettings) -> float:
    """Weighted avg/ceiling blend scaled by the games-played confidence. Injury, age and eligibility
    modifiers are applied on top of this by the draft engine's ranker."""
    raw = ranking.weight_avg * valuation.avg_fpts + ranking.weight_ceiling * valuation.best_game_fpts
    return raw * confidence_factor(valuation.games_played, ranking.min_games_full_confidence)
