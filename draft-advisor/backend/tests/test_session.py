"""DraftSession on the real fixture world: rankings, recommendation, picks, stacking, export round trip."""

import json

import pytest

from app.engine.draft_state import DraftError, KeeperAssignment
from app.engine.session import DraftSession
from app.services.pull_service import PullService, load_overrides, load_records
from app.services.valuation_service import ValuationService
from nba_fantasy_shared.models.draft import DraftState, KeeperHistory
from nba_fantasy_shared.models.export import SCHEMA_VERSION, DraftExport
from nba_fantasy_shared.models.league import KeeperSettings, LeagueSettings, Manager
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.storage import JsonStore

JOKIC, WALKER, DONCIC, BUTLER, ODURO = 203999, 1629022, 1629029, 202710, -2871


@pytest.fixture(scope="module")
def fixture_world(tmp_path_factory, fixtures_dir):
    store = JsonStore(tmp_path_factory.mktemp("data"))
    assert PullService(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir)).run().state == "done"
    players = {r.player_id: r for r in load_records(store, "2026-27")}
    overrides = load_overrides(store)
    valuations = ValuationService(store, "2025-26").compute(ScoringSettings())
    return players, overrides, valuations


def make_session(fixture_world, **league_kw) -> DraftSession:
    players, overrides, valuations = fixture_world
    league = LeagueSettings(league_id="lg1", name="Fixture League", **league_kw)
    managers = [Manager(manager_id=f"m{i}", name=f"Team {i}", is_user=(i == 1)) for i in range(1, 13)]
    return DraftSession(league, managers, DraftState(), KeeperHistory(),
                        dict(players), {k: v.model_copy() for k, v in overrides.items()}, dict(valuations))


def test_rankings_recommendation_pick_and_stacking(fixture_world):
    s = make_session(fixture_world)
    s.start([])
    rows = s.rankings()
    assert rows[0].player_id == JOKIC and rows[0].eligibility == ["C"] and rows[0].rank == 1
    assert all(r.rosterable for r in rows) and len(rows) == len(s.players)
    butler = next(r for r in rows if r.player_id == BUTLER)
    assert butler.injury_status == "out_short_term" and butler.injury_multiplier == 0.85
    oduro = next(r for r in rows if r.player_id == ODURO)
    assert oduro.value == 0.0 and not oduro.has_stats and oduro.rank > 15

    rec = s.recommend(JOKIC)
    assert rec.can_bid and 1 <= rec.recommended_max <= 186 and rec.my_max_bid == 186
    assert rec.replacement_value == 0.0  # 23 players in the pool, 180 rosterable slots
    assert len(rec.competitors) == 11

    s.engine.pick(JOKIC, "m1", rec.recommended_max)
    rows = s.rankings()
    assert all(r.player_id != JOKIC for r in rows)
    walker = next(r for r in rows if r.player_id == WALKER)
    assert walker.team_abbr == "DEN" and walker.stack_if_added == 2
    summary = next(m for m in s.manager_summaries() if m.manager_id == "m1")
    assert summary.stack == {"DEN": 1} and summary.budget.remaining == 200 - rec.recommended_max
    assert summary.picks[0]["player_name"] == "Nikola Jokić" and summary.open_slots["C"] == 0
    assert next(m for m in s.manager_summaries() if m.is_next_nominator).manager_id == "m2"
    with pytest.raises(DraftError):
        s.recommend(JOKIC)


def test_override_edit_propagates_into_rankings_and_recommendation(fixture_world):
    s = make_session(fixture_world)
    s.start([])
    before = s.recommend(JOKIC).fair_value
    edited = s.overrides[JOKIC].model_copy(update={"injury_status": "out_season", "injury_source": "manual"})
    s.set_override(edited)
    assert s.rankings()[0].player_id != JOKIC
    assert s.recommend(JOKIC).fair_value < before and s.recommend(JOKIC).fair_value == 1.0


