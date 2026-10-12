"""The room: for every other manager, which available players they are most likely to bid high on.

Nominating those players ("bait") makes that manager spend, which is how you drain a rival's budget. A
candidate must fill one of their open starting spots and be within their max bid. Candidates are ranked by
what we know about the manager (value only breaks ties), so the list is personal:

    +3  they drafted him before (this league or a history league)
    +3  he plays for one of their favourite NBA teams
    +1.5 he matches their age lean (young players / veterans)
    +2  they are a star chaser and he is in the top 3 tiers

The likely price is the market's fair value; 'they can go to' is their max bid.
"""

from __future__ import annotations

from .ranking import tiers

CANDIDATES = 60      # best available players looked at per manager
BAIT_PER_MANAGER = 3


def room_board(session, my_manager_id: str) -> list[dict]:
    from .bidding import market_rate

    available = session.available_ids()
    pool = session.pool_values()
    tier = tiers(pool)
    lg = session.league
    rate = market_rate(lg, session.managers, session.draft.picks, (pool.get(p, 0.0) for p in available), pool)
    fair = lambda v: round(lg.min_bid + max(0.0, v - rate.replacement) * rate.dollars_per_var)
    mine = {r.player_id: r for r in session.rank(session.engine.picks_for(my_manager_id), available)}

    out = []
    for s in session.manager_summaries():
        t = s.tendency or {}
        bait = []
        if not s.is_user and s.budget.open_mandatory > 0:
            rows = session.rank(session.engine.picks_for(s.manager_id), available)[:CANDIDATES]
            for r in rows:
                price = min(fair(r.value), rate.market_cap)
                if r.assignable_slot in (None, "BN") or price > s.budget.max_bid or price <= lg.min_bid:
                    continue
                score, why = 0.0, [f"needs a {r.assignable_slot}"]
                how = (t.get("drafted_before") or {}).get(str(r.player_id))
                if how:
                    score += 3
                    why.append(f"drafted him before ({how})")
                if r.team_abbr and r.team_abbr in (t.get("favorite_teams") or []):
                    score += 3
                    why.append(f"{r.team_abbr} fan")
                lean = t.get("lean")
                if r.age and ((lean == "young players" and r.age <= 25) or (lean == "veterans" and r.age >= 30)):
                    score += 1.5
                    why.append(f"likes {lean}")
                if t.get("style") == "star chaser" and tier.get(r.player_id, 99) <= 3:
                    score += 2
                    why.append("star chaser")
                me = mine.get(r.player_id)
                bait.append({
                    "player_id": r.player_id, "name": r.full_name, "team_abbr": r.team_abbr, "slot": r.assignable_slot,
                    "tier": tier.get(r.player_id), "price": price, "score": score, "value": r.value, "why": why,
                    "fits_me": bool(me and me.assignable_slot not in (None, "BN")),
                })
            bait.sort(key=lambda b: (-b["score"], -b["value"]))
            bait = bait[:BAIT_PER_MANAGER]
        out.append({
            "manager_id": s.manager_id, "name": s.name, "is_user": s.is_user, "is_next_nominator": s.is_next_nominator,
            "budget": s.budget.__dict__, "open_slots": s.open_slots, "picks": s.picks, "stack": s.stack,
            "tendency": t or None, "outbids_me": None, "bait": bait,
        })
    my_max = next(m["budget"]["max_bid"] for m in out if m["manager_id"] == my_manager_id)
    for m in out:
        if not m["is_user"]:
            m["outbids_me"] = m["budget"]["max_bid"] > my_max
    return out
