from datetime import datetime, timezone

from app.notify import due, title

NOW = datetime(2026, 11, 8, 1, 0, tzinfo=timezone.utc)


def test_due_sends_once_inside_the_alarm_window():
    swap = {"kind": "swap", "sid": "1", "backup_sid": "2", "alarm": "2026-11-08T00:55Z", "by": "2026-11-08T01:10Z"}
    late = {"kind": "gtd", "sid": "3", "alarm": "2026-11-08T01:30Z", "by": "2026-11-08T02:00Z"}   # alarm not reached
    gone = {"kind": "gtd", "sid": "4", "alarm": "2026-11-08T00:00Z", "by": "2026-11-08T00:30Z"}   # tip already passed
    out = {"kind": "out", "sid": "5", "alarm": "now", "by": "2026-11-08T02:00Z"}
    got = due([swap, late, gone, out], "2026-11-08", NOW, set())
    assert [w["sid"] for _, w in got] == ["1", "5"]
    assert not due([swap], "2026-11-08", NOW, {k for k, _ in got})


def test_title():
    assert title({"kind": "out", "name": "A"}) == "A OUT: bench"
    assert title({"kind": "swap", "name": "A", "backup": "B", "decision": "SWAP"}) == "SWAP: bench A, start B"
