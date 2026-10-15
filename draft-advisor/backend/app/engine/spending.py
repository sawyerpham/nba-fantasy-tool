"""Spending guide: where one manager's money stands against the room, a plan for the open slots, and
how far to go on a specific player.

per_slot        = remaining / open mandatory slots
allowance       = (remaining − min_bid × open bench) / open starter slots     # even split, bench at the minimum
inflation       = current $/VAR ÷ opening $/VAR  (opening = full budgets, nobody drafted; >1 means the
                  money left is chasing less talent than at the start, so prices run above fair value)
plan            = per open starter slot (position slots first, then G/F, then UTIL): the best available
                  player that fits and their recommended price, plus the best one whose price fits the
                  allowance; bench slots at min_bid each. A player appears at most once across the plan.
room_ps         = (room remaining − room bench at min_bid) / room open starter slots: what the average
                  open starter slot in the room will be paid for from here on
stretch(p)      = "comfort limit": the price after which my money per open starter drops below 80 % of room_ps
walk_away(p)    = "walk-away": the price after which it drops below 50 % of room_ps; never pay more
call on p       = target = fair value when no rival can pay it, else the market price (+ up to 25 %, never past the
                  comfort limit, for a top player when I'm in the top third by money and a bidding war is likely);
                  buy when target <= comfort limit, star (only) when <= walk-away, else pricey with "your max" = walk-away.
                  The same call and "your max" are shown everywhere (rankings, profile, live lot, Fit's price factor).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from nba_fantasy_shared.models.draft import Pick
from nba_fantasy_shared.models.league import LeagueSettings, Manager

from . import roster
from .bidding import BidRecommendation, MarketRate, market_rate, recommend_bid
from .budget import manager_budget
from .ranking import RankedPlayer

STARTER_ORDER: tuple[str, ...] = roster.POSITION_SLOTS + roster.FLEX_SLOTS + ("UTIL",)
FIT_SCAN_LIMIT = 200  # candidates examined per slot when looking for one that fits the allowance
DEFAULT_TARGETS = 5
NOMINATION_SCAN = 40  # available players considered for nomination ideas


@dataclass
class ManagerMoney:
    manager_id: str
    name: str
    is_user: bool
    remaining: int
    spent: int
    open_mandatory: int
    open_starters: int
    open_bench: int
    max_bid: int
    discretionary: int
    per_slot: float


@dataclass
class SlotPlan:
    slot: str
    budget: int
    best_id: int | None = None
    best_name: str | None = None
    best_price: int = 0
    fit_id: int | None = None
    fit_name: str | None = None
    fit_price: int = 0


@dataclass
class TargetAdvice:
    player_id: int
    name: str
    slot: str | None                 # slot they would take on my roster
    tier: str                        # top | starter | bench
    fair_value: float
    recommended: int                 # "market price": fair value × competition pressure, capped at my cap
    stretch: int                     # "comfort limit": above this, my money per open starter falls under 80 % of the room's
    walk_away: int                   # "walk-away": above this, under 50 %; never pay more
    all_in: int                      # my cap (the most I may legally bid)
    suggested: int                   # "your max": the most to bid (never past the walk-away)
    rivals_at_fair: int              # other managers who can pay fair value and fit the player
    rivals_above_market: int         # other managers whose max bid reaches the market max
    left_after: int
    per_slot_after: float            # per remaining mandatory slot
    per_starter_after: float         # per remaining starter slot after bench at min_bid
    room_per_starter: float
    verdict: str                     # the call: buy | star (star only) | pricey (too pricey) | cannot
    text: str


@dataclass
class SpendingGuide:
    manager_id: str
    name: str
    me: ManagerMoney
    managers: list[ManagerMoney]
    num_managers: int
    money_rank: int
    per_slot_rank: int              # 0 when the manager has no open slot
    room_remaining: int
    room_open_mandatory: int
    room_open_starters: int
    room_per_slot: float
    room_discretionary: int
    can_outbid_me: list[ManagerMoney]
    opening_dollars_per_var: float
    current_dollars_per_var: float
    inflation: float
    allowance: int
    plan: list[SlotPlan]
    bench_total: int
    plan_best_total: int
    plan_fit_total: int
    slack_best: int
    slack_fit: int
    focus: TargetAdvice | None
    targets: list[TargetAdvice]
    advice: list[str] = field(default_factory=list)
    nominations: list[dict] = field(default_factory=list)
    calls: dict[int, TargetAdvice] = field(default_factory=dict)   # call + your max for each of `call_ids`


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def manager_money(league: LeagueSettings, manager: Manager, picks: Iterable[Pick]) -> ManagerMoney:
    picks = list(picks)
    b = manager_budget(league, manager, picks)
    own = [p for p in picks if p.manager_id == manager.manager_id]
    opens = roster.open_slots(league, own)
    bench = opens.get("BN", 0)
    starters = sum(n for slot, n in opens.items() if slot not in ("BN", "IR"))
    return ManagerMoney(
        manager_id=manager.manager_id,
        name=manager.name,
        is_user=manager.is_user,
        remaining=b.remaining,
        spent=b.spent,
        open_mandatory=b.open_mandatory,
        open_starters=starters,
        open_bench=bench,
        max_bid=b.max_bid,
        discretionary=b.discretionary,
        per_slot=round(b.remaining / b.open_mandatory, 1) if b.open_mandatory else 0.0,
    )


def spending_guide(
    league: LeagueSettings,
    managers: list[Manager],
    picks: list[Pick],
    my_manager_id: str,
    available: list[RankedPlayer],
    pool_values: Mapping[int, float],
    progress: float,
    opening_dollars_per_var: float,
    focus_player_id: int | None = None,
    targets_n: int = DEFAULT_TARGETS,
    call_ids: Iterable[int] = (),
) -> SpendingGuide:
    min_bid = league.min_bid
    money = [manager_money(league, m, picks) for m in managers]
    me = next(x for x in money if x.manager_id == my_manager_id)
    n = len(money)
    money_rank = 1 + sum(1 for x in money if x.remaining > me.remaining)
    with_slots = [x for x in money if x.open_mandatory > 0]
    per_slot_rank = (1 + sum(1 for x in with_slots if x.per_slot > me.per_slot)) if me.open_mandatory else 0
    room_remaining = sum(x.remaining for x in money)
    room_open = sum(x.open_mandatory for x in money)
    room_open_starters = sum(x.open_starters for x in money)
    others = [x for x in money if x.manager_id != me.manager_id]
    can_outbid = sorted((x for x in others if x.max_bid > me.max_bid), key=lambda x: (-x.max_bid, x.name))

    rate: MarketRate = market_rate(league, managers, picks, (p.value for p in available), pool_values)
    inflation = round(rate.dollars_per_var / opening_dollars_per_var, 3) if opening_dollars_per_var > 0 else 1.0

    my_picks = [p for p in picks if p.manager_id == my_manager_id]
    opens = roster.open_slots(league, my_picks)
    bench_total = min_bid * me.open_bench
    allowance = int((me.remaining - bench_total) / me.open_starters) if me.open_starters else 0
    allowance = max(allowance, min_bid) if me.open_starters else 0
    candidates = [p for p in available if p.rosterable]
    recs: dict[int, BidRecommendation] = {}

    def rec_for(p: RankedPlayer) -> BidRecommendation:
        if p.player_id not in recs:
            recs[p.player_id] = recommend_bid(league, managers, picks, my_manager_id, p, available, pool_values, progress, rate=rate)
        return recs[p.player_id]

    def price(p: RankedPlayer) -> int:
        r = rec_for(p)
        return r.recommended_max if r.can_bid else max(min_bid, int(round(r.fair_value)))

    def build_plan(exclude: set[int], skip_slot: str | None = None) -> list[SlotPlan]:
        plan: list[SlotPlan] = []
        used: set[int] = set(exclude)
        skipped = False
        for slot in STARTER_ORDER:
            for _ in range(opens.get(slot, 0)):
                if slot == skip_slot and not skipped:
                    skipped = True
                    continue
                fitting = [p for p in candidates if p.player_id not in used and roster.slot_accepts(slot, p.eligibility)]
                entry = SlotPlan(slot=slot, budget=allowance)
                if fitting:
                    best = fitting[0]
                    entry.best_id, entry.best_name, entry.best_price = best.player_id, best.full_name, price(best)
                    used.add(best.player_id)
                    for p in fitting[:FIT_SCAN_LIMIT]:
                        if p.player_id in used and p.player_id != best.player_id:
                            continue
                        pr = price(p)
                        if pr <= allowance:
                            entry.fit_id, entry.fit_name, entry.fit_price = p.player_id, p.full_name, pr
                            used.add(p.player_id)
                            break
                plan.append(entry)
        return plan

    plan = build_plan(set())
    plan_best_total = sum(e.best_price for e in plan) + bench_total
    plan_fit_total = sum(e.fit_price for e in plan) + bench_total
    slack_best = me.remaining - plan_best_total
    slack_fit = me.remaining - plan_fit_total

    top_n = max(3, room_open_starters // 4)
    room_bench_min = min_bid * sum(x.open_bench for x in money)
    room_ps = (room_remaining - room_bench_min) / room_open_starters if room_open_starters else 0.0
    few_rivals = max(1, (n - 1) // 4)
    rich = money_rank <= max(1, -(-n // 3))  # top third of the room by money left

    def tier_of(p: RankedPlayer) -> str:
        idx = next((i for i, c in enumerate(candidates) if c.player_id == p.player_id), len(candidates))
        if idx < top_n:
            return "top"
        if idx < room_open_starters:
            return "starter"
        return "bench"

    def clamp(x: float) -> int:
        return int(max(min_bid, min(int(x), me.max_bid)))

    def advise(target: RankedPlayer) -> TargetAdvice:
        r = rec_for(target)
        slot = roster.assign_slot(league, my_picks, target.eligibility)
        tier = tier_of(target)
        fair = round(r.fair_value)
        rivals_at_fair = len(r.competitors)
        market = r.recommended_max
        rivals_above = sum(1 for x in others if x.max_bid >= market)
        base = dict(player_id=target.player_id, name=target.full_name, slot=slot, tier=tier, fair_value=round(r.fair_value, 2),
                    recommended=market, all_in=me.max_bid, rivals_at_fair=rivals_at_fair, rivals_above_market=rivals_above,
                    room_per_starter=round(room_ps, 1))
        if not r.can_bid or slot is None:
            reason = r.rationale[-1] if r.rationale else "no open slot"
            return TargetAdvice(**base, stretch=0, walk_away=0, suggested=0, left_after=me.remaining, per_slot_after=me.per_slot,
                                per_starter_after=0.0, verdict="cannot", text=f"CAN'T: you can't bid on {target.full_name}: {reason}")

        starter_slot = slot not in ("BN", "IR")
        starters_after = me.open_starters - 1 if starter_slot else me.open_starters
        bench_after = bench_total - (0 if starter_slot else min_bid)

        def per_starter(x: int) -> float:
            left = me.remaining - x - bench_after
            return left / starters_after if starters_after > 0 else float(left)

        if starters_after > 0 and room_ps > 0:
            stretch = clamp(me.remaining - bench_after - starters_after * 0.8 * room_ps)
            walk = clamp(me.remaining - bench_after - starters_after * 0.5 * room_ps)
        else:
            stretch = walk = me.max_bid
        walk = max(walk, stretch)

        def tail(x: int) -> str:
            left = me.remaining - x
            slots = me.open_mandatory - 1
            if slots <= 0:
                return f"that is your last slot, ${left} stays unspent"
            if starters_after <= 0:
                return f"you'd have ${left} for {slots} bench slot{'s' if slots != 1 else ''}"
            share = f" ({round(100 * per_starter(x) / room_ps)}% of the room's ${room_ps:.0f})" if room_ps > 0 else ""
            return (f"you'd have ${left} for {slots} slot{'s' if slots != 1 else ''}: ${per_starter(x):.0f} per starter{share}, "
                    f"bench at ${min_bid}")

        # What you'd pay if it goes your way: fair value when nobody else can pay it, else the market price, with
        # up to 25 % on top (never past the comfort limit) for a top player when you are rich and a war is likely.
        if rivals_at_fair == 0:
            target_price = clamp(fair)
        elif tier == "top" and rich and rivals_above > few_rivals and market <= stretch:
            target_price = max(market, min(stretch, int(round(market * 1.25))))
        else:
            target_price = min(market, me.max_bid)
        why = ("nobody else can afford him" if rivals_at_fair == 0
               else f"{rivals_above} rival{'s' if rivals_above != 1 else ''} can pay up to his max ${market}")
        if target_price <= stretch:
            suggested, verdict = target_price, "buy"
            text = (f"BUY: {target.full_name} is worth ${fair}; {why}, and either fits your budget. "
                    f"After ${target_price} {tail(target_price)}.")
        elif target_price <= walk:
            suggested, verdict = target_price, "star"
            text = (f"STAR ONLY: {target.full_name} is worth ${fair}, but bidding likely reaches ${target_price}, past your comfort "
                    f"limit ${stretch}. Pay that only if he's your star: after it {tail(target_price)}, so the rest become cheap picks.")
        else:
            suggested, verdict = walk, "pricey"
            text = (f"TOO PRICEY: {target.full_name} is worth ${fair}, but bidding likely reaches ${target_price}, past your walk-away ${walk}. Stop at ${walk}: "
                    f"paying ${target_price} leaves ${per_starter(target_price):.0f} per open starter, under half the room's ${room_ps:.0f}.")
        left = me.remaining - suggested
        per_slot_after = round(left / (me.open_mandatory - 1), 1) if me.open_mandatory > 1 else 0.0
        return TargetAdvice(**base, stretch=stretch, walk_away=walk, suggested=suggested, left_after=left,
                            per_slot_after=per_slot_after, per_starter_after=round(per_starter(suggested), 1),
                            verdict=verdict, text=text)

    focus = None
    if focus_player_id is not None:
        target = next((p for p in available if p.player_id == focus_player_id), None)
        if target is not None:
            focus = advise(target)

    by_id = {p.player_id: p for p in available}
    calls = {pid: advise(by_id[pid]) for pid in call_ids if pid in by_id}

    targets: list[TargetAdvice] = []
    if me.open_mandatory > 0:
        for p in candidates:
            if len(targets) >= targets_n:
                break
            if price(p) > me.max_bid:
                continue
            targets.append(advise(p))

    # ---- nomination ideas
    # drain: players the room will pay a lot for that you won't buy (no fitting slot, above your cap, or too pricey);
    # sneak: players you want that few rivals can afford right now, so they may go near fair value.
    # ponytail: scans the top NOMINATION_SCAN available; widen if late-draft suggestions run dry.
    nominations: list[dict] = []
    if me.open_mandatory > 0:
        drain, sneak = [], []
        for p in sorted(available, key=lambda x: -x.value)[:NOMINATION_SCAN]:
            r = rec_for(p)
            market = price(p)
            rivals = sum(1 for x in others if x.open_mandatory > 0 and x.max_bid >= market)
            if not p.rosterable or market > me.max_bid:
                if rivals >= 2:
                    drain.append((market * rivals, p, market, rivals, "you have no slot for him" if not p.rosterable else "above your cap"))
                continue
            a = advise(p)
            if a.verdict == "pricey":   # past your walk-away; a star-only player may still be your star
                if rivals >= 2:
                    drain.append((market * rivals, p, market, rivals, "too pricey for your build"))
            elif a.verdict == "buy" and r.can_bid and rivals <= few_rivals:
                sneak.append((-p.value, p, a.suggested, rivals, ""))
        for _, p, market, rivals, why in sorted(drain, key=lambda t: -t[0])[:3]:
            nominations.append({"kind": "drain", "player_id": p.player_id, "name": p.full_name, "price": market, "rivals": rivals,
                                "reason": f"{rivals} rivals can pay ~${market} and {why}: their money leaves the room"})
        for _, p, suggested, rivals, _ in sorted(sneak, key=lambda t: t[0])[:3]:
            nominations.append({"kind": "sneak", "player_id": p.player_id, "name": p.full_name, "price": suggested, "rivals": rivals,
                                "reason": f"only {rivals} rival{'s' if rivals != 1 else ''} can reach ${suggested} right now"})

    # ---- headline advice
    advice: list[str] = []
    if me.open_mandatory == 0:
        advice.append(f"Roster full: ${me.remaining} unspent.")
    else:
        advice.append(
            f"${me.remaining} for {me.open_mandatory} slot{'s' if me.open_mandatory != 1 else ''} "
            f"(${me.per_slot:.0f}/slot): {ordinal(money_rank)} most money of {n}, {ordinal(per_slot_rank)} per open slot."
        )
    if opening_dollars_per_var > 0 and rate.dollars_per_var > 0:
        if inflation >= 1.05:
            advice.append(f"Price level {inflation:.2f}×: more money than talent is left, stars will go over fair value.")
        elif inflation <= 0.95:
            advice.append(f"Price level {inflation:.2f}×: talent is outlasting money, bargains ahead.")
        else:
            advice.append("Price level near 1.00×: prices as at the start.")
    if me.open_mandatory > 0 and me.open_starters == 0:
        advice.append(f"Only bench slots left: ${me.discretionary} above the ${min_bid} minimums.")
    elif me.open_starters > 0:
        if slack_best >= 0:
            advice.append(f"The best available at every open starter slot costs ${plan_best_total}: ${slack_best} to spare.")
        else:
            advice.append(
                f"The best available at every open starter slot costs ${plan_best_total}, ${-slack_best} more than you have; "
                f"the within-budget picks cost ${plan_fit_total}."
            )
    if me.open_mandatory > 0:
        if can_outbid:
            names = ", ".join(f"{x.name} ${x.max_bid}" for x in can_outbid[:3]) + (" …" if len(can_outbid) > 3 else "")
            advice.append(f"{len(can_outbid)} manager{'s have' if len(can_outbid) != 1 else ' has'} a higher cap than your ${me.max_bid}: {names}.")
        else:
            advice.append(f"Nobody has a higher cap than your ${me.max_bid}.")

    return SpendingGuide(
        manager_id=me.manager_id,
        name=me.name,
        me=me,
        managers=sorted(money, key=lambda x: (-x.remaining, x.name)),
        num_managers=n,
        money_rank=money_rank,
        per_slot_rank=per_slot_rank,
        room_remaining=room_remaining,
        room_open_mandatory=room_open,
        room_open_starters=room_open_starters,
        room_per_slot=round(room_remaining / room_open, 1) if room_open else 0.0,
        room_discretionary=sum(x.discretionary for x in money),
        can_outbid_me=can_outbid,
        opening_dollars_per_var=round(opening_dollars_per_var, 3),
        current_dollars_per_var=round(rate.dollars_per_var, 3),
        inflation=inflation,
        allowance=allowance,
        plan=plan,
        bench_total=bench_total,
        plan_best_total=plan_best_total,
        plan_fit_total=plan_fit_total,
        slack_best=slack_best,
        slack_fit=slack_fit,
        focus=focus,
        targets=targets,
        advice=advice,
        nominations=nominations,
        calls=calls,
    )
