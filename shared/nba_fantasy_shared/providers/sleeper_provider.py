"""Sleeper public API (https://api.sleeper.app/v1, no auth) as FantasyPlatformProvider.

The /players/nba payload (2.5 MB, 2,109 entries) is cached on disk and never re-fetched inside
24 hours unless `force=True`, per Sleeper's "once per day at most" guidance. Nothing is fetched at
import or construction time. Normalizers are pure module-level functions shared with the fixtures.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import requests

from ..models.league import PlatformLeague, PlatformState
from ..models.players import ALL_POSITIONS, FantasyAttributes, PlayerBio, PlayerRef
from ..reconcile.names import normalize_name
from ..storage.json_store import JsonStore
from .base import CallFailed, CallRunner, FetchReport, ProgressCallback, as_int, emit, make_report, utcnow
from .nba_api_provider import parse_height, search_refs

log = logging.getLogger(__name__)

SLEEPER_BASE_URL = "https://api.sleeper.app/v1"
PLAYERS_CACHE_REL = "cache/sleeper_players.json"
STATE_CACHE_REL = "cache/sleeper_state.json"
PLAYERS_CACHE_MAX_AGE = timedelta(hours=24)

ROSTERED_STATUSES = {"ACT", "TWO-WAY", "SUS", "NWT"}


# ----------------------------------------------------------------------------- entry predicates


def is_placeholder(entry: dict[str, Any]) -> bool:
    """DEF team-defense rows, DUP rows and 'duplicate player' stubs carry no real player."""
    if entry.get("position") == "DEF" or entry.get("status") == "DUP":
        return True
    first = (entry.get("first_name") or "").strip()
    last = (entry.get("last_name") or "").strip()
    if not first and not last:
        return True
    return "duplicate" in normalize_name(f"{first} {last}")


def is_rostered(entry: dict[str, Any]) -> bool:
    return bool(entry.get("active")) and bool(entry.get("team")) and not is_placeholder(entry)


# ----------------------------------------------------------------------------- normalizers


def _ms_epoch_to_datetime(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _iso_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _positions(values: Any) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = values.split(",")
    return [v.strip() for v in values if v and v.strip() in ALL_POSITIONS]


def bio_from_sleeper_entry(entry: dict[str, Any], fetched_at: datetime | None = None) -> PlayerBio:
    first = entry.get("first_name") or ""
    last = entry.get("last_name") or ""
    full = entry.get("full_name") or f"{first} {last}".strip()
    return PlayerBio(
        source="sleeper",
        source_id=str(entry["player_id"]),
        full_name=full,
        first_name=first,
        last_name=last,
        normalized_name=normalize_name(f"{first} {last}"),
        team_abbr=entry.get("team") or None,
        roster_status=entry.get("status"),
        is_active=bool(entry.get("active")),
        position_raw=entry.get("position") or None,
        height_in=parse_height(entry.get("height")),
        weight_lbs=as_int(entry.get("weight")),
        birthdate=_iso_date(entry.get("birth_date")),
        age=float(entry["age"]) if entry.get("age") is not None else None,
        years_exp=as_int(entry.get("years_exp")),
        country=entry.get("birth_country") or None,
        college=entry.get("college") or None,
        fetched_at=fetched_at or utcnow(),
    )


def fantasy_attributes_from_entry(entry: dict[str, Any]) -> FantasyAttributes:
    metadata = entry.get("metadata") or {}
    alt = _positions(metadata.get("fantasy_positions")) if isinstance(metadata, dict) else []
    return FantasyAttributes(
        sleeper_id=str(entry["player_id"]),
        fantasy_positions=_positions(entry.get("fantasy_positions")),
        fantasy_positions_alt=alt or None,
        injury_status_raw=entry.get("injury_status") or None,
        injury_body_part=entry.get("injury_body_part") or None,
        injury_notes=entry.get("injury_notes") or None,
        injury_start_date=_iso_date(entry.get("injury_start_date")),
        search_rank=as_int(entry.get("search_rank")),
        news_updated=_ms_epoch_to_datetime(entry.get("news_updated")),
        team_changed_at=_ms_epoch_to_datetime(entry.get("team_changed_at")),
        depth_chart_position=entry.get("depth_chart_position") or None,
        depth_chart_order=as_int(entry.get("depth_chart_order")),
    )


def platform_state_from_json(data: dict[str, Any]) -> PlatformState:
    return PlatformState(
        season=str(data["season"]),
        season_type=str(data.get("season_type") or ""),
        previous_season=str(data["previous_season"]) if data.get("previous_season") else None,
        season_start_date=_iso_date(data.get("season_start_date")),
        week=as_int(data.get("week")),
        league_season=str(data["league_season"]) if data.get("league_season") else None,
    )


def platform_league_from_json(data: dict[str, Any]) -> PlatformLeague:
    scoring = {k: float(v) for k, v in (data.get("scoring_settings") or {}).items() if v is not None}
    return PlatformLeague(
        league_id=str(data["league_id"]),
        name=data.get("name") or "",
        sport=data.get("sport") or "",
        season=str(data.get("season") or ""),
        status=data.get("status") or "",
        total_rosters=as_int(data.get("total_rosters")) or 0,
        roster_positions=list(data.get("roster_positions") or []),
        settings=dict(data.get("settings") or {}),
        scoring_settings=scoring,
        draft_id=str(data["draft_id"]) if data.get("draft_id") else None,
        previous_league_id=str(data["previous_league_id"]) if data.get("previous_league_id") else None,
    )


def sleeper_season_to_roster_season(season: str) -> str:
    """Sleeper's '2026' -> '2026-27'."""
    year = int(season)
    return f"{year}-{str(year + 1)[2:]}"


