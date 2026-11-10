import React from "react";
import PlayerSidebar from "../core/PlayerSidebar.jsx";
import PlayerSearch from "../core/PlayerSearch.jsx";
import Icon from "../core/Icon.jsx";
import { GamePanel, TeamPanel, bestLineup, watchTitle } from "./SeasonPage.jsx";

// Pieces of the Season tab shared by the redesigned UIs (src/ui-command, src/ui-broadcast); `s` is useSeason()'s result.

/** The open card (player, game or NBA team) from the history in `s`, or null. */
export function CurrentCard({ s, leagueId }) {
  const c = s.cur;
  if (!c) return null;
  if (c.pid) return <PlayerSidebar leagueId={leagueId} playerId={c.pid} season plan={s.plan} onSelectPlayer={s.openPid} refreshKey={s.tick} onClose={s.close} onOpenGame={s.openGame} />;
  if (c.game) return <GamePanel key={c.game.game.event} sel={c.game} data={s.data} leagueId={leagueId} onOpenPid={s.openPid} onClose={s.close} />;
  return <TeamPanel key={c.team} abbr={c.team} leagueId={leagueId} onOpenPid={s.openPid} onClose={s.close} />;
}

/** Back / forward through the cards opened so far. */
export function CardNav({ s }) {
  return (
    <span className="card-nav">
      <button className="small" onClick={s.back} disabled={!s.back} aria-label="Back" data-testid="side-back"><Icon name="chevron-left" /></button>
      <button className="small" onClick={s.forward} disabled={!s.forward} aria-label="Forward" data-testid="side-forward"><Icon name="chevron-right" /></button>
    </span>
  );
}

/** ‹ WEEK n ›; clicking the week name goes back to the current week. */
export function WeekNav({ s }) {
  const { data, week, setWeek } = s;
  return (
    <span className="week-nav">
      <button className="small" disabled={data.week <= 1} onClick={() => setWeek(data.week - 1)} aria-label="Previous week"><Icon name="chevron-left" /></button>
      <strong className={`week-nav-name ${week ? "clickable" : ""}`} onClick={week ? () => setWeek(null) : undefined} title={week ? "Back to this week" : undefined}>WEEK {data.week}</strong>
      <button className="small" disabled={data.week >= Math.max(...data.weeks)} onClick={() => setWeek(data.week + 1)} aria-label="Next week"><Icon name="chevron-right" /></button>
    </span>
  );
}

/** Player / team search and the Sync button. */
export function SeasonTools({ s, leagueId }) {
  return (
    <span className="season-tools-x">
      <span className="season-search"><PlayerSearch leagueId={leagueId} onSelect={(p) => s.openPid(p.player_id)} onSelectTeam={s.openTeam} placeholder="Any player or team…" testId="season-search" /></span>
      <button className="small primary icon-btn" onClick={s.sync} disabled={s.syncing} data-testid="sync" aria-label="Sync with Sleeper"><Icon name="refresh" className={s.syncing ? "spin" : ""} /></button>
    </span>
  );
}

/** The league clock in ms. */
export const nowOf = (data) => (data.now ? Date.parse(data.now) : Date.now());

/** The next lineup check-in (ms) after now from a plan's timeline, or null when none is left this week. */
export const nextCheckIn = (plan, nowMs) => (plan.timeline?.segments || []).slice(0, -1).map((x) => Date.parse(x.to)).find((ms) => ms > nowMs) ?? null;

/**
 * The NBA games on `date` that any rostered player in the league plays in, one per game: { event, away, home, awayScore,
 * homeScore, state, detail, tip, mine (how many of yours play), sel (opens the game card) }, live ones first, then by tip.
 */
export function gamesOn(data, date) {
  const mine = new Set(data.teams.find((t) => t.is_user)?.players || []);
  const out = new Map();
  for (const [sid, p] of Object.entries(data.players)) for (const g of p.games || []) {
    if (g.date !== date || !g.event || !p.team) continue;
    const e = out.get(g.event) || {
      event: g.event, state: g.state, detail: g.detail, tip: g.tip, mine: 0, sel: { game: g, team: p.team, sid, name: p.name },
      ...(g.home ? { home: p.team, away: g.opp, homeScore: g.score, awayScore: g.opp_score } : { away: p.team, home: g.opp, awayScore: g.score, homeScore: g.opp_score }),
    };
    if (mine.has(sid)) e.mine += 1;
    out.set(g.event, e);
  }
  const rank = { in: 0, pre: 1, post: 2 };
  return [...out.values()].sort((a, b) => (rank[a.state] ?? 1) - (rank[b.state] ?? 1) || Date.parse(a.tip) - Date.parse(b.tip));
}

/** Today's games, or the next day's that has any when today has none. */
export function slate(data) {
  for (const d of data.dates.filter((x) => x >= data.today)) {
    const list = gamesOn(data, d);
    if (list.length) return { date: d, list };
  }
  return { date: data.today, list: [] };
}

/**
 * Everything that needs you now, in one list: the Sleeper swaps due now (the lineup grid's arrows), then the plan's watch
 * lines (GTD / OUT / swap windows / locks) by alarm time, then roster warnings. Each: { key, kind, when, title, text, sid, sid2, tone }.
 */
export function callsOf(data, plan) {
  const nowMs = nowOf(data);
  const games = Object.fromEntries(Object.entries(data.players).map(([sid, p]) => [sid, p.games]));
  const name = (sid) => data.players[sid]?.name || sid;
  const swaps = bestLineup(plan, nowMs, data.roster_positions, false, games).pairs.map((p) => ({
    key: `now-${p.n}`, kind: "swap", when: "now", title: `Swap ${name(p.in)} (${p.from}) and ${name(p.out)} (${p.to})`, sid: p.in, sid2: p.out, tone: "even",
  }));
  const watch = [...(plan.today?.watch || [])].sort((x, y) => (x.alarm === "now" ? "" : x.alarm || "~").localeCompare(y.alarm === "now" ? "" : y.alarm || "~"))
    .map((w) => ({
      key: `${w.kind}-${w.sid}-${w.backup_sid || ""}`, kind: w.kind, when: w.alarm, title: watchTitle(w), text: w.text, sid: w.sid, sid2: w.backup_sid,
      tone: ["gtd", "out"].includes(w.kind) || w.decision === "SWAP" ? "bad" : "even",
    }));
  const r = plan.roster;
  const roster = [
    ...(r?.illegal.length ? [{ key: "illegal", kind: "alert", when: "now", title: `Roster illegal: ${r.illegal.join(", ")} healthy on IR`, text: "Drop or trade someone: Sleeper blocks lineup changes and locks.", tone: "bad" }] : []),
    ...(r?.ir_candidates.length ? [{ key: "ir", kind: "alert", when: "now", title: `IR open: move ${r.ir_candidates.join(", ")} to IR`, tone: "even" }] : []),
  ];
  return [...swaps, ...watch, ...roster];
}
