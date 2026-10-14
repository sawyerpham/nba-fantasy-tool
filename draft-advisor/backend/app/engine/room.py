"""The room: every manager's money, roster (with photos, positions and projected FP/G) and habits."""

from __future__ import annotations

from .ranking import expected_fpts


def room_board(session, my_manager_id: str) -> list[dict]:
    lg = session.league

    def with_photo(pick: dict) -> dict:
        """A roster pick plus his Sleeper photo id, positions, age and projected FP/G (for the room cards)."""
        rec = session.players.get(pick["player_id"])
        fpg = expected_fpts(rec, session.valuations.get(rec.player_id), lg.ranking, lg.scoring)[0] if rec else None
        ov = session.overrides.get(pick["player_id"])
        return {**pick, "sleeper_id": rec.sleeper_id if rec else None, "fpg": round(fpg, 1) if fpg is not None else None,
                "pos": ov.eligibility if ov else [], "age": int(rec.bio.age) if rec and rec.bio.age else None}

    out = [{
        "manager_id": s.manager_id, "name": s.name, "is_user": s.is_user, "is_next_nominator": s.is_next_nominator,
        "budget": s.budget.__dict__, "open_slots": s.open_slots, "picks": [with_photo(p) for p in s.picks],
        "stack": s.stack, "tendency": s.tendency, "outbids_me": None,
    } for s in session.manager_summaries()]
    my_max = next(m["budget"]["max_bid"] for m in out if m["manager_id"] == my_manager_id)
    for m in out:
        if not m["is_user"]:
            m["outbids_me"] = m["budget"]["max_bid"] > my_max
    return out
