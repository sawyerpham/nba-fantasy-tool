"""Per-game scoring formula, bonus rules (each individually), stacking, and season aggregation."""

import json
from datetime import date

import pytest

from nba_fantasy_shared.models.league import RankingSettings
from nba_fantasy_shared.models.players import GameLine, PlayerValuation
from nba_fantasy_shared.models.scoring import BaseScoring, BonusRule, ScoringSettings
from nba_fantasy_shared.providers.nba_api_provider import game_line_from_row
from nba_fantasy_shared.scoring import (
    base_points,
    blended_value,
    confidence_factor,
    is_triple_double,
    score_game,
    valuate,
    valuate_all,
)

JOKIC = 203999
DEFAULT = ScoringSettings()


def line(game_id="1", game_date=date(2026, 1, 1), team="DEN", minutes=30.0, **stats) -> GameLine:
    base = dict(pts=0, reb=0, ast=0, stl=0, blk=0, tov=0, fgm=0, fga=0, ftm=0, fta=0, fg3m=0, fg3a=0, oreb=0, dreb=0, pf=0, plus_minus=0)
    base.update(stats)
    return GameLine(player_id=1, season="2025-26", game_id=game_id, game_date=game_date, team_abbr=team,
                    opponent_abbr="LAL", home=True, win=True, minutes=minutes, **base)


def only(rule_id: str) -> ScoringSettings:
    return ScoringSettings(bonuses=[r for r in DEFAULT.bonuses if r.id == rule_id])


# ---------------------------------------------------------------- base formula

def test_base_points_hand_computed_against_spec_values():
    g = line(pts=30, reb=10, ast=5, stl=2, blk=1, tov=3, fgm=11, fga=20, ftm=6, fg3m=2)
    expected = 30 * 0.25 + 10 * 0.4 + 5 * 0.5 + 2 * 0.75 + 1 * 0.75 + 3 * -0.5 + 11 * 0.25 + 20 * -0.1 + 6 * 0.05 + 2 * 0.3
    assert base_points(g, DEFAULT.base) == pytest.approx(expected) == pytest.approx(16.4)
    s = score_game(g, DEFAULT)
    assert s.bonuses_hit == () and s.bonus_points == 0 and s.fpts == pytest.approx(16.4)


def test_negative_categories_reduce_points():
    assert base_points(line(tov=4), DEFAULT.base) == pytest.approx(-2.0)
    assert base_points(line(fga=10), DEFAULT.base) == pytest.approx(-1.0)


def test_base_values_are_editable():
    custom = ScoringSettings(base=BaseScoring(pts=1.0, fga=0.0), bonuses=[])
    assert score_game(line(pts=20, fga=15), custom).fpts == pytest.approx(20.0)


# ---------------------------------------------------------------- each bonus rule individually

def test_triple_double_rule():
    s = score_game(line(pts=10, reb=10, ast=10), only("triple_double"))
    assert s.bonuses_hit == ("triple_double",) and s.bonus_points == 2.0
    assert score_game(line(pts=10, reb=10, ast=9), only("triple_double")).bonuses_hit == ()


def test_triple_double_counts_any_three_of_five_and_only_once_for_four():
    assert is_triple_double(line(pts=12, stl=10, blk=10))
    assert is_triple_double(line(reb=10, ast=10, blk=10))
    quad = score_game(line(pts=10, reb=10, ast=10, stl=10), only("triple_double"))
    assert quad.bonuses_hit == ("triple_double",) and quad.bonus_points == 2.0


def test_pts_40_rule():
    assert score_game(line(pts=40), only("pts_40")).bonus_points == 4.0
    assert score_game(line(pts=39), only("pts_40")).bonus_points == 0.0


def test_pts_50_rule():
    assert score_game(line(pts=50), only("pts_50")).bonus_points == 1.0
    assert score_game(line(pts=49), only("pts_50")).bonus_points == 0.0


def test_ast_15_rule():
    assert score_game(line(ast=15), only("ast_15")).bonus_points == 4.0
    assert score_game(line(ast=14), only("ast_15")).bonus_points == 0.0


def test_reb_20_rule():
    assert score_game(line(reb=20), only("reb_20")).bonus_points == 4.0
    assert score_game(line(reb=19), only("reb_20")).bonus_points == 0.0


def test_bonuses_stack_50_points_earns_40_and_50_bonus():
    s = score_game(line(pts=52), DEFAULT)
    assert s.bonuses_hit == ("pts_40", "pts_50") and s.bonus_points == 5.0
    assert s.fpts == pytest.approx(52 * 0.25 + 5.0)


def test_all_five_rules_can_stack_in_one_game():
    monster = line(pts=50, reb=20, ast=15, stl=1, blk=1)
    s = score_game(monster, DEFAULT)
    assert set(s.bonuses_hit) == {"triple_double", "pts_40", "pts_50", "ast_15", "reb_20"}
    assert s.bonus_points == 2 + 4 + 1 + 4 + 4


