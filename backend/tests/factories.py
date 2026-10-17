"""Small synthetic worlds for engine tests."""

from __future__ import annotations

from datetime import datetime, timezone

from nba_fantasy_shared.models.draft import DraftState, KeeperHistory
from nba_fantasy_shared.models.league import KeeperSettings, LeagueSettings, Manager, ManagerBehavior, RosterSlotSpec
from nba_fantasy_shared.models.players import PlayerBio, PlayerOverrides, PlayerRecord, PlayerValuation
from nba_fantasy_shared.reconcile.names import normalize_name

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def bio(pid: int, name: str, team: str | None, age: float | None = 27.0) -> PlayerBio:
    first, last = name.split(" ", 1)
    return PlayerBio(source="nba_api", source_id=str(pid), full_name=name, first_name=first, last_name=last,
                     normalized_name=normalize_name(name), team_abbr=team, age=age, fetched_at=NOW)


def record(pid: int, name: str, team: str | None = "DEN", age: float | None = 27.0, has_stats: bool = True) -> PlayerRecord:
    first, last = name.split(" ", 1)
    return PlayerRecord(player_id=pid, full_name=name, first_name=first, last_name=last, normalized_name=normalize_name(name),
                        team_abbr=team, bio=bio(pid, name, team, age), match_method="name_team", has_stats=has_stats)


def override(pid: int, eligibility: list[str], injury: str = "healthy", source: str = "sleeper") -> PlayerOverrides:
    return PlayerOverrides(player_id=pid, eligibility=eligibility, eligibility_source=source,  # type: ignore[arg-type]
                           injury_status=injury, injury_source=source, updated_at=NOW)  # type: ignore[arg-type]


def valuation(pid: int, avg: float, best: float, gp: int = 65, wk_best: float | None = None, weeks: int = 22) -> PlayerValuation:
    """Synthetic valuation. wk_best defaults to `best` so ordering by ceiling matches the single-best-game view."""
    return PlayerValuation(player_id=pid, stats_season="2025-26", games_played=gp, per_game_fpts=[], avg_fpts=avg,
                           best_game_fpts=best, weekly_best_avg=best if wk_best is None else wk_best, top_quarter_avg=best,
                           total_fpts=avg * gp, weeks_played=weeks, season_weeks=25, availability=round(weeks / 25, 3),
                           bonus_counts={}, minutes_avg=30.0, teams_played_for=["DEN"])


def small_league(num_managers: int = 3, budget: int = 50, **kw) -> LeagueSettings:
    """PG, SG, C, UTIL, BN×2 (6 mandatory) + 1 IR; $50 budgets."""
    defaults = dict(
        league_id="test", name="Test", num_managers=num_managers, budget_per_manager=budget, min_bid=1,
        roster_slots=[RosterSlotSpec(slot="PG", count=1), RosterSlotSpec(slot="SG", count=1), RosterSlotSpec(slot="C", count=1),
                      RosterSlotSpec(slot="UTIL", count=1), RosterSlotSpec(slot="BN", count=2), RosterSlotSpec(slot="IR", count=1)],
    )
    defaults.update(kw)
    return LeagueSettings(**defaults)


def managers(n: int = 3, budget: int = 50, user_index: int = 0, behaviors: dict[int, ManagerBehavior] | None = None) -> list[Manager]:
    return [
        Manager(manager_id=f"m{i + 1}", name=f"Manager {i + 1}", is_user=(i == user_index), budget_total=budget,
                behavior=(behaviors or {}).get(i, ManagerBehavior()))
        for i in range(n)
    ]


# (pid, name, team, eligibility, avg, best, gp, age, injury)
PlayerSpec = tuple[int, str, str, list[str], float, float, int, float, str]


def world(specs: list[PlayerSpec]):
    players = {s[0]: record(s[0], s[1], s[2], age=s[7]) for s in specs}
    overrides = {s[0]: override(s[0], s[3], injury=s[8]) for s in specs}
    valuations = {s[0]: valuation(s[0], s[4], s[5], gp=s[6]) for s in specs}
    return players, overrides, valuations


def default_world() -> tuple[dict, dict, dict]:
    """12 players: enough for a 3-manager × 6-slot draft with spares, varied positions and values."""
    specs: list[PlayerSpec] = [
        (1, "Ace Center", "DEN", ["C"], 40.0, 60.0, 65, 27.0, "healthy"),
        (2, "Bo Guard", "DEN", ["PG", "SG"], 36.0, 55.0, 70, 26.0, "healthy"),
        (3, "Cy Wing", "LAL", ["SF", "PF"], 30.0, 50.0, 60, 30.0, "healthy"),
        (4, "Dee Point", "LAL", ["PG"], 28.0, 45.0, 66, 24.0, "healthy"),
        (5, "Ed Two", "BOS", ["SG", "SF"], 25.0, 40.0, 72, 33.0, "healthy"),
        (6, "Fay Big", "BOS", ["C", "PF"], 22.0, 38.0, 50, 29.0, "day_to_day"),
        (7, "Gus Bench", "MIA", ["PG", "SG"], 18.0, 30.0, 80, 22.0, "healthy"),
        (8, "Hal Bench", "MIA", ["SF"], 15.0, 28.0, 75, 35.0, "healthy"),
        (9, "Ike Bench", "PHX", ["C"], 12.0, 24.0, 40, 28.0, "healthy"),
        (10, "Jo Spare", "PHX", ["PF"], 10.0, 20.0, 82, 31.0, "healthy"),
        (11, "Kai Spare", "OKC", ["SG"], 8.0, 15.0, 30, 21.0, "healthy"),
        (12, "Lou Rookie", "OKC", ["PG"], 30.0, 70.0, 3, 20.0, "healthy"),  # tiny sample, huge ceiling
    ]
    return world(specs)


def fresh_draft() -> DraftState:
    return DraftState()


def no_history() -> KeeperHistory:
    return KeeperHistory()


__all__ = ["NOW", "KeeperSettings", "bio", "record", "override", "valuation", "small_league", "managers", "world",
           "default_world", "fresh_draft", "no_history"]
