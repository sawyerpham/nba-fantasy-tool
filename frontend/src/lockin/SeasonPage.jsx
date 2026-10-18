import React, { useCallback, useEffect, useState } from "react";
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
        {view === "news" && <NewsView data={data} leagueId={leagueId} open={open} refreshKey={tick} />}
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

// One card per game he has this week (so 3-4 at most): day, tip time, then FP once played or the projection.
// lane (matchup cards): { xs: tip ms -> x px, scale }, so the chips line up as a timeline (see laneXs).
function GameChips({ games, today, lockDate, day, lane }) {   // day: the lineup day shown (its chip lights up, the rest dim)
  if (!games.length) return lane ? <span className="chips-lane"><span className="muted small">no games</span></span> : <span className="muted small">no games</span>;
  const chips = games.map((g) => {
        const played = g.fp != null, live = g.state === "in";
        return (
          <span key={g.date} style={lane?.xs ? { left: lane.xs.get(tipMs(g)) ?? 0, ...(lane.scale < 1 && { transform: `translateY(-50%) scale(${lane.scale})` }) } : undefined}
            className={`game-chip ${played ? "played" : ""} ${live ? "live" : ""} ${g.date === today ? "today" : ""} ${lockDate === g.date ? "locked" : ""} ${day ? (g.date === day ? "pick" : "dim") : ""}`}
            data-tip={`${dayName(g.date)} ${md(g.date)} ${g.home ? "vs" : "@"} ${g.opp} · ${played ? `${g.fp} FP in ${g.min} min` : live ? `live: ${g.detail}` : `tips ${timeOf(g.tip)} ${tzAbbr(Date.parse(g.tip))} · projected ${fp(g.proj)} FP`}${lockDate === g.date ? " · LOCKED" : ""}`}>
            <span className="gch-day">{dayName(g.date)} <span className="gch-time">{played ? "final" : live ? "LIVE" : timeOf(g.tip).replace(":00", "").replace(" PM", "p").replace(" AM", "a")}</span></span>
            <span className="gch-fp">{played ? fp(g.fp) : fp(g.proj)}</span>
          </span>
        );
      });
  if (!lane) return <span className="chips-row">{chips}</span>;
  return <span className="chips-lane">{lane.xs ? chips : <span className="chips-row">{chips}</span>}</span>;
}

const tipMs = (g) => Date.parse(g.tip) || Date.parse(`${g.date}T12:00:00`);

// A matchup's chips as a timeline: one x per distinct tip on both rosters, the earliest at the lane's left edge, spaced in
// proportion to time but pushed right wherever a player's chip would overlap his previous one. The time scale is
// the largest that still fits the last chip in the lane, so a week with 4-game players spreads less than one with 3.
// Too narrow even packed tight: the chips shrink (scale) until they fit, down to 80%; narrower than that, xs is null
// and the chips sit in a plain row (no time line).
const CHIP_W = 86, CHIP_GAP = 6;
function laneXs(rows, width) {   // rows: each player's tip ms, sorted
  const tips = [...new Set(rows.flat())].sort((a, b) => a - b);
  if (!tips.length || !width) return { xs: new Map(), scale: 1 };
  const t0 = tips[0], span = Math.max(1, tips.at(-1) - t0);
  const place = (s, cw) => {
    const x = new Map();
    let prev = 0;
    for (const t of tips) {
      let v = Math.max(prev, (s * (t - t0) / span) * (width - cw));
      for (const r of rows) { const i = r.indexOf(t); if (i > 0) v = Math.max(v, x.get(r[i - 1]) + cw + CHIP_GAP); }
      x.set(t, v); prev = v;
    }
    return x;
  };
  const fits = (s) => place(s, CHIP_W).get(tips.at(-1)) <= width - CHIP_W;
  if (!fits(0)) {
    const k = Math.round(place(0, CHIP_W).get(tips.at(-1)) / (CHIP_W + CHIP_GAP));   // chips packed end to end
    const cw = (width - k * CHIP_GAP) / (k + 1);
    return cw < 0.8 * CHIP_W ? { xs: null } : { xs: place(0, cw), scale: cw / CHIP_W };   // unreadable smaller: plain row
  }
  let lo = 0, hi = 1;
  if (fits(1)) lo = 1;
  else for (let k = 0; k < 20; k++) { const m = (lo + hi) / 2; if (fits(m)) lo = m; else hi = m; }
  return { xs: place(lo, CHIP_W), scale: 1 };
}

