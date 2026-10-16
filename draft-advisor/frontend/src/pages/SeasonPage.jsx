import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api, qs } from "../api.js";
import Headshot from "../components/Headshot.jsx";
import { PosList, PosTag } from "../components/Pos.jsx";
import PlayerSidebar from "../components/PlayerSidebar.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";
import { alarmSound } from "../components/sounds.js";

// The in-season tab: your Lock-In week (matchup, week plan with LOCK / PASS calls, every player's games Mon-Sun),
// today's lineup moves, the league (matchups + standings) and waiver claims. Any player name opens his season
// profile on the right. Data: backend services/season.py + engine/weekplan.py; refreshed every 2 minutes.
const REFRESH_MS = 60000;   // every minute: live scores feed the KEEP / SWAP calls
const VIEWS = [["week", "This week"], ["today", "Today"], ["league", "League"], ["waivers", "Waivers"]];

export const ctTime = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }) : "");
const dayName = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
const fp = (x) => (x == null ? "" : x.toFixed(1));

export default function SeasonPage({ leagueId }) {
  const [view, setView] = useState(() => localStorage.getItem("da.season.view") || "week");
  const [week, setWeek] = useState(null);
  const [plan, setPlan] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(null);
  const [tick, setTick] = useState(0);
  const [headerSlot, setHeaderSlot] = useState(null);
  useEffect(() => { setHeaderSlot(document.getElementById("header-slot")); }, []);

  const [pickedDay, setPickedDay] = useState(null);   // null = today on a game day, else the next game day
  const load = useCallback(() => {
    if (!leagueId) return;
    api.get(`/leagues/${leagueId}/season/week` + qs({ week })).then((w) => {
      const day = pickedDay && w.dates.includes(pickedDay) ? pickedDay
        : w.dates.find((d) => d >= w.today) || w.dates[0];
      return api.get(`/leagues/${leagueId}/season/plan` + qs({ week, today: day === w.today ? undefined : day }))
        .then((p) => { setData({ ...w, day }); setPlan(p); setError(""); });
    }).catch((e) => setError(e.message));
  }, [leagueId, week, pickedDay]);
  useEffect(() => { load(); const t = setInterval(load, REFRESH_MS); return () => clearInterval(t); }, [load, tick]);
  useEffect(() => { try { localStorage.setItem("da.season.view", view); } catch { /* ignore */ } }, [view]);

  // Alarms: each watch line has an alarm time (5 min before the later player's tip, 30 min before a GTD starter's).
  // When it comes, re-read the plan (live score) and ring with the current call. Works while this tab is open.
  const [alerts, setAlerts] = useState([]);
  const [armed, setArmed] = useState(() => { try { return localStorage.getItem("da.season.alarms") === "1"; } catch { return false; } });
  const arm = () => {
    alarmSound();   // the click also unlocks sound for later
    if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    setArmed(true); try { localStorage.setItem("da.season.alarms", "1"); } catch { /* ignore */ }
  };
  useEffect(() => {
    if (!armed || !plan?.today) return undefined;
    const timers = plan.today.watch.filter((w) => w.alarm).map((w) => {
      const ms = Date.parse(w.alarm) - Date.now();
      if (ms < 0 || ms > 24 * 3600e3) return null;
      return setTimeout(async () => {
        let line = w;
        try {
          const fresh = await api.get(`/leagues/${leagueId}/season/plan` + qs({ week }));
          setPlan(fresh);
          line = fresh.today?.watch.find((x) => x.kind === w.kind && (w.kind === "swap" ? x.backup_sid === w.backup_sid : x.sid === w.sid)) || w;
        } catch { /* ring with what we have */ }
        const title = line.kind === "gtd" ? `Check ${line.name} (GTD)` : line.decision === "SWAP" ? `SWAP: bench ${line.name}, start ${line.backup}` : `${line.decision}: ${line.backup} check`;
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
          <span className="muted small">{data.dates.length ? `${dayName(data.dates[0])} ${data.dates[0].slice(5)} – ${dayName(data.dates.at(-1))} ${data.dates.at(-1).slice(5)}` : ""}</span>
          <button className="small ghost" disabled={data.week <= 1} onClick={() => setWeek(data.week - 1)}>◂</button>
          <button className="small ghost" disabled={data.week >= Math.max(...data.weeks)} onClick={() => setWeek(data.week + 1)}>▸</button>
          {week && <button className="small ghost" onClick={() => setWeek(null)}>this week</button>}
          <nav className="season-tabs">
            {VIEWS.map(([id, label]) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)} data-testid={`season-${id}`}>{label}</button>)}
          </nav>
          <span className="season-search"><PlayerSearch leagueId={leagueId} onSelect={(p) => setSelected(p.player_id)} placeholder="Any player…" testId="season-search" /></span>
          <button className={`small ${armed ? "ghost" : "primary"}`} onClick={arm} data-testid="arm-alarms"
            data-tip="Rings at each swap check and GTD check while this tab is open, with a browser notification. Click once to allow sound and notifications.">
            {armed ? "🔔 Alarms on" : "🔕 Turn on alarms"}</button>
          <button className="small ghost" onClick={load} title="refresh now">↻</button>
          {error && <span className="small warn-text">{error}</span>}
        </div>
  );
  return (
    <div className="season-grid">
      <section className="season-main">
        {headerSlot ? createPortal(bar, headerSlot) : bar}
        {alerts.map((a) => (
          <div key={a.key} className={`panel roster-alert ${a.kind === "gtd" || a.decision === "SWAP" ? "bad" : "even"}`} data-testid="alarm-banner">
            <strong>⏰ {a.title}</strong> {a.text}
            <button className="tiny" style={{ marginLeft: 8 }} onClick={() => setAlerts((x) => x.filter((y) => y.key !== a.key))}>dismiss</button>
          </div>
        ))}
        <RosterAlerts roster={plan.roster} />
        {view === "week" && <WeekView data={data} plan={plan} open={open} setLock={setLock} leagueId={leagueId} setDay={setPickedDay} />}
        {view === "today" && <TodayView data={data} plan={plan} open={open} />}
        {view === "league" && <LeagueView data={data} leagueId={leagueId} open={open} />}
        {view === "waivers" && <WaiversView leagueId={leagueId} onSelect={setSelected} />}
      </section>
      <aside className="season-side">
        <PlayerSidebar leagueId={leagueId} playerId={selected} season plan={plan} onSelectPlayer={setSelected} refreshKey={tick} />
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
function GameChips({ games, today, lockDate }) {
  if (!games.length) return <span className="muted small">no games</span>;
  return (
    <span className="chips-row">
      {games.map((g) => {
        const played = g.fp != null, live = g.state === "in";
        return (
          <span key={g.date} className={`game-chip ${played ? "played" : ""} ${live ? "live" : ""} ${g.date === today ? "today" : ""} ${lockDate === g.date ? "locked" : ""}`}
            data-tip={`${dayName(g.date)} ${g.date.slice(5)} ${g.home ? "vs" : "@"} ${g.opp} · ${played ? `${g.fp} FP in ${g.min} min` : live ? `live: ${g.detail}` : `tips ${ctTime(g.tip)} CT · projected ${fp(g.proj)} FP`}${lockDate === g.date ? " · LOCKED" : ""}`}>
            <span className="gch-day">{dayName(g.date)} <span className="gch-time">{played ? "final" : live ? "LIVE" : ctTime(g.tip).replace(":00", "").replace(" PM", "p").replace(" AM", "a")}</span></span>
            <span className="gch-fp">{played ? fp(g.fp) : fp(g.proj)}</span>
          </span>
        );
      })}
    </span>
  );
}

const EXP_TIP = "Exp FP: the fantasy points this player is expected to put in your lineup this week. Only one of his games counts: " +
  "his locked game, else the better of locking his last game now and waiting for the rest (more games = more chances at a big one).";

// The call for the chosen day: LOCKED / LOCK / PASS when a game is locked or lockable, else the lineup move:
// "→ PG" (start him at PG), "→ BN" (sit him), IN (stays in), SIT (stays on the bench).
function dayCall(r, move, seated, data) {
  const g = (data.players[r.sid]?.games || []).find((x) => x.date === data.day);
  const when = move?.by ? ` before ${ctTime(move.by)} CT` : "";
  if (r.lock_status === "locked") return ["info", "LOCKED", `Locked ${r.lock_date}: this slot's score is set.`];
  if (r.action === "LOCK") return ["good", "LOCK", r.why];
  const pass = r.action === "PASS" ? `PASS on his last game (${r.why}). ` : "";
  if (move) {
    return move.to === "BN"
      ? ["bad", "→ BN", `${pass}Sit him ${dayName(data.day)}${g ? "" : " (no game)"}: his slot goes to someone who plays${when}.`]
      : ["good", `→ ${move.to}`, `${pass}Start him at ${move.to} ${dayName(data.day)}${when}${g ? `: ${g.home ? "vs" : "@"} ${g.opp} ${ctTime(g.tip)} CT` : ""}.`];
  }
  if (r.action === "PASS") return ["even", "PASS", r.why];
  if (seated) return ["", "IN", g ? `Plays ${dayName(data.day)} ${ctTime(g.tip)} CT: stays in.` : `No game ${dayName(data.day)}: nobody who plays needs his slot, so he stays in.`];
  return ["", "SIT", g ? `Plays ${dayName(data.day)} but the slots he fits go to players who play earlier or project more.` : `No game ${dayName(data.day)}.`];
}

function PlayerCard({ data, r, open, setLock, mine, side, move, seated }) {
  if (!r) return <div className={`mu-card empty ${side}`}><span className="muted small">empty</span></div>;
  const p = data.players[r.sid] || { games: [] };
  const [cls, word, tip] = mine ? dayCall(r, move, seated, data) : ["", "", ""];
  const lastPlayed = [...p.games].reverse().find((g) => g.fp != null);
  const starter = r.slot !== "BN" && r.slot !== "IR";
  return (
    <div className={`mu-card ${side} ${starter ? "" : "bench"}`} data-testid={`mu-${r.sid}`}>
      <div className="mu-top">
        <div className="mu-id clickable" onClick={() => open(r.sid)} data-testid={`open-${r.sid}`}>
        <Headshot sleeperId={r.sid} name={r.name} size={42} />
        <div className="mu-who">
          <div className="mu-name">{r.name}{r.injury !== "healthy" && <span className="inj" data-tip={p.injury_note}> {r.injury === "day_to_day" ? "GTD" : "OUT"}</span>}</div>
          <div className="small muted">{p.team || "FA"} · <PosList list={r.pos} />{r.seat && r.seat !== r.slot && <span data-tip={`The week plan seats him at ${r.seat}.`}> · plan: {r.seat}</span>}</div>
        </div>
        </div>
        <GameChips games={p.games} today={data.today} lockDate={r.lock_status === "locked" ? r.lock_date : null} />
        <div className="mu-exp" data-tip={EXP_TIP}><span className="bid-label">Exp</span><strong>{fp(r.value)}</strong></div>
        {mine && (
          <span className="mu-call">
            <span className={`verdict ${cls}`} data-tip={tip} data-testid={`call-${r.sid}`}>{word}</span>
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

const MODE = { ahead: ["good", "Ahead: the plan leans to sure points"], behind: ["bad", "Behind: the plan leans to big games"], even: ["", "Close: straight expected points"] };

// One matchup side by side. ◀ ▶ step through the league's matchups (yours first); calls and lock buttons show on
// yours only. Other matchups come from the plan endpoint for their first team (its opponent rides along).
function WeekView({ data, plan, open, setLock, leagueId, setDay }) {
  const moves = Object.fromEntries((plan.today?.moves || []).map((m) => [m.sid, m]));
  const seated = new Set(Object.values(plan.today?.seats || {}).flat());
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
  const L = bySlot(shown.players, data.roster_positions, data.reserve_slots);
  const R = o ? bySlot(o.players, data.roster_positions, data.reserve_slots) : { lines: [], bench: [], ir: [] };
  const mode = MODE[shown.mode] || MODE.even;
  // first: the first bench / IR row gets a gap above it (instead of a divider row, so every row can share the height)
  const row = (l, r, key, slot, first) => (
    <React.Fragment key={key}>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={l?.r} open={open} setLock={setLock} mine={isMine} side="left" move={isMine ? moves[l?.r?.sid] : null} seated={isMine && seated.has(l?.r?.sid)} /></div>
      <div className={`mu-slot ${first ? "first" : ""}`}><PosTag text={slot} /></div>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={r?.r} open={open} side="right" /></div>
    </React.Fragment>
  );
  return (
    <div className="panel matchup" data-testid="my-week">
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
          {!isMine && <button className="tiny" onClick={() => setIdx(mineIdx)}>mine</button>}
          {isMine && (
            <span className="day-pick" data-tip="Whose lineup the call column shows: that day's moves (start whoever plays, earliest tip first).">
              {data.dates.map((d) => (
                <button key={d} className={`tiny ${d === data.day ? "active" : ""} ${d === data.today ? "is-today" : ""}`} onClick={() => setDay(d)} data-testid={`day-${d}`}>
                  {dayName(d)}
                </button>
              ))}
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
      <div className="mu-grid">
        {L.lines.map((l, i) => row(l, R.lines[i], `s${i}`, l.slot))}
        {Array.from({ length: Math.max(L.bench.length, R.bench.length) }, (_, i) => row(L.bench[i], R.bench[i], `b${i}`, "BN", i === 0))}
        {Array.from({ length: Math.max(L.ir.length, R.ir.length) }, (_, i) => row(L.ir[i], R.ir[i], `i${i}`, "IR", i === 0))}
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

function TodayView({ data, plan, open }) {
  const t = plan.today;
  if (!t) return <div className="panel muted">No games for this week today ({data.today}). Today's lineup shows on game days.</div>;
  const name = (sid) => data.players[sid]?.name || sid;
  return (
    <>
      <div className="panel" data-testid="today-moves">
        <h3 style={{ marginTop: 0 }}>Today's moves in Sleeper <span className="small muted">{dayName(t.date)} {t.date.slice(5)}</span></h3>
        {t.moves.length > 0 && (() => {
          const first = t.moves.map((m) => m.by).filter(Boolean).sort()[0];
          return first && <div className="warn-text" style={{ marginBottom: 6 }}>Make these before <strong>{ctTime(first)} CT</strong> (the first tip-off they depend on); rows with a later time can wait until then.</div>;
        })()}
        {t.moves.length ? (
          <table className="small">
            <thead><tr><th>Player</th><th>From</th><th></th><th>To</th><th>Before</th></tr></thead>
            <tbody>{t.moves.map((m) => (
              <tr key={m.sid}><td className="clickable" onClick={() => open(m.sid)}><strong>{m.name}</strong></td><td><PosTag text={m.from} /></td><td>→</td><td><PosTag text={m.to} /></td>
                <td>{m.by ? `${ctTime(m.by)} CT` : <span className="muted">no game today: with the others</span>}</td></tr>))}</tbody>
          </table>
        ) : <div className="ok">Your lineup is already set for today.</div>}
      </div>
      {t.watch.length > 0 && (
        <div className="panel" data-testid="today-watch">
          <h3 style={{ marginTop: 0 }}>Watch tonight</h3>
          {[...t.watch].sort((a, b) => (a.by || "~").localeCompare(b.by || "~")).map((w, i) => (
            <div key={i} className={`watch-line ${w.kind}`}>
              <span className={`verdict ${w.kind === "gtd" ? "bad" : w.decision === "SWAP" ? "bad" : w.decision === "KEEP" ? "good" : "even"}`}>
                {w.kind === "gtd" ? "GTD" : w.decision}</span>{" "}
              {w.text} {w.by && <span className="muted">({w.kind === "gtd" ? "his tip" : `${w.backup} tips`} {ctTime(w.by)} CT{w.alarm ? ` · alarm ${ctTime(w.alarm)}` : ""})</span>}
            </div>
          ))}
        </div>
      )}
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Today's lineup</h3>
        <div className="today-seats">
          {Object.entries(t.seats).flatMap(([slot, sids]) => sids.map((sid) => (
            <div key={sid} className="today-seat clickable" onClick={() => open(sid)}>
              <PosTag text={slot} /> <Headshot sleeperId={sid} name={name(sid)} size={26} /> {name(sid)}
              {(() => { const g = data.players[sid]?.games.find((x) => x.date === t.date); return g ? <span className="small muted"> · {g.fp != null ? `${fp(g.fp)} FP` : `${ctTime(g.tip)} CT, proj ${fp(g.proj)}`}</span> : <span className="small muted"> · no game today</span>; })()}
            </div>
          )))}
        </div>
      </div>
    </>
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
              <td className="num">{fp(t.fpts)}</td><td className="num">${200 - (t.faab_used || 0)}</td></tr>))}</tbody>
        </table>
      </div>
    </>
  );
}

function WaiversView({ leagueId, onSelect }) {
  const [w, setW] = useState(null);
  useEffect(() => { api.get(`/leagues/${leagueId}/season/waivers`).then(setW).catch(() => setW(null)); }, [leagueId]);
  if (!w) return <div className="panel">Loading free agents…</div>;
  return (
    <div className="panel" data-testid="waivers">
      <h3 style={{ marginTop: 0 }}>Waiver claims <span className="small muted">blind bids · process {w.process} · ${w.faab_left} FAAB left of $200</span></h3>
      {w.drop && <div className="small" style={{ marginBottom: 8 }}>Drop candidate: <strong className="clickable" onClick={() => onSelect(w.drop.player_id)}>{w.drop.name}</strong> <span className="muted">(value {w.drop.value}, your weakest)</span></div>}
      {w.claims.length ? (
        <table className="small">
          <thead><tr><th>Player</th><th>Team</th><th>Pos</th><th className="num" data-tip="Rest-of-season value: projection, Lock-In best game and availability.">Value</th>
            <th className="num" data-tip="Value over your drop candidate.">Upgrade</th><th className="num">Games this wk</th><th className="num" data-tip="A guide: share of your FAAB that grows with the upgrade. Other bids are hidden.">Bid</th></tr></thead>
          <tbody>{w.claims.map((c) => (
            <tr key={c.player_id}><td className="clickable" onClick={() => onSelect(c.player_id)}><strong>{c.name}</strong>{c.injury !== "healthy" && <span className="inj"> {c.injury.replace(/_/g, " ")}</span>}</td>
              <td>{c.team}</td><td><PosList list={c.pos} /></td><td className="num">{c.value}</td><td className="num ok">+{c.upgrade}</td>
              <td className="num">{c.games_this_week}</td><td className="num"><strong>${c.bid}</strong></td></tr>))}</tbody>
        </table>
      ) : <div className="muted">No free agent is an upgrade over your weakest player.</div>}
    </div>
  );
}