def test_hide_unrosterable_setting(fixture_world):
    s = make_session(fixture_world)
    s.start([])
    # fill every slot a guard can take: PG, SG, UTIL×2, BN×8 -> 12 picks of PG/SG-eligible players
    guards = [r.player_id for r in s.rankings() if set(r.eligibility) & {"PG", "SG"}]
    assert len(guards) >= 10
    for pid in guards[:12] if len(guards) >= 12 else guards:
        s.engine.pick(pid, "m1", 1)
    visible = s.rankings()
    assert all(r.rosterable for r in visible)
    s.set_league(s.league.model_copy(update={"ranking": s.league.ranking.model_copy(update={"hide_unrosterable": False})}))
    everything = s.rankings()
    assert len(everything) >= len(visible)
    assert [r.rosterable for r in everything] == sorted([r.rosterable for r in everything], reverse=True)


def test_keepers_multiple_per_manager_and_history(fixture_world):
    s = make_session(fixture_world, keeper=KeeperSettings(enabled=True, max_per_manager=2))
    s.start([KeeperAssignment("m1", JOKIC, 60), KeeperAssignment("m1", DONCIC, 55), KeeperAssignment("m2", BUTLER, 20)])
    assert [p.is_keeper for p in s.draft.picks] == [True, True, True]
    assert s.engine.budget("m1").remaining == 85 and s.engine.budget("m1").open_mandatory == 13
    history = {(r.manager_id, r.player_id): r for r in s.keeper_history.records}
    assert set(history) == {("m1", JOKIC), ("m1", DONCIC), ("m2", BUTLER)}
    assert history[("m1", JOKIC)].season == "2026-27" and history[("m1", JOKIC)].cost.amount == 60
    with pytest.raises(DraftError, match="more than 2"):
        make_session(fixture_world, keeper=KeeperSettings(enabled=True, max_per_manager=2)).start(
            [KeeperAssignment("m1", pid, 5) for pid in (JOKIC, DONCIC, BUTLER)])


def test_export_round_trip(fixture_world):
    s = make_session(fixture_world)
    s.start([KeeperAssignment("m3", DONCIC, 50)])
    s.engine.pick(JOKIC, "m1", 70)
    s.engine.pick(BUTLER, "m2", 12)
    doc = s.to_export()
    assert doc.schema_version == SCHEMA_VERSION == 1 and doc.generated_by == "draft-advisor"
    assert set(doc.players) == {str(JOKIC), str(BUTLER), str(DONCIC)}
    assert doc.keepers.current[0].player_id == DONCIC and doc.keepers.history[0].player_id == DONCIC
    assert doc.players[str(BUTLER)].overrides.injury_status == "out_short_term"
    assert doc.players[str(JOKIC)].valuation.bonus_counts["triple_double"] == 34

    raw = doc.model_dump_json()
    restored = DraftExport.model_validate_json(raw)
    assert restored == doc
    players, overrides, valuations = fixture_world
    s2 = DraftSession.from_export(restored, players, overrides, valuations)
    assert s2.draft.status == "live" and len(s2.draft.picks) == 3
    assert s2.engine.budget("m1").remaining == 130 and s2.engine.next_nominator() == "m3"
    assert s2.rankings()[0].player_id != JOKIC
    s2.engine.undo()
    assert s2.engine.is_available(BUTLER)
    # a pool that lost a drafted player still restores from the snapshot
    s3 = DraftSession.from_export(restored, {k: v for k, v in players.items() if k != JOKIC}, overrides, valuations)
    assert JOKIC in s3.players and s3.engine.picks_for("m1")[0].player_id == JOKIC
    json.loads(raw)  # plain JSON on disk


