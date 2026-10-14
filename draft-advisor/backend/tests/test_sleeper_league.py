"""Sleeper league details cache and the league changelog."""

from app.services.sleeper_changelog import noticed_entries, transaction_entries
from app.services.sleeper_league import details_rel


def test_details_cache_does_not_share_a_file_with_the_providers_raw_league_cache():
    # SleeperProvider.fetch_league writes cache/sleeper_league_<id>.json; sharing it wiped rosters and keepers.
    assert details_rel("123") != "cache/sleeper_league_123.json"


def season(owners, keepers=None, roster_positions=("PG", "BN"), max_keepers=1, start_time=None):
    users = [{"user_id": u, "display_name": u.upper()} for u in owners.values() if u]
    rosters = [{"roster_id": rid, "owner_id": u, "keepers": (keepers or {}).get(rid)} for rid, u in owners.items()]
    return {"league": {"league_id": "L", "name": "lg", "roster_positions": list(roster_positions),
                       "settings": {"max_keepers": max_keepers}, "scoring_settings": {"pts": 1}},
            "users": users, "rosters": rosters, "draft": {"status": "pre_draft", "start_time": start_time}}


def test_noticed_entries_cover_members_keepers_rules_and_draft_time():
    old = season({1: "a", 2: "b"})
    new = season({1: "a", 2: "c"}, keepers={1: ["99"]}, roster_positions=("PG", "PG", "BN"), max_keepers=3, start_time=1_800_000_000_000)
    texts = {(e["who"], e["kind"], e["text"]) for e in noticed_entries(old, new, lambda s: f"P{s}", "t0", "t1")}
    assert ("C", "member", "took over roster 2 from B") in texts
    assert ("A", "keeper", "set keeper P99") in texts
    assert any(k == "rules" and t.startswith("roster changed") for _, k, t in texts)
    assert (None, "rules", "keeper limit: 1 → 3") in texts
    assert any(k == "draft" and "scheduled" in t for _, k, t in texts)
    assert noticed_entries(old, old, str, "t0", "t1") == []


def test_transactions_name_the_manager_and_skip_failed_waivers():
    s = season({1: "a", 2: "b"})
    txs = [
        {"transaction_id": "1", "status": "complete", "type": "waiver", "roster_ids": [1], "adds": {"7": 1}, "drops": {"8": 1},
         "settings": {"waiver_bid": 20}, "status_updated": 1_800_000_000_000},
        {"transaction_id": "2", "status": "failed", "type": "waiver", "roster_ids": [2], "adds": {"9": 2}},
        {"transaction_id": "3", "status": "complete", "type": "trade", "roster_ids": [1, 2], "adds": {"7": 2, "5": 1},
         "draft_picks": [], "created": 1_800_000_000_000},
    ]
    out = {e["id"]: e for e in transaction_entries(txs, s, lambda p: f"P{p}")}
    assert out["tx-1"]["who"] == "A" and out["tx-1"]["text"] == "added P7 and dropped P8 (waiver, $20 FAAB)"
    assert "tx-2" not in out
    assert out["tx-3"]["text"] == "Trade: A gets P5 · B gets P7"


def test_mock_draft_picks_are_matched_by_seat():
    from types import SimpleNamespace

    from app.services.sleeper_league import sync_picks

    me = SimpleNamespace(manager_id="m4", name="me", sleeper_user_id="u4", sleeper_roster_id=4)
    other = SimpleNamespace(manager_id="m6", name="six", sleeper_user_id="u6x", sleeper_roster_id=6)
    luka = SimpleNamespace(player_id=10, sleeper_id="1970", full_name="Luka")
    ant = SimpleNamespace(player_id=11, sleeper_id="2133", full_name="Ant")
    recorded = []
    engine = SimpleNamespace(drafted_ids=lambda: set(), pick=lambda pid, mid, price, slot: recorded.append((pid, mid, price)))
    session = SimpleNamespace(players={10: luka, 11: ant}, managers=[me, other], league=SimpleNamespace(min_bid=1),
                              draft=SimpleNamespace(status="live"), engine=engine, invalidate=lambda: None)
    draft = {"status": "drafting", "draft_order": {"u4": 4}, "slot_to_roster_id": {"4": 4, "6": 6}}
    picks = [{"pick_no": 1, "player_id": "1970", "picked_by": "", "roster_id": None, "draft_slot": 4, "metadata": {"amount": "58"}},
             {"pick_no": 2, "player_id": "2133", "picked_by": "", "roster_id": None, "draft_slot": 6, "metadata": {"amount": "27"}}]
    platform = SimpleNamespace(get_json=lambda path: picks if path.endswith("/picks") else draft)
    out = sync_picks(platform, session, "D")
    assert out["errors"] == [] and recorded == [(10, "m4", 58), (11, "m6", 27)]

    # the lot in progress comes from the draft metadata (player, high bid and its seat, nominator, clock)
    session.players[12] = SimpleNamespace(player_id=12, sleeper_id="1380", full_name="Giannis", team_abbr="MIA")
    draft["metadata"] = {"nominated_player_id": "1380", "highest_offer": "39", "offering_slot": "6", "offering_user_id": "",
                         "nominating_slot": "4", "timer_end_at": "2026-10-14T11:44:09Z"}
    live = sync_picks(platform, session, "D")["live"]
    assert live["player_id"] == 12 and live["high_bid"] == 39 and live["leader"] == "six" and live["nominated_by"] == "me"