// The time line's x: between tips it moves at an even pace from one chip's left edge (its tip) to the next.
function laneAt(xs, ms, start, end, width) {
  const pts = [[start, -8], ...xs, [Math.max(end, start + 1), width]];
  if (ms <= pts[0][0]) return pts[0][1];
  for (let i = 1; i < pts.length; i++) {
    const [t1, x1] = pts[i], [t0, x0] = pts[i - 1];
    if (ms <= t1) return t1 === t0 ? x1 : x0 + ((ms - t0) / (t1 - t0)) * (x1 - x0);
  }
  return width;
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

function PlayerCard({ data, r, open, setLock, mine, side, day, lane }) {
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
          <div className="small muted">{p.team || "FA"} · <PosList list={r.pos} /></div>
        </div>
        </div>
        <GameChips games={p.games} today={data.today} day={mine ? day || data.day : null} lockDate={r.lock_status === "locked" ? r.lock_date : null} lane={lane} />
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
  const gridRef = React.useRef(null);
  const slotIn = (st, r) => Object.entries(st || {}).find(([, ids]) => ids.includes(r.sid))?.[0] || (r.slot === "IR" ? "IR" : "BN");
  // The arrows show the changes: on "now" from your Sleeper lineup, further along from the lineup just before this
  // change point.
  const bestRows = seats ? plan.players.map((r) => ({ ...r, slot: best[r.sid] || (r.slot === "IR" ? "IR" : "BN") })) : plan.players;
  const before = Object.fromEntries(plan.players.map((r) => [r.sid, at == null || segIdx <= 0 ? r.slot : slotIn(tl.segments[segIdx - 1].seats, r)]));
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
  // Both teams' chip lanes share one width (the narrowest) and one time axis; each column has its own left edge.
  // Measured from the cards on screen.
  const [lane, setLane] = useState(null);
  React.useLayoutEffect(() => {
    const grid = gridRef.current;
    if (!grid) return undefined;
    const measure = () => {
      const g = grid.getBoundingClientRect().left;
      const side = (s) => [...grid.querySelectorAll(`.mu-card.${s} .chips-lane`)];
      const L = side("left"), R = side("right");
      if (!L.length && !R.length) return;
      const w = Math.min(...[...L, ...R].map((e) => e.getBoundingClientRect().width));
      const edge = (els) => (els.length ? els[0].getBoundingClientRect().left - g : null);
      const l = edge(L), r = edge(R);
      setLane((o) => (o && o.w === w && o.l === l && o.r === r ? o : { w, l, r }));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    return () => ro.disconnect();
  });
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
  const tips = (players) => players.map((r) => (data.players[r.sid]?.games || []).map(tipMs).sort((a, b) => a - b));
  const xs = laneXs([...tips(shown.players), ...tips(o?.players || [])], lane?.w);
  const lineMs = isMine ? atMs : nowMs;   // the slider only shows on your matchup
  const mode = MODE[shown.mode] || MODE.even;
  // first: the first bench / IR row gets a gap above it (instead of a divider row, so every row can share the height)
  const row = (l, r, key, slot, first) => (
    <React.Fragment key={key}>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={l?.r} open={open} setLock={setLock} mine={isMine} side="left" day={seg?.date} lane={xs} /></div>
      <div className={`mu-slot ${first ? "first" : ""}`}><PosTag text={slot} /></div>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={r?.r} open={open} side="right" lane={xs} /></div>
    </React.Fragment>
  );
  return (
    <div className="panel matchup" data-testid="my-week">
      {isMine && tl?.segments.length > 0 && <Timeline tl={tl} nowMs={nowMs} atMs={atMs} following={at == null} setAt={setAt} />}
      <div className="mu-head">
        <button className="mu-arrow" onClick={() => step(-1)} data-tip="Previous matchup" data-testid="mu-prev">◀</button>
        <div className="mu-team">
          <span className="mc-name">{shown.name}</span>{isMine && <span className="badge info">YOU</span>}
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
          <span className="mc-name">{o ? o.name : "no opponent"}</span>
        </div>
        <button className="mu-arrow" onClick={() => step(1)} data-tip="Next matchup" data-testid="mu-next">▶</button>
      </div>
      <div className={`mu-grid ${isMine ? "with-arrows" : ""}`} ref={gridRef}>
        {isMine && <SwapArrows gridRef={gridRef} pairs={pairs} names={(sid) => data.players[sid]?.name || sid} />}
        {tl && lane && xs.xs?.size > 0 && [["l", lane.l], ["r", lane.r]].filter(([, x]) => x != null).map(([k, x]) => (
          <div key={k} className="time-line" data-testid={`time-line-${k}`} style={{ left: x + laneAt(xs.xs, lineMs, Date.parse(tl.start), Date.parse(tl.end), lane.w) - 1 }} />
        ))}
        {L.lines.map((l, i) => row(l, R.lines[i], `s${i}`, l.slot))}
        {Array.from({ length: Math.max(L.bench.length, R.bench.length) }, (_, i) => row(L.bench[i], R.bench[i], `b${i}`, "BN", i === 0))}
        {Array.from({ length: Math.max(L.ir.length, R.ir.length) }, (_, i) => row(L.ir[i], R.ir[i], `i${i}`, "IR", i === 0))}
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
function SwapArrows({ gridRef, pairs, names }) {
  const [lines, setLines] = useState([]);
  const key = pairs.map((p) => `${p.out}>${p.in}`).join(",");
  React.useLayoutEffect(() => {
    const grid = gridRef.current;
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
  }, [gridRef, key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const step = Math.min(13, (ARROW_GUTTER - 24) / Math.max(1, lines.length));
  const end = ARROW_GUTTER - 6;   // just left of the cards
  return (
    <svg className="swap-arrows" width={ARROW_GUTTER} data-testid="swap-arrows">
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

// The week as a line (Mon 12 AM to the next Mon), 15-minute steps; the dot picks the time whose best lineup shows.
// The past is shaded and the dot can't go there (no lineup to set for it).
const STEP_MS = 15 * 60000;

function Timeline({ tl, nowMs, atMs, following, setAt }) {
  const start = Date.parse(tl.start), end = Date.parse(tl.end);
  const frac = (ms) => Math.min(1, Math.max(0, (ms - start) / (end - start)));
  const at = (ms) => `calc(${frac(ms)} * (100% - 16px) + 8px)`;   // where the 16px dot's centre sits for that time
  const days = Array.from({ length: 7 }, (_, i) => start + i * 86400000 + 12 * 3600000);   // noon of each day
  return (
    <div className="timeline" data-testid="timeline">
      <div className="tl-back">{!following && <button className="tiny" onClick={() => setAt(null)} data-testid="timeline-now">back to now</button>}</div>
      <div className="tl-main">
        <div className="tl-days">{days.map((d) => <span key={d}>{fmt(d, { weekday: "short" })} {fmt(d, { month: "2-digit", day: "2-digit" })}</span>)}</div>
        <div className="tl-bar">
          <div className="tl-past" style={{ width: at(nowMs) }} />
          {tl.segments.slice(0, -1).map((s) => <div key={s.to} className="tl-mark" style={{ left: at(Date.parse(s.to)) }} />)}
          <input type="range" min={start} max={end} step={STEP_MS} value={Math.round((atMs - start) / STEP_MS) * STEP_MS + start}
            onChange={(e) => setAt(Math.max(Number(e.target.value), nowMs))} aria-label="Lineup time" data-testid="timeline-slider" />
          <span className="tl-time" style={{ left: at(atMs) }} data-testid="timeline-time">{fmt(atMs, { hour: "numeric", minute: "2-digit" })}</span>
        </div>
      </div>
    </div>
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
function NewsNote({ n, data, open, owner }) {
  const p = data.players[n.sid];
  return (
    <div className="news-item">
      <div className="news-head">
        <span className="clickable news-player" onClick={() => open(n.sid)}>
          <Headshot sleeperId={n.sid} name={n.name} size={28} /> <strong>{n.name}</strong>
        </span>
        <InjuryTag tag={p?.injury_tag} note={p?.injury_note} />
        {owner && <span className="small muted">· {n.owner}</span>}
        <span className="small muted news-time">{newsTime(n.published)}</span>
      </div>
      <div className="news-title">{n.headline}</div>
      {n.story && <div className="small news-story">{n.story}</div>}
    </div>
  );
}

function NewsView({ data, leagueId, open, refreshKey }) {
  const [news, setNews] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.get(`/leagues/${leagueId}/season/news`).then((n) => { setNews(n); setError(""); }).catch((e) => setError(e.message));
  }, [leagueId, refreshKey]);
  if (error) return <div className="panel error">{error}</div>;
  if (!news) return <div className="panel muted">Loading news…</div>;
  return (
    <div className="news-col">
      <details className="panel news" open data-testid="news-mine">
        <summary><h3>My team <span className="small muted">({news.mine.length})</span></h3></summary>
        {news.mine.length ? news.mine.map((n, i) => <NewsNote key={i} n={n} data={data} open={open} />)
          : <div className="muted">No recent notes on your players.</div>}
      </details>
      <div className="panel news" data-testid="news-league">
        <h3>League-wide <span className="small muted">(other teams' players)</span></h3>
        {news.league.map((n, i) => <NewsNote key={i} n={n} data={data} open={open} owner />)}
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
                    <span>{t.name}</span><strong>{fp(m.points || 0)}</strong>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
      {shown && (
        <div className="panel" data-testid="team-roster">
          <h3 style={{ marginTop: 0 }}>{shown.name} <span className="small muted">expected {shown.expected} FP this week · {shown.games_left} games left</span>
            <button className="small ghost" style={{ marginLeft: 8 }} onClick={() => setShown(null)}>close</button></h3>
          <TeamColumn data={data} team={shown} open={open} />
        </div>
      )}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Standings</h3>
        <table className="small" data-testid="standings">
          <thead><tr><th>#</th><th>Team</th><th className="num">W</th><th className="num">L</th><th className="num">PF</th><th className="num">FAAB left</th></tr></thead>
          <tbody>{standings.map((t, i) => (
            <tr key={t.roster_id} className={t.is_user ? "you-need" : ""}><td>{i + 1}</td><td className="clickable" onClick={() => show(t.roster_id)}>{t.name}</td><td className="num">{t.wins}</td><td className="num">{t.losses}</td>
              <td className="num">{fp(t.fpts)}</td><td className="num">{data.waiver ? `$${(data.faab_budget ?? 100) - (t.faab_used || 0)}` : "?"}</td></tr>))}</tbody>
        </table>
      </div>
    </>
  );
}

function WaiversView({ leagueId, onSelect }) {
  const [w, setW] = useState(null);
  useEffect(() => { api.get(`/leagues/${leagueId}/season/waivers`).then(setW).catch(() => setW(null)); }, [leagueId]);
  if (!w) return <div className="panel">Loading free agents…</div>;
  if (w.error) return <div className="panel warn-text" data-testid="waivers-error">{w.error}</div>;
  const faab = w.type === "FAAB";
  return (
    <div className="panel" data-testid="waivers">
      <h3 style={{ marginTop: 0 }}>Waiver claims <span className="small muted">{faab ? <>blind FAAB bids · process {w.process} · ${w.faab_left} left of ${w.budget}</> : <>{w.type} waiver priority · process {w.process}</>}</span></h3>
      {w.drop && <div className="small" style={{ marginBottom: 8 }}>Drop candidate: <strong className="clickable" onClick={() => onSelect(w.drop.player_id)}>{w.drop.name}</strong> <span className="muted">(value {w.drop.value}, your weakest)</span></div>}
      {w.claims.length ? (
        <table className="small">
          <thead><tr><th>Player</th><th>Team</th><th>Pos</th><th className="num" data-tip="Rest-of-season value: projection, Lock-In best game and availability.">Value</th>
            <th className="num" data-tip="Value over your drop candidate.">Upgrade</th><th className="num">Games this wk</th><th className="num" data-tip="A guide: share of your FAAB that grows with the upgrade. Other bids are hidden.">Bid</th></tr></thead>
          <tbody>{w.claims.map((c) => (
            <tr key={c.player_id}><td className="clickable" onClick={() => onSelect(c.player_id)}><strong>{c.name}</strong><InjuryTag tag={c.injury_tag} /></td>
              <td>{c.team}</td><td><PosList list={c.pos} /></td><td className="num">{c.value}</td><td className="num ok">+{c.upgrade}</td>
              <td className="num">{c.games_this_week}</td><td className="num">{c.bid != null ? <strong>${c.bid}</strong> : <span className="muted">-</span>}</td></tr>))}</tbody>
        </table>
      ) : <div className="muted">No free agent is an upgrade over your weakest player.</div>}
    </div>
  );
}