# ----------------------------------------------------------------------------- live provider


class SleeperProvider:
    source = "sleeper"

    def __init__(
        self,
        store: JsonStore,
        runner: CallRunner | None = None,
        session: requests.Session | None = None,
        base_url: str = SLEEPER_BASE_URL,
        cache_max_age: timedelta = PLAYERS_CACHE_MAX_AGE,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self.store = store
        self.runner = runner or CallRunner()
        self.session = session or requests.Session()
        self.base_url = base_url.rstrip("/")
        self.cache_max_age = cache_max_age
        self._now = now
        self._payload: dict[str, Any] | None = None
        self._payload_pulled_at: datetime | None = None

    # ---- HTTP -----------------------------------------------------------------------------

    def _get_json(self, path: str, label: str) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

        def do() -> Any:
            resp = self.session.get(url, timeout=self.runner.policy.timeout_s)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

        return self.runner.call(label, do)

    # ---- players payload with the 24 h cache guard -----------------------------------------

    def load_players_payload(self, force: bool = False) -> tuple[dict[str, Any], bool, datetime | None]:
        """Returns (payload, served_from_cache, pulled_at)."""
        cached = self._read_cache()
        if cached is not None and not force:
            payload, pulled_at = cached
            age = self._now() - pulled_at
            if age < self.cache_max_age:
                log.info("Sleeper players served from cache (age %s < %s)", age, self.cache_max_age)
                self._payload, self._payload_pulled_at = payload, pulled_at
                return payload, True, pulled_at
        try:
            payload = self._get_json("players/nba", "Sleeper GET /players/nba")
        except CallFailed:
            if cached is not None:
                log.warning("Sleeper players fetch failed; falling back to stale cache")
                payload, pulled_at = cached
                self._payload, self._payload_pulled_at = payload, pulled_at
                return payload, True, pulled_at
            raise
        if not isinstance(payload, dict):
            raise ValueError("Sleeper /players/nba returned a non-object payload")
        pulled_at = self._now()
        self.store.write_json(PLAYERS_CACHE_REL, {"pulled_at": pulled_at.isoformat(), "payload": payload}, indent=None)
        self._payload, self._payload_pulled_at = payload, pulled_at
        return payload, False, pulled_at

    def _read_cache(self) -> tuple[dict[str, Any], datetime] | None:
        if self._payload is not None and self._payload_pulled_at is not None:
            return self._payload, self._payload_pulled_at
        if not self.store.exists(PLAYERS_CACHE_REL):
            return None
        try:
            data = self.store.read_json(PLAYERS_CACHE_REL)
            pulled_at = datetime.fromisoformat(data["pulled_at"])
            if pulled_at.tzinfo is None:
                pulled_at = pulled_at.replace(tzinfo=timezone.utc)
            return data["payload"], pulled_at
        except (KeyError, ValueError, TypeError) as exc:
            log.warning("Sleeper players cache unreadable (%s); will re-fetch", exc)
            return None

    def cache_age(self) -> timedelta | None:
        cached = self._read_cache()
        if cached is None:
            return None
        return self._now() - cached[1]

    # ---- protocol methods ------------------------------------------------------------------

    def fetch_player_pool(
        self,
        roster_season: str,
        on_progress: ProgressCallback | None = None,
        include_unrostered: bool = False,
        force: bool = False,
    ) -> tuple[list[PlayerBio], FetchReport]:
        started = utcnow()
        calls_before = self.runner.calls
        emit(on_progress, 0, 1, "Sleeper /players/nba")
        payload, from_cache, pulled_at = self.load_players_payload(force=force)
        fetched_at = pulled_at or utcnow()
        entries = [e for e in payload.values() if isinstance(e, dict) and not is_placeholder(e)]
        if not include_unrostered:
            entries = [e for e in entries if is_rostered(e)]
        bios = [bio_from_sleeper_entry(e, fetched_at) for e in entries]
        emit(on_progress, 1, 1, "Sleeper players loaded")
        report = make_report(
            "sleeper", "player_pool", started, requested=1, succeeded=1,
            endpoint_calls=self.runner.calls - calls_before, served_from_cache=from_cache,
        )
        return bios, report

    def fetch_fantasy_attributes(self, force: bool = False) -> tuple[dict[str, FantasyAttributes], FetchReport]:
        started = utcnow()
        calls_before = self.runner.calls
        payload, from_cache, _ = self.load_players_payload(force=force)
        attrs = {
            str(e["player_id"]): fantasy_attributes_from_entry(e)
            for e in payload.values()
            if isinstance(e, dict) and not is_placeholder(e)
        }
        report = make_report(
            "sleeper", "fantasy_attributes", started, requested=1, succeeded=1,
            endpoint_calls=self.runner.calls - calls_before, served_from_cache=from_cache,
        )
        return attrs, report

    def fetch_platform_state(self) -> PlatformState:
        data = self._get_json("state/nba", "Sleeper GET /state/nba")
        if not isinstance(data, dict):
            raise ValueError("Sleeper /state/nba returned no object")
        state = platform_state_from_json(data)
        self.store.write_json(STATE_CACHE_REL, {"pulled_at": self._now().isoformat(), "state": state.model_dump(mode="json")})
        return state

    def get_json(self, path: str) -> Any:
        """Any read-only Sleeper endpoint (league users/rosters, drafts, picks); None on 404."""
        return self._get_json(path, f"Sleeper GET /{path.lstrip('/')}")

    def fetch_projections(self, roster_season: str) -> dict[str, dict[str, float]]:
        """Season projections (per-game stats, incl. 'sp' = projected seconds) keyed by Sleeper player id.

        Sleeper's undocumented projections endpoint lives beside /v1, not under it. Entries without
        projected points are placeholders (retired players etc.) and are dropped. Each entry also gets
        'owned': the % of Sleeper leagues where the player is on a roster (undocumented research endpoint).
        """
        year = roster_season.split("-")[0]
        host = self.base_url.rsplit("/v1", 1)[0]
        data = self._get_json(f"{host}/projections/nba/{year}?season_type=regular", f"Sleeper GET /projections/nba/{year}")
        out = {
            str(e["player_id"]): {k: float(v) for k, v in e["stats"].items() if isinstance(v, (int, float))}
            for e in data or []
            if e.get("player_id") and (e.get("stats") or {}).get("pts")
        }
        try:
            research = self._get_json(f"{host}/players/nba/research/regular/{year}", f"Sleeper GET /players/nba/research/regular/{year}") or {}
        except CallFailed:
            research = {}   # ownership is nice to have; projections still count
        if research:   # players it leaves out are on (almost) no rosters
            for sid, proj in out.items():
                proj["owned"] = float((research.get(sid) or {}).get("owned") or 0.0)
        return out

    def fetch_league(self, sleeper_league_id: str) -> PlatformLeague | None:
        data = self._get_json(f"league/{sleeper_league_id}", f"Sleeper GET /league/{sleeper_league_id}")
        if not data:
            return None
        league = platform_league_from_json(data)
        self.store.write_json(f"cache/sleeper_league_{sleeper_league_id}.json", data)
        return league

    def search_players(self, query: str, limit: int = 20) -> list[PlayerRef]:
        cached = self._read_cache()
        if cached is None:
            return []
        refs = [
            PlayerRef(
                player_id=-int(e["player_id"]) if str(e["player_id"]).isdigit() else 0,
                full_name=e.get("full_name") or f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                first_name=e.get("first_name") or "",
                last_name=e.get("last_name") or "",
                is_active=bool(e.get("active")),
            )
            for e in cached[0].values()
            if isinstance(e, dict) and not is_placeholder(e)
        ]
        return search_refs(refs, query, limit)
