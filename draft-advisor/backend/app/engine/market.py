"""Position market and room trend: the panel under the spending guide.

per position (PG SG SF PF C):
  need     = open starting spots of that position across the room
  left     = starter-quality players (the top N available by value, N = open starting spots in the room)
             counted where they will be used: single-position players at their position, then each
             multi-position player, best first, at whichever of his positions has the most need still
             unfilled (a PF/C goes to C while C is the shorter one). "left" adds up to N.
  also     = multi-position players counted at another position who could also play here
  status   = scarce when left < need, tight when left < 1.3 × need, else plenty
  tier     = best tier left there, how many of it are left (names) and the value drop to the next tier's best
  chasers  = rivals with an open spot there whose cap reaches the fair value of the best player left there
room trend:
  sales    = the last sales (keepers skipped) vs fair value at the moment of the sale, replayed from the picks

ponytail: flex slots (G/F/UTIL) are not split across positions; count them per position if a league uses them.
"""

from __future__ import annotations

from . import roster
from .bidding import market_rate
from .ranking import tiers

POSITIONS = roster.POSITION_SLOTS
RECENT_SALES = 4


def _fair(rate, value: float, min_bid: int) -> float:
    return min(min_bid + max(0.0, value - rate.replacement) * rate.dollars_per_var, float(rate.market_cap))


def market_board(session, manager_id: str) -> dict:
    lg = session.league
    pool = session.pool_values()
    rows = session.rank(session.engine.picks_for(manager_id), session.available_ids())
    tier = tiers(pool)
    elig = {r.player_id: set(r.eligibility) for r in rows}

    opens = {m.manager_id: roster.open_slots(lg, session.engine.picks_for(m.manager_id)) for m in session.managers}
    room_starters = sum(n for o in opens.values() for s, n in o.items() if s not in ("BN", "IR"))
    top = sorted(rows, key=lambda r: -r.value)[:room_starters]
    best_by_pos = {pos: next((r for r in rows if pos in elig[r.player_id]), None) for pos in POSITIONS}
    calls = session.spending_guide(manager_id, call_ids=[r.player_id for r in best_by_pos.values() if r]).calls
    caps = {m.manager_id: session.engine.budget(m.manager_id).max_bid for m in session.managers}

    needs = {pos: sum(o.get(pos, 0) for o in opens.values()) for pos in POSITIONS}
    counted = {pos: 0 for pos in POSITIONS}
    also = {pos: 0 for pos in POSITIONS}
    multi = []
    for r in top:
        ps = [pos for pos in POSITIONS if pos in elig[r.player_id]]
        if len(ps) == 1:
            counted[ps[0]] += 1
        elif ps:
            multi.append(ps)
    for ps in multi:   # already best-first
        home = max(ps, key=lambda pos: needs[pos] - counted[pos])
        counted[home] += 1
        for pos in ps:
            if pos != home:
                also[pos] += 1

    positions = []
    for pos in POSITIONS:
        need, left = needs[pos], counted[pos]
        status = "scarce" if left < need else "tight" if left < 1.3 * need else "plenty"
        at_pos = [r for r in rows if pos in elig[r.player_id]]
        cliff = None
        if at_pos:
            t0 = tier.get(at_pos[0].player_id)
            group = [r for r in at_pos if tier.get(r.player_id) == t0]
            nxt = next((r for r in at_pos if tier.get(r.player_id) != t0), None)
            cliff = {"tier": t0, "left": len(group), "names": [r.full_name for r in group[:3]],
                     "next_tier": tier.get(nxt.player_id) if nxt else None,
                     "drop": round(max(0.0, group[0].value - nxt.value), 1) if nxt else None}
        best = best_by_pos[pos]
        fair = round(calls[best.player_id].fair_value) if best and best.player_id in calls else None
        chasers = [{"name": m.name, "cap": caps[m.manager_id]} for m in session.managers
                   if m.manager_id != manager_id and opens[m.manager_id].get(pos, 0) > 0 and fair is not None and caps[m.manager_id] >= fair]
        positions.append({"pos": pos, "need": need, "left": left, "also": also[pos], "status": status, "cliff": cliff,
                          "best": best.full_name if best else None, "best_fair": fair,
                          "chasers": sorted(chasers, key=lambda c: -c["cap"]), "my_open": opens[manager_id].get(pos, 0)})

    # Room trend: replay the picks to price each sale at its own moment.
    picks = session.draft.picks
    names = {m.manager_id: m.name for m in session.managers}
    taken: set[int] = set()
    sales = []
    for i, p in enumerate(picks):
        if not p.is_keeper:
            rate = market_rate(lg, session.managers, picks[:i], (v for pid, v in pool.items() if pid not in taken), pool)
            fair = round(_fair(rate, pool.get(p.player_id, 0.0), lg.min_bid))
            rec = session.players.get(p.player_id)
            sales.append({"player_id": p.player_id, "player": rec.full_name if rec else str(p.player_id),
                          "manager": names.get(p.manager_id, p.manager_id), "price": p.price, "fair": fair, "diff": p.price - fair})
        taken.add(p.player_id)
    recent = sales[-RECENT_SALES:][::-1]
    window = sales[-10:]
    return {"positions": positions, "sales": recent,
            "recent_diff": round(sum(s["diff"] for s in window) / len(window), 1) if window else None}
