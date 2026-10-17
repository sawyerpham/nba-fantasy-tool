import requests

import pytest

from nba_fantasy_shared.providers.base import CallFailed, CallRunner, RetryPolicy


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def make_runner(**policy) -> tuple[CallRunner, FakeClock]:
    clock = FakeClock()
    runner = CallRunner(RetryPolicy(**policy), sleep=clock.sleep, clock=clock.now)
    return runner, clock


def test_retries_transient_errors_then_succeeds():
    runner, clock = make_runner(delay_s=0.5, max_attempts=3, backoff=2.0)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise requests.exceptions.ReadTimeout("slow")
        return "ok"

    assert runner.call("flaky", flaky) == "ok"
    assert attempts["n"] == 3
    assert runner.calls == 3
    assert clock.sleeps == [0.5, 1.0]  # backoff between retries


def test_gives_up_after_max_attempts_with_call_failed():
    runner, _ = make_runner(delay_s=0.1, max_attempts=2)

    def always_403_html():
        raise ValueError("Expecting value: line 1 column 1")  # json.loads on an HTML body

    with pytest.raises(CallFailed) as info:
        runner.call("commonplayerinfo", always_403_html)
    assert info.value.attempts == 2
    assert "ValueError" in str(info.value)


def test_non_transient_errors_propagate_immediately():
    runner, _ = make_runner(max_attempts=3)

    def bug():
        raise TypeError("programming error")

    with pytest.raises(TypeError):
        runner.call("bug", bug)
    assert runner.calls == 1


def test_enforces_minimum_delay_between_calls():
    runner, clock = make_runner(delay_s=0.6)
    runner.call("a", lambda: 1)
    clock.t += 0.2  # only 0.2s passed since the last call
    runner.call("b", lambda: 2)
    assert clock.sleeps == [pytest.approx(0.4)]
