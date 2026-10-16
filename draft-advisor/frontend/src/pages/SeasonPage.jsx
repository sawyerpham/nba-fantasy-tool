import React, { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";
import Headshot from "../components/Headshot.jsx";
import { PosList, PosTag } from "../components/Pos.jsx";
import PlayerSidebar from "../components/PlayerSidebar.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";

// The in-season tab: your Lock-In week (matchup, week plan with LOCK / PASS calls, every player's games Mon-Sun),
// today's lineup moves, the league (matchups + standings) and waiver claims. Any player name opens his season
// profile on the right. Data: backend services/season.py + engine/weekplan.py; refreshed every 2 minutes.
const REFRESH_MS = 120000;
const VIEWS = [["week", "This week"], ["today", "Today"], ["league", "League"], ["waivers", "Waivers"]];
const ACTION = {
  LOCK: ["good", "Lock this game now (before his next tip-off)."],
  PASS: ["even", "Don't lock: his remaining games are worth more."],
  WAIT: ["", "No lockable game yet: his games are still to come."],
  LOCKED: ["info", "Locked: this slot's score is set."],
  BENCH: ["", "Not worth a starting slot this week."],
  DONE: ["", "No games left this week."],
};

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

  const load = useCallback(() => {
    if (!leagueId) return;
    Promise.all([api.get(`/leagues/${leagueId}/season/week` + qs({ week })), api.get(`/leagues/${leagueId}/season/plan` + qs({ week }))])
      .then(([w, p]) => { setData(w); setPlan(p); setError(""); })
      .catch((e) => setError(e.message));
  }, [leagueId, week]);
  useEffect(() => { load(); const t = setInterval(load, REFRESH_MS); return () => clearInterval(t); }, [load, tick]);
  useEffect(() => { try { localStorage.setItem("da.season.view", view); } catch { /* ignore */ } }, [view]);

  if (!leagueId) return <div className="panel muted">Pick a league on the League tab first.</div>;
  if (error && !data) return <div className="panel error">{error}</div>;
  if (!data || !plan) return <div className="panel">Loading the week from Sleeper…</div>;

  const pidOf = (sid) => data.players[sid]?.player_id;
  const open = (sid) => { const pid = pidOf(sid); if (pid) setSelected(pid); };
  const setLock = (sid, gameDate) => api.post(`/leagues/${leagueId}/season/locks`, { week: data.week, sleeper_id: sid, game_date: gameDate })
    .then(() => setTick((t) => t + 1)).catch((e) => setError(e.message));

  return (
    <div className="season-grid">
      <section className="season-main">
        <div className="panel row season-bar">
          <h2 style={{ margin: 0 }}>Week {data.week}</h2>
          <span className="muted small">{data.dates.length ? `${dayName(data.dates[0])} ${data.dates[0].slice(5)} – ${dayName(data.dates.at(-1))} ${data.dates.at(-1).slice(5)}` : ""}</span>
          <button className="small ghost" disabled={data.week <= 1} onClick={() => setWeek(data.week - 1)}>◂</button>
          <button className="small ghost" disabled={data.week >= Math.max(...data.weeks)} onClick={() => setWeek(data.week + 1)}>▸</button>
          {week && <button className="small ghost" onClick={() => setWeek(null)}>this week</button>}
          <nav className="season-tabs">
            {VIEWS.map(([id, label]) => <button key={id} className={view === id ? "active" : ""} onClick={() => setView(id)} data-testid={`season-${id}`}>{label}</button>)}
          </nav>
          <span className="season-search"><PlayerSearch leagueId={leagueId} onSelect={(p) => setSelected(p.player_id)} placeholder="Any player…" testId="season-search" /></span>
          <button className="small ghost" onClick={load} title="refresh now">↻</button>
          {error && <span className="small warn-text">{error}</span>}
        </div>
        <RosterAlerts roster={plan.roster} />
        {view === "week" && <WeekView data={data} plan={plan} open={open} setLock={setLock} />}
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

function Scoreboard({ plan }) {
  const o = plan.opponent;
  const mode = { ahead: ["good", "Ahead: the plan leans to sure points"], behind: ["bad", "Behind: the plan leans to big games"], even: ["", "Close: straight expected points"] }[plan.mode];
  return (
    <div className="panel matchup-card" data-testid="matchup">
      <div className="mc-side me">
        <div className="mc-name">{plan.name} <span className="badge info">YOU</span></div>
        <div className="mc-points">{fp(plan.points)}</div>
        <div className="small muted">expected <strong style={{ color: "var(--text)" }}>{plan.expected}</strong> · {plan.games_left} games left</div>
      </div>
      <div className="mc-vs"><span className={`verdict ${mode[0]}`} data-tip={mode[1]}>{plan.mode}</span></div>
      {o ? (
        <div className="mc-side">
          <div className="mc-name">{o.name}</div>
          <div className="mc-points">{fp(o.points)}</div>
          <div className="small muted">expected <strong style={{ color: "var(--text)" }}>{o.expected}</strong> · {o.games_left} games left · {o.locked} locked</div>
        </div>
      ) : <div className="mc-side muted">no opponent this week</div>}
    </div>
  );
}

function GameCell({ g, today, locked }) {
  if (!g) return <td className="gc none">·</td>;
  const played = g.fp != null;
  return (
    <td className={`gc ${played ? "played" : ""} ${g.date === today ? "today" : ""} ${locked ? "locked" : ""} ${g.state === "in" ? "live" : ""}`}
      data-tip={`${g.home ? "vs" : "@"} ${g.opp} · ${played ? `${g.fp} FP in ${g.min} min` : g.state === "in" ? `live: ${g.detail}` : `tips ${ctTime(g.tip)} CT · projected ${fp(g.proj)} FP`}${locked ? " · LOCKED" : ""}`}>
      <div className="gc-num">{played ? fp(g.fp) : g.state === "in" ? "live" : fp(g.proj)}</div>
      <div className="gc-opp">{g.home ? "" : "@"}{g.opp}</div>
    </td>
  );
}

function PlanTable({ data, rows, open, setLock, mine }) {
  const ordered = [...rows.filter((r) => r.slot !== "BN" && r.slot !== "IR"), ...rows.filter((r) => r.slot === "BN"), ...rows.filter((r) => r.slot === "IR")];
  const order = ["PG", "SG", "SF", "PF", "C", "BN", "IR"];
  ordered.sort((a, b) => order.indexOf(a.slot) - order.indexOf(b.slot));
  return (
    <table className="plan-week" data-testid={mine ? "my-week" : "opp-week"}>
      <thead>
        <tr><th>Slot</th><th>Player</th>{data.dates.map((d) => <th key={d} className={`gc ${d === data.today ? "today" : ""}`}>{dayName(d)}<div className="muted small">{d.slice(5)}</div></th>)}
          <th className="num" data-tip="What this player is worth to you this week: his locked score, else the better of locking now and waiting.">Value</th>
          {mine && <th>Call</th>}{mine && <th data-tip="Sleeper doesn't say which game you locked; the site guesses from the counted points. Tell it if it's wrong.">Locked?</th>}</tr>
      </thead>
      <tbody>
        {ordered.map((r) => {
          const p = data.players[r.sid] || { games: [] };
          const byDate = Object.fromEntries(p.games.map((g) => [g.date, g]));
          const [cls, tip] = ACTION[r.action] || ["", ""];
          const lastPlayed = [...p.games].reverse().find((g) => g.fp != null);
          return (
            <tr key={r.sid} className={`${r.slot === "BN" || r.slot === "IR" ? "bench-row" : ""} ${r.seat && r.seat !== r.slot ? "reseat" : ""}`}>
              <td><PosTag text={r.slot} />{r.seat && r.seat !== r.slot && <span className="small muted" data-tip={`The week plan seats him at ${r.seat}.`}> → {r.seat}</span>}</td>
              <td className="clickable plan-name" onClick={() => open(r.sid)}>
                <Headshot sleeperId={r.sid} name={r.name} size={28} />
                <span><strong>{r.name}</strong> <span className="small muted">{p.team || "FA"} · <PosList list={r.pos} /></span>
                  {r.injury !== "healthy" && <span className="inj small" data-tip={p.injury_note}> {r.injury.replace(/_/g, " ")}</span>}</span>
              </td>
              {data.dates.map((d) => <GameCell key={d} g={byDate[d]} today={data.today} locked={r.lock_status === "locked" && r.lock_date === d} />)}
              <td className="num"><strong>{fp(r.value)}</strong></td>
              {mine && <td><span className={`verdict ${cls}`} data-tip={`${tip} ${r.why}`}>{r.action}</span></td>}
              {mine && (
                <td className="small">
                  {r.slot === "BN" || r.slot === "IR" ? "" : r.lock_status === "locked" ? <span className="ok" data-tip="Click to say it isn't locked." onClick={() => setLock(r.sid, "")} style={{ cursor: "pointer" }}>✓ {r.lock_date?.slice(5)}</span>
                    : lastPlayed ? (
                      <span className="lock-btns">
                        {r.lock_status === "maybe" && <span className="muted" data-tip="Sleeper counts his latest game: locked, or just counting it for now?">? </span>}
                        <button className="tiny" onClick={() => setLock(r.sid, lastPlayed.date)} data-tip={`I locked his ${lastPlayed.date.slice(5)} game (${fp(lastPlayed.fp)}).`}>I locked</button>
                      </span>) : <span className="muted">—</span>}
                </td>
              )}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function WeekView({ data, plan, open, setLock }) {
  return (
    <>
      <Scoreboard plan={plan} />
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Your week plan <span className="small muted">expected {plan.expected} FP · numbers are FP (actual once played, else Sleeper's projection in your scoring)</span></h3>
        <PlanTable data={data} rows={plan.players} open={open} setLock={setLock} mine />
      </div>
      {plan.opponent && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>{plan.opponent.name} <span className="small muted">expected {plan.opponent.expected} FP</span></h3>
          <PlanTable data={data} rows={plan.opponent.players} open={open} />
        </div>
      )}
    </>
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
              <span className={`verdict ${w.kind === "gtd" ? "bad" : "even"}`}>{w.kind === "gtd" ? "GTD" : "SWAP?"}</span>{" "}
              {w.text} {w.by && <span className="muted">({w.kind === "gtd" ? "his tip" : `${w.backup} tips`} {ctTime(w.by)} CT)</span>}
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
          <PlanTable data={data} rows={shown.players} open={open} />
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
