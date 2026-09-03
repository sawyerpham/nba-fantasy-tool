"""Per-game fantasy points: base stat values plus per-game bonus rules (bonuses stack).

fpts(game) = sum(base[stat] * game[stat]) + sum(rule.bonus for every rule the game meets)

A 52-point game meets both the 40+ and the 50+ rule and earns both bonuses (decision 4).
A triple-double is 10+ in any three of pts / reb / ast / stl / blk; a quadruple-double still counts once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models.players import GameLine
from ..models.scoring import BaseScoring, BonusRule, ScoringSettings

TRIPLE_DOUBLE_STATS: tuple[str, ...] = ("pts", "reb", "ast", "stl", "blk")


@dataclass(frozen=True)
class GameScore:
    fpts: float
    base_points: float
    bonus_points: float
    bonuses_hit: tuple[str, ...] = field(default_factory=tuple)


def base_points(line: GameLine, base: BaseScoring) -> float:
    return (
        base.pts * line.pts
        + base.reb * line.reb
        + base.ast * line.ast
        + base.stl * line.stl
        + base.blk * line.blk
        + base.tov * line.tov
        + base.fgm * line.fgm
        + base.fga * line.fga
        + base.ftm * line.ftm
        + base.fg3m * line.fg3m
    )


def double_digit_categories(line: GameLine) -> int:
    return sum(1 for stat in TRIPLE_DOUBLE_STATS if getattr(line, stat) >= 10)


def is_triple_double(line: GameLine) -> bool:
    return double_digit_categories(line) >= 3


def rule_hits(line: GameLine, rule: BonusRule) -> bool:
    if rule.kind == "triple_double":
        return is_triple_double(line)
    if rule.kind == "stat_threshold":
        if rule.stat is None or rule.threshold is None:
            return False
        return getattr(line, rule.stat) >= rule.threshold
    return False


def score_game(line: GameLine, settings: ScoringSettings) -> GameScore:
    base = base_points(line, settings.base)
    hit = tuple(rule.id for rule in settings.bonuses if rule_hits(line, rule))
    bonus = sum(rule.bonus for rule in settings.bonuses if rule.id in hit)
    return GameScore(fpts=base + bonus, base_points=base, bonus_points=bonus, bonuses_hit=hit)
