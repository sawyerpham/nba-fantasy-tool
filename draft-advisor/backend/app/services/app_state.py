"""Process-wide state for the API: providers, JSON store, player pool, background pull, league sessions."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Iterable

from nba_fantasy_shared.models.export import DraftExport
from nba_fantasy_shared.models.league import LeagueSettings, Manager
from nba_fantasy_shared.models.players import PlayerOverrides, PlayerRecord, PlayerValuation
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.providers.base import FantasyPlatformProvider, StatsProvider
from nba_fantasy_shared.providers.sleeper_provider import PLAYERS_CACHE_REL
from nba_fantasy_shared.storage import JsonStore

from .. import config
from ..engine.session import DraftSession
from .league_repository import LeagueRepository, new_document
from .pull_service import PlayerDetailCache, PullService, PullStatus, load_overrides, load_projections, load_records, load_schedule, save_overrides
from .sleeper_league import load_details
from .valuation_service import ValuationService

log = logging.getLogger(__name__)


class PullAlreadyRunning(RuntimeError):
    pass


class AppState:
    def __init__(
        self,
        store: JsonStore,
        stats: StatsProvider,
        platform: FantasyPlatformProvider | None,
        roster_season: str = config.DEFAULT_ROSTER_SEASON,
        stats_season: str = config.DEFAULT_STATS_SEASON,
    ) -> None:
        self.store = store
        self.stats = stats
        self.platform = platform
        self.roster_season = roster_season
        self.stats_season = stats_season
        self.leagues = LeagueRepository(store)
        self.details = PlayerDetailCache(store, stats)
        self.players: dict[int, PlayerRecord] = {}
        self.overrides: dict[int, PlayerOverrides] = {}
        self.sessions: dict[str, DraftSession] = {}
        self._lock = threading.RLock()
        self._pull_thread: threading.Thread | None = None
        self._pull_service: PullService | None = None
        self.last_pull: PullStatus | None = None
        self.load_pool()

    # ------------------------------------------------------------------ player pool

    def load_pool(self) -> None:
        with self._lock:
            projections = load_projections(self.store, self.roster_season)
            self.players = {
                r.player_id: r.model_copy(update={"projection": projections.get(r.sleeper_id or "")})
                for r in load_records(self.store, self.roster_season)
            }
            self.overrides = load_overrides(self.store)
            self.schedule_games = load_schedule(self.store, self.roster_season)
            for session in self.sessions.values():
                session.schedule_games = self.schedule_games
                session.players = dict(self.players)
                session.overrides = self.overrides
                session.set_valuations(self.valuations_for(session.league.scoring, session.league.stats_season))
                session.sleeper_details = load_details(self.store, session.league.sleeper_league_id)
                session.sleeper_history = self._history(session.league)
        log.info("pool loaded: %d players, %d overrides", len(self.players), len(self.overrides))

    def _history(self, league: LeagueSettings) -> list[dict]:
        return [d for d in (load_details(self.store, i) for i in league.sleeper_history_league_ids) if d]

    def valuations_for(self, scoring: ScoringSettings, stats_season: str | None = None) -> dict[int, PlayerValuation]:
        service = ValuationService(self.store, stats_season or self.stats_season)
        if not self.store.exists(config.game_logs_rel(service.stats_season)):
            return {}
        return service.compute(scoring)

    def data_status(self) -> dict:
        def age(rel: str) -> float | None:
            delta = self.store.age(rel)
            return round(delta.total_seconds() / 3600, 2) if delta is not None else None

        reconcile = None
        rel = config.reconcile_rel(self.roster_season)
        if self.store.exists(rel):
            reconcile = self.store.read_json(rel)["report"]
        return {
            "roster_season": self.roster_season,
            "stats_season": self.stats_season,
            "players": len(self.players),
            "overrides": len(self.overrides),
            "caches": {
                "nba_player_pool_hours": age(config.nba_pool_rel(self.roster_season)),
                "game_logs_hours": age(config.game_logs_rel(self.stats_season)),
                "sleeper_players_hours": age(PLAYERS_CACHE_REL),
                "reconcile_hours": age(rel),
                "sleeper_projections_hours": age(config.projections_rel(self.roster_season)),
            },
            "reconcile": reconcile,
            "pull": self.pull_status(),
        }

    # ------------------------------------------------------------------ overrides

    def save_overrides(self) -> None:
        with self._lock:
            save_overrides(self.store, self.overrides)
            for session in self.sessions.values():
                session.overrides = self.overrides
                session.invalidate()

    def update_override(self, player_id: int, changes: dict) -> PlayerOverrides:
        """Manual edit: every touched field becomes source='manual'."""
        if player_id not in self.players:
            raise KeyError(player_id)
        now = datetime.now(timezone.utc)
        current = self.overrides.get(player_id) or PlayerOverrides(player_id=player_id, updated_at=now)
        data = current.model_dump()
        if "eligibility" in changes:
            data["eligibility"] = list(changes["eligibility"])
            data["eligibility_source"] = "manual"
        if "injury_status" in changes:
            data["injury_status"] = changes["injury_status"]
            data["injury_source"] = "manual"
        if "injury_note" in changes:
            data["injury_note"] = changes["injury_note"]
            data["injury_source"] = "manual"
        if "notes" in changes:
            data["notes"] = changes["notes"]
        data["updated_at"] = now
        updated = PlayerOverrides.model_validate(data)
        self.overrides[player_id] = updated
        self.save_overrides()
        return updated

    def reset_override(self, player_id: int, fields: Iterable[str]) -> PlayerOverrides:
        """Put selected fields back under Sleeper seeding (or 'none' when Sleeper knows nothing)."""
        from nba_fantasy_shared.reconcile.seeding import injury_note_from, map_injury

        record = self.players.get(player_id)
        if record is None:
            raise KeyError(player_id)
        now = datetime.now(timezone.utc)
        current = self.overrides.get(player_id) or PlayerOverrides(player_id=player_id, updated_at=now)
        data = current.model_dump()
        fantasy = record.fantasy
        injury_map = self._injury_map()
        for field in fields:
            if field == "eligibility":
                data["eligibility"] = list(fantasy.fantasy_positions) if fantasy else []
                data["eligibility_source"] = "sleeper" if fantasy and fantasy.fantasy_positions else "none"
            elif field == "injury":
                data["injury_status"] = map_injury(fantasy.injury_status_raw, injury_map) if fantasy else "healthy"
                data["injury_source"] = "sleeper" if fantasy else "none"
                data["injury_note"] = injury_note_from(fantasy.injury_body_part, fantasy.injury_notes) if fantasy else ""
            else:
                raise ValueError(f"unknown override field {field!r}; use 'eligibility' or 'injury'")
        data["updated_at"] = now
        updated = PlayerOverrides.model_validate(data)
        self.overrides[player_id] = updated
        self.save_overrides()
        return updated

    def _injury_map(self) -> dict:
        for session in self.sessions.values():
            return session.league.ranking.sleeper_injury_map
        return LeagueSettings(league_id="_", name="_").ranking.sleeper_injury_map

    # ------------------------------------------------------------------ background pull

    def pull_running(self) -> bool:
        return self._pull_thread is not None and self._pull_thread.is_alive()

    def pull_status(self) -> dict:
        service = self._pull_service
        if service is None:
            return {"state": "idle", "phase": "", "progress": None}
        return service.status.as_dict()

    def start_pull(self, sources: Iterable[str] = ("nba_api", "sleeper"), force_sleeper: bool = False,
                   skip_game_logs: bool = False, wait: bool = False) -> dict:
        with self._lock:
            if self.pull_running():
                raise PullAlreadyRunning("a pull is already running")
            service = PullService(self.store, self.stats, self.platform, roster_season=self.roster_season,
                                  stats_season=self.stats_season, injury_map=self._injury_map())
            self._pull_service = service
            sources = list(sources)

            def run() -> None:
                try:
                    service.run(sources=sources, force_sleeper=force_sleeper, skip_game_logs=skip_game_logs)
                finally:
                    self.last_pull = service.status
                    if service.status.state == "done":
                        if service.roster_season:
                            self.roster_season = service.roster_season
                        if service.stats_season:
                            self.stats_season = service.stats_season
                        try:
                            self.load_pool()
                        except Exception:  # noqa: BLE001
                            log.exception("reloading the pool after the pull failed")

            thread = threading.Thread(target=run, name="data-pull", daemon=True)
            self._pull_thread = thread
            thread.start()
        if wait:
            thread.join()
        return self.pull_status()

    def join_pull(self, timeout: float | None = None) -> None:
        if self._pull_thread is not None:
            self._pull_thread.join(timeout)

    # ------------------------------------------------------------------ league sessions

    def list_leagues(self) -> list[dict]:
        return self.leagues.summaries()

    def create_league(self, league: LeagueSettings, managers: list[Manager] | None = None) -> DraftSession:
        with self._lock:
            if self.leagues.exists(league.league_id):
                raise FileExistsError(league.league_id)
            doc = new_document(league, managers)
            self.leagues.save(doc)
            return self.get_session(league.league_id)

    def get_session(self, league_id: str) -> DraftSession:
        with self._lock:
            session = self.sessions.get(league_id)
            if session is None:
                doc = self.leagues.load(league_id)
                session = DraftSession.from_export(
                    doc, self.players, self.overrides, self.valuations_for(doc.league.scoring, doc.league.stats_season)
                )
                session.overrides = self.overrides  # shared, so edits propagate to every league
                session.sleeper_details = load_details(self.store, doc.league.sleeper_league_id)
                session.sleeper_history = self._history(doc.league)
                session.schedule_games = self.schedule_games
                self.sessions[league_id] = session
            return session

    def save_session(self, league_id: str) -> DraftExport:
        with self._lock:
            session = self.get_session(league_id)
            session.league.num_managers = len(session.managers)
            doc = session.to_export()
            self.leagues.save(doc)
            return doc

    def replace_league_settings(self, league_id: str, league: LeagueSettings) -> DraftSession:
        with self._lock:
            session = self.get_session(league_id)
            if league.league_id != league_id:
                raise ValueError("league_id cannot be changed")
            scoring_changed = league.scoring.scoring_hash() != session.league.scoring.scoring_hash()
            season_changed = league.stats_season != session.league.stats_season
            session.set_league(league)
            if scoring_changed or season_changed:
                session.set_valuations(self.valuations_for(league.scoring, league.stats_season))
            session.sleeper_details = load_details(self.store, league.sleeper_league_id)
            session.sleeper_history = self._history(league)
            self.save_session(league_id)
            return session

    def delete_league(self, league_id: str) -> None:
        with self._lock:
            self.sessions.pop(league_id, None)
            self.leagues.delete(league_id)

    def export_league(self, league_id: str) -> tuple[str, DraftExport]:
        with self._lock:
            doc = self.save_session(league_id)
            rel = self.leagues.export_copy(doc)
            return rel, doc
