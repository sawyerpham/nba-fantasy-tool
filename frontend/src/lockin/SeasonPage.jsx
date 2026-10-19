import React, { useCallback, useEffect, useState } from "react";
import { useNBAMatches, findMatch, watchUrl } from "./streams.jsx";
import { createPortal } from "react-dom";
import { api, qs } from "../api.js";
import Headshot from "../core/Headshot.jsx";
import { PosList, PosTag } from "../core/Pos.jsx";
import PlayerSidebar from "../core/PlayerSidebar.jsx";
import PlayerSearch from "../core/PlayerSearch.jsx";
import InjuryTag from "../core/InjuryTag.jsx";
import { fmt, setZone, timeOf, tzAbbr } from "./tz.js";
import { alarmSound } from "../core/sounds.js";

// The in-season tab: your Lock-In week (matchup, week plan with LOCK / PASS calls, every player's games Mon-Sun),
// today's lineup moves, the league (matchups + standings) and waiver claims. Any player name opens his season
// profile on the right. Data: backend services/season.py + engine/weekplan.py; refreshed every 2 minutes.
const REFRESH_MS = 60000;   // every minute: live scores feed the KEEP / SWAP calls
const VIEWS = [["week", "This week"], ["news", "News"], ["league", "League"], ["waivers", "Waivers"]];

const dayName = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
const md = (d) => d.slice(5).replace("-", "/");   // "2026-10-20" -> "10/20"
const fp = (x) => (x == null ? "" : x.toFixed(1));
// Player nicknames the managers set on Sleeper: shown unless switched off (Settings > General, this browser only).
const showNicks = () => { try { return localStorage.getItem("da.nicks") !== "off"; } catch { return true; } };

