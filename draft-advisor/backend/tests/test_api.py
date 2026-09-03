"""API layer end to end on the fixture world. The final test is the Phase 1D gate: export round trip."""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.app_state import AppState
from nba_fantasy_shared.models.export import DraftExport
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.storage import JsonStore

JOKIC, DONCIC, BUTLER, S_CURRY, SETH, WALKER = 203999, 1629029, 202710, 201939, 203552, 1629022
PROVISIONAL_LEAGUE = "000000000000000000"
NFL_LEAGUE = "289646328504385536"


@pytest.fixture(scope="module")
def env(tmp_path_factory, fixtures_dir):
    store = JsonStore(tmp_path_factory.mktemp("api-data"))
    state = AppState(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir))
    client = TestClient(create_app(state))
    return client, state, store, fixtures_dir


@pytest.fixture(scope="module")
def pulled(env):
    client, state, *_ = env
    r = client.post("/api/data/pull", json={})
    assert r.status_code == 202 and r.json()["state"] in ("running", "done")
    state.join_pull(timeout=30)
    status = client.get("/api/data/pull/status").json()
    assert status["state"] == "done", status
    return env


def league(client, league_id="lg1", name="League One"):
    r = client.post("/api/leagues", json={"league_id": league_id, "name": name})
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------ data

def test_health_and_empty_status_before_pull(env):
    client, state, *_ = env
    assert client.get("/api/health").json()["ok"] is True
    status = client.get("/api/data/status").json()
    assert status["pull"]["state"] in ("idle", "running", "done")


def test_pull_reports_progress_and_reloads_the_pool(pulled):
    client, state, *_ = pulled
    status = client.get("/api/data/pull/status").json()
    assert status["state"] == "done" and status["records"] == 23 and status["game_log_players"] == 19
    assert [r["source"] for r in status["reports"]] == ["nba_api", "sleeper", "sleeper", "nba_api"]
    assert status["reconcile_counts"]["name_team"] == 15
    data = client.get("/api/data/status").json()
    assert data["players"] == 23 and data["caches"]["game_logs_hours"] is not None
    assert data["reconcile"]["counts"]["sleeper_only"] == 1
    assert client.get("/api/health").json()["players"] == 23


def test_second_pull_request_while_running_is_rejected(pulled):
    client, state, *_ = pulled
    gate = threading.Event()
    blocker = threading.Thread(target=gate.wait, daemon=True)
    blocker.start()
    original = state._pull_thread
    state._pull_thread = blocker
    try:
        assert client.post("/api/data/pull", json={}).status_code == 409
    finally:
        gate.set()
        blocker.join()
        state._pull_thread = original


# ------------------------------------------------------------------ players

def test_player_search_is_accent_insensitive_and_marks_drafted(pulled):
    client, *_ = pulled
    hits = client.get("/api/players", params={"q": "jok"}).json()
    assert hits[0]["player_id"] == JOKIC and hits[0]["eligibility"] == ["C"] and hits[0]["injury_status"] == "healthy"
    curries = {h["full_name"] for h in client.get("/api/players", params={"q": "curry"}).json()}
    assert curries == {"Stephen Curry", "Seth Curry"}
    assert client.get("/api/players", params={"q": "zzz"}).json() == []


def test_player_detail_with_valuation_and_history(pulled):
    client, *_ = pulled
    body = client.get(f"/api/players/{JOKIC}").json()
    assert body["record"]["team_abbr"] == "DEN" and body["overrides"]["eligibility_source"] == "sleeper"
    assert body["valuation"]["bonus_counts"]["triple_double"] == 34
    assert len(body["detail"]["season_totals"]) == 11 and body["detail"]["birthdate"] == "1995-02-19"
    no_hist = client.get(f"/api/players/{S_CURRY}", params={"include_history": "false"}).json()
    assert no_hist["detail"] is None and no_hist["valuation"]["games_played"] > 0
    assert client.get("/api/players/1").status_code == 404


