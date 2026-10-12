"""Rank available players for one manager.

value = (w_avg × FP/G + w_ceiling × ceiling) × confidence(games) × availability × injury multiplier × age multiplier
FP/G    = projection_weight × projected FP/G (Sleeper) + (1 − projection_weight) × last season's FP/G
ceiling = average of each week's best game by default (Lock-In), or the single best game / top-quarter average,
          scaled by FP/G ÷ last season's FP/G so a growing role lifts the ceiling too. The weekly-best ceiling's
          edge over FP/G is also scaled by the team's schedule (games per week, playoff weeks double).
scarcity: value + (average replacement level − replacement level at the player's scarcest position), where a
          position's replacement level is its best player left once every team's starting slots are filled.
A player with a projection but no game logs (rookie, missed season) uses the projection alone at full confidence.
Players who cannot fill any of the manager's open slots sink to the bottom (or are hidden by the UI).
Everything is pure: re-running after a pick, an override edit, or a settings change re-sorts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, RankingSettings
from types import SimpleNamespace

from nba_fantasy_shared.models.players import PlayerOverrides, PlayerRecord, PlayerValuation
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.scoring import availability_factor, base_points, ceiling_value, confidence_factor

from . import roster


@dataclass
class RankedPlayer:
    player_id: int
    full_name: str
    sleeper_id: str | None
    team_abbr: str | None
    eligibility: list[str]
    eligibility_source: str
    injury_status: str
    injury_note: str
    age: float | None
    games_played: int
    avg_fpts: float
    proj_fpts: float | None
    last_fpts: float
    proj_min: float | None      # Sleeper's projected minutes per game
    last_min: float | None      # last season's minutes per game
    owned_pct: float | None     # % of Sleeper leagues with him on a roster
    schedule_factor: float      # Lock-In schedule vs an average team (1.0 = average)
    scarcity: float             # FP added (or taken) for position scarcity
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


# Sleeper projection stat keys -> GameLine attribute names used by the scoring formula.
PROJECTION_KEYS = {"pts": "pts", "reb": "reb", "ast": "ast", "stl": "stl", "blk": "blk", "tov": "to",
                   "fgm": "fgm", "fga": "fga", "ftm": "ftm", "fg3m": "tpm"}
# ponytail: one league-wide ceiling/avg ratio for players with no game logs; per-position ratios if it matters.
NO_HISTORY_CEILING_RATIO = 1.3


def projected_fpts(record: PlayerRecord, valuation: PlayerValuation | None, scoring: ScoringSettings | None) -> float | None:
    """Projected FP/G: base scoring on Sleeper's per-game projection, plus last season's bonus rate."""
    if not record.projection or scoring is None:
        return None
    line = SimpleNamespace(**{attr: record.projection.get(key, 0.0) for attr, key in PROJECTION_KEYS.items()})
    bonus = valuation.bonus_fpts_per_game if valuation else 0.0
    return base_points(line, scoring.base) + bonus


def expected_fpts(
    record: PlayerRecord, valuation: PlayerValuation | None, ranking: RankingSettings, scoring: ScoringSettings | None,
    schedule_factor: float = 1.0,
) -> tuple[float, float]:
    """Returns (FP/G used for ranking, ceiling scaled to match)."""
    avg, ceiling = _expected_fpts(record, valuation, ranking, scoring)
    if ranking.ceiling_metric == "weekly_best" and schedule_factor != 1.0:
        w = min(1.0, max(0.0, ranking.schedule_weight))
        ceiling = avg + (ceiling - avg) * (1 + w * (schedule_factor - 1))
    return avg, ceiling


def _expected_fpts(
    record: PlayerRecord, valuation: PlayerValuation | None, ranking: RankingSettings, scoring: ScoringSettings | None
) -> tuple[float, float]:
    proj = projected_fpts(record, valuation, scoring)
    last = valuation.avg_fpts if valuation else 0.0
    if proj is None:
        return last, ceiling_value(valuation, ranking) if valuation else 0.0
    if not valuation or last <= 0:
        return proj, proj * NO_HISTORY_CEILING_RATIO
    w = min(1.0, max(0.0, ranking.projection_weight))
    avg = w * proj + (1 - w) * last
    return avg, ceiling_value(valuation, ranking) * avg / last


# Expected best of N games, in standard deviations above a player's mean (max of N normal draws).
BEST_OF_N = {1: 0.0, 2: 0.564, 3: 0.846, 4: 1.029, 5: 1.163, 6: 1.267}
PLAYOFF_WEEK_WEIGHT = 2.0   # a fantasy playoff week decides more than a regular-season week


def schedule_factors(games: Mapping[str, Mapping[str, int]], weeks: Iterable[int], playoff_weeks: Iterable[int] = ()) -> dict[str, float]:
    """Each team's Lock-In schedule edge: average best-of-N over the fantasy weeks, divided by the league average.

    Weeks where a team has no game yet (NBA Cup knockouts still to be scheduled) are skipped.
    """
    playoff = set(playoff_weeks)
    edge: dict[str, float] = {}
    for team, by_week in games.items():
        num = den = 0.0
        for w in weeks:
            n = by_week.get(str(w), 0)
            if n <= 0:
                continue
            weight = PLAYOFF_WEEK_WEIGHT if w in playoff else 1.0
            num += weight * BEST_OF_N[min(n, 6)]
            den += weight
        if den:
            edge[team] = num / den
    mean = sum(edge.values()) / len(edge) if edge else 0.0
    return {t: e / mean for t, e in edge.items()} if mean > 0 else {}


def scarcity_bonus(
    values: Mapping[int, float], eligibility: Mapping[int, list[str]], league: LeagueSettings,
) -> dict[int, float]:
    """FP to add per player for position scarcity (see module docstring); none for players with no position.

    ponytail: static over the whole pool, like the replacement level; recompute from the available pool
    during the draft if positions drain unevenly.
    """
    w = min(1.0, max(0.0, league.ranking.scarcity_weight))
    caps = roster.slot_capacity(league)
    remaining = {s: n * league.num_managers for s, n in caps.items() if s not in ("BN", "IR")}
    total = dict(remaining)
    if not w or not remaining:
        return {}
    placed: set[int] = set()
    for pid, _ in sorted(values.items(), key=lambda kv: -kv[1]):
        if not any(remaining.values()):
            break
        open_ = [s for s in roster.candidate_slots(eligibility.get(pid, [])) if remaining.get(s, 0) > 0]
        if not open_:
            continue
        # Position slots before UTIL, then the emptiest one, so a PG/SG fills whichever guard spot is shorter.
        slot = max(open_, key=lambda s: (s != "UTIL", remaining[s] / total[s]))
        remaining[slot] -= 1
        placed.add(pid)
    positions = [p for p in roster.POSITION_SLOTS if p in total]
    repl = {p: max((v for pid, v in values.items() if pid not in placed and p in eligibility.get(pid, [])), default=0.0)
            for p in positions}
    if not repl:
        return {}
    mean = sum(repl.values()) / len(repl)
    out = {}
    for pid in values:
        mine = [repl[p] for p in eligibility.get(pid, []) if p in repl]
        if mine:
            out[pid] = w * (mean - min(mine))
    return out


def player_value(
    record: PlayerRecord,
    override: PlayerOverrides | None,
    valuation: PlayerValuation | None,
    ranking: RankingSettings,
    scoring: ScoringSettings | None = None,
    schedule_factor: float = 1.0,
) -> tuple[float, float, float, float, float, float]:
    """Returns (value, blended, confidence, injury_mult, age_mult, availability_mult)."""
    avg, ceiling = expected_fpts(record, valuation, ranking, scoring, schedule_factor)
    blended = ranking.weight_avg * avg + ranking.weight_ceiling * ceiling
    has_projection = projected_fpts(record, valuation, scoring) is not None
    if valuation is None:
        confidence, avail = (1.0 if has_projection else 0.0), 1.0
    else:
        # A projection already accounts for a short sample, so it lifts the games-played discount.
        confidence = 1.0 if has_projection else confidence_factor(valuation.games_played, ranking.min_games_full_confidence)
        avail = availability_factor(valuation, ranking)
    inj = injury_multiplier(override.injury_status if override else "healthy", ranking)
    age = age_multiplier(record.bio.age, ranking)
    if has_projection:
        # The projection already prices in age; the penalty only applies to the last-season share of FP/G.
        w = min(1.0, max(0.0, ranking.projection_weight)) if valuation is not None else 1.0
        age = 1.0 - (1.0 - age) * (1.0 - w)
    return blended * confidence * avail * inj * age, blended, confidence, inj, age, avail


def pool_values(
    players: Mapping[int, PlayerRecord],
    overrides: Mapping[int, PlayerOverrides],
    valuations: Mapping[int, PlayerValuation],
    ranking: RankingSettings,
    scoring: ScoringSettings | None = None,
    schedule: Mapping[str, float] | None = None,
) -> dict[int, float]:
    """Roster-independent value of every player in the pool (drafted or not), before position scarcity."""
    schedule = schedule or {}
    return {
        pid: player_value(rec, overrides.get(pid), valuations.get(pid), ranking, scoring, schedule.get(rec.team_abbr or "", 1.0))[0]
        for pid, rec in players.items()
    }


TIER_DROP = 0.94  # a new tier starts once a player is 6 % below the best player of the current tier


def tiers(values: Mapping[int, float], drop: float = TIER_DROP) -> dict[int, int]:
    """Tier number (1 = best) for every player, from the whole pool so tiers stay put as players are drafted."""
    out: dict[int, int] = {}
    tier, top = 0, None
    for pid, v in sorted(values.items(), key=lambda kv: -kv[1]):
        if top is None or v < top * drop:
            tier, top = tier + 1, v
        out[pid] = tier
    return out


def rank_players(
    league: LeagueSettings,
    players: Mapping[int, PlayerRecord],
    overrides: Mapping[int, PlayerOverrides],
    valuations: Mapping[int, PlayerValuation],
    my_picks: Iterable[Pick],
    available_ids: Iterable[int],
    schedule: Mapping[str, float] | None = None,
    scarcity: Mapping[int, float] | None = None,
) -> list[RankedPlayer]:
    schedule, scarcity = schedule or {}, scarcity or {}
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
        sched = schedule.get(rec.team_abbr or "", 1.0)
        value, blended, confidence, inj, age_mult, avail = player_value(rec, override, valuation, ranking, league.scoring, sched)
        bonus = scarcity.get(pid, 0.0)
        value = max(0.0, value + bonus)
        avg, ceiling = expected_fpts(rec, valuation, ranking, league.scoring, sched)
        proj = projected_fpts(rec, valuation, league.scoring)
        eligibility = list(override.eligibility) if override else []
        slot = roster.assign_slot(league, my_picks, eligibility)
        rows.append(
            RankedPlayer(
                player_id=pid,
                full_name=rec.full_name,
                sleeper_id=rec.sleeper_id,
                team_abbr=rec.team_abbr,
                eligibility=eligibility,
                eligibility_source=override.eligibility_source if override else "none",
                injury_status=override.injury_status if override else "healthy",
                injury_note=override.injury_note if override else "",
                age=rec.bio.age,
                games_played=valuation.games_played if valuation else 0,
                avg_fpts=round(avg, 2),
                proj_fpts=round(proj, 2) if proj is not None else None,
                last_fpts=valuation.avg_fpts if valuation else 0.0,
                proj_min=round(rec.projection["sp"] / 60, 1) if rec.projection and rec.projection.get("sp") else None,
                last_min=valuation.minutes_avg if valuation else None,
                owned_pct=rec.projection.get("owned") if rec.projection else None,
                schedule_factor=round(sched, 3),
                scarcity=round(bonus, 2),
                best_game_fpts=valuation.best_game_fpts if valuation else 0.0,
                weekly_best_avg=valuation.weekly_best_avg if valuation else 0.0,
                top_quarter_avg=valuation.top_quarter_avg if valuation else 0.0,
                total_fpts=valuation.total_fpts if valuation else 0.0,
                availability=valuation.availability if valuation else 0.0,
                weeks_played=valuation.weeks_played if valuation else 0,
                ceiling=round(ceiling, 2),
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