// A fantasy team: its Sleeper avatar, its team name, and the manager's username when that differs.
function TeamName({ t, cls = "", size = 24 }) {
  return (
    <span className="team-name-tag">
      {t.avatar && <img className="team-avatar" src={t.avatar} width={size} height={size} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
      <span className={cls}>{t.name}</span>
      {t.user && t.user !== t.name && <span className="small muted">{t.user}</span>}
    </span>
  );
}


export default function SeasonPage({ leagueId }) {
  const [view, setView] = useState(() => { const v = localStorage.getItem("da.season.view"); return VIEWS.some(([id]) => id === v) ? v : "week"; });
  const [week, setWeek] = useState(null);
  const [plan, setPlan] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [tick, setTick] = useState(0);
  const [headerSlot, setHeaderSlot] = useState(null);
  useEffect(() => { setHeaderSlot(document.getElementById("header-slot")); }, []);

  // The plan is "what to do now": the backend re-runs the rules against the clock on every load (today until its
  // games are over, then the next game day), so reload every minute and whenever the tab comes back into view.
  const load = useCallback(() => {
    if (!leagueId) return;
    Promise.all([api.get(`/leagues/${leagueId}/season/week` + qs({ week })), api.get(`/leagues/${leagueId}/season/plan` + qs({ week }))])
      .then(([w, p]) => { setZone(w.tz); setData(w); setPlan(p); setError(""); })
      .catch((e) => setError(e.message));
  }, [leagueId, week]);
  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    const back = () => { if (document.visibilityState === "visible") load(); };
    document.addEventListener("visibilitychange", back);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", back); };
  }, [load, tick]);
  useEffect(() => { try { localStorage.setItem("da.season.view", view); } catch { /* ignore */ } }, [view]);
  const [syncing, setSyncing] = useState(false);
  const sync = () => {
    setSyncing(true);
    api.post(`/leagues/${leagueId}/season/sync`, {}).then(() => setTick((t) => t + 1)).catch((e) => setError(e.message)).finally(() => setSyncing(false));
  };

  // Alarms: each watch line has an alarm time (5 min before the later player's tip, 30 min before a GTD starter's).
  // When it comes, re-read the plan (live score) and ring with the current call. Works while this tab is open.
  const [alerts, setAlerts] = useState([]);
  const rung = React.useRef(new Set());   // "now" alarms already rung (late scratches)
  const [armed, setArmed] = useState(() => { try { return localStorage.getItem("da.season.alarms") === "1"; } catch { return false; } });
  const arm = () => {
    alarmSound();   // the click also unlocks sound for later
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    setArmed(true); try { localStorage.setItem("da.season.alarms", "1"); } catch { /* ignore */ }
  };
  useEffect(() => {
    if (!armed || !plan?.today) return undefined;
    const timers = plan.today.watch.filter((w) => w.alarm).map((w) => {
      const key = `${plan.today.date}-${w.kind}-${w.sid}`;
      if (w.alarm === "now" && rung.current.has(key)) return null;
      if (w.alarm === "now") rung.current.add(key);
      const ms = w.alarm === "now" ? 0 : Date.parse(w.alarm) - Date.now();
      if (ms < 0 || ms > 24 * 3600e3) return null;
      return setTimeout(async () => {
        let line = w;
        try {
          const fresh = await api.get(`/leagues/${leagueId}/season/plan` + qs({ week }));
          setPlan(fresh);
          line = fresh.today?.watch.find((x) => x.kind === w.kind && (w.kind === "swap" ? x.backup_sid === w.backup_sid : x.sid === w.sid)) || w;
          if (w.kind === "lock" && !fresh.today?.watch.some((x) => x.kind === "lock" && x.sid === w.sid)) return;   // locked meanwhile
        } catch { /* ring with what we have */ }
        const title = line.kind === "gtd" ? `Check ${line.name} (GTD)` : line.kind === "out" ? `${line.name} is OUT` : line.kind === "lock" ? `Lock ${line.name} now`
          : line.decision === "SWAP" ? `SWAP: bench ${line.name}, start ${line.backup}` : `${line.decision}: ${line.backup} check`;
        alarmSound();
        setAlerts((a) => [{ key: `${w.sid}-${w.kind}-${Date.now()}`, title, text: line.text, decision: line.decision, kind: line.kind }, ...a]);
        try { if (Notification.permission === "granted") new Notification(title, { body: line.text }); } catch { /* ignore */ }
      }, ms);
    }).filter(Boolean);
    return () => timers.forEach(clearTimeout);
  }, [armed, plan?.today?.watch?.map((w) => `${w.sid}${w.alarm}`).join(","), leagueId, week]);

  if (!leagueId) return <div className="panel muted">Pick a league on the League tab first.</div>;
  if (error && !data) return <div className="panel error">{error}</div>;
  if (!data || !plan) return <div className="panel">Loading the week from Sleeper…</div>;

  const pidOf = (sid) => data.players[sid]?.player_id;
  const open = (sid) => { const pid = pidOf(sid); if (pid) setSelected(pid); };
  const setLock = (sid, gameDate) => api.post(`/leagues/${leagueId}/season/locks`, { week: data.week, sleeper_id: sid, game_date: gameDate })
    .then(() => setTick((t) => t + 1)).catch((e) => setError(e.message));

  // The week bar lives in the app header (top bar) while this tab is open.
  const bar = (
        <div className="season-bar">
          <strong className="season-week">Week {data.week}</strong>
          <span className="muted small">{data.dates.length ? `${dayName(data.dates[0])} ${md(data.dates[0])} – ${dayName(data.dates.at(-1))} ${md(data.dates.at(-1))}` : ""}</span>
          <button className="mu-arrow" disabled={data.week <= 1} onClick={() => setWeek(data.week - 1)} data-tip="Previous week">◀</button>
          <button className="mu-arrow" disabled={data.week >= Math.max(...data.weeks)} onClick={() => setWeek(data.week + 1)} data-tip="Next week">▶</button>
          {week && <button className="small ghost" onClick={() => setWeek(null)}>this week</button>}
          <nav className="season-tabs">
            {VIEWS.map(([id, label]) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)} data-testid={`season-${id}`}>{label}</button>)}
          </nav>
          <span className="season-search"><PlayerSearch leagueId={leagueId} onSelect={(p) => setSelected(p.player_id)} placeholder="Any player…" testId="season-search" /></span>
          <button className={`small ${armed ? "ghost" : "primary"}`} onClick={arm} data-testid="arm-alarms"
            data-tip="Rings at each swap check and GTD check while this tab is open, with a browser notification. Click once to allow sound and notifications.">
            {armed ? "🔔 Alarms on" : "🔕 Turn on alarms"}</button>
          <button className="small primary" onClick={sync} disabled={syncing} data-testid="sync"
            data-tip="Pull your lineup, locks, scores and news from Sleeper now and recompute the best lineup.">
            {syncing ? "Syncing…" : "⟳ Sync"}</button>
          {error && <span className="small warn-text">{error}</span>}
        </div>
  );
  return (
    <div className="season-grid">
      <section className="season-main">
        {headerSlot ? createPortal(bar, headerSlot) : bar}
        {alerts.map((a) => (
          <div key={a.key} className={`panel roster-alert ${["gtd", "out"].includes(a.kind) || a.decision === "SWAP" ? "bad" : "even"}`} data-testid="alarm-banner">
            <strong>⏰ {a.title}</strong> {a.text}
            <button className="tiny" style={{ marginLeft: 8 }} onClick={() => setAlerts((x) => x.filter((y) => y.key !== a.key))}>dismiss</button>
          </div>
        ))}
        <RosterAlerts roster={plan.roster} />
        {view === "week" && <WeekView key={data.week} data={data} plan={plan} open={open} setLock={setLock} leagueId={leagueId} />}
        {view === "news" && <NewsView leagueId={leagueId} open={setSelected} refreshKey={tick} />}
        {view === "league" && <LeagueView data={data} leagueId={leagueId} open={open} />}
        {view === "waivers" && <WaiversView leagueId={leagueId} onSelect={setSelected} />}
      </section>
      <aside className="season-side">
        <PlayerSidebar leagueId={leagueId} playerId={selected} season plan={plan} onSelectPlayer={setSelected} refreshKey={tick} onClose={() => setSelected(null)} />
      </aside>
    </div>
  );
}

function RosterAlerts({ roster }) {
  if (!roster) return null;
  return (
    <>
      {roster.illegal.length > 0 && (
        <div className="panel roster-alert bad" data-testid="roster-illegal">
          <strong>Roster illegal:</strong> {roster.illegal.join(", ")} {roster.illegal.length > 1 ? "are" : "is"} healthy on IR, which makes 16 healthy players.
          Sleeper won't let you change your lineup or lock games until you drop someone or trade.
        </div>
      )}
      {roster.ir_candidates.length > 0 && (
        <div className="panel roster-alert even" data-testid="roster-ir">
          <strong>IR spot open ({roster.ir_open}):</strong> move {roster.ir_candidates.join(", ")} to IR. That opens a roster spot for a waiver claim (see Waivers).
        </div>
      )}
    </>
  );
}

const gameTip = (g, played, live, lockDate, href) =>
  `${dayName(g.date)} ${md(g.date)} ${g.home ? "vs" : "@"} ${g.opp} · ${played ? `${g.fp} FP in ${g.min} min` : live ? `live: ${g.detail}` : `tips ${timeOf(g.tip)} ${tzAbbr(Date.parse(g.tip))} · projected ${fp(g.proj)} FP`}${lockDate === g.date ? " · LOCKED" : ""}${href ? " · ▶ opens streamed.pk" : ""}`;
const shortTime = (iso) => timeOf(iso).replace(":00", "").replace(" PM", "p").replace(" AM", "a");

