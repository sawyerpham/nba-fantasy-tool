"""The room: every manager's money, roster (with photos, positions, availability and projected FP/G), habits,
and two team strength estimates for the Teams view of the rankings:

    fp_gen    = Σ projected FP/G of the players in starting spots (what the lineup produces per game)
    win_score = Σ over every starting spot of the expected weekly-best game (what Lock-In scores) × availability,
                never below a replacement-level player (the best one left once every team has its starters; a
                worse starter would be swapped for him). An empty starting spot counts as replacement level plus
                what the team's money per open starting spot buys at the current price of value, so a team that
                still has its money is not ranked as if it will start nobody.
"""

from __future__ import annotations

from nba_fantasy_shared.scoring.aggregate import NO_GAMES_AVAILABILITY

from .bidding import market_rate
from .ranking import expected_fpts


def room_board(session, my_manager_id: str) -> list[dict]:
    lg = session.league
    schedule = session.schedule()

    def stats(pid: int) -> tuple[float, float, float | None]:
        """(projected FP/G, expected weekly-best FP, availability last season or None with no games)."""
        rec, val = session.players[pid], session.valuations.get(pid)
        avg, ceiling = expected_fpts(rec, val, lg.ranking, lg.scoring, schedule.get(rec.team_abbr or "", 1.0))
        return avg, ceiling, (val.availability if val and val.games_played else None)

    def with_photo(pick: dict) -> dict:
        """A roster pick plus his Sleeper photo id, positions, age, availability and projected FP/G."""
        rec = session.players.get(pick["player_id"])
        avg, _, avail = stats(rec.player_id) if rec else (None, None, None)
        ov = session.overrides.get(pick["player_id"])
        return {**pick, "sleeper_id": rec.sleeper_id if rec else None, "fpg": round(avg, 1) if avg is not None else None,
                "avail": avail, "pos": ov.eligibility if ov else [], "age": int(rec.bio.age) if rec and rec.bio.age else None}

    # Replacement level: the weekly-best of the player ranked just past every team's starters.
    starter_slots = sum(s.count for s in lg.roster_slots if s.slot not in ("BN", "IR"))
    pool = session.pool_values()
    ranked = sorted(pool, key=lambda pid: -pool[pid])
    repl_pid = ranked[min(len(ranked) - 1, starter_slots * len(session.managers))] if ranked else None
    repl = stats(repl_pid)[1] * NO_GAMES_AVAILABILITY if repl_pid is not None else 0.0

    rate = market_rate(lg, session.managers, session.draft.picks, (pool[p] for p in session.available_ids()), pool)

    out = []
    for s in session.manager_summaries():
        starters = [p for p in s.picks if p["slot"] not in ("BN", "IR")]
        fp_gen = win = 0.0
        for p in starters:
            avg, ceiling, avail = stats(p["player_id"])
            fp_gen += avg
            win += max(repl, ceiling * (avail if avail is not None else NO_GAMES_AVAILABILITY))
        empty = max(0, starter_slots - len(starters))
        b = s.budget
        if empty:
            # ponytail: value bought with money is in ranking-value units (≈ FP); fine for ordering teams mid-draft.
            open_bench = max(0, b.open_mandatory - empty)
            per_starter = max(0.0, (b.remaining - open_bench * lg.min_bid) / empty - lg.min_bid)
            bought = per_starter / rate.dollars_per_var if rate.dollars_per_var > 0 else 0.0
            win += empty * (repl + bought)
        out.append({
            "manager_id": s.manager_id, "name": s.name, "is_user": s.is_user, "is_next_nominator": s.is_next_nominator,
            "budget": b.__dict__, "per_slot": round(b.remaining / b.open_mandatory, 1) if b.open_mandatory else 0.0,
            "open_slots": s.open_slots, "picks": [with_photo(p) for p in s.picks],
            "stack": s.stack, "tendency": s.tendency, "outbids_me": None,
            "fp_gen": round(fp_gen, 1), "win_score": round(win, 1), "empty_starters": empty,
        })
    my_max = next(m["budget"]["max_bid"] for m in out if m["manager_id"] == my_manager_id)
    for m in out:
        if not m["is_user"]:
            m["outbids_me"] = m["budget"]["max_bid"] > my_max
    return out
