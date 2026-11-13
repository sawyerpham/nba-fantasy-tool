
import pytest

from app.core.engine.keepers import KeeperCandidate, evaluate_keepers, verdict_for
from app.core.engine.session import DraftSession
from app.core.services.pull_service import PullService, load_overrides, load_records
from app.core.services.valuation_service import ValuationService
from nba_fantasy_shared.models.draft import DraftState, KeeperHistory
from nba_fantasy_shared.models.league import KeeperEscalation, KeeperSettings, LeagueSettings, Manager
from nba_fantasy_shared.models.scoring import ScoringSettings
from nba_fantasy_shared.providers.fixture_provider import FixturePlatformProvider, FixtureStatsProvider
from nba_fantasy_shared.storage import JsonStore

JOKIC, S_CURRY, WALKER = 203999, 201939, 1629022


@pytest.mark.parametrize("last, expected", [(17, 20), (4, 4), (5, 6), (9, 10), (10, 12), (20, 24), (49, 58), (50, 60), (0, 1), (1, 1)])
def test_league_rule_one_dollar_per_full_five(last, expected):
    """League rule one dollar per full five."""
    assert KeeperEscalation().price(last) == expected


def test_escalation_is_editable_or_disabled():
    """Escalation is editable or disabled."""
    assert KeeperEscalation(step_dollars=10, increase_per_step=2).price(25) == 29
    assert KeeperEscalation(enabled=False).price(17) == 17
    assert LeagueSettings(league_id="L", name="L").keeper.escalation.price(17) == 20  # default rule


@pytest.mark.parametrize("surplus, fair, expected", [(8, 28, "good"), (2, 15, "good"), (1.5, 15, "even"), (-1, 15, "even"),
                                                     (-2, 15, "bad"), (-3, 40, "even"), (-4, 40, "bad"), (5, 40, "good")])
def test_verdict_thresholds(surplus, fair, expected):
    """Verdict thresholds."""
    assert verdict_for(surplus, fair) == expected


@pytest.fixture(scope="module")
def session(tmp_path_factory, fixtures_dir):
    """A session built from a fixture pull, for the keeper evaluations."""
    store = JsonStore(tmp_path_factory.mktemp("keepers"))
    assert PullService(store, FixtureStatsProvider(fixtures_dir), FixturePlatformProvider(fixtures_dir)).run().state == "done"
    players = {r.player_id: r for r in load_records(store, "2026-27")}
    league = LeagueSettings(league_id="k", name="Keepers", keeper=KeeperSettings(max_per_manager=2))
    managers = [Manager(manager_id=f"m{i}", name=f"Team {i}", is_user=(i == 1)) for i in range(1, 13)]
    return DraftSession(league, managers, DraftState(), KeeperHistory(), players, load_overrides(store),
                        ValuationService(store, "2025-26").compute(ScoringSettings()))


def test_evaluate_computes_price_and_verdict_before_the_draft(session):
    """Evaluate computes price and verdict before the draft."""
    [jokic, walker] = evaluate_keepers(session, [KeeperCandidate("m1", JOKIC, last_price=17), KeeperCandidate("m2", WALKER, last_price=17)])
    assert jokic.computed_price == 20 and jokic.keeper_price == 20 and jokic.last_price == 17
    assert jokic.fair_value > 20 and jokic.surplus == round(jokic.fair_value - 20, 2) and jokic.verdict == "good"
    assert jokic.rank == 1 and jokic.affordable and "keep" in jokic.note
    assert walker.fair_value == 1.0 and walker.keeper_price == 20 and walker.verdict == "bad" and "let go" in walker.note


def test_explicit_price_override_and_unaffordable_flag(session):
    """Explicit price override and unaffordable flag."""
    [ev] = evaluate_keepers(session, [KeeperCandidate("m1", JOKIC, last_price=17, keeper_price=60)])
    assert ev.keeper_price == 60 and ev.computed_price == 20
    [too_much] = evaluate_keepers(session, [KeeperCandidate("m1", JOKIC, last_price=190)])
    assert too_much.keeper_price == 228 and not too_much.affordable and "cap" in too_much.note


def test_unknown_player_is_a_draft_error(session):
    """Unknown player is a draft error."""
    from app.core.engine.draft_state import DraftError
    with pytest.raises(DraftError):
        evaluate_keepers(session, [KeeperCandidate("m1", 1, 5)])


def test_next_years_value_ages_him_even_when_a_projection_keeps_this_years_free_of_it():
    """With projection_weight 1 this season's value carries no age penalty (the projection prices age in), but next
    year's still moves one year down the curve: 31+ loses 3 % a year until the cap."""
    from app.core.engine.keepers import YOUNG_GROWTH, next_year_factor
    from app.core.engine.ranking import age_multiplier
    from nba_fantasy_shared.models.league import RankingSettings

    r = RankingSettings()
    assert r.projection_weight == 1.0 and r.age_penalty_start == 31
    assert next_year_factor(33, r) == pytest.approx(age_multiplier(34, r) / age_multiplier(33, r)) == pytest.approx(0.91 / 0.94)
    assert next_year_factor(31, r) == pytest.approx(0.97)
    assert next_year_factor(30, r) == 1.0 and next_year_factor(26, r) == 1.0   # next season is still at or under the start age
    assert next_year_factor(41, r) == 1.0                                      # past the 25 % cap: nothing more to lose
    assert next_year_factor(None, r) == 1.0
    # growth: only while next season is one he plays at 21 or younger
    assert next_year_factor(19.6, r) == YOUNG_GROWTH and next_year_factor(20.9, r) == YOUNG_GROWTH
    assert next_year_factor(21.0, r) == 1.0 and next_year_factor(23, r) == 1.0


def test_keeper_outlook_grows_a_teenager_and_ages_a_veteran(session):
    """The same player bought at the same price is worth more next year at 19 than at 26, and less at 34."""
    from app.core.engine.keepers import keeper_outlook

    row = next(r for r in session.rank([], session.available_ids()) if r.player_id == JOKIC)
    rec = session.players[JOKIC]
    worth = {}
    for age in (19, 26, 34):
        session.players[JOKIC] = rec.model_copy(update={"bio": rec.bio.model_copy(update={"age": age})})
        worth[age] = keeper_outlook(session, row, 20)["next_worth"]
    session.players[JOKIC] = rec
    assert worth[19] > worth[26] > worth[34]
