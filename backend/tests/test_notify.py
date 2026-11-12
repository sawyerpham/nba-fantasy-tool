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


def test_lineup_moves_are_due_before_the_tip_they_must_beat_in_one_message():
    from zoneinfo import ZoneInfo

    from app.notify import move_lines, moves_text
    moves = [{"sid": "1", "name": "Harden", "from": "BN", "to": "PG", "by": "2026-11-08T01:20Z"},    # due: 30 min before
             {"sid": "2", "name": "Sharpe", "from": "BN", "to": "C", "by": "2026-11-08T02:00Z"},     # not yet
             {"sid": "3", "name": "Dunn", "from": "PG", "to": "BN", "by": None}]                     # no deadline: rides along
    got = due(move_lines(moves), "2026-11-08", NOW, set())
    assert [m["sid"] for _, m in got] == ["1"]
    text = moves_text([m for _, m in got], [m for m in moves if not m["by"]], ZoneInfo("America/New_York"))
    assert text == "Set your lineup before 8:20 PM:\nHarden: BN → PG\nDunn: PG → BN"
    assert not due(move_lines(moves), "2026-11-08", NOW, {k for k, _ in got})


def test_title():
    assert title({"kind": "out", "name": "A"}) == "A OUT: bench"
    assert title({"kind": "swap", "name": "A", "backup": "B", "decision": "SWAP"}) == "SWAP: bench A, start B"


def test_prefs_gate_lines_and_a_lock_call_needs_its_wpa():
    from app.notify import NotifyPrefs, wanted

    prefs = NotifyPrefs(lock_min_wpa=5, swap=False).model_dump()
    players = {"1": {"sid": "1", "win_lock": 0.71, "win_wait": 0.64}, "2": {"sid": "2", "win_lock": 0.60, "win_wait": 0.58}}
    assert wanted({"kind": "lock", "sid": "1"}, prefs, players)             # locking adds 7 points
    assert not wanted({"kind": "lock", "sid": "2"}, prefs, players)         # only 2
    assert not wanted({"kind": "lock", "sid": "9"}, prefs, players)         # win chances unknown: not above a threshold
    assert wanted({"kind": "lock", "sid": "9"}, NotifyPrefs().model_dump(), players)   # threshold 0: every lock call
    assert not wanted({"kind": "swap", "sid": "1"}, prefs, players) and wanted({"kind": "gtd", "sid": "1"}, prefs, players)
    assert wanted({"kind": "status", "change": "cleared"}, prefs, players)
    assert not wanted({"kind": "status", "change": "out"}, {**prefs, "out": False}, players)


def test_status_changes_on_your_roster_after_the_first_poll():
    from app.notify import status_lines

    seen = {}
    players = {"1": {"name": "A", "injury_tag": "GTD", "injury_note": "GTD: Knee - Soreness"}, "2": {"name": "B", "injury_tag": None},
               "3": {"name": "C", "injury_tag": "Out"}}
    assert status_lines(seen, players, ["1", "2", "3"]) == []               # first poll: baseline only
    players = {"1": {"name": "A", "injury_tag": None}, "2": {"name": "B", "injury_tag": "Out", "injury_note": "Out: Ankle - Sprain"},
               "3": {"name": "C", "injury_tag": "DTD", "injury_note": "DTD"}}
    got = status_lines(seen, players, ["1", "2", "3"])
    assert [(w["change"], w["text"]) for w in got] == [("cleared", "A cleared to play (was GTD)"), ("out", "B is now Out: Ankle - Sprain"),
                                                       ("dtd", "C is now DTD")]
    assert all(w["kind"] == "status" and w["alarm"] == "now" for w in got)
    assert status_lines(seen, players, ["1", "2", "3"]) == []               # nothing changed since
    assert [k for k, _ in due(got, "2026-11-12", NOW, set())] == ["2026-11-12|status|1|ok", "2026-11-12|status|2|Out", "2026-11-12|status|3|DTD"]


def test_notify_api_reports_the_link_and_saves_the_prefs(tmp_path, fixtures_dir, monkeypatch):
    from fastapi.testclient import TestClient

    from app import notify
    from app.core.services.app_state import AppState
    from app.main import create_app
    from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
    from nba_fantasy_shared.storage import JsonStore

    monkeypatch.setattr(notify, "load_env", lambda *a, **k: None)   # never the developer's own .env
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    store = JsonStore(tmp_path)
    client = TestClient(create_app(AppState(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir))))
    r = client.get("/api/notify")
    assert r.status_code == 200 and r.json() == {"configured": False, "prefs": notify.NotifyPrefs().model_dump()}
    r = client.put("/api/notify/prefs", json={"lock": False, "lock_min_wpa": 5})
    assert r.status_code == 200 and r.json()["lock"] is False and r.json()["lock_min_wpa"] == 5 and r.json()["swap"] is True
    assert client.get("/api/notify").json()["prefs"] == r.json() and notify.read_prefs(store) == r.json()
    assert client.put("/api/notify/prefs", json={"lock_min_wpa": 500}).status_code == 422
