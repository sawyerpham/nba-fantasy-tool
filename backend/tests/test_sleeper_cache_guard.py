
import json
from datetime import datetime, timedelta, timezone

import pytest
import requests

from nba_fantasy_shared.providers.base import CallFailed, CallRunner, RetryPolicy
from nba_fantasy_shared.providers.sleeper_provider import PLAYERS_CACHE_REL, SleeperProvider
from nba_fantasy_shared.storage import JsonStore

T0 = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    """A fake HTTP response with a status and payload."""
    def __init__(self, status_code: int, payload):
        """Store the status and payload."""
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        """Raise an HTTPError for status 400 and above."""
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        """The payload."""
        return self._payload


class FakeSession:
    """A fake requests session that serves canned routes and records the URLs."""
    def __init__(self, routes: dict):
        """Store the routes and start with no calls."""
        self.routes = routes
        self.calls: list[str] = []

    def get(self, url: str, timeout=None):
        """Record the URL and return its canned response."""
        self.calls.append(url)
        result = self.routes[url.split("/v1/")[1]]
        if isinstance(result, Exception):
            raise result
        return result


class Clock:
    """A controllable clock."""
    def __init__(self, start: datetime):
        """Start at a given time."""
        self.now = start

    def __call__(self) -> datetime:
        """The current fake time."""
        return self.now


@pytest.fixture
def payload(fixtures_dir):
    """The captured Sleeper players payload."""
    with (fixtures_dir / "sleeper/players_nba.json").open(encoding="utf-8") as fh:
        return json.load(fh)


def make(tmp_path, payload, routes=None):
    """A SleeperProvider over a fake session and clock, with a temp store."""
    session = FakeSession(routes or {"players/nba": FakeResponse(200, payload)})
    clock = Clock(T0)
    runner = CallRunner(RetryPolicy(delay_s=0, max_attempts=2), sleep=lambda s: None)
    provider = SleeperProvider(JsonStore(tmp_path), runner, session=session, now=clock)
    return provider, session, clock


def test_first_fetch_hits_network_second_within_24h_serves_cache(tmp_path, payload):
    """First fetch hits network second within 24h serves cache."""
    provider, session, clock = make(tmp_path, payload)
    bios, report = provider.fetch_player_pool("2026-27")
    assert not report.served_from_cache and report.endpoint_calls == 1 and len(session.calls) == 1
    assert provider.store.exists(PLAYERS_CACHE_REL)

    clock.now = T0 + timedelta(hours=23, minutes=59)
    fresh = SleeperProvider(provider.store, CallRunner(RetryPolicy(delay_s=0)), session=session, now=clock)  # new process
    bios2, report2 = fresh.fetch_player_pool("2026-27")
    assert report2.served_from_cache and report2.endpoint_calls == 0 and len(session.calls) == 1
    assert [b.source_id for b in bios2] == [b.source_id for b in bios]
    attrs, report3 = fresh.fetch_fantasy_attributes()
    assert report3.served_from_cache and len(session.calls) == 1 and "1658" in attrs


def test_refetches_after_24h_or_when_forced(tmp_path, payload):
    """Refetches after 24h or when forced."""
    provider, session, clock = make(tmp_path, payload)
    provider.fetch_player_pool("2026-27")
    clock.now = T0 + timedelta(hours=24, minutes=1)
    _, report = provider.fetch_player_pool("2026-27")
    assert not report.served_from_cache and len(session.calls) == 2

    _, report = provider.fetch_player_pool("2026-27", force=True)
    assert not report.served_from_cache and len(session.calls) == 3


def test_fetch_failure_falls_back_to_stale_cache(tmp_path, payload):
    """Fetch failure falls back to stale cache."""
    provider, session, clock = make(tmp_path, payload)
    provider.fetch_player_pool("2026-27")
    clock.now = T0 + timedelta(days=3)
    session.routes["players/nba"] = requests.exceptions.ConnectionError("down")
    _, report = provider.fetch_player_pool("2026-27")
    assert report.served_from_cache


def test_fetch_failure_without_cache_raises(tmp_path, payload):
    """Fetch failure without cache raises."""
    provider, _, _ = make(tmp_path, payload, routes={"players/nba": requests.exceptions.ReadTimeout("slow")})
    with pytest.raises(CallFailed):
        provider.fetch_player_pool("2026-27")


def test_league_404_returns_none_and_state_parses(tmp_path, payload):
    """League 404 returns none and state parses."""
    routes = {
        "players/nba": FakeResponse(200, payload),
        "league/1": FakeResponse(404, None),
        "state/nba": FakeResponse(200, {"season": "2026", "season_type": "off", "previous_season": "2025",
                                        "season_start_date": "2026-10-20", "week": 0}),
    }
    provider, session, _ = make(tmp_path, payload, routes=routes)
    assert provider.fetch_league("1") is None
    state = provider.fetch_platform_state()
    assert state.season == "2026" and state.previous_season == "2025"


def test_search_uses_cached_payload_only(tmp_path, payload):
    """Search uses cached payload only."""
    provider, session, _ = make(tmp_path, payload)
    assert provider.search_players("jokic") == []  # nothing cached yet, no network
    provider.fetch_player_pool("2026-27")
    hits = provider.search_players("jokic")
    assert hits and hits[0].full_name == "Nikola Jokić" and hits[0].player_id == -1658
    assert len(session.calls) == 1
