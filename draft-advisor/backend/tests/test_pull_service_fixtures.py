"""End-to-end pull through PullService using the captured fixtures (no network)."""

import json

import pytest

from app import config
from app.core.services.pull_service import PullService, load_game_logs, load_overrides, load_records, save_overrides
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.storage import JsonStore

JOKIC, BUTLER, ADAMS, KUMINGA, SETH_CURRY, NELSON_JR = 203999, 202710, 203500, 1630228, 203552, 1642392
WALKER, DEROZAN, BITTLE, ODURO, HALIBURTON = 1629022, 201942, 1642927, -2871, 1630169


@pytest.fixture
def service(tmp_path, fixtures_dir):
    store = JsonStore(tmp_path)
    return PullService(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir))


def test_full_pull_from_fixtures(service):
    status = service.run()
    assert status.state == "done", status.error
    assert service.roster_season == "2026-27" and service.stats_season == "2025-26"  # derived from Sleeper state
    assert status.reconcile.counts == {
        "name_team": 15, "name_only": 3, "birthdate": 1, "nba_only": 1, "static_list": 2, "sleeper_only": 1,
    }
    rep = status.reconcile
    assert rep.sleeper_all_size == 23 and rep.sleeper_rostered_size == 20 and rep.nba_pool_size == 20
    assert [c["name"] for c in rep.team_conflicts] == ["Jonathan Kuminga", "Bennedict Mathurin"]
    assert [u["name"] for u in rep.unmatched_nba] == ["Nate Bittle"]
    assert [u["name"] for u in rep.unmatched_sleeper] == ["Josh Oduro"]
    assert rep.collisions[0]["name"] == "Jameer Nelson Jr." and rep.collisions[0]["resolved"]

    records = {r.player_id: r for r in load_records(service.store, "2026-27")}
    assert len(records) == 23
    assert records[KUMINGA].team_abbr == "MIN" and records[KUMINGA].team_conflict == {"nba_api": "ATL", "sleeper": "MIN"}
    assert records[SETH_CURRY].unsigned_per_sleeper and records[SETH_CURRY].team_abbr == "GSW" and records[SETH_CURRY].sleeper_status == "FA"
    assert records[NELSON_JR].match_method == "birthdate" and records[NELSON_JR].sleeper_id == "2808"
    assert records[WALKER].match_method == "static_list" and records[WALKER].team_abbr == "DEN" and records[WALKER].has_stats
    assert records[ODURO].match_method == "sleeper_only" and not records[ODURO].has_stats and records[ODURO].sleeper_status == "TWO-WAY"
    assert records[BITTLE].match_method == "nba_only" and records[BITTLE].fantasy is None
    assert records[JOKIC].bio.birthdate is not None and records[JOKIC].bio.age == 31.0

    logs = load_game_logs(service.store, "2025-26")
    assert len(logs[JOKIC]) == 65 and logs[JOKIC][0].game_date.isoformat() == "2025-10-23"
    assert logs[WALKER] == []  # per-player fallback fixture with zero games
    assert DEROZAN in logs and len(logs[DEROZAN]) > 0
    assert ODURO not in logs and BITTLE not in logs
    log_report = next(r for r in status.reports if r.operation == "game_logs")
    # Players absent from the batch and without a per-player fixture are listed, never silently dropped:
    # Bittle (rookie), Haliburton (missed 2025-26), Nelson Jr. (rookie). Live, the per-player fallback returns 0 rows.
    assert log_report.failed == {str(BITTLE): "fixture missing", str(HALIBURTON): "fixture missing", str(NELSON_JR): "fixture missing"}
    assert log_report.requested == 22 and log_report.succeeded == 19

    overrides = load_overrides(service.store)
    assert overrides[JOKIC].eligibility == ["C"] and overrides[JOKIC].eligibility_source == "sleeper"
    assert overrides[JOKIC].injury_status == "healthy" and overrides[JOKIC].injury_source == "sleeper"
    assert overrides[BUTLER].injury_status == "out_short_term" and overrides[BUTLER].injury_note == "Knee — Surgery"
    assert overrides[BUTLER].injury_sleeper_raw == "Out"
    # fixture state is the off-season: DTD seeds as healthy, Sleeper's raw tag is kept
    assert overrides[ADAMS].injury_status == "healthy" and overrides[ADAMS].injury_sleeper_raw == "DTD"
    assert overrides[BITTLE].eligibility == [] and overrides[BITTLE].eligibility_source == "none" and overrides[BITTLE].injury_source == "none"
    assert overrides[ODURO].eligibility_source == "sleeper"
    assert status.seeded_overrides == 22

    # every cache file from DESIGN.md 1.8 exists
    for rel in (config.nba_pool_rel("2026-27"), config.game_logs_rel("2025-26"), config.reconcile_rel("2026-27"),
                config.OVERRIDES_REL, config.player_detail_rel(NELSON_JR)):
        assert service.store.exists(rel), rel


def test_second_pull_reseeds_from_sleeper_and_keeps_notes(service):
    assert service.run().state == "done"
    overrides = load_overrides(service.store)
    jokic = overrides[JOKIC]
    jokic.eligibility, jokic.eligibility_source, jokic.notes = ["C", "PF"], "manual", "my note"
    adams = overrides[ADAMS]
    adams.injury_status, adams.injury_source = "out_season", "sleeper"  # a stale sleeper-sourced value
    save_overrides(service.store, overrides)

    assert service.run(skip_game_logs=True).state == "done"
    after = load_overrides(service.store)
    assert after[JOKIC].eligibility == ["C"] and after[JOKIC].eligibility_source == "sleeper" and after[JOKIC].notes == "my note"
    assert after[ADAMS].injury_status == "healthy" and after[ADAMS].injury_source == "sleeper"  # refreshed (off-season DTD)

def test_pull_without_sleeper_source_yields_nba_only_records(service):
    status = service.run(sources=["nba_api"], skip_game_logs=True)
    assert status.state == "done"
    assert status.reconcile.counts == {"nba_only": 20}
    overrides = load_overrides(service.store)
    assert all(o.eligibility_source == "none" for o in overrides.values())


def test_status_as_dict_is_json_serializable(service):
    status = service.run(skip_game_logs=True)
    json.dumps(status.as_dict())
