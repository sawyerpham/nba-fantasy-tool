"""The whole draft as one Markdown block to paste into a chat with Claude.

Rules, scoring, where the draft stands, every manager's money, roster and habits, my spending picture, the
best available players and (optionally) the player on the block. Everything comes from the same numbers the
app shows, so the text never disagrees with the screen.
"""

from __future__ import annotations

from collections import Counter

from .ranking import tiers

INJURY = {"day_to_day": "DTD", "out_short_term": "OUT", "out_long_term": "OUT-LT", "out_season": "OUT-SEASON"}


def _money(m) -> str:
    b = m.budget
    return f"${b.remaining} left, cap ${b.max_bid}, {b.open_mandatory} slots to fill"


def _call_cells(c, label) -> str:
    if c is None:
        return "- | -"
    if c.verdict == "cannot":
        return "- | CAN'T"
    return f"${c.suggested} | {label[c.verdict]}"


def draft_context(session, manager_id: str, focus_player_id: int | None = None, top: int = 60) -> str:
    from ..services.sleeper_league import draft_habits, fantasy_weeks

    lg = session.league
    me = next(m for m in session.managers if m.manager_id == manager_id)
    summaries = session.manager_summaries()
    name_of = {m.manager_id: m.name for m in session.managers}
    out: list[str] = []
    w = out.append

    w(f"# NBA fantasy auction draft: {lg.name}{'' if lg.roster_season in lg.name else f' ({lg.roster_season})'}")
    w(f"I am **{me.name}**. Help me decide what to do next in this live auction. Numbers below come from my draft tool.\n")

    # ---- rules
    w("## League rules")
    slots = ", ".join(f"{s.slot}×{s.count}" if s.count > 1 else s.slot for s in lg.roster_slots)
    w(f"- {len(session.managers)} managers, ${lg.budget_per_manager} budget each, min bid ${lg.min_bid}; roster: {slots}.")
    w(f"- Format: {lg.scoring_format.replace('_', ' ')}, game mode {lg.game_mode.replace('_', '-')} "
      "(Lock-In: each starting slot scores one game per week that you lock in, so a player's best game of the week matters).")
    b = lg.scoring.base
    w(f"- Scoring per stat: pts {b.pts}, reb {b.reb}, ast {b.ast}, stl {b.stl}, blk {b.blk}, TO {b.tov}, FGM {b.fgm}, "
      f"FGA {b.fga}, FTM {b.ftm}, 3PM {b.fg3m}.")
    bonuses = ", ".join(("triple-double" if r.kind == "triple_double" else f"{r.threshold}+ {r.stat}") + f" +{r.bonus:g}"
                        for r in lg.scoring.bonuses)
    if bonuses:
        w(f"- Bonuses: {bonuses}.")
    if lg.keeper.enabled:
        e = lg.keeper.escalation
        w(f"- Keepers: up to {lg.keeper.max_per_manager} per manager; price = last year's + ${e.increase_per_step} per full ${e.step_dollars}.")
    _, playoffs = fantasy_weeks(session.sleeper_details, session.schedule_games)
    if playoffs:
        w(f"- Fantasy playoffs: weeks {playoffs[0]}-{playoffs[-1]}.")

    # ---- where the draft stands
    d = session.draft
    w("\n## Draft so far")
    w(f"- Status: {d.status}; {len(d.picks)} picks made, {len(session.available_ids())} players left, {round(session.engine.progress() * 100)}% of roster spots filled.")
    if d.status == "live":
        order = d.nomination_order
        nxt = session.engine.next_nominator()
        if nxt in order:
            i = order.index(nxt)
            w(f"- Nomination order from now: {' → '.join(name_of[x] for x in order[i:] + order[:i])}.")
    if d.current_nomination:
        p = session.players.get(d.current_nomination.player_id)
        w(f"- **On the block now: {p.full_name if p else d.current_nomination.player_id}** "
          f"(nominated by {name_of.get(d.current_nomination.nominated_by, '?')}).")
    if d.picks:
        w("- Picks in order (K = keeper):")
        for pk in d.picks:
            p = session.players.get(pk.player_id)
            w(f"  {pk.pick_number}. {p.full_name if p else pk.player_id} ({p.team_abbr if p else '?'}) → "
              f"{name_of.get(pk.manager_id, pk.manager_id)} ${pk.price}{' K' if pk.is_keeper else ''}")

    # ---- managers
    habits = draft_habits([session.sleeper_details, *session.sleeper_history]) if session.sleeper_details else {}
    sleeper_of = {m.manager_id: m.sleeper_user_id for m in session.managers}
    w("\n## Managers")
    for s in summaries:
        roster_txt = ", ".join(f"{p['slot']} {p['player_name']} ${p['price']}" for p in s.picks) or "nobody yet"
        need = ", ".join(f"{k}×{v}" if v > 1 else k for k, v in s.open_slots.items() if v and k != "IR") or "full"
        w(f"### {s.name}{' (me)' if s.is_user else ''}{' (nominates next)' if s.is_next_nominator else ''}")
        w(f"- Money: {_money(s)}. Still needs: {need}.")
        w(f"- Roster: {roster_txt}.")
        t = s.tendency or {}
        traits = []
        if t.get("style") and t["style"] != "new":
            buys = ", ".join(f"{x['name']} ${x['price']}" for x in t.get("top_buys", []))
            traits.append(f"last auction ({t.get('season')}): {t['style']}, top buys {buys}, {t.get('dollar_picks', 0)} $1 picks")
        elif t.get("style") == "new":
            traits.append("no auction history with this league")
        h = habits.get(sleeper_of.get(s.manager_id)) or {}
        if h.get("favorite_teams"):
            traits.append(f"likes {', '.join(h['favorite_teams'])} players")
        if h.get("lean"):
            traits.append(f"leans {h['lean']}")
        if h.get("early_positions"):
            traits.append(f"early picks are usually {', '.join(list(h['early_positions'])[:3])}")
        if h.get("reach") is not None:
            traits.append(f"reach {h['reach']:+.1f} (ADP minus pick; positive = takes players early)")
        if traits:
            w(f"- Habits: {'; '.join(traits)}.")

    # ---- my spending picture
    if d.status == "live":
        g = session.spending_guide(manager_id)
        w("\n## My money vs the room")
        w(f"- Me: ${g.me.remaining} for {g.me.open_mandatory} slots (${g.me.per_slot}/slot), {g.money_rank} of {g.num_managers} in money. "
          f"Room: ${g.room_remaining} for {g.room_open_mandatory} slots. Price level: {g.inflation:.2f}×.")

    # ---- best available
    rows = session.rank(session.engine.picks_for(manager_id), session.available_ids())
    tier = tiers(session.pool_values())
    left = Counter(tier.get(r.player_id) for r in rows)
    size = Counter(tier.values())
    calls = session.spending_guide(manager_id, call_ids=[r.player_id for r in rows[:top]]).calls if d.status == "live" else {}
    label = {"buy": "BUY", "star": "STAR ONLY", "pricey": "TOO PRICEY", "cannot": "CAN'T"}
    w(f"\n## Best available (top {min(top, len(rows))} by value; my slot = where he'd go on my roster)")
    w("| # | tier | player | team | pos | FP/G | wk-best | avail | age | value | price | call | my slot | notes |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows[:top]:
        notes = [INJURY[r.injury_status]] if r.injury_status in INJURY else []
        if r.proj_fpts is not None and r.last_fpts and abs(r.proj_fpts - r.last_fpts) >= 1:
            notes.append(f"proj {r.proj_fpts - r.last_fpts:+.1f} vs last yr")
        t = tier.get(r.player_id)
        w(f"| {r.rank} | T{t}{' (last 2)' if size[t] >= 3 and left[t] <= 2 else ''} | {r.full_name} | {r.team_abbr or '-'} | {'/'.join(r.eligibility)} | "
          f"{r.avg_fpts:.1f} | {r.ceiling:.1f} | {round(r.availability * 100)}% | {int(r.age) if r.age else '-'} | {r.value:.1f} | "
          f"{_call_cells(calls.get(r.player_id), label)} | {r.assignable_slot or '-'} | {', '.join(notes)} |")

    # ---- the player I'm asking about
    focus = focus_player_id or (d.current_nomination.player_id if d.current_nomination else None)
    if focus and session.engine.is_available(focus):
        from .fit import team_fit

        f = team_fit(session, manager_id, focus)
        w(f"\n## Player in question: {session.players[focus].full_name}")
        w(f"- My tool's read: **{f.headline}**")
        for r in f.reasons:
            w(f"  - {r}")
        before = [f"{s.name} ({s.tendency['drafted_before'][str(focus)]})" for s in summaries
                  if not s.is_user and s.tendency and str(focus) in (s.tendency.get("drafted_before") or {})]
        if before:
            w(f"- Rivals who drafted him before: {'; '.join(before)}.")

    w("\n## How to read this")
    w("- FP/G = expected fantasy points per game (Sleeper projection). wk-best = expected best game of a week (what Lock-In scores). "
      "avail = share of fantasy weeks he played, last 3 seasons weighted 50/30/20. value = my tool's ranking score in FP. "
      "price = the most I should spend on him now (what he'll likely go for in this room, never past my walk-away). "
      "call: BUY (his going rate is within my comfort limit), STAR ONLY (between my comfort limit and walk-away: only worth it as my star), "
      "TOO PRICEY (past my walk-away; my price is the walk-away), CAN'T (no slot or above my cap). "
      "Comfort limit = paying more leaves under 80% of the room's average per open starter; walk-away = under 50%. "
      "Cap = the most a manager may legally bid. Fit = 0-100 match for my team (quality vs best left × role × price call).")
    return "\n".join(out)
