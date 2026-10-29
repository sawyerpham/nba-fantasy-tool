
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Protocol, TypeVar

import requests
from pydantic import BaseModel, Field

from ..models.league import PlatformLeague, PlatformState
from ..models.players import (
    FantasyAttributes,
    GameLine,
    PlayerBio,
    PlayerDetail,
    PlayerRef,
    Source,
    TeamRef,
)

log = logging.getLogger(__name__)

T = TypeVar("T")


class FetchProgress(BaseModel):
    """Progress of a fetch: items done out of total, the current label and the failure count."""
    done: int
    total: int
    current_label: str = ""
    failed: int = 0


ProgressCallback = Callable[[FetchProgress], None]


class FetchReport(BaseModel):
    """What a provider call did: source, operation, timing, how many items were requested / succeeded, failures by key, endpoint calls and whether it was served from cache."""
    source: Source
    operation: str
    started_at: datetime
    finished_at: datetime
    requested: int
    succeeded: int
    failed: dict[str, str] = Field(default_factory=dict)
    endpoint_calls: int = 0
    served_from_cache: bool = False

    @property
    def ok(self) -> bool:
        """True when nothing failed."""
        return not self.failed


class RetryPolicy(BaseModel):
    """Retry settings: minimum delay between calls, attempts, backoff factor and per-call timeout."""
    delay_s: float = 0.6
    max_attempts: int = 3
    backoff: float = 2.0
    timeout_s: float = 30.0


# Exceptions that mean "transient provider problem, retry then skip", never "bug".
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    requests.exceptions.RequestException,  # ReadTimeout, ConnectionError, HTTPError ...
    ValueError,  # json.JSONDecodeError (403 HTML body) is a ValueError
    KeyError,  # a result set missing from the response
)


class CallFailed(Exception):
    """Raised by CallRunner.call when every attempt failed."""

    def __init__(self, label: str, attempts: int, last_error: BaseException):
        """Remember the label, the attempts made and the last error."""
        super().__init__(f"{label}: {type(last_error).__name__} after {attempts} attempts: {last_error}")
        self.label = label
        self.attempts = attempts
        self.last_error = last_error


class CallRunner:
    """Enforces a minimum delay between network calls and retries transient failures.

    `sleep` and `clock` are injectable so tests run instantly.
    """

    def __init__(
        self,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a runner; `sleep` and `clock` are injectable so tests run instantly."""
        self.policy = policy or RetryPolicy()
        self._sleep = sleep
        self._clock = clock
        self._last_call_at: float | None = None
        self.calls = 0

    def _wait_for_slot(self) -> None:
        """Sleep long enough to keep the minimum delay since the previous call."""
        if self._last_call_at is None:
            return
        elapsed = self._clock() - self._last_call_at
        remaining = self.policy.delay_s - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def call(self, label: str, fn: Callable[[], T]) -> T:
        """Run `fn`, retrying transient failures with exponential backoff; raises CallFailed when every attempt failed."""
        last_error: BaseException | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self._wait_for_slot()
            self.calls += 1
            self._last_call_at = self._clock()
            try:
                return fn()
            except RETRYABLE_EXCEPTIONS as exc:  # noqa: PERF203
                last_error = exc
                log.warning("%s: attempt %d/%d failed: %s: %s", label, attempt, self.policy.max_attempts, type(exc).__name__, exc)
                if attempt < self.policy.max_attempts:
                    self._sleep(self.policy.delay_s * (self.policy.backoff ** (attempt - 1)))
        assert last_error is not None
        raise CallFailed(label, self.policy.max_attempts, last_error)


def utcnow() -> datetime:
    """The current time in UTC."""
    return datetime.now(timezone.utc)


class PlayerDataProvider(Protocol):
    """Shared surface: both providers implement it."""

    source: Source

    def fetch_player_pool(
        self, roster_season: str, on_progress: ProgressCallback | None = None
    ) -> tuple[list[PlayerBio], FetchReport]:
        """The player pool for a roster season as PlayerBios, with a report of the fetch."""

    def search_players(self, query: str, limit: int = 20) -> list[PlayerRef]:
        """Search players by name."""


class StatsProvider(PlayerDataProvider, Protocol):
    """nba_api: static reference data, game logs, career detail."""

    def list_players(self, active_only: bool = True) -> list[PlayerRef]:
        """The static player list (active players only by default)."""

    def list_teams(self) -> list[TeamRef]:
        """The static team list."""

    def fetch_game_logs(
        self,
        stats_season: str,
        player_ids: list[int],
        on_progress: ProgressCallback | None = None,
    ) -> tuple[dict[int, list[GameLine]], FetchReport]:
        """Game logs for the given players in a stats season, with a report (failures are listed, not raised)."""

    def fetch_player_detail(self, player_id: int) -> PlayerDetail:
        """One player's detail: bio facts and career season totals."""


class FantasyPlatformProvider(PlayerDataProvider, Protocol):
    """Sleeper: eligibility, injury status, platform state, league settings."""

    def fetch_fantasy_attributes(
        self, force: bool = False
    ) -> tuple[dict[str, FantasyAttributes], FetchReport]:
        """Fantasy attributes (positions, injuries, ranks, projections) by Sleeper id, with a report."""

    def fetch_platform_state(self) -> PlatformState:
        """The platform's current state (season, season type, week)."""

    def fetch_league(self, sleeper_league_id: str) -> PlatformLeague | None:
        """A league document from the platform, or None when it doesn't exist."""


def make_report(
    source: Source,
    operation: str,
    started_at: datetime,
    requested: int,
    succeeded: int,
    failed: dict[str, str] | None = None,
    endpoint_calls: int = 0,
    served_from_cache: bool = False,
) -> FetchReport:
    """Build a FetchReport finished now."""
    return FetchReport(
        source=source,
        operation=operation,
        started_at=started_at,
        finished_at=utcnow(),
        requested=requested,
        succeeded=succeeded,
        failed=failed or {},
        endpoint_calls=endpoint_calls,
        served_from_cache=served_from_cache,
    )


def emit(on_progress: ProgressCallback | None, done: int, total: int, label: str = "", failed: int = 0) -> None:
    """Report progress to the callback, if there is one."""
    if on_progress is not None:
        on_progress(FetchProgress(done=done, total=total, current_label=label, failed=failed))


def as_int(value: Any) -> int | None:
    """Lenient int parse: '243' -> 243, 'Undrafted' -> None, 20.0 -> 20, None -> None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