def test_fit_card_and_fit_column_give_the_same_score(fixture_world):
    from app.engine.fit import fit_scores, team_fit

    s = make_session(fixture_world)
    before = team_fit(s, "m1", JOKIC)
    assert before.score == 100 and before.score_lines[2].startswith("Price: not counted")
    s.start([])
    rows = s.rankings("m1", 40)
    calls = s.spending_guide("m1", call_ids=[r.player_id for r in rows]).calls
    column = fit_scores(s, "m1", rows, calls)
    for pid in (r.player_id for r in rows[:8]):
        assert team_fit(s, "m1", pid).score == column[pid]["score"]
        # one call and one "your max" per player, whichever screen asks
        focus = s.spending_guide("m1", pid).focus
        assert (focus.verdict, focus.suggested, focus.recommended) == (calls[pid].verdict, calls[pid].suggested, calls[pid].recommended)
        assert focus.suggested <= focus.walk_away or focus.verdict == "cannot"
    # Fill every slot a center can start in (C, UTIL×2): another center is now bench only and scores lower.
    centers = [pid for pid, o in s.overrides.items() if "C" in o.eligibility and pid in s.players and pid != JOKIC and s.engine.is_available(pid)][:3]
    for pid, slot in zip(centers, ("C", "UTIL", "UTIL")):
        s.engine.pick(pid, "m1", 1, slot)
    s.invalidate()
    bench = team_fit(s, "m1", JOKIC)
    assert bench.score_lines[1].startswith("Role: bench only") and "bench only" in bench.headline

def test_draft_context_has_rules_state_managers_and_the_player_on_the_block(fixture_world):
    from app.engine.context import draft_context

    s = make_session(fixture_world)
    s.start([])
    s.engine.nominate(JOKIC)
    text = draft_context(s, "m1", top=10)
    for heading in ("## League rules", "## Draft so far", "## Managers", "## My money vs the room", "## Best available", "## Player in question"):
        assert heading in text
    assert "I am **Team 1**" in text and "On the block now: Nikola Joki" in text and "### Team 12" in text


def test_fit_scores_drop_bench_only_and_unaffordable_players(fixture_world):
    from app.engine.fit import fit_scores

    s = make_session(fixture_world)
    rows = s.rankings("m1", 30)
    fits = fit_scores(s, "m1", rows, {})
    assert fits[rows[0].player_id]["score"] == 100   # best player left, starting slot, no prices before the draft
    s.start([])
    rows = s.rankings("m1", 30)
    top = rows[0]
    from dataclasses import replace

    call = s.spending_guide("m1", top.player_id).focus
    for verdict, score, word in (("pricey", 40, "TOO PRICEY"), ("star", 85, "STAR ONLY"), ("cannot", 0, "CAN'T")):
        fits = fit_scores(s, "m1", rows, {top.player_id: replace(call, verdict=verdict)})
        assert fits[top.player_id]["score"] == score and f"call {word}" in fits[top.player_id]["why"]


def test_room_board_lists_every_manager_with_photos_and_who_can_outbid_me(fixture_world):
    from app.engine.room import room_board

    s = make_session(fixture_world)
    s.start([])
    s.engine.pick(JOKIC, "m2", 60)
    board = room_board(s, "m1")
    assert len(board) == 12 and board[0]["is_user"] and board[0]["outbids_me"] is None
    jokic = board[1]["picks"][0]
    assert jokic["player_id"] == JOKIC and jokic["fpg"] > 0 and jokic["pos"] == ["C"]


def test_market_board_counts_need_and_supply_and_prices_each_sale_at_its_moment(fixture_world):
    from app.engine.market import market_board

    s = make_session(fixture_world)
    s.start([])
    s.engine.pick(JOKIC, "m2", 80)
    s.invalidate()
    b = market_board(s, "m1")
    c = next(p for p in b["positions"] if p["pos"] == "C")
    assert [p["pos"] for p in b["positions"]] == ["PG", "SG", "SF", "PF", "C"]
    per_team = next(x.count for x in s.league.roster_slots if x.slot == "C")
    assert c["need"] == 12 * per_team - 1 and c["my_open"] == per_team and c["status"] in {"scarce", "tight", "plenty"}
    assert c["cliff"]["left"] >= 1 and all(ch["name"] != s.managers[0].name for ch in c["chasers"])
    sale = b["sales"][0]
    assert sale["player_id"] == JOKIC and sale["price"] == 80 and sale["diff"] == 80 - sale["fair"] and sale["fair"] > 1
    assert b["levels"][0] == 1.0 and len(b["levels"]) == 2
