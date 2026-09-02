"""nba_api-backed StatsProvider.

Normalization functions are module-level and pure so the FixtureProvider and the tests
exercise exactly the same code path as the live provider. Field names below are the ones
observed in real responses (see DESIGN.md appendix A), read by name via get_normalized_dict().
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Any, Iterable

from ..models.players import GameLine, PlayerBio, PlayerDetail, PlayerRef, SeasonTotals, TeamRef
from ..reconcile.names import normalize_name
from .base import (
    CallFailed,
    CallRunner,
    FetchReport,
    ProgressCallback,
    as_int,
    emit,
    make_report,
    utcnow,
)

log = logging.getLogger(__name__)

REGULAR_SEASON = "Regular Season"


# ----------------------------------------------------------------------------- seasons


def season_start_year(season: str) -> int:
    return int(season[:4])


def season_label(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[2:]}"


def previous_season(season: str) -> str:
    return season_label(season_start_year(season) - 1)


def season_from_season_id(season_id: str) -> str:
    """'22025' -> '2025-26' (leading digit is the season type: 2 = regular season)."""
    text = str(season_id)
    return season_label(int(text[-4:]))


# ----------------------------------------------------------------------------- field parsers

_HEIGHT_FT_IN = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")


def parse_height(value: Any) -> int | None:
    """'6-11' -> 83 ; '83' -> 83 ; None/'' -> None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    match = _HEIGHT_FT_IN.match(text)
    if match:
        return int(match.group(1)) * 12 + int(match.group(2))
    return as_int(text)


def parse_matchup(matchup: str) -> tuple[str, str, bool]:
    """'DEN @ SAS' -> ('DEN', 'SAS', False) ; 'DEN vs. SAS' -> ('DEN', 'SAS', True)."""
    parts = matchup.split()
    if len(parts) != 3:
        raise ValueError(f"unexpected MATCHUP format: {matchup!r}")
    team, sep, opponent = parts
    home = sep.lower().startswith("vs")
    return team, opponent, home


def parse_game_date(value: str) -> date:
    """'Apr 12, 2026' (PlayerGameLog) or '2026-04-12T00:00:00' (PlayerGameLogs)."""
    text = value.strip()
    if "T" in text or (len(text) >= 10 and text[4] == "-"):
        return date.fromisoformat(text[:10])
    return datetime.strptime(text, "%b %d, %Y").date()


def parse_iso_datetime_date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


# ----------------------------------------------------------------------------- row normalizers


def game_line_from_row(row: dict[str, Any]) -> GameLine:
    """Works for both PlayerGameLog rows (Player_ID/Game_ID/SEASON_ID, MIN int, 'Apr 12, 2026')
    and PlayerGameLogs rows (PLAYER_ID/GAME_ID/SEASON_YEAR, MIN float, ISO date)."""
    player_id = row.get("Player_ID", row.get("PLAYER_ID"))
    game_id = row.get("Game_ID", row.get("GAME_ID"))
    if "SEASON_YEAR" in row and row["SEASON_YEAR"]:
        season = str(row["SEASON_YEAR"])
    else:
        season = season_from_season_id(row["SEASON_ID"])
    team, opponent, home = parse_matchup(row["MATCHUP"])
    if row.get("TEAM_ABBREVIATION"):
        team = row["TEAM_ABBREVIATION"]
    wl = row.get("WL")
    win = None if wl not in ("W", "L") else wl == "W"
    minutes = row.get("MIN")
    return GameLine(
        player_id=int(player_id),
        season=season,
        game_id=str(game_id),
        game_date=parse_game_date(str(row["GAME_DATE"])),
        team_abbr=team,
        opponent_abbr=opponent,
        home=home,
        win=win,
        minutes=float(minutes) if minutes is not None else 0.0,
        pts=as_int(row.get("PTS")) or 0,
        reb=as_int(row.get("REB")) or 0,
        ast=as_int(row.get("AST")) or 0,
        stl=as_int(row.get("STL")) or 0,
        blk=as_int(row.get("BLK")) or 0,
        tov=as_int(row.get("TOV")) or 0,
        fgm=as_int(row.get("FGM")) or 0,
        fga=as_int(row.get("FGA")) or 0,
        ftm=as_int(row.get("FTM")) or 0,
        fta=as_int(row.get("FTA")) or 0,
        fg3m=as_int(row.get("FG3M")) or 0,
        fg3a=as_int(row.get("FG3A")) or 0,
        oreb=as_int(row.get("OREB")) or 0,
        dreb=as_int(row.get("DREB")) or 0,
        pf=as_int(row.get("PF")) or 0,
        plus_minus=as_int(row.get("PLUS_MINUS")) or 0,
    )