def test_override_patch_and_reset_track_sources(pulled):
    client, state, *_ = pulled
    r = client.patch(f"/api/players/{BUTLER}/overrides", json={"injury_status": "out_long_term", "injury_note": "Knee, out until Jan"})
    assert r.status_code == 200
    assert r.json()["injury_status"] == "out_long_term" and r.json()["injury_source"] == "manual"
    assert r.json()["eligibility_source"] == "sleeper"  # untouched field keeps its source
    r = client.patch(f"/api/players/{BUTLER}/overrides", json={"eligibility": ["SF", "PF", "SG"]})
    assert r.json()["eligibility"] == ["SF", "PF", "SG"] and r.json()["eligibility_source"] == "manual"
    assert state.overrides[BUTLER].injury_status == "out_long_term"  # persisted in memory
    assert json.loads(state.store.path("player_overrides.json").read_text(encoding="utf-8"))[str(BUTLER)]["injury_source"] == "manual"
    r = client.post(f"/api/players/{BUTLER}/overrides/reset", json={"fields": ["injury", "eligibility"]})
    assert r.json()["injury_status"] == "out_short_term" and r.json()["injury_source"] == "sleeper"
    assert r.json()["injury_note"] == "Knee — Surgery" and r.json()["eligibility_source"] == "sleeper"
    assert client.patch(f"/api/players/{BUTLER}/overrides", json={}).status_code == 400
    assert client.patch("/api/players/1/overrides", json={"notes": "x"}).status_code == 404
    assert client.patch(f"/api/players/{BUTLER}/overrides", json={"injury_status": "bogus"}).status_code == 422


# ------------------------------------------------------------------ leagues

def test_create_list_get_delete_league(pulled):
    client, *_ = pulled
    doc = league(client, "tmp", "Temp")
    assert doc["schema_version"] == 1 and len(doc["managers"]) == 12 and doc["draft"]["status"] == "setup"
    assert doc["league"]["roster_season"] == "2026-27" and doc["league"]["budget_per_manager"] == 200
    assert client.post("/api/leagues", json={"league_id": "tmp", "name": "dup"}).status_code == 409
    assert client.post("/api/leagues", json={"league_id": "bad id!", "name": "x"}).status_code == 400
    assert {row["league_id"] for row in client.get("/api/leagues").json()} >= {"tmp"}
    assert client.get("/api/leagues/tmp").json()["league"]["name"] == "Temp"
    assert client.delete("/api/leagues/tmp").status_code == 204
    assert client.get("/api/leagues/tmp").status_code == 404
    assert client.get("/api/leagues/tmp/draft").status_code == 404


def test_settings_put_recomputes_valuations_and_validates(pulled):
    client, state, *_ = pulled
    league(client, "lg-settings", "Settings")
    before = client.get(f"/api/players/{JOKIC}", params={"league_id": "lg-settings", "include_history": "false"}).json()["valuation"]["avg_fpts"]
    settings = client.get("/api/leagues/lg-settings/settings").json()
    settings["scoring"]["base"]["pts"] = 1.0
    settings["ranking"]["min_games_full_confidence"] = 10
    settings["keeper"]["max_per_manager"] = 2
    r = client.put("/api/leagues/lg-settings/settings", json=settings)
    assert r.status_code == 200 and r.json()["scoring"]["base"]["pts"] == 1.0 and r.json()["keeper"]["max_per_manager"] == 2
    after = client.get(f"/api/players/{JOKIC}", params={"league_id": "lg-settings", "include_history": "false"}).json()["valuation"]["avg_fpts"]
    assert after > before
    assert client.get("/api/leagues/lg-settings").json()["league"]["scoring"]["base"]["pts"] == 1.0  # persisted
    settings["budget_per_manager"] = 10  # cannot fill 15 mandatory slots at $1
    assert client.put("/api/leagues/lg-settings/settings", json=settings).status_code in (400, 422)
    settings["budget_per_manager"] = 200
    settings["league_id"] = "other"
    assert client.put("/api/leagues/lg-settings/settings", json=settings).status_code == 400


