"""Orchestrates the pre-draft data pull: nba_api pool + Sleeper players -> reconcile -> game logs -> seed overrides.

Runs synchronously; the API layer wraps it in a thread and polls `status`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Iterable, Mapping

from nba_fantasy_shared.models.league import PlatformState
from nba_fantasy_shared.models.players import (
    FantasyAttributes,
    GameLine,
    InjuryStatus,
    PlayerBio,
    PlayerDetail,
    PlayerOverrides,
    PlayerRecord,
    ReconcileReport,
)
from nba_fantasy_shared.providers.base import (
    CallFailed,
    FantasyPlatformProvider,
    FetchProgress,
    FetchReport,
    StatsProvider,
    utcnow,
)
from nba_fantasy_shared.providers.sleeper_provider import sleeper_season_to_roster_season
from nba_fantasy_shared.reconcile import ReconcileInputs, reconcile, seed_overrides
from nba_fantasy_shared.storage import JsonStore

from ... import config

log = logging.getLogger(__name__)


@dataclass
class PullStatus:
    state: str = "idle"  # idle | running | done | failed
    phase: str = ""
    progress: FetchProgress | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reports: list[FetchReport] = field(default_factory=list)
    reconcile: ReconcileReport | None = None
    platform_state: PlatformState | None = None
    seeded_overrides: int = 0
    records: int = 0
    game_log_players: int = 0
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "phase": self.phase,
            "progress": self.progress.model_dump() if self.progress else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "reports": [r.model_dump(mode="json") for r in self.reports],
            "reconcile_counts": self.reconcile.counts if self.reconcile else None,
            "platform_state": self.platform_state.model_dump(mode="json") if self.platform_state else None,
            "seeded_overrides": self.seeded_overrides,
            "records": self.records,
            "game_log_players": self.game_log_players,
            "error": self.error,
        }


class PlayerDetailCache:
    """On-demand PlayerDetail fetch with on-disk cache; used for birthdate tiebreaks and the sidebar."""

    def __init__(self, store: JsonStore, stats: StatsProvider) -> None:
        self.store = store
        self.stats = stats

    def get(self, player_id: int) -> PlayerDetail | None:
        rel = config.player_detail_rel(player_id)
        cached = self.store.read_model_or_none(rel, PlayerDetail)
        if cached is not None:
            return cached
        try:
            detail = self.stats.fetch_player_detail(player_id)
        except (CallFailed, OSError, ValueError, KeyError) as exc:
            log.warning("player detail %s unavailable: %s: %s", player_id, type(exc).__name__, exc)
            return None
        self.store.write_model(rel, detail)
        return detail

    def birthdate(self, player_id: int) -> date | None:
        detail = self.get(player_id)
        return detail.birthdate if detail else None


def load_overrides(store: JsonStore) -> dict[int, PlayerOverrides]:
    if not store.exists(config.OVERRIDES_REL):
        return {}
    raw = store.read_json(config.OVERRIDES_REL)
    return {int(k): PlayerOverrides.model_validate(v) for k, v in raw.items()}


def save_overrides(store: JsonStore, overrides: Mapping[int, PlayerOverrides]) -> None:
    store.write_json(
        config.OVERRIDES_REL,
        {str(k): v.model_dump(mode="json") for k, v in sorted(overrides.items())},
    )


def load_records(store: JsonStore, roster_season: str) -> list[PlayerRecord]:
    rel = config.reconcile_rel(roster_season)
    if not store.exists(rel):
        return []
    return [PlayerRecord.model_validate(r) for r in store.read_json(rel)["records"]]


def load_projections(store: JsonStore, roster_season: str) -> dict[str, dict[str, float]]:
    rel = config.projections_rel(roster_season)
    return store.read_json(rel)["projections"] if store.exists(rel) else {}


def load_schedule(store: JsonStore, roster_season: str) -> dict[str, dict[str, int]]:
    rel = config.schedule_rel(roster_season)
    return store.read_json(rel)["games"] if store.exists(rel) else {}


def load_game_logs(store: JsonStore, stats_season: str) -> dict[int, list[GameLine]]:
    rel = config.game_logs_rel(stats_season)
    if not store.exists(rel):
        return {}
    raw = store.read_json(rel)["logs"]
    return {int(pid): [GameLine.model_validate(g) for g in lines] for pid, lines in raw.items()}


class PullService:
    def __init__(
        self,
        store: JsonStore,
        stats: StatsProvider,
        platform: FantasyPlatformProvider | None,
        roster_season: str | None = None,
        stats_season: str | None = None,
        injury_map: Mapping[str, InjuryStatus] | None = None,
    ) -> None:
        self.store = store
        self.stats = stats
        self.platform = platform
        self.roster_season = roster_season
        self.stats_season = stats_season
        self.injury_map = injury_map
        self.status = PullStatus()
        self.details = PlayerDetailCache(store, stats)

    # ---- progress plumbing --------------------------------------------------------------------

    def _phase(self, name: str) -> None:
        self.status.phase = name
        self.status.progress = None
        log.info("pull phase: %s", name)

    def _on_progress(self, progress: FetchProgress) -> None:
        self.status.progress = progress

    # ---- main entry -----------------------------------------------------------------------------

    def run(
        self,
        sources: Iterable[str] = ("nba_api", "sleeper"),
        force_sleeper: bool = False,
        skip_game_logs: bool = False,
    ) -> PullStatus:
        sources = set(sources)
        st = self.status
        st.state, st.started_at, st.error = "running", utcnow(), None
        st.reports = []
        try:
            self._resolve_seasons(sources)
            assert self.roster_season and self.stats_season
            nba_bios = self._pull_nba_pool()
            self._pull_schedule()
            self._pull_standings()
            self._pull_availability_history()
            sleeper_all, fantasy = self._pull_sleeper(sources, force_sleeper)
            self._pull_projections(sources)
            self._pull_sleeper_leagues(sources)
            records, report = self._reconcile(nba_bios, sleeper_all, fantasy)
            if not skip_game_logs:
                self._pull_game_logs(records)
            self._seed(records)
            st.state = "done"
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller/UI, never swallowed
            log.exception("pull failed")
            st.state, st.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            st.finished_at = utcnow()
            st.phase = "finished" if st.state == "done" else st.phase
        return st

    # ---- steps ----------------------------------------------------------------------------------

    def _resolve_seasons(self, sources: set[str]) -> None:
        if self.platform is not None and "sleeper" in sources:
            self._phase("sleeper_state")
            try:
                state = self.platform.fetch_platform_state()
                self.status.platform_state = state
                if self.roster_season is None:
                    self.roster_season = sleeper_season_to_roster_season(state.season)
                if self.stats_season is None and state.previous_season:
                    self.stats_season = sleeper_season_to_roster_season(state.previous_season)
            except (CallFailed, ValueError) as exc:
                log.warning("Sleeper state unavailable (%s); using configured seasons", exc)
        self.roster_season = self.roster_season or config.DEFAULT_ROSTER_SEASON
        self.stats_season = self.stats_season or config.DEFAULT_STATS_SEASON

    def _pull_nba_pool(self) -> list[PlayerBio]:
        self._phase("nba_pool")
        bios, report = self.stats.fetch_player_pool(self.roster_season, self._on_progress)
        self.status.reports.append(report)
        self.store.write_json(
            config.nba_pool_rel(self.roster_season),
            {"pulled_at": utcnow().isoformat(), "report": report.model_dump(mode="json"),
             "bios": [b.model_dump(mode="json") for b in bios]},
            indent=None,
        )
        return bios

    def _pull_standings(self) -> None:
        """Last season's records, for the NBA Teams view (an upgrade, never a requirement)."""
        if not hasattr(self.stats, "fetch_standings"):
            return
        self._phase("nba_standings")
        try:
            standings = self.stats.fetch_standings(self.stats_season)
        except (CallFailed, ValueError, KeyError) as exc:
            log.warning("NBA standings unavailable (%s); keeping the previous cache", exc)
            return
        if standings:
            self.store.write_json(config.standings_rel(self.stats_season),
                                  {"pulled_at": utcnow().isoformat(), "teams": standings}, indent=None)

    def _pull_availability_history(self) -> None:
        """Share of fantasy weeks played in the two seasons before the stats season (for 3-season availability)."""
        if not hasattr(self.stats, "fetch_game_dates"):
            return
        self._phase("availability_history")
        from nba_fantasy_shared.scoring import season_week_shares

        seasons: dict[str, dict[str, float]] = {}
        for season in config.prior_seasons(self.stats_season):
            try:
                shares = season_week_shares(self.stats.fetch_game_dates(season))
            except (CallFailed, ValueError, KeyError) as exc:
                log.warning("game dates for %s unavailable (%s); keeping the previous cache", season, exc)
                return
            seasons[season] = {str(pid): v for pid, v in shares.items()}
        self.store.write_json(config.AVAILABILITY_HISTORY_REL, {"pulled_at": utcnow().isoformat(), "seasons": seasons}, indent=None)

    def _pull_schedule(self) -> None:
        if not hasattr(self.stats, "fetch_schedule"):
            return
        self._phase("nba_schedule")
        try:
            games = self.stats.fetch_schedule(self.roster_season)
        except (CallFailed, ValueError, KeyError) as exc:  # the schedule is an upgrade, not a requirement
            log.warning("NBA schedule unavailable (%s); keeping the previous cache", exc)
            return
        if games:
            self.store.write_json(config.schedule_rel(self.roster_season),
                                  {"pulled_at": utcnow().isoformat(), "games": games}, indent=None)

    def _pull_sleeper(self, sources: set[str], force: bool) -> tuple[list[PlayerBio], dict[str, FantasyAttributes]]:
        if self.platform is None or "sleeper" not in sources:
            return [], {}
        self._phase("sleeper_players")
        bios, report = self.platform.fetch_player_pool(
            self.roster_season, self._on_progress, include_unrostered=True, force=force
        )
        self.status.reports.append(report)
        attrs, report2 = self.platform.fetch_fantasy_attributes(force=False)
        self.status.reports.append(report2)
        return bios, attrs

    def _pull_projections(self, sources: set[str]) -> None:
        if self.platform is None or "sleeper" not in sources or not hasattr(self.platform, "fetch_projections"):
            return
        self._phase("sleeper_projections")
        try:
            projections = self.platform.fetch_projections(self.roster_season)
        except (CallFailed, ValueError) as exc:  # projections are an upgrade, not a requirement
            log.warning("Sleeper projections unavailable (%s); keeping the previous cache", exc)
            return
        self.store.write_json(
            config.projections_rel(self.roster_season),
            {"pulled_at": utcnow().isoformat(), "projections": projections},
            indent=None,
        )

    def _pull_sleeper_leagues(self, sources: set[str]) -> None:
        """Managers, keepers and past auctions for every saved league linked to a Sleeper league."""
        if self.platform is None or "sleeper" not in sources or not hasattr(self.platform, "get_json"):
            return
        from .league_repository import LeagueRepository
        from .sleeper_league import pull_details

        repo = LeagueRepository(self.store)
        ids: set[str] = set()
        for lid in repo.list_ids():
            league = repo.load(lid).league
            ids |= {league.sleeper_league_id, *league.sleeper_history_league_ids} - {None, ""}
        ids = sorted(ids)
        for sleeper_id in ids:
            self._phase(f"sleeper_league {sleeper_id}")
            try:
                pull_details(self.platform, self.store, sleeper_id)
            except (CallFailed, ValueError) as exc:  # league details are an upgrade, not a requirement
                log.warning("Sleeper league %s unavailable (%s)", sleeper_id, exc)
        if ids:
            from .sleeper_league import write_profiles

            write_profiles(self.store)

    def _reconcile(
        self, nba_bios: list[PlayerBio], sleeper_all: list[PlayerBio], fantasy: dict[str, FantasyAttributes]
    ) -> tuple[list[PlayerRecord], ReconcileReport]:
        self._phase("reconcile")
        inputs = ReconcileInputs(
            roster_season=self.roster_season,
            nba_pool=nba_bios,
            sleeper_all=sleeper_all,
            fantasy=fantasy,
            nba_static=self.stats.list_players(active_only=False),
        )
        records, report = reconcile(inputs, birthdate_lookup=self.details.birthdate)
        self.status.reconcile = report
        self.status.records = len(records)
        self.store.write_json(
            config.reconcile_rel(self.roster_season),
            {"report": report.model_dump(mode="json"), "records": [r.model_dump(mode="json") for r in records]},
            indent=None,
        )
        return records, report

    def _pull_game_logs(self, records: list[PlayerRecord]) -> dict[int, list[GameLine]]:
        self._phase("game_logs")
        ids = [r.player_id for r in records if r.has_stats]
        logs, report = self.stats.fetch_game_logs(self.stats_season, ids, self._on_progress)
        self.status.reports.append(report)
        self.status.game_log_players = len(logs)
        self.store.write_json(
            config.game_logs_rel(self.stats_season),
            {"pulled_at": utcnow().isoformat(), "stats_season": self.stats_season,
             "report": report.model_dump(mode="json"),
             "logs": {str(pid): [g.model_dump(mode="json") for g in lines] for pid, lines in logs.items()}},
            indent=None,
        )
        return logs

    def _seed(self, records: list[PlayerRecord]) -> None:
        self._phase("seed_overrides")
        existing = load_overrides(self.store)
        state = self.status.platform_state
        preseason = state is not None and state.season_type in ("pre", "off")
        seeded = seed_overrides(records, existing, self.injury_map, ignore_short_term=preseason)
        save_overrides(self.store, seeded)
        self.status.seeded_overrides = sum(1 for o in seeded.values() if o.seeded_at is not None)