def sort_game_lines(lines: Iterable[GameLine]) -> list[GameLine]:
    return sorted(lines, key=lambda g: (g.game_date, g.game_id))


def bio_from_playerindex_row(row: dict[str, Any], fetched_at: datetime | None = None) -> PlayerBio:
    first = row.get("PLAYER_FIRST_NAME") or ""
    last = row.get("PLAYER_LAST_NAME") or ""
    full = f"{first} {last}".strip()
    team_id = as_int(row.get("TEAM_ID"))
    team_abbr = row.get("TEAM_ABBREVIATION") or None
    if not team_id:
        team_id, team_abbr = None, None
    roster_status = row.get("ROSTER_STATUS")
    return PlayerBio(
        source="nba_api",
        source_id=str(row["PERSON_ID"]),
        full_name=full,
        first_name=first,
        last_name=last,
        normalized_name=normalize_name(full),
        team_abbr=team_abbr,
        team_id=team_id,
        roster_status=None if roster_status is None else str(as_int(roster_status)),
        is_active=True if roster_status else None,
        position_raw=row.get("POSITION") or None,
        height_in=parse_height(row.get("HEIGHT")),
        weight_lbs=as_int(row.get("WEIGHT")),
        draft_year=as_int(row.get("DRAFT_YEAR")),
        draft_round=as_int(row.get("DRAFT_ROUND")),
        draft_number=as_int(row.get("DRAFT_NUMBER")),
        country=row.get("COUNTRY") or None,
        college=row.get("COLLEGE") or None,
        fetched_at=fetched_at or utcnow(),
    )


def season_totals_from_row(row: dict[str, Any]) -> SeasonTotals:
    return SeasonTotals(
        season=str(row["SEASON_ID"]),
        team_id=as_int(row.get("TEAM_ID")) or 0,
        team_abbr=row.get("TEAM_ABBREVIATION") or "TOT",
        age=row.get("PLAYER_AGE"),
        gp=as_int(row.get("GP")) or 0,
        gs=as_int(row.get("GS")) or 0,
        minutes=as_int(row.get("MIN")) or 0,
        pts=as_int(row.get("PTS")) or 0,
        reb=as_int(row.get("REB")) or 0,
        ast=as_int(row.get("AST")) or 0,
        stl=as_int(row.get("STL")) or 0,
        blk=as_int(row.get("BLK")) or 0,
        tov=as_int(row.get("TOV")) or 0,
        fgm=as_int(row.get("FGM")) or 0,
        fga=as_int(row.get("FGA")) or 0,
        fg3m=as_int(row.get("FG3M")) or 0,
        fg3a=as_int(row.get("FG3A")) or 0,
        ftm=as_int(row.get("FTM")) or 0,
        fta=as_int(row.get("FTA")) or 0,
    )


def detail_from_responses(
    player_id: int,
    common_player_info: dict[str, list[dict[str, Any]]],
    career_stats: dict[str, list[dict[str, Any]]],
    fetched_at: datetime | None = None,
) -> PlayerDetail:
    info_rows = common_player_info.get("CommonPlayerInfo") or []
    info = info_rows[0] if info_rows else {}
    totals = [season_totals_from_row(r) for r in career_stats.get("SeasonTotalsRegularSeason") or []]
    return PlayerDetail(
        player_id=player_id,
        birthdate=parse_iso_datetime_date(info.get("BIRTHDATE")),
        season_exp=as_int(info.get("SEASON_EXP")),
        position_raw=info.get("POSITION") or None,
        height_in=parse_height(info.get("HEIGHT")),
        weight_lbs=as_int(info.get("WEIGHT")),
        school=info.get("SCHOOL") or None,
        country=info.get("COUNTRY") or None,
        draft_year=as_int(info.get("DRAFT_YEAR")),
        draft_round=as_int(info.get("DRAFT_ROUND")),
        draft_number=as_int(info.get("DRAFT_NUMBER")),
        season_totals=totals,
        fetched_at=fetched_at or utcnow(),
    )