def test_managers_endpoints(pulled):
    client, *_ = pulled
    league(client, "lg-managers", "Managers")
    r = client.patch("/api/leagues/lg-managers/managers/m2", json={"name": "Early Eddie", "behavior": {"spend_pace": "early", "aggression": 1.2}})
    assert r.status_code == 200 and r.json()["behavior"]["spend_pace"] == "early"
    r = client.patch("/api/leagues/lg-managers/managers/m3", json={"is_user": True})
    managers = client.get("/api/leagues/lg-managers/managers").json()
    assert [m["manager_id"] for m in managers if m["is_user"]] == ["m3"]
    assert client.patch("/api/leagues/lg-managers/managers/m99", json={"name": "x"}).status_code == 404
    two = [{"manager_id": "a", "name": "A", "is_user": True, "budget_total": 200}, {"manager_id": "b", "name": "B", "budget_total": 200}]
    r = client.put("/api/leagues/lg-managers/managers", json=two)
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.get("/api/leagues/lg-managers/draft").json()["nomination_order"] == ["a", "b"]
    assert client.get("/api/leagues/lg-managers/settings").json()["num_managers"] == 2
    assert client.put("/api/leagues/lg-managers/managers", json=[two[1]]).status_code == 400  # nobody is the user


def test_keeper_evaluate_endpoint(pulled):
    client, *_ = pulled
    league(client, "lg-keep", "Keeper check")
    r = client.post("/api/leagues/lg-keep/keepers/evaluate", json={"candidates": [
        {"manager_id": "m1", "player_id": JOKIC, "last_price": 17},
        {"manager_id": "m1", "player_id": WALKER, "last_price": 17, "keeper_price": 3},
    ]})
    assert r.status_code == 200, r.text
    jokic, walker = r.json()
    assert jokic["keeper_price"] == 20 and jokic["verdict"] == "good" and jokic["full_name"] == "Nikola Jokić"
    assert walker["keeper_price"] == 3 and walker["computed_price"] == 20 and walker["verdict"] in ("bad", "even")
    assert client.post("/api/leagues/lg-keep/keepers/evaluate", json={"candidates": [{"manager_id": "m1", "player_id": 1, "last_price": 5}]}).status_code == 400
    # the rule itself is a league setting
    settings = client.get("/api/leagues/lg-keep/settings").json()
    assert settings["keeper"]["escalation"] == {"enabled": True, "step_dollars": 5, "increase_per_step": 1}
    settings["keeper"]["escalation"]["increase_per_step"] = 2
    assert client.put("/api/leagues/lg-keep/settings", json=settings).status_code == 200
    r = client.post("/api/leagues/lg-keep/keepers/evaluate", json={"candidates": [{"manager_id": "m1", "player_id": JOKIC, "last_price": 17}]})
    assert r.json()[0]["keeper_price"] == 23


def test_keeper_history_put_validates_max_per_manager(pulled):
    client, *_ = pulled
    league(client, "lg-keepers", "Keepers")
    rec = {"season": "2025-26", "manager_id": "m1", "player_id": JOKIC, "player_name": "Nikola Jokić", "cost": {"type": "auction", "amount": 55}}
    assert client.put("/api/leagues/lg-keepers/keepers/history", json={"records": [rec, {**rec, "player_id": DONCIC}]}).status_code == 400
    r = client.put("/api/leagues/lg-keepers/keepers/history", json={"records": [rec, {**rec, "manager_id": "m2", "player_id": DONCIC}]})
    assert r.status_code == 200 and len(r.json()["records"]) == 2
    assert len(client.get("/api/leagues/lg-keepers/keepers/history").json()["records"]) == 2
    assert len(client.get("/api/leagues/lg-keepers").json()["keepers"]["history"]) == 2


