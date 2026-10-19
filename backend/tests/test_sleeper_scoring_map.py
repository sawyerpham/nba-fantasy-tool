"""Sleeper scoring-key map: mapped values, unknown/unsupported/missing reporting."""

import json

from nba_fantasy_shared.models.scoring import BaseScoring, ScoringSettings
from nba_fantasy_shared.providers.sleeper_provider import platform_league_from_json
from nba_fantasy_shared.scoring import map_sleeper_scoring
from nba_fantasy_shared.scoring.sleeper_scoring_map import EXPECTED_KEYS


def load(fixtures_dir, rel):
    with (fixtures_dir / rel).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_provisional_nba_fixture_maps_exactly_onto_spec_defaults(fixtures_dir):
    raw = load(fixtures_dir, "sleeper/league_nba_provisional.json")
    assert "PROVISIONAL" in raw["_fixture_note"]  # hand-written, not a captured response
    league = platform_league_from_json(raw)
    assert league.sport == "nba" and league.roster_positions.count("BN") == 8 and league.roster_positions.count("IR") == 2

    result = map_sleeper_scoring(league.scoring_settings)
    assert result.provisional is False
    assert result.clean, (result.unknown_keys, result.unsupported_nonzero, result.missing_expected)
    assert result.settings.source == "sleeper"
    assert result.settings.base == BaseScoring()
    default = ScoringSettings()
    assert [(r.id, r.kind, r.stat, r.threshold, r.bonus) for r in result.settings.bonuses] == \
        [(r.id, r.kind, r.stat, r.threshold, r.bonus) for r in default.bonuses]
    assert result.settings.scoring_hash() == default.scoring_hash()  # identical values -> identical valuation cache
    assert result.applied["to"] == "base.tov" and result.applied["tpm"] == "base.fg3m" and result.applied["td"] == "bonus.triple_double"


def test_real_nba_league_keys_map_cleanly():
    # the real league's scoring_settings (2026-10-19): bonuses carry a "p" suffix; ff / tf are fouls scored 0
    real = {"ast": 0.5, "blk": 0.75, "bonus_ast_15p": 4.0, "bonus_pt_40p": 4.0, "bonus_pt_50p": 1.0, "bonus_reb_20p": 4.0,
            "fga": -0.1, "fgm": 0.25, "ftm": 0.05, "pts": 0.25, "reb": 0.4, "stl": 0.75, "td": 2.0, "to": -0.5, "tpm": 0.3,
            "ff": 0.0, "tf": 0.0}
    result = map_sleeper_scoring(real)
    assert result.clean, (result.unknown_keys, result.unsupported_nonzero, result.missing_expected)
    assert result.settings.scoring_hash() == ScoringSettings().scoring_hash()   # same as the SPEC defaults


def test_unknown_keys_are_reported_not_ignored():
    result = map_sleeper_scoring({"pts": 0.25, "some_new_key": 3.0, "another": 0.0})
    assert result.unknown_keys == ["some_new_key", "another"]
    assert not result.clean


def test_unsupported_categories_reported_only_when_nonzero():
    result = map_sleeper_scoring({"pts": 0.25, "dd": 1.5, "fta": 0.0, "oreb": 0.0})
    assert result.unsupported_nonzero == {"dd": 1.5}
    assert result.unknown_keys == []


def test_missing_expected_keys_are_listed():
    result = map_sleeper_scoring({})
    assert result.missing_expected == list(EXPECTED_KEYS)
    assert result.settings.bonuses == []


def test_dynamic_bonus_thresholds_are_parsed():
    result = map_sleeper_scoring({"bonus_stl_5": 2.0, "bonus_pts_30": 1.5, "bonus_blk_5": 2.5})
    rules = {r.id: r for r in result.settings.bonuses}
    assert rules["stl_5"].stat == "stl" and rules["stl_5"].threshold == 5 and rules["stl_5"].bonus == 2.0
    assert rules["pts_30"].stat == "pts" and rules["pts_30"].threshold == 30
    assert rules["blk_5"].bonus == 2.5
    assert result.unknown_keys == []


def test_values_override_spec_defaults():
    result = map_sleeper_scoring({"pts": 1.0, "reb": 1.2, "td": 5.0, "bonus_pt_40": 0.0})
    assert result.settings.base.pts == 1.0 and result.settings.base.reb == 1.2
    assert result.settings.base.ast == BaseScoring().ast  # untouched keys keep SPEC defaults
    rules = {r.id: r for r in result.settings.bonuses}
    assert rules["triple_double"].bonus == 5.0 and rules["pts_40"].bonus == 0.0


def test_nfl_league_is_mostly_unknown_keys(fixtures_dir):
    league = platform_league_from_json(load(fixtures_dir, "sleeper/league_289646328504385536.json"))
    assert league.sport == "nfl"
    result = map_sleeper_scoring(league.scoring_settings)
    assert len(result.unknown_keys) > 20 and not result.clean  # callers must gate on sport == "nba" first
