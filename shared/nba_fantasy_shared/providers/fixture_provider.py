"""Providers that serve captured real responses from a fixtures directory.

Layout (all files are the normalized JSON exactly as the live APIs returned it):
  nba/static_players.json              list of nba_api static player dicts
  nba/static_teams.json                list of nba_api static team dicts
  nba/playerindex_{season}.json        list of PlayerIndex rows
  nba/biostats_{season}.json           list of LeagueDashPlayerBioStats rows
  nba/playergamelogs_{season}.json     list of PlayerGameLogs rows
  nba/playergamelog_{pid}_{season}.json list of PlayerGameLog rows
  nba/commonplayerinfo_{pid}.json      normalized dict (CommonPlayerInfo, PlayerHeadlineStats, ...)
  nba/playercareerstats_{pid}.json     normalized dict (SeasonTotalsRegularSeason, ...)
  sleeper/players_nba.json             dict keyed by Sleeper player id
  sleeper/state_nba.json               dict
  sleeper/league_{id}.json             dict
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..models.league import PlatformLeague, PlatformState
from ..models.players import FantasyAttributes, GameLine, PlayerBio, PlayerDetail, PlayerRef, TeamRef
from .base import FetchReport, ProgressCallback, emit, make_report, utcnow
from .nba_api_provider import (
    apply_ages,
    bio_from_playerindex_row,
    detail_from_responses,
    game_line_from_row,
    player_ref_from_static,
    previous_season,
    search_refs,
    sort_game_lines,
    team_ref_from_static,
)
from .sleeper_provider import (
    bio_from_sleeper_entry,
    fantasy_attributes_from_entry,
    is_placeholder,
    is_rostered,
    platform_league_from_json,
    platform_state_from_json,
)


class FixtureMissing(FileNotFoundError):
    pass


def _load(path: Path) -> Any:
    if not path.is_file():
        raise FixtureMissing(str(path))
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class FixtureStatsProvider:
    source = "nba_api"

    def __init__(self, root: Path | str, fetched_at: datetime | None = None) -> None:
        self.root = Path(root) / "nba"
        self.fetched_at = fetched_at or utcnow()
        self.calls = 0

    def list_players(self, active_only: bool = True) -> list[PlayerRef]:
        refs = [player_ref_from_static(r) for r in _load(self.root / "static_players.json")]
        return [r for r in refs if r.is_active] if active_only else refs

    def list_teams(self) -> list[TeamRef]:
        return [team_ref_from_static(r) for r in _load(self.root / "static_teams.json")]

    def search_players(self, query: str, limit: int = 20) -> list[PlayerRef]:
        return search_refs(self.list_players(active_only=False), query, limit)

    def fetch_player_pool(
        self, roster_season: str, on_progress: ProgressCallback | None = None
    ) -> tuple[list[PlayerBio], FetchReport]:
        started = utcnow()
        self.calls += 1
        rows = _load(self.root / f"playerindex_{roster_season}.json")
        bios = [bio_from_playerindex_row(r, self.fetched_at) for r in rows]
        age_path = self.root / f"biostats_{roster_season}.json"
        offset = 0
        if not age_path.is_file():
            age_path, offset = self.root / f"biostats_{previous_season(roster_season)}.json", 1
        if age_path.is_file():
            self.calls += 1
            apply_ages(bios, _load(age_path), offset)
        emit(on_progress, 1, 1, "fixture pool")
        return bios, make_report("nba_api", "player_pool", started, 1, 1, endpoint_calls=self.calls, served_from_cache=True)

    def fetch_game_logs(
        self, stats_season: str, player_ids: list[int], on_progress: ProgressCallback | None = None
    ) -> tuple[dict[int, list[GameLine]], FetchReport]:
        started = utcnow()
        failed: dict[str, str] = {}
        grouped: dict[int, list[GameLine]] = {}
        batch_path = self.root / f"playergamelogs_{stats_season}.json"
        if batch_path.is_file():
            self.calls += 1
            for row in _load(batch_path):
                line = game_line_from_row(row)
                grouped.setdefault(line.player_id, []).append(line)
        wanted = [pid for pid in player_ids if pid > 0]
        for pid in wanted:
            if pid in grouped:
                continue
            path = self.root / f"playergamelog_{pid}_{stats_season}.json"
            if path.is_file():
                self.calls += 1
                grouped[pid] = [game_line_from_row(r) for r in _load(path)]
            else:
                failed[str(pid)] = "fixture missing"
        result = {pid: sort_game_lines(grouped[pid]) for pid in wanted if pid in grouped}
        emit(on_progress, len(wanted), len(wanted), "fixture logs", failed=len(failed))
        return result, make_report("nba_api", "game_logs", started, len(wanted), len(result), failed, self.calls, True)

    def fetch_player_detail(self, player_id: int) -> PlayerDetail:
        self.calls += 2
        info = _load(self.root / f"commonplayerinfo_{player_id}.json")
        career = _load(self.root / f"playercareerstats_{player_id}.json")
        return detail_from_responses(player_id, info, career, self.fetched_at)


class FixturePlatformProvider:
    source = "sleeper"

    def __init__(self, root: Path | str, fetched_at: datetime | None = None) -> None:
        self.root = Path(root) / "sleeper"
        self.fetched_at = fetched_at or utcnow()

    def _payload(self) -> dict[str, Any]:
        return _load(self.root / "players_nba.json")

    def fetch_player_pool(
        self,
        roster_season: str,
        on_progress: ProgressCallback | None = None,
        include_unrostered: bool = False,
        force: bool = False,
    ) -> tuple[list[PlayerBio], FetchReport]:
        started = utcnow()
        entries = [e for e in self._payload().values() if isinstance(e, dict) and not is_placeholder(e)]
        if not include_unrostered:
            entries = [e for e in entries if is_rostered(e)]
        bios = [bio_from_sleeper_entry(e, self.fetched_at) for e in entries]
        emit(on_progress, 1, 1, "fixture sleeper")
        return bios, make_report("sleeper", "player_pool", started, 1, 1, served_from_cache=True)

    def fetch_fantasy_attributes(self, force: bool = False) -> tuple[dict[str, FantasyAttributes], FetchReport]:
        started = utcnow()
        attrs = {
            str(e["player_id"]): fantasy_attributes_from_entry(e)
            for e in self._payload().values()
            if isinstance(e, dict) and not is_placeholder(e)
        }
        return attrs, make_report("sleeper", "fantasy_attributes", started, 1, 1, served_from_cache=True)

    def fetch_platform_state(self) -> PlatformState:
        return platform_state_from_json(_load(self.root / "state_nba.json"))

    def fetch_league(self, sleeper_league_id: str) -> PlatformLeague | None:
        path = self.root / f"league_{sleeper_league_id}.json"
        if path.is_file():
            return platform_league_from_json(_load(path))
        # Hand-named fixtures (e.g. league_nba_provisional.json) are matched on their league_id field.
        for candidate in sorted(self.root.glob("league_*.json")):
            data = _load(candidate)
            if str(data.get("league_id")) == str(sleeper_league_id):
                return platform_league_from_json(data)
        return None

    def search_players(self, query: str, limit: int = 20) -> list[PlayerRef]:
        refs = [
            PlayerRef(
                player_id=-int(e["player_id"]),
                full_name=e.get("full_name") or f"{e.get('first_name', '')} {e.get('last_name', '')}".strip(),
                first_name=e.get("first_name") or "",
                last_name=e.get("last_name") or "",
                is_active=bool(e.get("active")),
            )
            for e in self._payload().values()
            if isinstance(e, dict) and not is_placeholder(e) and str(e["player_id"]).isdigit()
        ]
        return search_refs(refs, query, limit)