// One card per game he has this week (so 3-4 at most): day, tip time, then FP once played or the projection.
// Used outside the matchup (League tab); the matchup lays games out by day (WeekCells).
function GameChips({ games, today, lockDate, team }) {
  const { list: matches } = useNBAMatches();
  if (!games.length) return <span className="muted small">no games</span>;
  return (
    <span className="chips-row">{games.map((g) => {
      const played = g.fp != null, live = g.state === "in";
      const m = findMatch(matches, g, team);
      const href = m ? watchUrl(m) : null;
      const Tag = href ? "a" : "span";
      return (
        <Tag key={g.date} {...(href ? { href, target: "_blank", rel: "noopener noreferrer" } : {})}
          onClick={href ? (e) => e.stopPropagation() : undefined}
          className={`game-chip ${played ? "played" : ""} ${live ? "live" : ""} ${g.date === today ? "today" : ""} ${lockDate === g.date ? "locked" : ""} ${href ? "watch" : ""}`}
          data-tip={gameTip(g, played, live, lockDate, href)}>
          <span className="gch-day">{dayName(g.date)} <span className="gch-time">{played ? "final" : live ? "LIVE" : shortTime(g.tip)}</span></span>
          <span className="gch-fp">{played ? fp(g.fp) : fp(g.proj)}</span>
        </Tag>
      );
    })}</span>
  );
}

const tipMs = (g) => Date.parse(g.tip) || Date.parse(`${g.date}T12:00:00`);
const GAME_MS = 135 * 60000;   // a game's length (tip to final), as the backend's timeline assumes
const dayIdx = (date, monday) => Math.round((Date.parse(date) - Date.parse(monday)) / 864e5);   // 0 = Monday
const mondayOf = (iso) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return d.toISOString().slice(0, 10);
};

// A player's week in the matchup: 7 day cells (Mon-Sun), the same columns as the timeline header above, so the
// time line runs straight down through them. Each game shows its state at the line's time (lineMs):
// done (final, or tipped more than a game's length before), on (tipped, still going) or still to come.
function WeekCells({ games, week, lockDate, team }) {
  const { list: matches } = useNBAMatches();
  const cells = Array(7).fill(null);
  for (const g of games) { const i = dayIdx(g.date, week.monday); if (i >= 0 && i < 7) cells[i] = g; }
  return (
    <div className="week-cells">{cells.map((g, i) => {
      if (!g) return <span key={i} />;
      const played = g.fp != null, live = g.state === "in", t = tipMs(g);
      const state = played && !live ? "done" : week.lineMs >= t + GAME_MS ? "past" : live || week.lineMs >= t ? "on" : "";
      const m = findMatch(matches, g, team);
      const href = m ? watchUrl(m) : null;
      const Tag = href ? "a" : "span";
      return (
        <Tag key={i} {...(href ? { href, target: "_blank", rel: "noopener noreferrer" } : {})}
          onClick={href ? (e) => e.stopPropagation() : undefined}
          className={`game-cell ${state} ${live ? "live" : ""} ${lockDate === g.date ? "locked" : ""} ${week.day === g.date ? "pick" : ""} ${href ? "watch" : ""}`}
          data-tip={gameTip(g, played, live, lockDate, href)}>
          <span className="gc-time">{played && !live ? "final" : live ? "LIVE" : shortTime(g.tip)}</span>
          <span className="gc-fp">{played ? fp(g.fp) : fp(g.proj)}</span>
        </Tag>
      );
    })}</div>
  );
}

const EXP_TIP = "Exp FP: the fantasy points this player is expected to put in your lineup this week. Only one of his games counts: " +
  "his locked game, else the better of locking his last game now and waiting for the rest (more games = more chances at a big one).";

// The lineup itself is the advice (your side shows the best lineup); the only call left is locking.
function lockCall(r) {
  if (r.lock_status === "locked") return ["info", "LOCKED", `Locked ${r.lock_date}: this slot's score is set.`];
  if (r.action === "LOCK") return ["good", "LOCK", r.why];
  if (r.action === "PASS") return ["even", "PASS", r.why];
  return ["", "", ""];
}

function PlayerCard({ data, r, open, setLock, mine, side, week }) {   // week: the matchup's day lane (WeekCells)
  if (!r) return <div className={`mu-card empty ${side}`}><span className="muted small">empty</span></div>;
  const p = data.players[r.sid] || { games: [] };
  const [cls, word, tip] = mine ? lockCall(r) : ["", "", ""];
  const lastPlayed = [...p.games].reverse().find((g) => g.fp != null);
  const starter = r.slot !== "BN" && r.slot !== "IR";
  return (
    <div className={`mu-card ${side} ${starter ? "" : "bench"}`} data-testid={`mu-${r.sid}`}>
      <div className="mu-top">
        <div className="mu-id clickable" onClick={() => open(r.sid)} data-testid={`open-${r.sid}`}>
        <Headshot sleeperId={r.sid} name={r.name} size={42} />
        <div className="mu-who">
          <div className="mu-name">{r.name}<InjuryTag tag={p.injury_tag} note={p.injury_note} /></div>
          <div className="small muted mu-sub">{p.team || "FA"} · <PosList list={r.pos} />
            {p.nick && showNicks() && <span className="nick" data-tip={`Nickname on Sleeper: ${p.nick}`}> · “{p.nick}”</span>}</div>
        </div>
        </div>
        {week
          ? <WeekCells games={p.games} team={p.team} week={mine ? week : { ...week, day: null }} lockDate={r.lock_status === "locked" ? r.lock_date : null} />
          : <GameChips games={p.games} team={p.team} today={data.today} lockDate={r.lock_status === "locked" ? r.lock_date : null} />}
        {mine && (
          <span className="mu-call">
            {word && <span className={`verdict ${cls}`} data-tip={tip} data-testid={`call-${r.sid}`}>{word}</span>}
            {r.win_lock != null && (word === "LOCK" || word === "PASS") && (
              <span className="small muted win-pair" data-tip={r.why}>lock {Math.round(r.win_lock * 100)}% · wait {Math.round(r.win_wait * 100)}%</span>
            )}
        <div className="mu-exp" data-tip={EXP_TIP}><span className="bid-label">Exp</span><strong>{fp(r.value)}</strong></div>
            {starter && (r.lock_status === "locked"
              ? <span className="ok small clickable" data-tip="Locked. Click if that's wrong." onClick={() => setLock(r.sid, "")}> ✓</span>
              : lastPlayed && <button className="tiny" onClick={() => setLock(r.sid, lastPlayed.date)}
                  data-tip={`${r.lock_status === "maybe" ? "Sleeper counts his latest game: locked or not? " : ""}Click if you locked his ${dayName(lastPlayed.date)} game (${fp(lastPlayed.fp)}).`}>
                  {r.lock_status === "maybe" ? "locked?" : "I locked"}</button>)}
          </span>
        )}
      </div>
    </div>
  );
}

