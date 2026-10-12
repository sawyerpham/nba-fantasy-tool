"""Map a Sleeper league's flat `scoring_settings` dict onto ScoringSettings.

PROVISIONAL: the NBA key names below are Sleeper's conventional names as best known; they have NOT
been verified against a real NBA league (no sleeper_league_id was available, decision 11). Sleeper's
docs and the only public example league are NFL. Every key that is not recognised is reported in
`unknown_keys`; recognised-but-unsupported categories with a non-zero value are reported in
`unsupported_nonzero`; expected keys that are absent are reported in `missing_expected`.
Nothing is silently ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from ..models.scoring import BaseScoring, BonusRule, ScoringSettings

PROVISIONAL = True

# Sleeper key -> BaseScoring field. All provisional.
BASE_KEYS: dict[str, str] = {
    "pts": "pts",
    "reb": "reb",
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "to": "tov",
    "fgm": "fgm",
    "fga": "fga",
    "ftm": "ftm",
    "tpm": "fg3m",
}

# Recognised Sleeper NBA categories that ScoringSettings does not model (SPEC.md scores 10 base stats).
UNSUPPORTED_KEYS: frozenset[str] = frozenset(
    {"fta", "tpa", "oreb", "dreb", "pf", "min", "fgmi", "ftmi", "tpmi", "dd", "qd", "ejection", "tech", "flagrant"}
)

TRIPLE_DOUBLE_KEY = "td"

# bonus_pt_40 / bonus_ast_15 / bonus_reb_20 / bonus_stl_5 ... -> stat_threshold rules
# A real NBA league (2026-10-11) names them with a "p" suffix: bonus_pt_40p, bonus_ast_15p, bonus_reb_20p.
_BONUS_PATTERN = re.compile(r"^bonus_(pt|pts|reb|ast|stl|blk)_(\d+)p?$")
_BONUS_STAT = {"pt": "pts", "pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk"}

EXPECTED_KEYS: tuple[str, ...] = tuple(BASE_KEYS) + (
    TRIPLE_DOUBLE_KEY,
    "bonus_pt_40",
    "bonus_pt_50",
    "bonus_ast_15",
    "bonus_reb_20",
)


@dataclass
class SleeperScoringMapResult:
    settings: ScoringSettings
    applied: dict[str, str] = field(default_factory=dict)          # sleeper key -> "base.pts" / "bonus.pts_40"
    unknown_keys: list[str] = field(default_factory=list)
    unsupported_nonzero: dict[str, float] = field(default_factory=dict)
    missing_expected: list[str] = field(default_factory=list)
    provisional: bool = PROVISIONAL
    note: str = (
        "Sleeper NBA scoring key names are provisional: not yet verified against a real NBA league. "
        "Review 'applied', 'unknown_keys' and 'unsupported_nonzero' before trusting the mapped values."
    )

    @property
    def clean(self) -> bool:
        return not self.unknown_keys and not self.unsupported_nonzero and not self.missing_expected


def map_sleeper_scoring(scoring_settings: Mapping[str, float]) -> SleeperScoringMapResult:
    base = BaseScoring()
    bonuses: list[BonusRule] = []
    result = SleeperScoringMapResult(settings=ScoringSettings(base=base, bonuses=bonuses, source="sleeper"))

    seen_bonus_ids: set[str] = set()
    for key, raw in scoring_settings.items():
        value = float(raw) if raw is not None else 0.0
        if key in BASE_KEYS:
            setattr(base, BASE_KEYS[key], value)
            result.applied[key] = f"base.{BASE_KEYS[key]}"
            continue
        if key == TRIPLE_DOUBLE_KEY:
            bonuses.append(BonusRule(id="triple_double", kind="triple_double", bonus=value))
            seen_bonus_ids.add("triple_double")
            result.applied[key] = "bonus.triple_double"
            continue
        match = _BONUS_PATTERN.match(key)
        if match:
            stat = _BONUS_STAT[match.group(1)]
            threshold = int(match.group(2))
            rule_id = f"{stat}_{threshold}"
            bonuses.append(BonusRule(id=rule_id, kind="stat_threshold", stat=stat, threshold=threshold, bonus=value))
            seen_bonus_ids.add(rule_id)
            result.applied[key] = f"bonus.{rule_id}"
            continue
        if key in UNSUPPORTED_KEYS:
            if value != 0.0:
                result.unsupported_nonzero[key] = value
            continue
        result.unknown_keys.append(key)

    result.missing_expected = [k for k in EXPECTED_KEYS if k not in scoring_settings]
    # Keep the SPEC rule order for the well-known bonuses so hashes stay stable across sources.
    order = {"triple_double": 0, "pts_40": 1, "pts_50": 2, "ast_15": 3, "reb_20": 4}
    bonuses.sort(key=lambda r: (order.get(r.id, 99), r.id))
    result.settings = ScoringSettings(base=base, bonuses=bonuses, source="sleeper")
    return result