def test_thresholds_and_bonus_amounts_are_editable():
    custom = ScoringSettings(bonuses=[BonusRule(id="pts_35", kind="stat_threshold", stat="pts", threshold=35, bonus=10.0)])
    assert score_game(line(pts=36), custom).bonus_points == 10.0
    assert score_game(line(pts=34), custom).bonus_points == 0.0


# ---------------------------------------------------------------- aggregation

def test_valuate_average_ceiling_counts_and_team_history():
    games = [
        line("3", date(2026, 3, 1), "BKN", 36.0, pts=41, reb=5, ast=5),     # 10.25+2+2.5 + 4 = 18.75
        line("1", date(2025, 11, 1), "PHX", 30.0, pts=10, reb=10, ast=10),  # 2.5+4+5 + 2 = 13.5
        line("2", date(2025, 12, 1), "PHX", 24.0, pts=8, tov=2),            # 2 - 1 = 1.0
    ]
    v = valuate(1, "2025-26", games, DEFAULT)
    assert v.games_played == 3
    assert v.per_game_fpts == [13.5, 1.0, 18.75]  # chronological regardless of input order
    assert v.avg_fpts == pytest.approx(round((13.5 + 1.0 + 18.75) / 3, 2))
    assert v.best_game_fpts == 18.75
    assert v.bonus_counts == {"triple_double": 1, "pts_40": 1, "pts_50": 0, "ast_15": 0, "reb_20": 0}
    assert v.minutes_avg == 30.0
    assert v.teams_played_for == ["PHX", "BKN"]


def test_valuate_zero_games():
    v = valuate(1, "2025-26", [], DEFAULT)
    assert v.games_played == 0 and v.avg_fpts == 0.0 and v.best_game_fpts == 0.0 and v.per_game_fpts == []
    assert v.bonus_counts == {r.id: 0 for r in DEFAULT.bonuses}


def test_valuate_all_covers_requested_ids_even_without_logs():
    out = valuate_all({1: [line(pts=10)]}, DEFAULT, "2025-26", player_ids=[1, 2])
    assert out[1].games_played == 1 and out[2].games_played == 0


@pytest.mark.parametrize("gp, min_games, expected", [(0, 20, 0.0), (3, 20, 0.15), (10, 20, 0.5), (20, 20, 1.0), (65, 20, 1.0), (5, 0, 1.0)])
def test_confidence_factor(gp, min_games, expected):
    assert confidence_factor(gp, min_games) == pytest.approx(expected)


def test_blended_value_uses_weights_and_confidence():
    full = PlayerValuation(player_id=1, stats_season="2025-26", games_played=65, per_game_fpts=[], avg_fpts=50.0,
                           best_game_fpts=80.0, bonus_counts={}, minutes_avg=34.0, teams_played_for=["DEN"])
    small = full.model_copy(update={"games_played": 3, "avg_fpts": 60.0, "best_game_fpts": 95.0})
    ranking = RankingSettings()  # 0.6 / 0.4, min 20 games
    assert blended_value(full, ranking) == pytest.approx(0.6 * 50 + 0.4 * 80)
    assert blended_value(small, ranking) == pytest.approx((0.6 * 60 + 0.4 * 95) * 0.15)
    assert blended_value(small, ranking) < blended_value(full, ranking)  # 3-game sample cannot out-rank a full season
    standard = RankingSettings(weight_avg=1.0, weight_ceiling=0.0)
    assert blended_value(full, standard) == pytest.approx(50.0)


# ---------------------------------------------------------------- real data cross-checks

def load(fixtures_dir, rel):
    with (fixtures_dir / rel).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_jokic_2025_26_has_34_triple_doubles_matching_nba_com_td3(fixtures_dir):
    per_player_rows = load(fixtures_dir, "nba/playergamelog_203999_2025-26.json")
    lines = [game_line_from_row(r) for r in per_player_rows]
    v = valuate(JOKIC, "2025-26", lines, DEFAULT)
    assert v.games_played == 65
    assert v.bonus_counts["triple_double"] == 34

    batch_rows = [r for r in load(fixtures_dir, "nba/playergamelogs_2025-26.json") if r["PLAYER_ID"] == JOKIC]
    assert sum(r["TD3"] for r in batch_rows) == 34  # NBA.com's own count
    assert sum(1 for g in lines if is_triple_double(g)) == 34

    assert len(v.per_game_fpts) == 65
    assert v.best_game_fpts == max(v.per_game_fpts) >= v.avg_fpts > 0
    assert v.avg_fpts == pytest.approx(sum(v.per_game_fpts) / 65, abs=0.01)
    assert v.teams_played_for == ["DEN"]
    assert confidence_factor(v.games_played, 20) == 1.0


def test_traded_player_has_two_teams_in_history(fixtures_dir):
    rows = [r for r in load(fixtures_dir, "nba/playergamelogs_2025-26.json") if r["PLAYER_ID"] == 1630631]  # Jose Alvarado
    v = valuate(1630631, "2025-26", [game_line_from_row(r) for r in rows], DEFAULT)
    assert len(v.teams_played_for) == 2