// Slot order down the middle (PG PG SG SG ... C C), then every bench spot and every IR spot (empty ones too);
// each team's players fill their current slots.
function bySlot(rows, positions, irSlots) {
  const pool = {};
  for (const r of [...rows].sort((a, b) => b.value - a.value)) (pool[r.slot] ||= []).push(r);
  const fill = (slot, n) => Array.from({ length: n }, () => ({ slot, r: (pool[slot] || []).shift() }));
  const lines = positions.filter((x) => x !== "BN" && x !== "IR").map((slot) => ({ slot, r: (pool[slot] || []).shift() }));
  const bench = fill("BN", Math.max(positions.filter((x) => x === "BN").length, (pool.BN || []).length));
  const ir = fill("IR", Math.max(irSlots || 0, (pool.IR || []).length));
  return { lines, bench, ir };
}

const MODE = { ahead: ["good", "60%+ to win"], behind: ["bad", "40% or less to win"], even: ["", "Close: 40-60% to win"] };
const WIN_TIP = "Chance to win the week: your counted/locked points + what your other slots are expected to add (with their " +
  "spread) vs the same for your opponent. Every LOCK / PASS and KEEP / SWAP call picks the choice with the higher chance.";

// One matchup side by side. ◀ ▶ step through the league's matchups (yours first); calls and lock buttons show on
// yours only. Other matchups come from the plan endpoint for their first team (its opponent rides along).
function WeekView({ data, plan, open, setLock, leagueId }) {
  // Your side shows the best lineup at the timeline's time (default: now): everyone in the slot he should be in then,
  // not his Sleeper slot. The timeline has one lineup per game day; locked players never move.
  const [at, setAt] = useState(null);   // ms; null = follow the clock
  const tl = plan.timeline, nowMs = data.now ? Date.parse(data.now) : Date.now();
  const atMs = Math.max(at ?? nowMs, nowMs);
  const segIdx = tl ? Math.max(0, tl.segments.findIndex((s) => atMs < Date.parse(s.to))) : -1;
  const seg = tl?.segments[segIdx];
  const seats = seg ? seg.seats : plan.today?.seats;
  const best = {};
  for (const [slot, sids] of Object.entries(seats || {})) for (const sid of sids) best[sid] = slot;
  // The arrows show the changes from your Sleeper lineup as it is right now, at any point of the timeline (not from
  // the previous check-in's planned lineup), so they're the moves you'd make in Sleeper from where you are.
  const bestRows = seats ? plan.players.map((r) => ({ ...r, slot: best[r.sid] || (r.slot === "IR" ? "IR" : "BN") })) : plan.players;
  const before = Object.fromEntries(plan.players.map((r) => [r.sid, r.slot]));
  const pairs = seats ? swapPairs(before, Object.fromEntries(bestRows.map((r) => [r.sid, r.slot])), data.roster_positions) : [];
  const mineIdx = Math.max(0, data.matchups.findIndex((pair) => pair.some((m) => m.roster_id === plan.roster_id)));
  const [idx, setIdx] = useState(mineIdx);
  const [other, setOther] = useState(null);
  const isMine = idx === mineIdx;
  useEffect(() => {
    if (isMine) { setOther(null); return; }
    const rid = data.matchups[idx]?.[0]?.roster_id;
    api.get(`/leagues/${leagueId}/season/plan` + qs({ week: data.week, roster_id: rid })).then(setOther).catch(() => setOther(null));
  }, [idx, isMine, leagueId, data.week, data.matchups]);
  const shown = isMine ? plan : other;
  const n = data.matchups.length;
  const step = (d) => setIdx((i) => (i + d + n) % n);
  const nav = (
    <>
      <button className="mu-arrow left" onClick={() => step(-1)} data-tip="Previous matchup" data-testid="mu-prev">◀</button>
      <button className="mu-arrow right" onClick={() => step(1)} data-tip="Next matchup" data-testid="mu-next">▶</button>
    </>
  );
  if (!shown) return <div className="panel matchup"><div className="mu-head">{nav}<div className="muted">Loading matchup {idx + 1} of {n}…</div></div></div>;
  const o = shown.opponent;
  const L = bySlot(isMine ? bestRows : shown.players, data.roster_positions, data.reserve_slots);
  const R = o ? bySlot(o.players, data.roster_positions, data.reserve_slots) : { lines: [], bench: [], ir: [] };
  const lineMs = isMine ? atMs : nowMs;   // the slider only shows on your matchup
  // One grid for the whole matchup (subgrid columns: name | Mon-Sun | call · slot · name | Mon-Sun | call): the header
  // row holds the timeline (days, check-in ticks, slider) over the day lanes, and the time line runs down through them.
  const week = { monday: tl ? tl.start.slice(0, 10) : mondayOf(data.dates[0] || data.today), lineMs, day: seg?.date || data.day };
  const span = tl ? [Date.parse(tl.start), Date.parse(tl.end)] : null;
  const mode = MODE[shown.mode] || MODE.even;
  // first: the first bench / IR row gets a gap above it (instead of a divider row, so every row can share the height)
  const row = (l, r, key, slot, first, i) => (
    <React.Fragment key={key}>
      <div className={`mu-cell ${first ? "first" : ""}`} style={{ gridRow: i + 2, gridColumn: "1 / span 3" }}><PlayerCard data={data} r={l?.r} open={open} setLock={setLock} mine={isMine} side="left" week={week} /></div>
      <div className={`mu-slot ${first ? "first" : ""}`} style={{ gridRow: i + 2, gridColumn: 4 }}><PosTag text={slot} /></div>
      <div className={`mu-cell ${first ? "first" : ""}`} style={{ gridRow: i + 2, gridColumn: "5 / span 3" }}><PlayerCard data={data} r={r?.r} open={open} side="right" week={week} /></div>
    </React.Fragment>
  );
  const nBench = Math.max(L.bench.length, R.bench.length), nIr = Math.max(L.ir.length, R.ir.length);
  const nRows = L.lines.length + nBench + nIr;
  const overlay = (col) => span && (   // the past shaded and the time line, over one side's day lane, every row
    <div className="lane-over" style={{ gridColumn: col, gridRow: `2 / span ${nRows}` }}>
      <div className="lane-past" style={{ width: lanePos(span, nowMs) }} />
      <div className="time-line" data-testid={`time-line-${col}`} style={{ left: lanePos(span, lineMs) }} />
    </div>
  );
  return (
    <div className="panel matchup" data-testid="my-week">
      <div className="mu-head">
        <button className="mu-arrow" onClick={() => step(-1)} data-tip="Previous matchup" data-testid="mu-prev">◀</button>
        <div className="mu-team">
          <TeamName t={shown} cls="mc-name" size={34} />{isMine && <span className="badge info">YOU</span>}
          <span className="mc-points">{fp(shown.points)}</span>
          <span className="small muted"><span data-tip={EXP_TIP}>exp <strong style={{ color: "var(--text)" }}>{shown.expected}</strong></span> · {shown.games_left} left</span>
        </div>
        <div className="mu-mid">
          <span className="small muted">{idx + 1}/{n}</span>
          <span className={`verdict ${mode[0]}`} data-tip={mode[1]}>{shown.mode}</span>
          {shown.win_chance != null && <strong className="win-chance" data-tip={WIN_TIP}>{Math.round(shown.win_chance * 100)}% to win</strong>}
          {!isMine && <button className="tiny" onClick={() => setIdx(mineIdx)}>mine</button>}
          {isMine && (seg?.date || data.day) && (
            <span className="lineup-day" data-tip="Your side is the best lineup for this day: set Sleeper to match. Start whoever plays, earliest tip first; slots nobody playing that day needs go by each player's next game. Move the timeline above to see the lineup for a later time.">
              Best lineup: <strong>{(seg?.date || data.day) === data.today ? "today" : dayName(seg?.date || data.day)}</strong>
            </span>
          )}
        </div>
        <div className="mu-team right">
          {o && <span className="small muted"><span data-tip={EXP_TIP}>exp <strong style={{ color: "var(--text)" }}>{o.expected}</strong></span> · {o.games_left} left · {o.locked} locked</span>}
          <span className="mc-points">{o ? fp(o.points) : ""}</span>
          {o ? <TeamName t={o} cls="mc-name" size={34} /> : <span className="mc-name">no opponent</span>}
        </div>
        <button className="mu-arrow" onClick={() => step(1)} data-tip="Next matchup" data-testid="mu-next">▶</button>
      </div>
      <div className={`mu-grid week ${isMine ? "with-arrows" : ""}`}>
        {isMine && <SwapArrows pairs={pairs} names={(sid) => data.players[sid]?.name || sid} />}
        <div className="wk-head-left" style={{ gridColumn: 1, gridRow: 1 }}>
          {isMine && tl?.segments.length > 0 && <NextCheck tl={tl} nowMs={nowMs} following={at == null} setAt={setAt} />}
        </div>
        <div style={{ gridColumn: 2, gridRow: 1 }}>
          <WeekAxis monday={week.monday} day={isMine ? week.day : null} today={data.today}
            slider={isMine && tl?.segments.length > 0 ? { tl, nowMs, atMs, setAt } : null} />
        </div>
        {o && <div style={{ gridColumn: 6, gridRow: 1 }}><WeekAxis monday={week.monday} today={data.today} /></div>}
        {L.lines.map((l, i) => row(l, R.lines[i], `s${i}`, l.slot, false, i))}
        {Array.from({ length: nBench }, (_, i) => row(L.bench[i], R.bench[i], `b${i}`, "BN", i === 0, L.lines.length + i))}
        {Array.from({ length: nIr }, (_, i) => row(L.ir[i], R.ir[i], `i${i}`, "IR", i === 0, L.lines.length + nBench + i))}
        {overlay(2)}
        {o && overlay(6)}
      </div>
    </div>
  );
}