def test_sleeper_preview_and_apply(pulled):
    client, *_ = pulled
    league(client, "lg-sleeper", "Sleeper Test")
    r = client.post("/api/leagues/lg-sleeper/sleeper/preview", json={"sleeper_league_id": PROVISIONAL_LEAGUE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["scoring_map"]["provisional"] is True and body["scoring_map"]["unknown_keys"] == []
    assert [d["field"] for d in body["diffs"]] == ["name"]  # provisional fixture mirrors SPEC defaults exactly
    r = client.post("/api/leagues/lg-sleeper/sleeper/apply", json={"sleeper_league_id": PROVISIONAL_LEAGUE, "apply": ["name", "scoring", "roster_slots", "keepers"]})
    assert r.status_code == 200
    assert r.json()["name"] == "Provisional NBA league fixture" and r.json()["scoring"]["source"] == "sleeper"
    assert r.json()["sleeper_league_id"] == PROVISIONAL_LEAGUE and r.json()["keeper"]["max_per_manager"] == 1
    assert client.post("/api/leagues/lg-sleeper/sleeper/preview", json={"sleeper_league_id": NFL_LEAGUE}).status_code == 400
    assert client.post("/api/leagues/lg-sleeper/sleeper/preview", json={"sleeper_league_id": "1"}).status_code == 404


# ------------------------------------------------------------------ draft

def test_full_draft_flow_over_the_api(pulled):
    client, state, *_ = pulled
    league(client, "lg-draft", "Draft")
    top = client.get("/api/leagues/lg-draft/rankings", params={"limit": 3}).json()
    assert top[0]["player_id"] == JOKIC and top[0]["rank"] == 1 and top[0]["rosterable"]

    r = client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": JOKIC, "manager_id": "m1", "price": 10})
    assert r.status_code == 400 and "not live" in r.json()["detail"]
    r = client.post("/api/leagues/lg-draft/draft/start", json={"keepers": [{"manager_id": "m3", "player_id": DONCIC, "cost": 50}]})
    assert r.status_code == 200
    view = r.json()
    assert view["status"] == "live" and view["next_nominator"] == "m1" and view["picks"][0]["is_keeper"] is True
    m3 = next(m for m in view["managers"] if m["manager_id"] == "m3")
    assert m3["budget"]["remaining"] == 150 and m3["budget"]["open_mandatory"] == 14 and m3["open_slots"]["PG"] == 0

    r = client.post("/api/leagues/lg-draft/draft/nominate", json={"player_id": JOKIC, "manager_id": "m2"})
    assert r.status_code == 400 and "m1's turn" in r.json()["detail"]
    r = client.post("/api/leagues/lg-draft/draft/nominate", json={"player_id": JOKIC})
    assert r.json()["current_nomination"]["nominated_by"] == "m1"

    rec = client.get(f"/api/leagues/lg-draft/recommend/{JOKIC}").json()
    assert rec["can_bid"] and rec["my_max_bid"] == 186 and 1 <= rec["recommended_max"] <= 186 and rec["rationale"]
    assert client.get("/api/leagues/lg-draft/recommend/1").status_code == 400

    r = client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": JOKIC, "manager_id": "m1", "price": 187})
    assert r.status_code == 400 and "exceeds max bid" in r.json()["detail"]
    r = client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": JOKIC, "manager_id": "m1", "price": rec["recommended_max"]})
    assert r.status_code == 200 and r.json()["picks"][-1]["nominated_by"] == "m1" and r.json()["next_nominator"] == "m2"
    assert all(row["player_id"] != JOKIC for row in client.get("/api/leagues/lg-draft/rankings").json())
    assert client.post("/api/leagues/lg-draft/draft/undo").json()["next_nominator"] == "m1"
    assert client.get("/api/leagues/lg-draft/rankings", params={"limit": 1}).json()[0]["player_id"] == JOKIC
    r = client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": JOKIC, "manager_id": "m1", "price": 70, "slot": "UTIL"})
    assert r.json()["picks"][-1]["slot"] == "UTIL"
    r = client.post("/api/leagues/lg-draft/draft/reassign", json={"pick_number": 2, "slot": "C"})
    assert r.json()["picks"][-1]["slot"] == "C"
    r = client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": BUTLER, "manager_id": "m2", "price": 12})
    assert r.json()["next_nominator"] == "m3" and r.json()["progress"] == pytest.approx(2 / 179, abs=1e-4)

    walker = next(row for row in client.get("/api/leagues/lg-draft/rankings").json() if row["player_id"] == WALKER)
    assert walker["stack_if_added"] == 2  # DEN with Jokić
    hits = client.get("/api/players", params={"q": "jok", "league_id": "lg-draft"}).json()
    assert hits[0]["drafted_by"] == "m1"
    everyone = client.get("/api/leagues/lg-draft/rankings", params={"include_unrosterable": "true"}).json()
    assert len(everyone) == 23 - 3
    r = client.put("/api/leagues/lg-draft/draft/nomination-order", json={"order": ["m12"] + [f"m{i}" for i in range(1, 12)]})
    assert r.status_code == 200 and r.json()["nomination_order"][0] == "m12"
    assert r.json()["next_nominator"] == "m3"  # reordering on the fly keeps whose turn it is
    assert client.put("/api/leagues/lg-draft/draft/nomination-order", json={"order": ["m1"]}).status_code == 400
    r = client.put("/api/leagues/lg-draft/draft/next-nominator", json={"manager_id": "m8"})
    assert r.status_code == 200 and r.json()["next_nominator"] == "m8"
    assert client.put("/api/leagues/lg-draft/draft/next-nominator", json={"manager_id": "m99"}).status_code == 400

    # persisted: a fresh AppState over the same store sees the same draft
    fresh = AppState(state.store, state.stats, state.platform)
    s2 = fresh.get_session("lg-draft")
    assert len(s2.draft.picks) == 3 and s2.engine.budget("m1").remaining == 130 and s2.draft.status == "live"
    assert client.post("/api/leagues/lg-draft/draft/complete").json()["status"] == "complete"
    assert client.post("/api/leagues/lg-draft/draft/pick", json={"player_id": SETH, "manager_id": "m4", "price": 1}).status_code == 400


def test_settings_managers_keepers_and_scoring_are_editable_mid_draft(pulled):
    """SPEC Definition of Done: league settings editable both at setup and mid-draft."""
    client, state, *_ = pulled
    league(client, "lg-mid", "Mid-draft edits")
    assert client.post("/api/leagues/lg-mid/draft/start", json={"keepers": []}).status_code == 200
    assert client.post("/api/leagues/lg-mid/draft/pick", json={"player_id": JOKIC, "manager_id": "m2", "price": 60}).status_code == 200
    before = client.get("/api/leagues/lg-mid/rankings", params={"limit": 1}).json()[0]

    # per-category point values + bonus threshold, while live -> valuations and rankings change immediately
    settings = client.get("/api/leagues/lg-mid/settings").json()
    settings["scoring"]["base"]["ast"] = 3.0
    settings["scoring"]["bonuses"][1]["threshold"] = 30  # pts_40 -> 30+
    settings["ranking"]["weight_ceiling"] = 0.0
    assert client.put("/api/leagues/lg-mid/settings", json=settings).status_code == 200
    after = client.get("/api/leagues/lg-mid/rankings", params={"limit": 1}).json()[0]
    assert after["avg_fpts"] != before["avg_fpts"] or after["player_id"] != before["player_id"]
    assert client.get("/api/leagues/lg-mid/draft").json()["status"] == "live"  # draft untouched

    # roster slots + budget while live: budgets and open slots recompute for every manager
    settings = client.get("/api/leagues/lg-mid/settings").json()
    settings["roster_slots"] = [s for s in settings["roster_slots"] if s["slot"] != "BN"] + [{"slot": "BN", "count": 6}]
    settings["budget_per_manager"] = 250
    assert client.put("/api/leagues/lg-mid/settings", json=settings).status_code == 200
    view = client.get("/api/leagues/lg-mid/draft").json()
    m2 = next(m for m in view["managers"] if m["manager_id"] == "m2")
    assert m2["budget"]["open_mandatory"] == 12 and m2["open_slots"]["BN"] == 6
    # per-manager budget edit mid-draft (Sleeper budgets are per manager)
    r = client.patch("/api/leagues/lg-mid/managers/m2", json={"budget_total": 250, "name": "Renamed"})
    assert r.status_code == 200
    m2 = next(m for m in client.get("/api/leagues/lg-mid/draft").json()["managers"] if m["manager_id"] == "m2")
    assert m2["budget"]["remaining"] == 190 and m2["name"] == "Renamed"

    # nomination order and keeper history while live
    order = [f"m{i}" for i in range(12, 0, -1)]
    assert client.put("/api/leagues/lg-mid/draft/nomination-order", json={"order": order}).json()["nomination_order"] == order
    rec = {"season": "2025-26", "manager_id": "m4", "player_id": DONCIC, "player_name": "Luka Dončić", "cost": {"type": "auction", "amount": 61}}
    assert client.put("/api/leagues/lg-mid/keepers/history", json={"records": [rec]}).status_code == 200
    assert client.get("/api/leagues/lg-mid").json()["keepers"]["history"][0]["cost"]["amount"] == 61
    assert client.get("/api/leagues/lg-mid/draft").json()["status"] == "live"


# ------------------------------------------------------------------ gate: export round trip

def _comparable(doc: DraftExport) -> dict:
    return doc.model_dump(mode="json", exclude={"generated_at"})


def test_gate_export_round_trips_with_no_data_loss(pulled):
    client, state, store, _ = pulled
    league(client, "lg-export", "Export League")
    client.patch(f"/api/players/{S_CURRY}/overrides", json={"injury_status": "day_to_day", "notes": "watch minutes"})
    r = client.post("/api/leagues/lg-export/draft/start", json={"keepers": [{"manager_id": "m3", "player_id": DONCIC, "cost": 50}]})
    assert r.status_code == 200
    for pid, mgr, price in [(JOKIC, "m1", 70), (BUTLER, "m2", 12), (S_CURRY, "m1", 25), (WALKER, "m4", 1)]:
        assert client.post("/api/leagues/lg-export/draft/pick", json={"player_id": pid, "manager_id": mgr, "price": price}).status_code == 200

    r = client.post("/api/leagues/lg-export/export")
    assert r.status_code == 200
    body = r.json()
    on_disk = json.loads(store.path(body["relative_path"]).read_text(encoding="utf-8"))
    assert on_disk == body["document"]

    exported = DraftExport.model_validate(on_disk)                      # parses under the versioned model
    assert exported.schema_version == 1 and exported.generated_by == "draft-advisor"
    session = state.get_session("lg-export")
    assert _comparable(exported) == _comparable(session.to_export())    # byte-for-byte the session's state
    assert _comparable(DraftExport.model_validate_json(exported.model_dump_json())) == _comparable(exported)

    # every drafted player carries record + overrides + valuation; keepers and history are present
    assert set(exported.players) == {str(p) for p in (DONCIC, JOKIC, BUTLER, S_CURRY, WALKER)}
    curry = exported.players[str(S_CURRY)]
    assert curry.overrides.injury_status == "day_to_day" and curry.overrides.notes == "watch minutes" and curry.overrides.injury_source == "manual"
    assert exported.players[str(JOKIC)].valuation.bonus_counts["triple_double"] == 34
    assert exported.players[str(WALKER)].valuation.games_played == 0 and exported.players[str(WALKER)].record.match_method == "static_list"
    assert [k.player_id for k in exported.keepers.current] == [DONCIC]
    assert exported.keepers.history[0].player_id == DONCIC and exported.keepers.history[0].season == "2026-27"
    assert [p.player_id for p in exported.draft.picks] == [DONCIC, JOKIC, BUTLER, S_CURRY, WALKER]
    assert exported.league.mandatory_slot_count() == 15 and exported.league.total_slot_count() == 17

    # the league file on disk is the same document, and a fresh process restores an identical session
    assert _comparable(DraftExport.model_validate(store.read_json("leagues/lg-export.json"))) == _comparable(exported)
    fresh = AppState(store, state.stats, state.platform)
    restored = fresh.get_session("lg-export")
    assert _comparable(restored.to_export()) == _comparable(exported)
    assert restored.engine.budget("m1").remaining == 105 and restored.engine.next_nominator() == "m5"
    assert restored.rankings()[0].player_id not in {JOKIC, DONCIC}
    # and the snapshot alone (no pool) still restores the drafted players
    from app.engine.session import DraftSession
    lonely = DraftSession.from_export(exported, {}, {}, {})
    assert {p.player_id for p in lonely.draft.picks} <= set(lonely.players)
    assert lonely.engine.budget("m3").remaining == 150
