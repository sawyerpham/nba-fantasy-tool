import React, { useCallback, useEffect, useState } from "react";
import { useNBAMatches, findMatch, watchUrl } from "./streams.jsx";
import { createPortal } from "react-dom";
import { api, qs } from "../api.js";
import Headshot from "../core/Headshot.jsx";
import { PosList, PosTag } from "../core/Pos.jsx";
import PlayerSidebar from "../core/PlayerSidebar.jsx";
import PlayerSearch from "../core/PlayerSearch.jsx";
import InjuryTag from "../core/InjuryTag.jsx";
import { fmt, setZone, timeOf } from "./tz.js";
import { alarmSound } from "../core/sounds.js";
import { reseat, swapSteps } from "./swaps.js";

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
        {selected
          ? <PlayerSidebar leagueId={leagueId} playerId={selected} season plan={plan} onSelectPlayer={setSelected} refreshKey={tick} onClose={() => setSelected(null)} />
          : <LockinGuide data={data} plan={plan} leagueId={leagueId} setLock={setLock} />}
      </aside>
    </div>
  );
}

// The right side when no player is open: the week's Lock-In numbers for any team (yours by default; the drop-down
// loads another's plan from the plan endpoint). Stats, not instructions:
//   Matchup        - win probability; projected final, banked points and games left for both teams;
//   By approach    - win probability locking every lockable game now vs leaving every slot open vs the plan's mix
//                    (backend outlook); the opponent's remaining projections and banked games;
//   Lockable games - each game that could be locked now: its score, the open slot's value (his later games or a spare
//                    bench player's, the best each day: backend open_slot), win % locked vs open, the next tip;
//   Swap windows, Injury watch - tonight's live-vs-later comparisons and questionable / out starters.
const pct = (x) => `${Math.round((x ?? 0) * 100)}%`;
const lastName = (n) => n.split(" ").slice(1).join(" ") || n;
function LockinGuide({ data, plan, leagueId, setLock }) {
  const [rid, setRid] = useState(plan.roster_id);
  const [other, setOther] = useState(null);
  const mine = rid === plan.roster_id;
  useEffect(() => {
    if (mine) return;
    setOther(null);
    api.get(`/leagues/${leagueId}/season/plan` + qs({ week: data.week, roster_id: rid })).then(setOther).catch(() => setOther(null));
  }, [rid, mine, leagueId, data.week, data.now]);
  const p = mine ? plan : other;
  const picker = (
    <select className="guide-team" value={rid} onChange={(e) => setRid(Number(e.target.value))} data-testid="guide-team">
      {[...data.teams].sort((a, b) => b.is_user - a.is_user || (a.user || a.name).localeCompare(b.user || b.name)).map((t) => (
        <option key={t.roster_id} value={t.roster_id}>{t.user || t.name}{t.is_user ? " (you)" : ""}</option>))}
    </select>
  );
  const head = <div className="guide-head"><h3>Week stats</h3>{picker}</div>;
  if (!p) return <div className="panel scroll guide" data-testid="lockin-guide">{head}<div className="muted small">Loading…</div></div>;

  const when = (t) => fmt(t, { weekday: "short", hour: "numeric", minute: "2-digit" });
  const nextTip = (sid) => (data.players[sid]?.games || []).find((g) => g.state === "pre" && g.fp == null)?.tip;
  const watch = p.today?.watch || [];
  const o = p.opponent, out = p.outlook;
  const edge = (r) => (r.win_lock ?? 0) - (r.win_wait ?? 0);   // win probability locked minus open
  const lockable = p.players.filter((r) => r.seat && r.x != null && r.lock_status !== "locked" && r.lock_status !== "guess")
    .sort((a, b) => edge(b) - edge(a));
  const swaps = watch.filter((w) => w.kind === "swap"), injuries = watch.filter((w) => w.kind === "gtd" || w.kind === "out");
  const remaining = (o?.players || []).filter((r) => r.seat && r.locked == null && r.w > 0).sort((a, b) => b.w - a.w).slice(0, 4);
  const banked = (o?.players || []).filter((r) => r.locked != null).sort((a, b) => b.locked - a.locked);
  const odds = out ? [["Lock all now", out.safe], ["Leave all open", out.risky], ["Plan mix", p.win_chance]] : [];
  const top = Math.max(...odds.map(([, v]) => v ?? 0));
  const signed = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}`;
  // a guessed lock (?) can be answered here: ✓ locked / ✕ not locked (saved like your own lock answers)
  const chip = (r, value, guess) => (
    <span key={r.sid} className="guide-chip"><Headshot sleeperId={r.sid} name={r.name} size={22} />{lastName(r.name)} <strong>{value}{guess ? "?" : ""}</strong>
      {guess && setLock && <>
        <button className="chip-btn" onClick={() => setLock(r.sid, r.lock_date)} data-tip="He locked it">✓</button>
        <button className="chip-btn" onClick={() => setLock(r.sid, "")} data-tip="Not locked">✕</button>
      </>}</span>
  );
  const side = (t, label) => (
    <div className="hub-side">
      <div className="hub-team">{label}</div>
      <div className="hub-stat"><span>Projected</span><strong>{fp(t.expected)}</strong></div>
      <div className="hub-stat"><span>Banked</span><strong>{fp(t.points)}</strong></div>
      <div className="hub-stat"><span>Games left</span><strong>{t.games_left}</strong></div>
    </div>
  );
  return (
    <div className="panel scroll guide" data-testid="lockin-guide">
      {head}
      {o && (
        <section className="guide-card">
          <div className="hub-win"><span className="bid-label">Win probability</span><strong>{pct(p.win_chance)}</strong></div>
          <div className="hub-sides">{side(p, p.user || p.name)}{side(o, o.user || o.name)}</div>
        </section>
      )}
      {out && (
        <section className="guide-card">
          <div className="bid-label">Win probability by approach</div>
          <div className="guide-odds">{odds.map(([label, v]) => (
            <div key={label} className={`guide-odd ${v === top ? "best" : ""}`}>
              <span className="small">{label}</span>
              <span className="guide-bar"><span style={{ width: pct(v) }} /></span>
              <strong className="small">{pct(v)}</strong>
            </div>
          ))}</div>
          {remaining.length > 0 && <div className="guide-chips"><span className="bid-label">{o.user || o.name}: remaining projection</span>{remaining.map((r) => chip(r, `~${fp(r.w)}`))}</div>}
          {banked.length > 0 && <div className="guide-chips"><span className="bid-label">{o.user || o.name}: banked</span>{banked.map((r) => chip(r, fp(r.locked), r.lock_status === "guess"))}</div>}
        </section>
      )}
      {lockable.length > 0 && <>
        <h4>Lockable games</h4>
        {lockable.map((r) => {
          const e = edge(r), tip = nextTip(r.sid);
          // the open slot: the best game it can still take each day, his or a spare bench player's (backend open_slot)
          const from = (r.slot_from || []).map(([d, who]) => `${dayName(d)}${who === r.name ? "" : ` ${lastName(who)}`}`);
          return (
            <div key={r.sid} className={`guide-lock ${e >= 0 ? "lock" : "pass"}`}>
              <Headshot sleeperId={r.sid} name={r.name} size={38} />
              <div className="guide-lock-main">
                <div className="guide-lock-top"><strong>{r.name}</strong> <span className="muted small">{r.seat}</span></div>
                <div className="small muted">Open slot ~{fp(r.slot_w ?? r.w)}{from.length ? ` · ${from.join(", ")}` : " · no games left"}</div>
                {r.win_lock != null && <div className="small muted">Win % locked <span className="guide-hi">{pct(r.win_lock)}</span> · open <span className="guide-hi">{pct(r.win_wait)}</span></div>}
                {r.lock_at?.length > 0 && (() => {
                  // which slot to lock him in: the rest of the lineup's value with him locked in each slot he can play
                  const [best, ...rest] = r.lock_at;
                  const diff = rest.filter((o) => best.team - o.team >= 0.05);
                  const detail = r.lock_at.map((o) => `${o.slot}: ${o.open} slot${o.open === 1 ? "" : "s"} left, ${o.others} others can play it`).join(" · ");
                  return <div className="small muted" data-tip={detail}>Lock slot <span className="guide-hi">{best.slot}</span>
                    {r.slot !== best.slot ? ` (now ${r.slot})` : ""}
                    {diff.length ? ` · ${diff.map((o) => `${o.slot} −${fp(best.team - o.team)}`).join(", ")}` : rest.length ? ` · ${rest.map((o) => o.slot).join(", ")} the same` : " · only option"}</div>;
                })()}
                {tip && <div className="small muted">Next tip {when(tip)}</div>}
              </div>
              <div className="guide-lock-side"><span className="guide-lock-x">{fp(r.x)}</span>
                {r.win_lock != null && <span className={`hub-edge ${e >= 0 ? "up" : "down"}`} data-tip="Win probability locked minus open, in points">{signed(e)}</span>}</div>
            </div>
          );
        })}
      </>}
      {swaps.length > 0 && <>
        <h4>Swap windows</h4>
        {swaps.map((w) => (
          <div key={w.backup_sid} className="guide-row">
            <Headshot sleeperId={w.backup_sid} name={w.backup} size={30} />
            <div className="small">
              <div><strong>{w.backup}</strong> <span className="muted">for</span> <strong>{w.name}</strong> <span className="muted">· window {when(w.alarm)}</span></div>
              <div className="muted">{w.est != null ? `${lastName(w.name)} projected finish ~${fp(w.est)} · ${lastName(w.backup)} ~${fp(w.swap)}` : `${lastName(w.name)} not started · ${lastName(w.backup)} ~${fp(w.swap)}`}</div>
              {w.win_keep != null && <div className="muted">Win % keep <span className="guide-hi">{pct(w.win_keep)}</span> · swap <span className="guide-hi">{pct(w.win_swap)}</span></div>}
            </div>
          </div>
        ))}
      </>}
      {injuries.length > 0 && <>
        <h4>Injury watch</h4>
        {injuries.map((w) => (
          <div key={`${w.kind}-${w.sid}`} className="guide-row"><Headshot sleeperId={w.sid} name={w.name} size={30} />
            <div className="small"><strong>{w.name}</strong> <span className="muted">· {w.kind === "out" ? "out" : "questionable"}{w.slot ? ` · ${w.slot}` : ""}{w.by ? ` · tips ${when(w.by)}` : ""}</span>
              {w.backup && <div className="muted">Bench option: {w.backup}</div>}</div></div>
        ))}
      </>}
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

// One card per game he has this week (so 3-4 at most): day, tip time, then his FP (— before the game) with the
// projection small beside it; live, the projection turns green / red as his pace (backend live_estimate) beats it or not.
// A game that can't be locked (or count any more) is crossed out: every game but the locked one once he's locked;
// a final game once a later one has tipped, or that the backend can't lock (lockable = r.x: benched for it); a live
// game while he sits on the bench (it won't count, and it's too late to start him).
// Games off the lineup day dim, except the locked game and a final game he can still lock.
// lane (matchup cards): { xs: tip ms -> x px, scale }, so the chips line up as a timeline (see laneXs).
function GameChips({ games, today, lockDate, lockGuess, lockable, benched, day, lane, team }) {
  const { list: matches } = useNBAMatches();
  if (!games.length) return lane ? <span className="chips-lane"><span className="muted small">no games</span></span> : <span className="muted small">no games</span>;
  const chips = games.map((g, i) => {
        // live: ESPN says in progress, or his stats are coming in before ESPN's state catches up; final only once ESPN says so
        const played = g.fp != null, live = g.state === "in" || (played && g.state !== "post");
        const later = games.slice(i + 1).some((x) => x.state !== "pre" || x.fp != null);
        const dead = lockDate ? g.date !== lockDate : (g.state === "post" && (later || !lockable)) || (live && benched);
        const upcoming = g.state === "pre" && !played && !dead;   // only a game still to come gets the purple border
        const m = findMatch(matches, g, team);
        const href = m ? watchUrl(m) : null;
        const Tag = href ? "a" : "span";
        // the hover adds only what the card doesn't show (day, time, FP and expected FP are on it)
        const tip = [
          // "MIA 81 vs MIN 104" (his team first; no scores before the tip)
          [team, g.score, g.home ? "vs" : "@", g.opp, g.opp_score].filter((x) => x != null && x !== "").join(" "),
          !live && played && g.min != null && `${g.min} min`,
          g.b2b && g.state === "pre" && "2nd night of a back-to-back",
          g.beat != null && `${Math.round(g.beat * 100)}% to score higher this week`,   // locked too: was it the right call
          lockDate === g.date ? (lockGuess ? "locked (a guess: his next game confirms it)" : "locked") : dead && "can't be locked",
        ].filter(Boolean).join(" · ") + (g.box ? `\n${boxLine(g.box)}` : "");
        return (
          <Tag key={g.date} {...(href ? { href, target: "_blank", rel: "noopener noreferrer" } : {})}
            onClick={href ? (e) => e.stopPropagation() : undefined}
            style={lane?.xs ? { left: lane.xs.get(tipMs(g)) ?? 0, ...(lane.scale < 1 && { transform: `translateY(-50%) scale(${lane.scale})` }) } : undefined}
            className={`game-chip ${played ? "played" : ""} ${live ? "live" : ""} ${g.date === today && upcoming ? "today" : ""} ${lockDate === g.date ? `locked ${lockGuess ? "guess" : ""}` : ""} ${day ? (g.date === day && upcoming ? "pick" : lockDate === g.date || live || (g.state === "post" && !dead) ? "" : "dim") : ""} ${href ? "watch" : ""} ${dead ? "dead" : ""}`}
            data-tip={tip}>
            <span className="gch-day">{live ? shortQuarter(g.detail) : dayName(g.date)} <span className="gch-time">{live ? "LIVE" : lockDate === g.date ? <LockIcon /> : played ? "final" : timeOf(g.tip).replace(":00", "").replace(" PM", "p").replace(" AM", "a")}</span></span>
            <span className="gch-fp">{played ? fp(g.fp) : "—"}<span className={`gch-exp ${live && g.pace != null && g.proj != null ? (g.pace >= g.proj ? "up" : "down") : ""}`}>{fp(g.proj)}</span></span>
          </Tag>
        );
      });
  if (!lane) return <span className="chips-row">{chips}</span>;
  return <span className="chips-lane">{lane.xs ? chips : <span className="chips-row">{chips}</span>}</span>;
}

// ESPN's live status in quarters: "3:14 - 1st" -> "Q1 3:14", "1:05 - OT" -> "OT 1:05", "End of 3rd" -> "End of Q3"
const quarters = (detail) => (detail || "").replace(/^(.+) - (\d)(?:st|nd|rd|th)$/, "Q$2 $1").replace(/^(.+) - (\d?OT)$/, "$2 $1")
  .replace(/\b(\d)(?:st|nd|rd|th)\b/g, "Q$1");
// ...short enough for a live card's top line, in place of the weekday: "Q1 3:14", "End Q3", "Half"
const shortQuarter = (detail) => quarters(detail).replace("End of ", "End ").replace("Start of ", "Start ").replace("Halftime", "Half") || "—";

// His box score on one line: "38 PTS, 5 REB, 3 AST, 0 BLK, 12/21 FG, 7/8 FT, 3 TO, 5 PF"
const boxLine = (b) => `${b.pts} PTS, ${b.reb} REB, ${b.ast} AST, ${b.blk} BLK, ${b.fgm}/${b.fga} FG, ${b.ftm}/${b.fta} FT, ${b.to} TO, ${b.pf} PF`;

// a small padlock: a locked game shows it where "final" would be
const LockIcon = () => (
  <svg className="gch-lock" viewBox="0 0 10 12" aria-label="locked">
    <path d="M3 5.2V3.6a2 2 0 0 1 4 0v1.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
    <rect x="1" y="5" width="8" height="6.5" rx="1.6" fill="currentColor" />
  </svg>
);

const tipMs = (g) => Date.parse(g.tip) || Date.parse(`${g.date}T12:00:00`);

// A matchup's chips as a timeline: one x per distinct tip on both rosters, the earliest at the lane's left edge.
// Each game day starts clear of the previous day's chips (so the time line never sits on an earlier day's chips);
// within a day the tips spread by the hour (4-12 px an hour, as much as fits); room left over spaces the days in
// proportion to time. Too narrow even at 4 px an hour: the chips shrink (scale) down to 65%; narrower than that, xs is
// null and the chips sit in a plain row (no time line).
const CHIP_W = 86, CHIP_GAP = 6, HOUR_MIN = 4, HOUR_MAX = 12;
function laneXs(games, width) {   // games: [tip ms, game date] for every chip in the matchup
  const day = new Map(games);
  const tips = [...day.keys()].sort((a, b) => a - b);
  if (!tips.length || !width) return { xs: new Map(), scale: 1 };
  const t0 = tips[0], span = Math.max(1, tips.at(-1) - t0);
  const place = (s, h, cw) => {   // s: share of the lane spaced by time; h: px an hour within a day; cw: chip width
    const x = new Map();
    let prev = 0, start = 0, first = t0, last = t0;
    for (const t of tips) {
      const lin = (s * (t - t0) / span) * (width - cw);
      let v;
      if (day.get(t) !== day.get(last)) { v = Math.max(prev + cw + CHIP_GAP, lin); start = v; first = t; }
      else v = Math.max(prev, start + ((t - first) / 3600e3) * h, lin);
      x.set(t, v); prev = v; last = t;
    }
    return x;
  };
  const ok = (s, h, cw) => place(s, h, cw).get(tips.at(-1)) + cw <= width;
  const most = (lo, hi, f) => {   // the largest value in [lo, hi] that f accepts (f grows with it), or null
    if (f(hi)) return hi;
    if (!f(lo)) return null;
    for (let i = 0; i < 20; i++) { const m = (lo + hi) / 2; if (f(m)) lo = m; else hi = m; }
    return lo;
  };
  const h = most(HOUR_MIN, HOUR_MAX, (v) => ok(0, v, CHIP_W));
  if (h == null) {
    const cw = most(0.65 * CHIP_W, CHIP_W, (v) => ok(0, HOUR_MIN, v));
    return cw == null ? { xs: null } : { xs: place(0, HOUR_MIN, cw), scale: cw / CHIP_W };
  }
  const s = most(0, 1, (v) => ok(v, h, CHIP_W));
  return { xs: place(s, h, CHIP_W), scale: 1 };
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

const EXP_TIP = "Expected final score: locked points plus what each slot is expected to add (each player's locked game, " +
  "else the better of locking his last game and waiting for his later ones).";

function PlayerCard({ data, r, open, setLock, mine, side, day, lane }) {
  if (!r) return <div className={`mu-card empty ${side}`}><span className="muted small">empty</span></div>;
  const p = data.players[r.sid] || { games: [] };
  const starter = r.slot !== "BN" && r.slot !== "IR";
  const locked = r.lock_status === "locked" || r.lock_status === "guess";   // guess: Sleeper can't tell yet, the math says locked
  return (
    <div className={`mu-card ${side} ${starter ? "" : "bench"} ${locked ? "done" : ""}`} data-testid={`mu-${r.sid}`}>
      <div className="mu-top">
        <div className="mu-id clickable" onClick={() => open(r.sid)} data-testid={`open-${r.sid}`}>
        <Headshot sleeperId={r.sid} name={r.name} size={42} />
        <div className="mu-who">
          <div className="mu-name">{r.name}<InjuryTag tag={p.injury_tag} note={p.injury_note} /></div>
          <div className="small muted mu-sub">{p.team || (p.retired ? "Retired" : "FA")} <PosList list={r.pos} />
            {p.nick && showNicks() && <span className="nick" data-tip="Nickname set on Sleeper"> · “{p.nick}”</span>}</div>
        </div>
        </div>
        <GameChips games={p.games} team={p.team} today={data.today} day={mine ? day || data.day : day} lockDate={locked ? r.lock_date : null} lockGuess={r.lock_status === "guess"} lockable={r.x != null} benched={r.slot === "BN" || r.slot === "IR"} lane={lane} />
        {mine && starter && locked && (
          <span className="mu-call"><span className="ok small clickable" data-tip="Click if he isn't locked" onClick={() => setLock(r.sid, "")}> ✓</span></span>
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

// One matchup side by side. ◀ ▶ step through the league's matchups (yours first); calls and lock buttons show on
// yours only. Other matchups come from the plan endpoint for their first team (its opponent rides along).
function WeekView({ data, plan, open, setLock, leagueId }) {
  const mineIdx = Math.max(0, data.matchups.findIndex((pair) => pair.some((m) => m.roster_id === plan.roster_id)));
  const [idx, setIdx] = useState(mineIdx);
  const [other, setOther] = useState(null);
  const isMine = idx === mineIdx;
  const shown = isMine ? plan : other;
  // Your side shows your best lineup at the timeline's time (default: now); rivals show their real Sleeper lineup.
  // Each side's arrows are the moves from its Sleeper lineup to its best one. In the Sleeper
  // gap (data.sleeper_gap) the arrows hide and, at now, each side shows its Sleeper lineup as is.
  const [at, setAt] = useState(null);   // ms; null = follow the clock (so does the slider pushed into the past)
  const tl = shown?.timeline, nowMs = data.now ? Date.parse(data.now) : Date.now();
  const atMs = Math.max(at ?? nowMs, nowMs);
  const gap = data.sleeper_gap ? (atMs > nowMs ? "arrows" : "all") : null;
  const gamesOf = Object.fromEntries(Object.entries(data.players).map(([sid, p]) => [sid, p.games]));
  const me = bestLineup(shown, atMs, data.roster_positions, gap, !isMine, gamesOf), them = bestLineup(shown?.opponent, atMs, data.roster_positions, gap, true, gamesOf);
  const seg = me.seg;
  const gridRef = React.useRef(null);
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
  const L = bySlot(me.rows, data.roster_positions, data.reserve_slots);
  const R = o ? bySlot(them.rows, data.roster_positions, data.reserve_slots) : { lines: [], bench: [], ir: [] };
  const games = (players) => players.flatMap((r) => (data.players[r.sid]?.games || []).map((g) => [tipMs(g), g.date]));
  const irRows = Math.max(L.ir.length, R.ir.length);
  const allRows = L.lines.length + Math.max(L.bench.length, R.bench.length) + irRows;
  const xs = laneXs([...games(shown.players), ...games(o?.players || [])], lane?.w);
  // first: the first bench / IR row gets a gap above it (instead of a divider row, so every row can share the height)
  const row = (l, r, key, slot, first) => (
    <React.Fragment key={key}>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={l?.r} open={open} setLock={setLock} mine={isMine} side="left" day={seg?.date} lane={xs} /></div>
      <div className={`mu-slot ${first ? "first" : ""}`}><PosTag text={slot} /></div>
      <div className={`mu-cell ${first ? "first" : ""}`}><PlayerCard data={data} r={r?.r} open={open} side="right" day={them.seg?.date} lane={xs} /></div>
    </React.Fragment>
  );
  return (
    <div className="panel matchup" data-testid="my-week">
      {tl?.segments.length > 0 && <Timeline tl={tl} nowMs={nowMs} atMs={atMs} setAt={setAt} />}
      {gap && <div className="small muted mu-gap" data-testid="sleeper-gap">Sleeper still shows the day that just ended: lineups set for the next day don't show until it rolls over, so the arrows are off till then.</div>}
      <div className="mu-head">
        <button className="mu-arrow" onClick={() => step(-1)} data-tip="Previous matchup" data-testid="mu-prev">◀</button>
        {/* each side: name outside, score toward the centre, its expected final (small, grey) just outside the score */}
        <div className="mu-team">
          <TeamName t={shown} cls="mc-name" size={34} />{isMine && <span className="badge info">YOU</span>}
          <span className="small muted">{shown.games_left} left</span>
          <span className="mu-score"><span className="mu-exp-total" data-tip={EXP_TIP}>{shown.expected}</span><span className="mc-points">{fp(shown.points)}</span></span>
        </div>
        <div className="mu-mid">
          <span className="small muted">{idx + 1}/{n}</span>
          {!isMine && <button className="tiny" onClick={() => setIdx(mineIdx)}>mine</button>}
        </div>
        <div className="mu-team right">
          {o && <span className="mu-score"><span className="mc-points">{fp(o.points)}</span><span className="mu-exp-total" data-tip={EXP_TIP}>{o.expected}</span></span>}
          {o && <span className="small muted">{o.games_left} left · {o.locked} locked</span>}
          {o ? <TeamName t={o} cls="mc-name" size={34} /> : <span className="mc-name">no opponent</span>}
        </div>
        <button className="mu-arrow" onClick={() => step(1)} data-tip="Next matchup" data-testid="mu-next">▶</button>
      </div>
      {/* starters + bench fill the window; IR rows sit below the fold (scroll down), at the same row height */}
      <div className="mu-scroll">
      <div className="mu-grid with-arrows" ref={gridRef} style={irRows ? { height: `calc(${allRows / (allRows - irRows)} * (100% + 5px) - 5px)` } : undefined}>
        <SwapArrows pairs={me.pairs} side="left" names={(sid) => data.players[sid]?.name || sid} />
        <SwapArrows pairs={them.pairs} side="right" names={(sid) => data.players[sid]?.name || sid} />
        {tl && lane && xs.xs?.size > 0 && [["l", lane.l], ["r", lane.r]].filter(([, x]) => x != null).map(([k, x]) => (
          <div key={k} className="time-line" data-testid={`time-line-${k}`} style={{ left: x + laneAt(xs.xs, atMs, Date.parse(tl.start), Date.parse(tl.end), lane.w) - 1 }} />
        ))}
        {L.lines.map((l, i) => row(l, R.lines[i], `s${i}`, l.slot))}
        {Array.from({ length: Math.max(L.bench.length, R.bench.length) }, (_, i) => row(L.bench[i], R.bench[i], `b${i}`, "BN", i === 0))}
        {Array.from({ length: irRows }, (_, i) => row(L.ir[i], R.ir[i], `i${i}`, "IR", i === 0))}
      </div>
      </div>
    </div>
  );
}

// A team's best lineup at `atMs` from its timeline (one lineup per check-in; locked players never move): rows with
// everyone in the slot he should be in then, and the swaps from its Sleeper lineup as it is right now (so the arrows
// are the moves you'd make in Sleeper from where you are, at any point of the timeline).
// gap: "all" = Sleeper lineup as is, no arrows; "arrows" = best lineup, no arrows (they'd start from a stale lineup).
// asIs (rivals): rows stay their real Sleeper lineup; the arrows still show the moves to the best one.
const GAME_MS = 135 * 60000;   // a game counts as under way this long after its tip (as the backend's timeline does)
function bestLineup(team, atMs, positions, gap, asIs, games = {}) {
  const tl = team?.timeline, players = team?.players || [];
  const seg = tl?.segments[Math.max(0, tl.segments.findIndex((s) => atMs < Date.parse(s.to)))];
  const seats = seg ? seg.seats : team?.today?.seats;
  if (!seats || gap === "all") return { seg, rows: players, pairs: [] };
  const best = {};
  for (const [slot, sids] of Object.entries(seats)) for (const sid of sids) best[sid] = slot;
  // the plan says who starts; reseat keeps everyone who already starts in his Sleeper slot, so the moves are fewest
  const now = Object.fromEntries(players.map((r) => [r.sid, r.slot]));
  const pos = Object.fromEntries(players.map((r) => [r.sid, r.pos || []]));
  // Sleeper won't move these: locked in (or guessed locked), or benched with his game under way at the time shown (too
  // late to start him). A starter mid-game can still be benched for a later player (the plan's KEEP / SWAP calls).
  const playing = (sid) => (games[sid] || []).some((g) => {
    const tip = Date.parse(g.tip);
    return tip <= atMs && g.state !== "post" && (g.state === "in" || atMs < tip + GAME_MS);
  });
  const fixed = new Set(players.filter((r) => r.lock_status === "locked" || r.lock_status === "guess"
    || (r.slot === "BN" && playing(r.sid))).map((r) => r.sid));
  const after = reseat(now, Object.fromEntries(players.map((r) => [r.sid, best[r.sid] || (r.slot === "IR" ? "IR" : "BN")])), pos, positions, fixed);
  const rows = players.map((r) => ({ ...r, slot: after[r.sid] }));
  return { seg, rows: asIs ? players : rows, pairs: gap ? [] : swapSteps(now, after, pos, !asIs) };
}

// The arrows, in a lane beside a team's cards (left of the left team, right of the right team, mirrored by CSS): one
// per Sleeper swap (swapSteps), joining the two players who trade places (a head at both ends), numbered in the order
// to make them and coloured by the starting slot it fills. Measured from the cards on screen; redrawn when the grid
// changes size.
const ARROW_GUTTER = 80;
function SwapArrows({ pairs, side, names }) {
  const svgRef = React.useRef(null);
  const [lines, setLines] = useState([]);
  const key = pairs.map((p) => `${p.n}:${p.a}>${p.b}`).join(",");
  React.useLayoutEffect(() => {
    // the grid through our own svg: on mount the grid's ref isn't attached yet when this runs (children first)
    const grid = svgRef.current?.parentElement;
    if (!grid) return undefined;
    const measure = () => {
      const top = grid.getBoundingClientRect().top;
      const mid = (sid) => {
        const el = grid.querySelector(`.mu-card.${side}[data-testid="mu-${sid}"]`);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return r.top + r.height / 2 - top;
      };
      // shortest arrows nearest the cards, longest outside: nested lines cross as little as possible
      // each step joins the cards its two players' slots show at that step (earlier steps taken as done: swapSteps a / b)
      setLines(pairs.map((p) => ({ ...p, y1: mid(p.b), y2: mid(p.a) })).filter((l) => l.y1 != null && l.y2 != null)
        .sort((a, b) => Math.abs(a.y1 - a.y2) - Math.abs(b.y1 - b.y2)));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(grid);
    return () => ro.disconnect();
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  const step = Math.min(13, (ARROW_GUTTER - 24) / Math.max(1, lines.length));
  // the steps whose order matters (sharing a player with another step: a chain), numbered 1, 2, ... in step order
  const label = {};
  for (const s of pairs) {
    if (pairs.some((o) => o.n !== s.n && [o.in, o.out].some((x) => x === s.in || x === s.out))) label[s.n] = Object.keys(label).length + 1;
  }
  const end = ARROW_GUTTER - 6;   // just left of the cards
  return (
    <svg ref={svgRef} className={`swap-arrows ${side}`} width={ARROW_GUTTER} data-testid={`swap-arrows-${side}`}>
      {lines.map((l, i) => {
        const x = end - 12 - i * step, r = 6, dir = l.y2 < l.y1 ? -1 : 1;
        const color = `var(--pos-${(String(l.slot).match(/PG|SG|SF|PF|C/) || ["C"])[0]})`;
        // A number only where order matters: a step sharing a player with another step (a chain); a lone swap can be
        // made any time, so it's a plain line. The vertical run breaks around the number (mid ± gap), so the line never
        // crosses it; neighbouring lines put theirs at different heights so side-by-side numbers don't run together.
        const chained = label[l.n] != null;
        const mid = l.y1 + (l.y2 - l.y1) * [0.5, 0.3, 0.7][i % 3], gap = chained ? 10 : 0;
        const d = `M ${end - 5} ${l.y1} H ${x + r} Q ${x} ${l.y1} ${x} ${l.y1 + dir * r} V ${mid - dir * gap} `
          + `M ${x} ${mid + dir * gap} V ${l.y2 - dir * r} Q ${x} ${l.y2} ${x + r} ${l.y2} H ${end - 5}`;
        const head = (y) => `${end - 6},${y - 5} ${end + 1},${y} ${end - 6},${y + 5}`;
        return (
          <g key={l.n} style={{ color }}>
            <title>{`Swap ${names(l.in)} (${l.from}) and ${names(l.out)} (${l.to})`}</title>
            <path d={d} className="swap-path" />
            <polygon points={head(l.y1)} fill="currentColor" />
            <polygon points={head(l.y2)} fill="currentColor" />
            {/* the step number on the line's middle; the right lane is mirrored, so flip the text back */}
            {chained && <text className="swap-n" x={side === "right" ? -x : x} y={mid} transform={side === "right" ? "scale(-1,1)" : undefined}>{label[l.n]}</text>}
          </g>
        );
      })}
    </svg>
  );
}

// The week as a line (Mon 12 AM to the next Mon), 15-minute steps; the dot picks the time whose best lineup shows.
// The past is shaded and the dot can't go there (no lineup to set for it).
const STEP_MS = 15 * 60000;

function Timeline({ tl, nowMs, atMs, setAt }) {
  const start = Date.parse(tl.start), end = Date.parse(tl.end);
  const frac = (ms) => Math.min(1, Math.max(0, (ms - start) / (end - start)));
  const at = (ms) => `calc(${frac(ms)} * (100% - 16px) + 8px)`;   // where the 16px dot's centre sits for that time
  const days = Array.from({ length: 7 }, (_, i) => start + i * 86400000 + 12 * 3600000);   // noon of each day
  // the next purple mark still ahead: when to open Sleeper next ("in 1 day, 4 hours")
  const next = tl.segments.slice(0, -1).map((s) => Date.parse(s.to)).find((ms) => ms > nowMs);
  const mins = next ? Math.ceil((next - nowMs) / 60000) : 0;
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  const plural = (n, unit) => `${n} ${unit}${n === 1 ? "" : "s"}`;
  const until = d ? `${plural(d, "day")}, ${plural(h, "hour")}` : h ? `${plural(h, "hour")}, ${plural(m, "minute")}` : plural(m, "minute");
  return (
    <div className="timeline" data-testid="timeline">
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
      <button className="tl-next" onClick={() => next && setAt(next)} disabled={!next} data-testid="next-check"
        data-tip="The next time the lineup changes: open Sleeper then and make every swap at once. Click to show that lineup.">
        {/* two short lines, as tall as the timeline beside it */}
        <span><span className="tl-next-label">Next check-in</span> <span className="small muted">{next ? `in ${until}` : "none left this week"}</span></span>
        {next && <strong>{fmt(next, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</strong>}
      </button>
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