def player_ref_from_static(row: dict[str, Any]) -> PlayerRef:
    return PlayerRef(
        player_id=int(row["id"]),
        full_name=row["full_name"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        is_active=bool(row["is_active"]),
    )


def team_ref_from_static(row: dict[str, Any]) -> TeamRef:
    return TeamRef(
        team_id=int(row["id"]),
        abbreviation=row["abbreviation"],
        full_name=row["full_name"],
        nickname=row["nickname"],
        city=row["city"],
    )


def search_refs(refs: Iterable[PlayerRef], query: str, limit: int = 20) -> list[PlayerRef]:
    """Accent/punctuation-insensitive search; prefix matches rank above substring matches."""
    q = normalize_name(query)
    if not q:
        return []
    prefix: list[PlayerRef] = []
    inner: list[PlayerRef] = []
    for ref in refs:
        name = normalize_name(ref.full_name)
        if name.startswith(q) or any(part.startswith(q) for part in name.split()):
            prefix.append(ref)
        elif q in name:
            inner.append(ref)
    ordered = sorted(prefix, key=lambda r: (not r.is_active, r.full_name)) + sorted(
        inner, key=lambda r: (not r.is_active, r.full_name)
    )
    return ordered[:limit]


def apply_ages(bios: list[PlayerBio], age_rows: list[dict[str, Any]], season_offset: int) -> int:
    """Attach LeagueDashPlayerBioStats AGE (+ offset seasons) to bios by player id. Returns count set."""
    ages = {int(r["PLAYER_ID"]): r.get("AGE") for r in age_rows if r.get("PLAYER_ID") is not None}
    count = 0
    for bio in bios:
        age = ages.get(int(bio.source_id))
        if age is not None:
            bio.age = float(age) + season_offset
            count += 1
    return count


# ----------------------------------------------------------------------------- live provider


class NbaApiProvider:
    source = "nba_api"

    def __init__(self, runner: CallRunner | None = None) -> None:
        self.runner = runner or CallRunner()
        self._static_players: list[PlayerRef] | None = None
        self._static_teams: list[TeamRef] | None = None

    # ---- static -------------------------------------------------------------------------

    def list_players(self, active_only: bool = True) -> list[PlayerRef]:
        if self._static_players is None:
            from nba_api.stats.static import players as static_players

            self._static_players = [player_ref_from_static(r) for r in static_players.get_players()]
        if active_only:
            return [p for p in self._static_players if p.is_active]
        return list(self._static_players)

    def list_teams(self) -> list[TeamRef]:
        if self._static_teams is None:
            from nba_api.stats.static import teams as static_teams

            self._static_teams = [team_ref_from_static(r) for r in static_teams.get_teams()]
        return list(self._static_teams)

    def search_players(self, query: str, limit: int = 20) -> list[PlayerRef]:
        return search_refs(self.list_players(active_only=False), query, limit)

    # ---- network helpers -----------------------------------------------------------------

    def _timeout(self) -> float:
        return self.runner.policy.timeout_s

    def _normalized(self, label: str, factory) -> dict[str, list[dict[str, Any]]]:
        return self.runner.call(label, lambda: factory().get_normalized_dict())

    # ---- bulk ---------------------------------------------------------------------------

    def fetch_player_pool(
        self, roster_season: str, on_progress: ProgressCallback | None = None
    ) -> tuple[list[PlayerBio], FetchReport]:
        from nba_api.stats.endpoints import leaguedashplayerbiostats, playerindex

        started = utcnow()
        failed: dict[str, str] = {}
        calls_before = self.runner.calls
        emit(on_progress, 0, 2, "nba_api PlayerIndex")
        data = self._normalized(
            f"PlayerIndex({roster_season})",
            lambda: playerindex.PlayerIndex(season=roster_season, timeout=self._timeout()),
        )
        rows = data.get("PlayerIndex") or []
        fetched_at = utcnow()
        bios = [bio_from_playerindex_row(r, fetched_at) for r in rows]
        emit(on_progress, 1, 2, "nba_api LeagueDashPlayerBioStats")

        # Age: try the roster season first (populated once the season starts), else previous season + 1.
        age_season, offset = roster_season, 0
        try:
            age_rows = self._normalized(
                f"LeagueDashPlayerBioStats({age_season})",
                lambda: leaguedashplayerbiostats.LeagueDashPlayerBioStats(season=age_season, timeout=self._timeout()),
            ).get("LeagueDashPlayerBioStats") or []
            if not age_rows:
                age_season, offset = previous_season(roster_season), 1
                age_rows = self._normalized(
                    f"LeagueDashPlayerBioStats({age_season})",
                    lambda: leaguedashplayerbiostats.LeagueDashPlayerBioStats(
                        season=age_season, timeout=self._timeout()
                    ),
                ).get("LeagueDashPlayerBioStats") or []
            apply_ages(bios, age_rows, offset)
        except CallFailed as exc:
            failed["LeagueDashPlayerBioStats"] = str(exc)
        emit(on_progress, 2, 2, "nba_api pool done", failed=len(failed))
        report = make_report(
            "nba_api", "player_pool", started, requested=1, succeeded=1, failed=failed,
            endpoint_calls=self.runner.calls - calls_before,
        )
        return bios, report

    def fetch_game_logs(
        self,
        stats_season: str,
        player_ids: list[int],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[dict[int, list[GameLine]], FetchReport]:
        from nba_api.stats.endpoints import playergamelog, playergamelogs

        started = utcnow()
        failed: dict[str, str] = {}
        calls_before = self.runner.calls
        wanted = [pid for pid in player_ids if pid > 0]
        grouped: dict[int, list[GameLine]] = {}

        emit(on_progress, 0, len(wanted) + 1, "nba_api PlayerGameLogs (league-wide)")
        try:
            batch = self._normalized(
                f"PlayerGameLogs({stats_season})",
                lambda: playergamelogs.PlayerGameLogs(
                    season_nullable=stats_season,
                    season_type_nullable=REGULAR_SEASON,
                    timeout=max(self._timeout(), 60),
                ),
            ).get("PlayerGameLogs") or []
        except CallFailed as exc:
            failed["PlayerGameLogs"] = str(exc)
            batch = []
        for row in batch:
            try:
                line = game_line_from_row(row)
            except (KeyError, ValueError) as exc:
                failed[f"row:{row.get('GAME_ID')}:{row.get('PLAYER_ID')}"] = f"{type(exc).__name__}: {exc}"
                continue
            grouped.setdefault(line.player_id, []).append(line)

        # Per-player fallback only for requested players the batch did not cover.
        missing = [pid for pid in wanted if pid not in grouped]
        done = 1
        emit(on_progress, done, len(wanted) + 1, f"batch covered {len(wanted) - len(missing)} / {len(wanted)}")
        for pid in missing:
            label = f"PlayerGameLog({pid}, {stats_season})"
            try:
                rows = self._normalized(
                    label,
                    lambda pid=pid: playergamelog.PlayerGameLog(
                        player_id=pid, season=stats_season, season_type_all_star=REGULAR_SEASON,
                        timeout=self._timeout(),
                    ),
                ).get("PlayerGameLog") or []
                grouped[pid] = [game_line_from_row(r) for r in rows]
            except CallFailed as exc:
                failed[str(pid)] = str(exc)
            except (KeyError, ValueError) as exc:
                failed[str(pid)] = f"{type(exc).__name__}: {exc}"
            done += 1
            emit(on_progress, done, len(wanted) + 1, label, failed=len(failed))

        result = {pid: sort_game_lines(grouped[pid]) for pid in wanted if pid in grouped}
        report = make_report(
            "nba_api", "game_logs", started, requested=len(wanted), succeeded=len(result), failed=failed,
            endpoint_calls=self.runner.calls - calls_before,
        )
        return result, report

    # ---- on demand -----------------------------------------------------------------------

    def fetch_player_detail(self, player_id: int) -> PlayerDetail:
        from nba_api.stats.endpoints import commonplayerinfo, playercareerstats

        info = self._normalized(
            f"CommonPlayerInfo({player_id})",
            lambda: commonplayerinfo.CommonPlayerInfo(player_id=player_id, timeout=self._timeout()),
        )
        # Players with no NBA games yet (rookies, two-ways) get a response without any result set
        # from playercareerstats (observed: KeyError 'resultSet' for 1642392). Bio still counts.
        try:
            career = self._normalized(
                f"PlayerCareerStats({player_id})",
                lambda: playercareerstats.PlayerCareerStats(player_id=player_id, timeout=self._timeout()),
            )
        except CallFailed as exc:
            log.warning("career stats unavailable for %s (%s); returning bio only", player_id, exc.last_error)
            career = {}
        return detail_from_responses(player_id, info, career)