// Who replaces whom from lineup `before` to lineup `after` (sid -> slot): each player newly starting is paired with a
// player leaving the lineup, the one from the same slot when there is one. Moves between starting slots aren't swaps.
const isStarter = (slot) => slot && slot !== "BN" && slot !== "IR";
function swapPairs(before, after, positions) {
  const ins = Object.keys(after).filter((sid) => isStarter(after[sid]) && !isStarter(before[sid]))
    .sort((a, b) => positions.indexOf(after[a]) - positions.indexOf(after[b]));
  const outs = Object.keys(before).filter((sid) => isStarter(before[sid]) && !isStarter(after[sid]));
  return ins.flatMap((sid) => {
    if (!outs.length) return [];
    const k = outs.findIndex((o) => before[o] === after[sid]);
    return [{ in: sid, out: outs.splice(k < 0 ? 0 : k, 1)[0], slot: after[sid] }];
  });
}

// The arrows, in a lane left of your cards: from the player going to the bench to the one taking his place,
// coloured by that slot's position. Measured from the cards on screen; redrawn when the grid changes size.
const ARROW_GUTTER = 80;
function SwapArrows({ pairs, names }) {
  const svgRef = React.useRef(null);
  const [lines, setLines] = useState([]);
  const key = pairs.map((p) => `${p.out}>${p.in}`).join(",");
  React.useLayoutEffect(() => {
    // the grid through our own svg: on mount the grid's ref isn't attached yet when this runs (children first)
    const grid = svgRef.current?.parentElement;
    if (!grid) return undefined;
    const measure = () => {
      const top = grid.getBoundingClientRect().top;
      const mid = (sid) => {
        const el = grid.querySelector(`.mu-card.left[data-testid="mu-${sid}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return r.top + r.height / 2 - top;
      };
      // shortest arrows nearest the cards, longest outside: nested lines cross as little as possible
      setLines(pairs.map((p) => ({ ...p, y1: mid(p.out), y2: mid(p.in) })).filter((l) => l.y1 != null && l.y2 != null)
        .sort((a, b) => Math.abs(a.y1 - a.y2) - Math.abs(b.y1 - b.y2)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    return () => ro.disconnect();
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const step = Math.min(13, (ARROW_GUTTER - 24) / Math.max(1, lines.length));
  const end = ARROW_GUTTER - 6;   // just left of the cards
  return (
    <svg ref={svgRef} className="swap-arrows" width={ARROW_GUTTER} data-testid="swap-arrows">
      {lines.map((l, i) => {
        const x = end - 12 - i * step, r = 6, dir = l.y2 < l.y1 ? -1 : 1;
        const color = `var(--pos-${(String(l.slot).match(/PG|SG|SF|PF|C/) || ["C"])[0]})`;
        const d = `M ${end} ${l.y1} H ${x + r} Q ${x} ${l.y1} ${x} ${l.y1 + dir * r} V ${l.y2 - dir * r} Q ${x} ${l.y2} ${x + r} ${l.y2} H ${end - 5}`;
        return (
          <g key={`${l.out}>${l.in}`} style={{ color }}>
            <title>{`${names(l.in)} takes the place of ${names(l.out)} at ${l.slot}`}</title>
            <path d={d} className="swap-path" />
            <circle cx={end} cy={l.y1} r="3" fill="currentColor" />
            <polygon points={`${end - 6},${l.y2 - 5} ${end + 1},${l.y2} ${end - 6},${l.y2 + 5}`} fill="currentColor" />
          </g>
        );
      })}
    </svg>
  );
}

// The week (Mon 12 AM to the next Mon) across a day lane: a time's x in it. The lane and the day cells are inset 8px
// on each side, where the slider's 16px dot can't reach, so the dot, the day columns and the time line all agree.
const STEP_MS = 15 * 60000;
const lanePos = ([start, end], ms) => `calc(${Math.min(1, Math.max(0, (ms - start) / (end - start)))} * (100% - 16px) + 8px)`;

// The header over a day lane: Mon-Sun (the lineup's day lit), and on your side the timeline: check-in ticks and the
// dot that picks the time whose best lineup shows (15-minute steps; the past is shaded and out of reach).
function WeekAxis({ monday, day, today, slider }) {
  const dates = Array.from({ length: 7 }, (_, i) => new Date(Date.parse(monday) + i * 864e5).toISOString().slice(0, 10));
  const s = slider, span = s && [Date.parse(s.tl.start), Date.parse(s.tl.end)];
  return (
    <div className="wk-axis" data-testid={s ? "timeline" : undefined}>
      <div className="wk-days">{dates.map((d) => (
        <span key={d} className={`${d === day ? "pick" : ""} ${d === today ? "today" : ""}`}>{dayName(d)} <span className="wk-md">{md(d)}</span></span>
      ))}</div>
      {s && (
        <div className="tl-bar">
          <div className="tl-past" style={{ width: lanePos(span, s.nowMs) }} />
          {s.tl.segments.slice(0, -1).map((x) => <div key={x.to} className="tl-mark" style={{ left: lanePos(span, Date.parse(x.to)) }} />)}
          <input type="range" min={span[0]} max={span[1]} step={STEP_MS} value={Math.round((s.atMs - span[0]) / STEP_MS) * STEP_MS + span[0]}
            onChange={(e) => s.setAt(Math.max(Number(e.target.value), s.nowMs))} aria-label="Lineup time" data-testid="timeline-slider" />
          <span className="tl-time" style={{ left: lanePos(span, s.atMs) }} data-testid="timeline-time">{fmt(s.atMs, { hour: "numeric", minute: "2-digit" })}</span>
        </div>
      )}
    </div>
  );
}

// The next purple tick still ahead: when to open Sleeper next ("in 1 day, 4 hours"); click to show that lineup.
function NextCheck({ tl, nowMs, following, setAt }) {
  const next = tl.segments.slice(0, -1).map((s) => Date.parse(s.to)).find((ms) => ms > nowMs);
  const mins = next ? Math.ceil((next - nowMs) / 60000) : 0;
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  const until = d ? `${plural(d, "day")}, ${plural(h, "hour")}` : h ? `${plural(h, "hour")}, ${plural(m, "minute")}` : plural(m, "minute");
  return (
    <>
      <button className="tl-next" onClick={() => next && setAt(next)} disabled={!next} data-testid="next-check"
        data-tip="The next time the lineup changes: open Sleeper then and make every swap at once. Click to show that lineup.">
        <span className="tl-next-label">Next check-in{next && <span className="tl-next-in"> · in {until}</span>}</span>
        {next ? <strong>{fmt(next, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</strong>
          : <span className="small muted">none left this week</span>}
      </button>
      {!following && <button className="tiny" onClick={() => setAt(null)} data-testid="timeline-now">back to now</button>}
    </>
  );
}

// Another team's week (League tab): the same cards in one column.
function TeamColumn({ data, team, open }) {
  const { lines, bench, ir } = bySlot(team.players, data.roster_positions, data.reserve_slots);
  return (
    <div className="team-col">
      {[...lines, ...bench, ...ir].map((line, i) => (
        <div key={i} className="team-col-row"><div className="mu-slot"><PosTag text={line.slot} /></div><PlayerCard data={data} r={line.r} open={open} side="left" /></div>
      ))}
    </div>
  );
}

// News: fantasy notes on your players (collapsible, always starts open), then on the other teams' players under it.
// Reloads on Sync (refreshKey); the backend caches both for 15 minutes otherwise.
// "2d 5h ago · 10/14/26" (under an hour: "35m ago")
const newsTime = (iso) => {
  if (!iso) return "";
  const t = new Date(iso), mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60);
  const ago = mins < 60 ? `${mins}m` : d ? `${d}d ${h}h` : `${h}h`;
  return `${ago} ago · ${fmt(t, { month: "2-digit", day: "2-digit", year: "2-digit" })}`;
};

// One note: who (opens his profile), his injury tag, the fantasy team that has him (league-wide), when, the note.
function NewsNote({ n, open, owner }) {
  const title = n.headline.startsWith(`${n.name} - `) ? n.headline.slice(n.name.length + 3) : n.headline;   // name is already above
  return (
    <div className={`news-item ${n.injury ? "injury" : ""}`}>
      <div className="news-head">
        <span className="clickable news-player" onClick={() => open(n.player_id)}>
          <Headshot sleeperId={n.sid} name={n.name} size={28} /> <strong>{n.name}</strong>
        </span>
        <InjuryTag tag={n.injury_tag} note={n.injury_note} />
        {n.team && <span className="small muted">{n.team}</span>}
        {owner && <span className="small muted">· {n.owner}</span>}
        <span className="small muted news-time">{newsTime(n.published)}</span>
      </div>
      <div className="news-title">{title}</div>
      {n.story && <div className="small news-story">{n.story}</div>}
    </div>
  );
}

const LEAGUE_NEWS = 80;   // newest league-wide notes shown (after filtering)

function NewsView({ leagueId, open, refreshKey }) {
  const [news, setNews] = useState(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState(""), [nba, setNba] = useState(""), [mgr, setMgr] = useState(""), [inj, setInj] = useState(false);
  useEffect(() => {
    api.get(`/leagues/${leagueId}/season/news`).then((n) => { setNews(n); setError(""); }).catch((e) => setError(e.message));
  }, [leagueId, refreshKey]);
  if (error) return <div className="panel error">{error}</div>;
  if (!news) return <div className="panel muted">Loading news…</div>;
  const words = q.toLowerCase().trim();
  // search: player, NBA team, manager's username or the note itself; the manager pick only narrows the league list
  const keep = (n) => (!nba || n.team === nba) && (!inj || n.injury)
    && (!words || [n.name, n.team, n.user, n.headline, n.story].join(" ").toLowerCase().includes(words));
  const mine = news.mine.filter(keep), free = news.free.filter(keep);
  const league = news.league.filter((n) => keep(n) && (!mgr || n.user === mgr));
  const nbaTeams = [...new Set([...news.mine, ...news.league, ...news.free].map((n) => n.team).filter(Boolean))].sort();
  const managers = [...new Set(news.league.map((n) => n.user))].sort((a, b) => a.localeCompare(b));
  return (
    <div className="news-col">
      <div className="panel news-filters" data-testid="news-filters">
        <input type="search" placeholder="Search player, team, manager or note…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="news-search" />
        <select value={nba} onChange={(e) => setNba(e.target.value)} data-testid="news-nba"><option value="">All NBA teams</option>{nbaTeams.map((t) => <option key={t}>{t}</option>)}</select>
        <select value={mgr} onChange={(e) => setMgr(e.target.value)} data-testid="news-manager"><option value="">All managers</option>{managers.map((m) => <option key={m}>{m}</option>)}</select>
        <label className="inline"><input type="checkbox" checked={inj} onChange={(e) => setInj(e.target.checked)} data-testid="news-injuries" /> Injuries only</label>
        {(q || nba || mgr || inj) && <button className="small ghost" onClick={() => { setQ(""); setNba(""); setMgr(""); setInj(false); }}>clear</button>}
      </div>
      {!mgr && (
        <details className="panel news" open data-testid="news-mine">
          <summary><h3>My team <span className="small muted">({mine.length})</span></h3></summary>
          {mine.length ? mine.map((n, i) => <NewsNote key={i} n={n} open={open} />)
            : <div className="muted">No recent notes on your players{q || nba || inj ? " match" : ""}.</div>}
        </details>
      )}
      {!mgr && free.length > 0 && (
        <details className="panel news" open data-testid="news-free">
          <summary><h3>Free agents <span className="small muted">(most added / dropped on Sleeper today, {free.length})</span></h3></summary>
          {free.map((n, i) => <NewsNote key={i} n={n} open={open} />)}
        </details>
      )}
      <div className="panel news" data-testid="news-league">
        <h3>League-wide <span className="small muted">({mgr || "other teams' players"}{league.length > LEAGUE_NEWS ? `, newest ${LEAGUE_NEWS} of ${league.length}` : ""})</span></h3>
        {league.length ? league.slice(0, LEAGUE_NEWS).map((n, i) => <NewsNote key={i} n={n} open={open} owner />)
          : <div className="muted">No notes match.</div>}
      </div>
    </div>
  );
}

function LeagueView({ data, leagueId, open }) {
  const team = Object.fromEntries(data.teams.map((t) => [t.roster_id, t]));
  const [shown, setShown] = useState(null);   // another team's week plan (roster + games), from the plan endpoint
  const show = (rid) => api.get(`/leagues/${leagueId}/season/plan` + qs({ week: data.week, roster_id: rid })).then(setShown).catch(() => setShown(null));
  const standings = [...data.teams].sort((a, b) => b.wins - a.wins || b.fpts - a.fpts);
  return (
    <>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Matchups · week {data.week}</h3>
        <div className="league-matchups">
          {data.matchups.map((pair, i) => (
            <div key={i} className="lm-card">
              {pair.map((m) => {
                const t = team[m.roster_id] || {}, other = pair.find((x) => x !== m);
                return (
                  <div key={m.roster_id} className={`lm-row clickable ${t.is_user ? "me" : ""} ${other && (m.points || 0) > (other.points || 0) ? "lead" : ""}`}
                    onClick={() => show(m.roster_id)} data-tip="Show this team's roster and games">
                    <TeamName t={t} size={22} /><strong>{fp(m.points || 0)}</strong>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {shown && (
        <div className="panel" data-testid="team-roster">
          <h3 style={{ marginTop: 0 }}><TeamName t={shown} size={28} /> <span className="small muted">expected {shown.expected} FP this week · {shown.games_left} games left</span>
            <button className="small ghost" style={{ marginLeft: 8 }} onClick={() => setShown(null)}>close</button></h3>
          <TeamColumn data={data} team={shown} open={open} />
        </div>
      )}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Standings</h3>
        <table className="small" data-testid="standings">
          <thead><tr><th>#</th><th>Team</th><th className="num">W</th><th className="num">L</th><th className="num">PF</th><th className="num">FAAB left</th></tr></thead>
          <tbody>{standings.map((t, i) => (
            <tr key={t.roster_id} className={t.is_user ? "you-need" : ""}><td>{i + 1}</td><td className="clickable" onClick={() => show(t.roster_id)}><TeamName t={t} size={22} /></td><td className="num">{t.wins}</td><td className="num">{t.losses}</td>
              <td className="num">{fp(t.fpts)}</td><td className="num">{data.waiver ? `$${(data.faab_budget ?? 100) - (t.faab_used || 0)}` : "?"}</td></tr>))}</tbody>
        </table>
      </div>
    </>
  );
}

function WaiversView({ leagueId, onSelect }) {
  const [w, setW] = useState(null);
  useEffect(() => { api.get(`/leagues/${leagueId}/season/waivers`).then(setW).catch(() => setW(null)); }, [leagueId]);
  if (!w) return <div className="panel waivers">Loading free agents…</div>;
  if (w.error) return <div className="panel waivers warn-text" data-testid="waivers-error">{w.error}</div>;
  const faab = w.type === "FAAB";
  const top = Math.max(...w.claims.map((c) => c.upgrade), 0.01);   // upgrade bars scale to the best one
  return (
    <div className="panel waivers" data-testid="waivers">
      <div className="wv-head">
        <h3>Waiver claims</h3>
        <span className="wv-chip">{faab ? "Blind FAAB" : `${w.type} priority`}</span>
        <span className="wv-chip">Process {w.process}</span>
        {faab && (
          <span className="wv-faab" data-tip="FAAB left this season">
            <span className="wv-meter"><span style={{ width: `${(w.faab_left / w.budget) * 100}%` }} /></span>
            <strong>${w.faab_left}</strong><span className="muted"> / ${w.budget}</span>
          </span>
        )}
      </div>
      {w.drop && (
        <div className="wv-drop clickable" onClick={() => onSelect(w.drop.player_id)}>
          <Headshot sleeperId={w.drop.sleeper_id} name={w.drop.name} size={32} />
          <div><div className="small muted">Drop candidate · your weakest</div><strong>{w.drop.name}</strong></div>
          <span className="wv-drop-val"><span className="small muted">value</span> {w.drop.value.toFixed(2)}</span>
        </div>
      )}
      {w.claims.length ? (
        <table className="wv-table">
          <thead><tr><th>Player</th><th className="num" data-tip="Rest-of-season value: projection, Lock-In best game and availability.">Value</th>
            <th data-tip="Value over your drop candidate.">Upgrade</th><th className="num">Games this wk</th>
            <th className="num" data-tip="A guide: share of your FAAB that grows with the upgrade. Other bids are hidden.">Bid</th></tr></thead>
          <tbody>{w.claims.map((c) => (
            <tr key={c.player_id} className="clickable" onClick={() => onSelect(c.player_id)}>
              <td><div className="wv-player"><Headshot sleeperId={c.sleeper_id} name={c.name} size={36} />
                <div><strong>{c.name}</strong><InjuryTag tag={c.injury_tag} /><div className="small muted">{c.team} · <PosList list={c.pos} /></div></div></div></td>
              <td className="num">{c.value.toFixed(2)}</td>
              <td><div className="wv-up"><span className="wv-bar"><span style={{ width: `${(c.upgrade / top) * 100}%` }} /></span><span className="ok">+{c.upgrade.toFixed(2)}</span></div></td>
              <td className="num">{c.games_this_week}</td>
              <td className="num">{c.bid != null ? <span className="wv-bid">${c.bid}</span> : <span className="muted">-</span>}</td></tr>))}</tbody>
        </table>
      ) : <div className="muted">No free agent is an upgrade over your weakest player.</div>}
    </div>
  );
}
