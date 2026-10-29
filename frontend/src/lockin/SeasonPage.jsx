import React, { useCallback, useContext, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useNBAMatches, findMatch, watchUrl } from "./streams.jsx";
import { createPortal } from "react-dom";
import { api, qs } from "../api.js";
import Headshot from "../core/Headshot.jsx";
import { PosList, PosTag } from "../core/Pos.jsx";
import PlayerSidebar, { DepthGrid, TeamRanks } from "../core/PlayerSidebar.jsx";
import TeamLink, { TeamLinkContext } from "../core/TeamLink.jsx";
import PlayerSearch from "../core/PlayerSearch.jsx";
import InjuryTag from "../core/InjuryTag.jsx";
import { fmt, setZone, timeOf } from "./tz.js";
import { alarmSound } from "../core/sounds.js";
import { reseat, swapSteps } from "./swaps.js";

// The in-season tab: your Lock-In week (matchup, week plan with LOCK / PASS calls, every player's games Mon-Sun),
// today's lineup moves, the league (matchups + standings) and waiver claims. Any player name opens his season
// profile on the right. Data: backend services/season.py + engine/weekplan.py; refreshed every 2 minutes.
const REFRESH_MS = 60000;   // every minute: live scores feed the KEEP / SWAP calls

const dayName = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
const md = (d) => d.slice(5).replace("-", "/");   // "2026-10-20" -> "10/20"
const fp = (x) => (x == null ? "" : x.toFixed(2));   // fantasy points: 2 decimals, like Sleeper
// Player nicknames the managers set on Sleeper: shown unless switched off (Settings > General, this browser only).
const showNicks = () => { try { return localStorage.getItem("da.nicks") !== "off"; } catch { return true; } };
// A narrow window (keep in step with the 1599px @media block in styles.css): the chips become a small bar graph per
// game and lose the hourly timeline (laneXs), and the swap-arrow lanes slim down. 4K / wide windows are untouched.
const NARROW = "(max-width: 1599px)";
const useNarrow = () => useSyncExternalStore(
  (cb) => { const m = window.matchMedia(NARROW); m.addEventListener("change", cb); return () => m.removeEventListener("change", cb); },
  () => window.matchMedia(NARROW).matches);

// A fantasy team: its Sleeper avatar, its team name, and under it the manager's username (when that differs) and
// W-L record, with a green up / red down arrow for the latest result.
function TeamName({ t, cls = "", size = 24, record = true }) {
  const rec = record && t.wins != null;
  return (
    <span className="team-name-tag">
      {t.avatar && <img className="team-avatar" src={t.avatar} width={size} height={size} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />}
      <span className="team-name-lines">
        <span className={cls}>{t.name}</span>
        {(rec || (t.user && t.user !== t.name)) && <span className="small muted team-sub">
          {t.user && t.user !== t.name && <span className="team-user">{t.user}</span>}
          {rec && <span className="team-rec" data-testid="team-record">{t.wins}-{t.losses}{t.last === "W" && <span className="good-text"> ▲</span>}{t.last === "L" && <span className="warn-text"> ▼</span>}</span>}
        </span>}
      </span>
    </span>
  );
}


export default function SeasonPage({ leagueId, view }) {   // view: week | news | league | waivers (the app's top tabs)
  const [week, setWeek] = useState(null);
  const [plan, setPlan] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  // The right side's history, like a browser's: each entry a player profile { pid }, a game card { game: { game, team,
  // sid, name } } (GamePanel) or an NBA team's card { team: abbr } (TeamPanel); ‹ › step through it, opening something
  // new drops what was ahead. ✕ clears it back to the guide.
  const [nav, setNav] = useState({ stack: [], i: -1 });
  const cur = nav.stack[nav.i], selected = cur?.pid ?? null, game = cur?.game ?? null, team = cur?.team ?? null;
  const go = (entry) => setNav(({ stack, i }) => {
    const same = (a, b) => (a?.pid && a.pid === b.pid) || (a?.game && a.game.game.event === b.game?.game.event) || (a?.team && a.team === b.team);
    return same(stack[i], entry) ? { stack, i } : { stack: [...stack.slice(0, i + 1), entry], i: i + 1 };
  });
  const close = () => setNav({ stack: [], i: -1 });
  const setSelected = (pid) => (pid ? go({ pid }) : close());
  const [tick, setTick] = useState(0);
  const [headerSlot, setHeaderSlot] = useState(null);
  useEffect(() => { setHeaderSlot(document.getElementById("header-slot")); }, []);
  // the header's ◀ Week ▶ sits over the middle of the matchup column: its x within the header, kept on resize
  const mainRef = useRef(null), weekRef = useRef(null);
  const [weekX, setWeekX] = useState(null);

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
    const on = !armed;   // the effect below clears the pending timers when this turns off
    if (on) {
      alarmSound();   // the click also unlocks sound for later
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    }
    setArmed(on); try { localStorage.setItem("da.season.alarms", on ? "1" : "0"); } catch { /* ignore */ }
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

  if (!leagueId) return <div className="panel muted" data-testid="no-league">No Sleeper league selected!</div>;
  if (error && !data) return <div className="panel error">{error}</div>;
  useEffect(() => {
    const m = mainRef.current, h = headerSlot?.closest("header");
    if (!m || !h) return;
    const place = () => {   // centred only when it clears the tabs and the search box; else inline after the tabs
      const a = m.getBoundingClientRect(), c = a.left + a.width / 2, wk = weekRef.current;
      const nav = h.querySelector("nav").getBoundingClientRect().right, right = h.querySelector(".season-search")?.getBoundingClientRect().left;
      const w = wk ? wk.children[2].getBoundingClientRect().right - wk.children[0].getBoundingClientRect().left : 0, after = wk?.lastElementChild?.offsetWidth || 0;
      setWeekX(c - w / 2 >= nav + 24 && (right == null || c + w / 2 + 12 + after + 24 <= right) ? c - h.getBoundingClientRect().left : null);
    };
    const ro = new ResizeObserver(place);
    ro.observe(m); ro.observe(h);
    return () => ro.disconnect();
  }, [headerSlot, !!(data && plan)]);
  if (!data || !plan) return <div className="panel">Loading the week from Sleeper…</div>;

  const pidOf = (sid) => data.players[sid]?.player_id;
  const open = (sid) => { const pid = pidOf(sid); if (pid) setSelected(pid); };
  const openGame = (g) => go({ game: g });
  const openTeam = (abbr) => go({ team: abbr });
  const setLock = (sid, gameDate) => api.post(`/leagues/${leagueId}/season/locks`, { week: data.week, sleeper_id: sid, game_date: gameDate })
    .then(() => setTick((t) => t + 1)).catch((e) => setError(e.message));

  // The week bar lives in the app header (top bar) while this tab is open.
  const bar = (
        <div className="season-bar">
          <span className="season-weeknav" ref={weekRef} style={weekX != null ? { left: weekX } : undefined}>
            <button className="mu-arrow" disabled={data.week <= 1} onClick={() => setWeek(data.week - 1)} data-tip="Previous week">◀</button>
            <strong className="season-week">Week {data.week}</strong>
            <button className="mu-arrow" disabled={data.week >= Math.max(...data.weeks)} onClick={() => setWeek(data.week + 1)} data-tip="Next week">▶</button>
            <span className="season-weeknav-after">
              <span className="muted small">{data.league_name}</span>
              {week && <button className="small ghost" onClick={() => setWeek(null)}>this week</button>}
            </span>
          </span>
          {error && <span className="small warn-text">{error}</span>}
          <span className="season-search" style={{ marginLeft: "auto" }}><PlayerSearch leagueId={leagueId} onSelect={(p) => setSelected(p.player_id)} onSelectTeam={openTeam} placeholder="Any player or team…" testId="season-search" /></span>
          <button className="small primary" onClick={sync} disabled={syncing} data-testid="sync"
            data-tip="Pull your lineup, locks, scores and news from Sleeper now and recompute the best lineup.">
            {syncing ? "Syncing…" : "⟳ Sync"}</button>
          <button className={`small primary bell ${armed ? "" : "off"}`} onClick={arm} data-testid="arm-alarms" aria-label={armed ? "Alarms on" : "Turn on alarms"}
            data-tip={`${armed ? "Alarms on. " : "Alarms off: click to turn on. "}Rings at each swap check and GTD check while this tab is open, with a browser notification. Click once to allow sound and notifications.`}>🔔</button>
        </div>
  );
  return (
    <TeamLinkContext.Provider value={openTeam}>
    <div className="season-grid">
      <section className="season-main" ref={mainRef}>
        {headerSlot ? createPortal(bar, headerSlot) : bar}
        {alerts.map((a) => (
          <div key={a.key} className={`panel roster-alert ${["gtd", "out"].includes(a.kind) || a.decision === "SWAP" ? "bad" : "even"}`} data-testid="alarm-banner">
            <strong>⏰ {a.title}</strong> {a.text}
            <button className="tiny" style={{ marginLeft: 8 }} onClick={() => setAlerts((x) => x.filter((y) => y.key !== a.key))}>dismiss</button>
          </div>
        ))}
        {view === "week" && <WeekView key={data.week} data={data} plan={plan} open={open} openGame={openGame} setLock={setLock} leagueId={leagueId} />}
        {view === "news" && <NewsView leagueId={leagueId} open={setSelected} refreshKey={tick} />}
        {view === "league" && <LeagueView data={data} leagueId={leagueId} open={open} />}
        {view === "waivers" && <WaiversView leagueId={leagueId} onSelect={setSelected} />}
      </section>
      <aside className={`season-side ${cur ? "has-nav" : ""}`}>
        {cur && (
          <span className="side-nav">
            <button onClick={() => setNav((n) => ({ ...n, i: n.i - 1 }))} disabled={!nav.i} title="Back" aria-label="Back" data-testid="side-back">‹</button>
            <button onClick={() => setNav((n) => ({ ...n, i: n.i + 1 }))} disabled={nav.i === nav.stack.length - 1} title="Forward" aria-label="Forward" data-testid="side-forward">›</button>
          </span>
        )}
        {selected
          ? <PlayerSidebar leagueId={leagueId} playerId={selected} season plan={plan} onSelectPlayer={setSelected} refreshKey={tick} onClose={close} onOpenGame={openGame} />
          : game ? <GamePanel key={game.game.event} sel={game} data={data} leagueId={leagueId}
            onOpenPid={setSelected} onClose={close} />
          : team ? <TeamPanel key={team} abbr={team} leagueId={leagueId} onOpenPid={setSelected} onClose={close} />
          : <LockinGuide data={data} plan={plan} leagueId={leagueId} setLock={setLock} open={open} />}
      </aside>
    </div>
    </TeamLinkContext.Provider>
  );
}

// The right side's Team card (a team's name clicked anywhere on the Season tab, or a team in the News tab's report):
// logo and name, then tabs (backend /season/team), Roster first and open:
//   Roster    offense / defense ranks and the depth chart (names coloured by injury), then the injuries
//             (yellow: questionable / game-time / day-to-day; red: out / IR);
//   Schedule  every game: vs / @ the opponent, and W / L with the score once it's played;
//   Stats     every player's per-game line for this team;
//   News      the News tab's notes, on this team's players only (loaded when the tab opens).
const TEAM_TABS = [["roster", "Roster"], ["schedule", "Schedule"], ["stats", "Stats"], ["news", "News"]];
const teamLogo = (abbr) => `https://sleepercdn.com/images/team_logos/nba/${abbr.toLowerCase()}.png`;
const shortName = (n) => { const [first, ...rest] = (n || "").split(" "); return rest.length ? `${first[0]}. ${rest.join(" ")}` : n; };
function TeamPanel({ abbr, leagueId, onOpenPid, onClose }) {
  const [t, setT] = useState(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState("roster");
  const [news, setNews] = useState(null);
  useEffect(() => { api.get(`/leagues/${leagueId}/season/team` + qs({ abbr })).then(setT).catch((e) => setError(e.message)); }, [leagueId, abbr]);
  useEffect(() => {
    if (tab === "news" && !news) api.get(`/leagues/${leagueId}/season/team/news` + qs({ abbr })).then((x) => setNews(x.news)).catch(() => setNews([]));
  }, [tab, news, leagueId, abbr]);
  return (
    <div className="panel scroll team-panel" data-testid="team-panel">
      <button className="sidebar-close" onClick={onClose} title="Close team" data-testid="team-close">✕</button>
      {!t ? <div className="muted">{error || `Loading ${abbr}…`}</div> : <>
        <div className="tp-head">
          <img src={t.logo} alt="" width={52} height={52} onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
          <div>
            <h3 className="tp-name">{t.name}{t.conference && <span className={`conf conf-${t.conference}`}>{t.conference}</span>}</h3>
            <div className="small muted">team <strong style={{ color: "var(--text)" }}>#{t.talent_rank}</strong> of {t.teams} in projected fantasy talent</div>
          </div>
        </div>
        <nav className="profile-tabs" data-testid="team-tabs">
          {TEAM_TABS.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`team-tab-${id}`}>{label}</button>)}
        </nav>
        {tab === "schedule" && (
          <div className="tp-schedule" data-testid="team-schedule">{t.schedule.map((g) => (
            <div key={g.date} className="tp-game">
              <span className="small muted tp-date">{dayName(g.date)} {md(g.date)}</span>
              <span className="muted tp-at">{g.home ? "vs" : "@"}</span>
              <img src={teamLogo(g.opp)} alt="" width={22} height={22} />
              <TeamLink abbr={g.opp}>{t.names[g.opp] || g.opp}</TeamLink>
              {g.result && <span className="tp-result"><strong className={g.result === "W" ? "ok" : "warn-text"}>{g.result}</strong> {g.pts}-{g.opp_pts}</span>}
            </div>
          ))}</div>
        )}
        {tab === "roster" && (
          <div className="team-card">
            {t.ranks && <TeamRanks r={t.ranks} />}
            <DepthGrid grid={t.depth_grid} onSelectPlayer={onOpenPid} />
          </div>
        )}
        {tab === "stats" && (
          <div className="tp-stats-wrap"><table className="tp-stats" data-testid="team-stats">
            <thead><tr><th>{t.name}</th>{["MIN", "PTS", "REB", "AST", "FG%", "FT%", "3P%", "STL", "BLK", "TO", "PF"].map((h) => <th key={h} className="num">{h}</th>)}</tr></thead>
            <tbody>{t.stats.map((r) => (
              <tr key={r.sleeper_id} className="clickable" onClick={() => onOpenPid(r.player_id)}>
                <td><span className="tp-player"><Headshot sleeperId={r.sleeper_id} name={r.name} size={22} /><span>{shortName(r.name)}</span> <PosList list={r.pos} /></span></td>
                {r.gp ? ["min", "pts", "reb", "ast", "fg_pct", "ft_pct", "tp_pct", "stl", "blk", "to", "pf"].map((k) => <td key={k} className="num">{r[k] ?? "—"}</td>)
                  : <td className="num muted" colSpan={11}>no games yet</td>}
              </tr>
            ))}</tbody>
          </table></div>
        )}
        {tab === "news" && (news ? (news.length ? news.map((n, i) => <NewsNote key={i} n={n} open={onOpenPid} />) : <div className="muted">No recent notes on this team's players.</div>)
          : <div className="muted">Loading news…</div>)}
        {tab === "roster" && (
          <div data-testid="team-injuries">{[["q", "? Questionable", "Game-time and day-to-day decisions"], ["out", "(−) Out", "Out and injured reserve"]].map(([g, title, sub]) => {
            const list = t.injuries.filter((h) => h.group === g);
            return (
              <section key={g} className={`tp-inj health-box-${g}`}>
                <h4 className={`health-${g}`}>{title} <span className="small muted">· {sub} ({list.length})</span></h4>
                {list.length ? list.map((h) => (
                  <div key={h.sid} className={`tp-inj-row ${h.player_id ? "clickable" : ""}`} onClick={() => h.player_id && onOpenPid(h.player_id)}>
                    <Headshot sleeperId={h.sid} name={h.name} size={28} />
                    <span><strong className={`health-${g}`}>{h.name}</strong> <span className="small muted">{h.pos.join(" ")}</span></span>
                    <span className="small tp-inj-tag">{h.status}{h.body ? ` · ${h.body}` : ""}{h.note ? ` · ${h.note}` : ""}</span>
                  </div>
                )) : <div className="small muted">None.</div>}
              </section>
            );
          })}</div>
        )}
      </>}
    </div>
  );
}

// The right side when a game card is clicked: that NBA game (backend game_detail, ESPN's summary), live or past.
// Score and status, a stream link (streamed.pk) while it's on, each team's top 5 by fantasy points with their headline stats (like Sleeper's),
// then per team its box score (players who got minutes, fantasy points in the league's scoring; rostered players tagged with their fantasy
// team; any player matched to ours clickable for his profile), its offense / defense ranks and depth chart (the Team card's).
// Before the tip: both teams with their records, ranks and depth charts. Team names open the Team card. Refreshes every minute.
const BOX_COLS = [["MIN", (r) => r.min], ["PTS", (r) => r.stats.pts], ["REB", (r) => r.stats.reb], ["AST", (r) => r.stats.ast],
  ["STL", (r) => r.stats.stl], ["BLK", (r) => r.stats.blk], ["TO", (r) => r.stats.to], ["FG", (r) => `${r.stats.fgm}-${r.stats.fga}`],
  ["3PT", (r) => `${r.stats.tpm}-${r.stats.tpa}`], ["FT", (r) => `${r.stats.ftm}-${r.stats.fta}`], ["PF", (r) => r.stats.pf]];
const initialName = (n) => { const [first, ...rest] = (n || "").split(" "); return rest.length ? `${first[0]}. ${rest.join(" ")}` : n; };   // "R. Hachimura"
const normName = (n) => (n || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z ]/g, "")
  .replace(/\b(jr|sr|ii|iii|iv)\b/g, "").replace(/\s+/g, " ").trim();
const GpHead = ({ src, size }) => src
  ? <img className="gp-head" src={src} alt="" width={size} height={size} style={{ width: size, height: size }} loading="lazy" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
  : <span className="gp-head" style={{ width: size, height: size }} />;
function GamePanel({ sel, data, leagueId, onOpenPid, onClose }) {
  const [g, setG] = useState(null);
  const [error, setError] = useState("");
  const { list: matches } = useNBAMatches();
  useEffect(() => {
    const load = () => api.get(`/leagues/${leagueId}/season/game` + qs({ event: sel.game.event })).then((x) => { setG(x); setError(""); }).catch((e) => setError(e.message));
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [leagueId, sel.game.event]);
  // fantasy rosters by name (ESPN's names, Sleeper's ids): who owns each player in the box score
  const owner = {};
  for (const t of data.teams) for (const sid of t.players) {
    const n = data.players[sid]?.name;
    if (n) owner[normName(n)] = { sid, team: t.user || t.name, mine: t.is_user };
  }
  const watch = sel.game.state !== "post" ? watchUrl(findMatch(matches, sel.game, sel.team)) : null;   // any game not over
  const when = g?.tip ? fmt(g.tip, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";
  const status = !g ? "" : g.state === "in" ? quarters(g.detail) : g.state === "post" ? "Final" : `Tips ${fmt(g.tip, { hour: "numeric", minute: "2-digit" })}`;
  return (
    <div className="panel scroll game-panel" data-testid="game-panel">
      <button className="sidebar-close" onClick={onClose} title="Close game" data-testid="game-close">✕</button>
      {!g ? <div className="muted">{error || "Loading the game…"}</div> : <>
        <div className="gp-score">
          {g.teams.map((t, i) => (
            <React.Fragment key={t.abbr}>
              {i === 1 && <div className="gp-status"><span className={g.state === "in" ? "gp-live" : ""}>{status}</span><span className="small muted">{when}</span></div>}
              <div className={`gp-team ${i ? "home" : ""}`}>
                {t.logo && <TeamLink abbr={t.abbr}><img src={t.logo} alt="" width={40} height={40} /></TeamLink>}
                {/* before the tip: the team's record where the score will go */}
                <div><div className="gp-abbr"><TeamLink abbr={t.abbr} /></div>
                  {g.state === "pre" ? <div className="gp-record">{t.record || "—"}</div> : <div className="gp-pts">{t.score ?? "—"}</div>}</div>
              </div>
            </React.Fragment>
          ))}
        </div>
        {watch && <div className="gp-actions"><a className="gp-watch" href={watch} target="_blank" rel="noopener noreferrer">▶ Watch</a></div>}
        {g.teams.some((t) => t.players.length) && (
          <section className="gp-section" data-testid="game-leaders">
            <h4>Top performers</h4>
            <div className="gp-leaders">{g.teams.map((t) => (
              <div key={t.abbr}>
                <div className="gp-leaders-team">{t.logo && <img src={t.logo} alt="" width={18} height={18} />}<TeamLink abbr={t.abbr} /></div>
                {[...t.players].sort((a, b) => b.fp - a.fp).slice(0, 5).map((r) => {
                  const own = owner[normName(r.name)];
                  return (
                    <div key={r.name} className={`gp-leader ${r.player_id ? "clickable" : ""}`} onClick={r.player_id ? () => onOpenPid(r.player_id) : undefined}>
                      <GpHead src={r.head} size={34} />
                      <div>
                        <div className={`gp-name ${own?.mine ? "gp-mine-name" : ""}`}>{r.name}{r.jersey && <span className="gp-jersey">#{r.jersey}</span>}</div>
                        <div className="gp-line"><span className="gp-fp">{fp(r.fp)} FP</span>
                          {r.lead.map(([k, v]) => <span key={k}><strong>{v}</strong> {k}</span>)}</div>
                      </div>
                    </div>
                  );
                })}
              </div>
            ))}</div>
          </section>
        )}
        {g.teams.map((t) => {
          const rows = [...t.players].sort((a, b) => b.starter - a.starter || b.min - a.min);
          return (
            <section key={t.abbr} className="gp-section">
              <h4><TeamLink abbr={t.abbr}>{t.name}</TeamLink></h4>
              {g.state === "pre" ? null : rows.length ? (
                <table className="gp-box"><thead><tr><th>Player</th><th className="num">FP</th>{BOX_COLS.map(([h]) => <th key={h} className="num">{h}</th>)}</tr></thead>
                  <tbody>{rows.map((r) => {
                    const own = owner[normName(r.name)];
                    return (
                      <tr key={r.name} className={own?.mine ? "gp-mine" : ""}>
                        <td className={r.player_id ? "clickable" : ""} onClick={r.player_id ? () => onOpenPid(r.player_id) : undefined}>
                          <span className="gp-player">
                            <GpHead src={r.head} size={22} />
                            <span className="gp-name">{initialName(r.name)}</span>
                          </span>
                        </td>
                        <td className="num"><strong>{fp(r.fp)}</strong></td>
                        {BOX_COLS.map(([h, f]) => <td key={h} className="num">{f(r)}</td>)}
                      </tr>
                    );
                  })}</tbody></table>
              ) : <div className="small muted">No minutes yet.</div>}
              {t.dnp.some((d) => d.reason) && <div className="small muted gp-dnp">{g.state === "post" ? "DNP" : "Not in yet"}: {t.dnp.filter((d) => d.reason).map((d) => d.name).join(", ")}</div>}
              {t.ranks && <TeamRanks r={t.ranks} />}
              <DepthGrid grid={t.depth_grid} onSelectPlayer={onOpenPid} />
            </section>
          );
        })}
      </>}
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
// open(sid): a player's name opens his profile.
function LockinGuide({ data, plan, leagueId, setLock, open }) {
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
  const lockable = p.players.filter((r) => r.seat && r.x != null && r.x_final && r.lock_status !== "locked" && r.lock_status !== "guess")   // final games only
    .sort((a, b) => edge(b) - edge(a));
  const swaps = watch.filter((w) => w.kind === "swap"), injuries = watch.filter((w) => w.kind === "gtd" || w.kind === "out");
  const remaining = (o?.players || []).filter((r) => r.seat && r.locked == null && r.w > 0).sort((a, b) => b.w - a.w).slice(0, 4);
  const banked = (o?.players || []).filter((r) => r.locked != null).sort((a, b) => b.locked - a.locked);
  const odds = out ? [["Lock all now", out.safe], ["Leave all open", out.risky], ["Plan mix", p.win_chance]] : [];
  const top = Math.max(...odds.map(([, v]) => v ?? 0));
  const signed = (x) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)}`;
  // a guessed lock (?) can be answered here: ✓ locked / ✕ not locked (saved like your own lock answers)
  const chip = (r, value, guess) => (
    <span key={r.sid} className="guide-chip"><span className="clickable guide-who" onClick={() => open(r.sid)}><Headshot sleeperId={r.sid} name={r.name} size={22} />{lastName(r.name)}</span> <strong>{value}{guess ? "?" : ""}</strong>
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
      {mine && <RosterAlerts roster={plan.roster} />}
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
          const e = edge(r), tip = nextTip(r.sid), nba = data.players[r.sid]?.team;
          // the open slot: the best game it can still take each day, his or a spare bench player's (backend open_slot)
          const from = (r.slot_from || []).map(([d, who]) => `${dayName(d)}${who === r.name ? "" : ` ${lastName(who)}`}`);
          return (
            <div key={r.sid} className={`guide-lock ${Math.abs(e) < 0.015 ? "even" : e > 0 ? "lock" : "pass"}`}>
              <Headshot sleeperId={r.sid} name={r.name} size={38} />
              <div className="guide-lock-main">
                <div className="guide-lock-top"><strong className="clickable" onClick={() => open(r.sid)}>{r.name}</strong> <span className="muted small">{r.seat}</span>
                  {nba && <span className="small muted"> · <TeamLink abbr={nba}><img src={teamLogo(nba)} alt="" width={16} height={16} style={{ verticalAlign: "-3px" }} /> {nba}</TeamLink></span>}</div>
                <div className="small muted">Open slot ~{fp(r.slot_w ?? r.w)}{from.length ? ` · ${from.join(", ")}` : " · no games left"}</div>
                {r.win_lock != null && (() => {
                  // locked where he sits now, when that isn't the best slot: what skipping the move costs
                  const here = r.lock_at?.find((o) => o.slot === r.slot && o !== r.lock_at[0] && o.win != null);
                  return <div className="small muted">Win % locked <span className="guide-hi">{pct(r.win_lock)}</span>{here ? ` at ${r.lock_at[0].slot}` : ""}
                    {here && <> · <span className="warn-text">{pct(here.win)} at {here.slot}</span> where he sits</>}
                    {" "}· open <span className="guide-hi">{pct(r.win_wait)}</span></div>;
                })()}
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
              <div><strong className="clickable" onClick={() => open(w.backup_sid)}>{w.backup}</strong> <span className="muted">for</span> <strong className="clickable" onClick={() => open(w.sid)}>{w.name}</strong> <span className="muted">· window {when(w.alarm)}</span></div>
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
            <div className="small"><strong className="clickable" onClick={() => open(w.sid)}>{w.name}</strong> <span className="muted">· {w.kind === "out" ? "out" : "questionable"}{w.slot ? ` · ${w.slot}` : ""}{w.by ? ` · tips ${when(w.by)}` : ""}</span>
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
// projection small beside it; live, that number is where his game is headed instead (backend pace: live_estimate), green /
// red as it beats his projection or not; once the game is final it goes back to the pregame projection.
// A game that can't be locked (or count any more) is crossed out: every game but the locked one once he's locked;
// a final game once a later one has tipped, or that the backend can't lock (lockable = r.x: benched for it); a live
// game while he sits on the bench (it won't count, and it's too late to start him).
// Games off the lineup day dim, except the locked game and a final game he can still lock.
// lane (matchup cards): { xs: tip ms -> x px, scale }, so the chips line up as a timeline (see laneXs).
// onOpen(game): a click opens that game on the right (GamePanel).
// onLock(date): the corner padlock locks / unlocks: open on a final game he can still lock (lock it), filled on the
// locked game (unlock: "").
// The stream (streamed.pk) of a game that's on or about to start: a ▶ in the same corner (a final game has none).
function GameChips({ games, today, lockDate, lockGuess, lockable, benched, day, lane, team, onOpen, onLock }) {
  const { list: matches } = useNBAMatches();
  const graph = useNarrow();
  // graph bars share one scale per player: his best projection / score this week
  const peak = Math.max(1, ...games.map((x) => Math.max(x.fp ?? 0, x.pace ?? 0, x.proj ?? 0)));
  // each chip's stream: a scan of every listed stream, so once per list / games, not on every render (the slider re-renders)
  const watches = React.useMemo(() => games.map((g) => (g.state !== "post" ? watchUrl(findMatch(matches, g, team)) : null)), [matches, games, team]);
  if (!games.length) return lane ? <span className="chips-lane"><span className="muted small">no games</span></span> : <span className="muted small">no games</span>;
  const chips = games.map((g, i) => {
        // live: ESPN says in progress, or his stats are coming in before ESPN's state catches up; final only once ESPN says so
        const played = g.fp != null, live = g.state === "in" || (played && g.state !== "post");
        const later = games.slice(i + 1).some((x) => x.state !== "pre" || x.fp != null);
        const dead = lockDate ? g.date !== lockDate : (g.state === "post" && (later || !lockable)) || (live && benched);
        const upcoming = g.state === "pre" && !played && !dead;   // only a game still to come gets the purple border
        const toggle = !onLock ? null : lockDate === g.date ? "" : g.state === "post" && played && !dead ? g.date : null;
        const lockClick = (e) => { e.stopPropagation(); onLock(toggle); };
        const watch = watches[i];   // any game not over
        const exp = live && g.pace != null ? g.pace : g.proj;
        // the hover adds only what the card doesn't show (day, time, FP and expected FP are on it; the graph shows less)
        const tip = [
          graph && [timeOf(g.tip), played && `${fp(g.fp)} FP`, exp != null && `proj ${fp(exp)}`].filter(Boolean).join(" · "),
          // "MIA 81 vs MIN 104" (his team first; no scores before the tip)
          [team, g.score, g.home ? "vs" : "@", g.opp, g.opp_score].filter((x) => x != null && x !== "").join(" "),
          played && g.min != null && `${g.min} min${live ? " so far" : ""}`,
          g.b2b && g.state === "pre" && "2nd night of a back-to-back",
          g.beat != null && `${Math.round(g.beat * 100)}% to score higher this week`,   // locked too: was it the right call
          lockDate === g.date ? (lockGuess ? "locked (a guess: his next game confirms it)" : "locked") : dead && "can't be locked",
          toggle === "" ? "padlock: unlock" : toggle && "padlock: lock",
          watch && "▶: watch",
        ].filter(Boolean).join(" · ") + (g.box ? `\n${boxLine(g.box)}` : "");
        return (
          <span key={g.date} onClick={onOpen && g.event ? (e) => { e.stopPropagation(); onOpen(g); } : undefined}
            style={lane?.xs ? { left: lane.xs.get(tipMs(g)) ?? 0, ...(lane.scale < 1 && { width: 100 * lane.scale }) } : undefined}
            className={`game-chip ${graph ? "graph" : ""} ${played ? "played" : ""} ${live ? "live" : ""} ${g.date === today && upcoming ? "today" : ""} ${lockDate === g.date ? `locked ${lockGuess ? "guess" : ""}` : ""} ${day ? (g.date === day && upcoming ? "pick" : lockDate === g.date || live || (g.state === "post" && !dead) ? "" : "dim") : ""} ${dead ? "dead" : ""} ${onOpen && g.event ? "openable" : ""}`}
            data-tip={tip}>
            <span className="gch-day">{live ? shortQuarter(g.detail) : dayName(g.date)} <span className="gch-time">{live ? "LIVE"
              : lockDate === g.date && toggle !== "" ? <LockIcon />   /* the corner's unlock padlock says it otherwise */
              : played ? "final" : timeOf(g.tip).replace(":00", "").replace(" PM", "p").replace(" AM", "a")}</span></span>
            {toggle && <button className="gch-lockbtn corner" onClick={lockClick} aria-label="Lock" data-testid="lock-game"><LockIcon open /></button>}
            {toggle === "" && <button className="gch-lockbtn corner unlock" onClick={lockClick} aria-label="Unlock" data-testid="unlock-game"><LockIcon /></button>}
            {watch && <a className="gch-lockbtn corner watch" href={watch} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()} aria-label="Watch" data-testid="watch-game"><svg className="gch-play" viewBox="0 0 9 10" aria-hidden="true"><path d="M0 0L9 5L0 10Z" fill="currentColor" /></svg></a>}
            {graph ? <>
              <span className="gch-bar"><i className="exp" style={{ height: `${100 * (exp ?? 0) / peak}%` }} />{played && <i className="act" style={{ height: `${100 * g.fp / peak}%` }} />}</span>
              <span className="gch-fp">{fp(played ? g.fp : exp)}</span>
            </> : <span className="gch-fp">{played ? fp(g.fp) : "—"}<span className={`gch-exp ${live && g.pace != null && g.proj != null ? (g.pace >= g.proj ? "up" : "down") : ""}`}>{fp(exp)}</span></span>}
          </span>
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

// a small padlock: a locked game with no unlock button shows it where "final" would be; open (shackle lifted) on the lock button
const LockIcon = ({ open }) => (
  <svg className="gch-lock" viewBox="0 0 10 12" aria-hidden="true">
    <path d={open ? "M3 5.2V2.6a2 2 0 0 1 4 0v.6" : "M3 5.2V3.6a2 2 0 0 1 4 0v1.6"} fill="none" stroke="currentColor" strokeWidth="1.4" />
    <rect x="1" y="5" width="8" height="6.5" rx="1.6" fill="currentColor" />
  </svg>
);

const tipMs = (g) => Date.parse(g.tip) || Date.parse(`${g.date}T12:00:00`);

// A matchup's chips as a timeline: one x per distinct tip on both rosters, the earliest at the lane's left edge.
// Each game day starts clear of the previous day's chips (so the time line never sits on an earlier day's chips);
// within a day the tips spread by the hour (4-12 px an hour, as much as fits); room left over spaces the days in
// proportion to time. Too narrow even at 4 px an hour: the chips shrink (scale) down to 65%; narrower than that, xs is
// null and the chips sit in a plain row (no time line).
const CHIP_W = 100, CHIP_GAP = 6, HOUR_MIN = 4, HOUR_MAX = 12;
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

// Re-render a card only when what it shows changes: the slider re-renders the grid every step, and bestLineup hands
// back fresh row objects each time (so r is compared field by field).
const sameFields = (a, b) => a === b || (!!a && !!b && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every((k) => a[k] === b[k]));
const sameCard = (a, b) => Object.keys(a).every((k) => (k === "r" ? sameFields(a.r, b.r) : a[k] === b[k]));
const PlayerCard = React.memo(function PlayerCard({ data, r, open, openGame, setLock, mine, side, day, lane }) {
  if (!r) return <div className={`mu-card empty ${side}`}><span className="muted small">empty</span></div>;
  const p = data.players[r.sid] || { games: [] };
  const starter = r.slot !== "BN" && r.slot !== "IR";
  const locked = r.lock_status === "locked" || r.lock_status === "guess";   // guess: Sleeper can't tell yet, the math says locked
  return (
    <div className={`mu-card ${side} ${starter ? "" : "bench"} ${locked ? "done" : ""}`} data-testid={`mu-${r.sid}`}>
      <div className="mu-top">
        <div className="mu-id clickable" onClick={() => open(r.sid)} data-testid={`open-${r.sid}`}>
        <Headshot sleeperId={r.sid} name={r.name} size={34} />
        <div className="mu-who">
          <div className="mu-name">{r.name}<InjuryTag tag={p.injury_tag} note={p.injury_note} /></div>
          <div className="small muted mu-sub">{p.team || (p.retired ? "Retired" : "FA")} <PosList list={r.pos} />
            {p.nick && showNicks() && <span className="nick" data-tip="Nickname set on Sleeper"> · “{p.nick}”</span>}</div>
        </div>
        </div>
        <GameChips games={p.games} team={p.team} today={data.today} day={mine ? day || data.day : day} lockDate={locked ? r.lock_date : null} lockGuess={r.lock_status === "guess"} lockable={r.x != null} benched={r.slot === "BN" || r.slot === "IR"} lane={lane}
          onOpen={openGame ? (g) => openGame({ game: g, team: p.team, sid: r.sid, name: r.name }) : null}
          onLock={setLock ? (date) => setLock(r.sid, date) : null} />
      </div>
    </div>
  );
}, sameCard);

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
function WeekView({ data, plan, open, openGame, setLock, leagueId }) {
  const mineIdx = Math.max(0, data.matchups.findIndex((pair) => pair.some((m) => m.roster_id === plan.roster_id)));
  const [idx, setIdx] = useState(mineIdx);
  const [other, setOther] = useState(null);
  const isMine = idx === mineIdx;
  const shown = isMine ? plan : other;
  // Your side shows your best lineup at the timeline's time (default: now); rivals show their real Sleeper lineup.
  // Each side's arrows are the moves from its Sleeper lineup to its best one. In the Sleeper gap (data.sleeper_gap: Sleeper
  // still serves the day that just ended) that lineup is the one it carries into the next day, so the arrows start from it.
  const [at, setAt] = useState(null);   // ms; null = follow the clock (so does the slider pushed into the past)
  const tl = shown?.timeline, nowMs = data.now ? Date.parse(data.now) : Date.now();
  const atMs = Math.max(at ?? nowMs, nowMs);
  const gap = data.sleeper_gap;
  const gamesOf = React.useMemo(() => Object.fromEntries(Object.entries(data.players).map(([sid, p]) => [sid, p.games])), [data.players]);
  const best = bestLineup(shown, atMs, data.roster_positions, !isMine, gamesOf), them = bestLineup(shown?.opponent, atMs, data.roster_positions, true, gamesOf);
  // Your side can show the best lineup (default) or the one you have in Sleeper now; the toggle is live only when they differ.
  const [view, setView] = useState("best");
  const differs = isMine && best.rows.some((r, i) => r.slot !== shown.players[i].slot);
  const me = differs && view === "sleeper" ? bestLineup(shown, atMs, data.roster_positions, true, gamesOf) : best;   // as-is rows, arrows still to the best
  const seg = me.seg;
  const gridRef = React.useRef(null);
  useEffect(() => {
    if (isMine) { setOther(null); return; }
    const rid = data.matchups[idx]?.[0]?.roster_id;
    api.get(`/leagues/${leagueId}/season/plan` + qs({ week: data.week, roster_id: rid })).then(setOther).catch(() => setOther(null));
  const narrow = useNarrow(), gutter = narrow ? 60 : ARROW_GUTTER;
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
  // the chips' x positions: the same object until the plan or the lane width changes, so the cards can skip re-rendering
  const games = (players) => players.flatMap((r) => (data.players[r.sid]?.games || []).map((g) => [tipMs(g), g.date]));
  const xs = React.useMemo(() => (narrow ? { xs: null } : laneXs([...games(shown?.players || []), ...games(shown?.opponent?.players || [])], lane?.w)),
    [shown, data.players, lane?.w, narrow]);   // eslint-disable-line react-hooks/exhaustive-deps
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
  const irRows = Math.max(L.ir.length, R.ir.length);
  const allRows = L.lines.length + Math.max(L.bench.length, R.bench.length) + irRows;
  // first: the first bench / IR row gets a gap above it: a 5px empty track (with the grid's gaps, 10px more than between rows),
  // so every player row keeps the same height
  const nBench = Math.max(L.bench.length, R.bench.length);
  const tracks = [...Array(L.lines.length).fill("minmax(0, 1fr)"), ...(nBench ? ["5px", ...Array(nBench).fill("minmax(0, 1fr)")] : []),
    ...(irRows ? ["5px", ...Array(irRows).fill("minmax(0, 1fr)")] : [])];
  const row = (l, r, key, slot, first, gr) => (
    <React.Fragment key={key}>
      <div className="mu-cell" style={{ gridRow: gr }}><PlayerCard data={data} r={l?.r} open={open} openGame={openGame} setLock={setLock} mine={isMine} side="left" day={seg?.date} lane={xs} /></div>
      <div className={`mu-slot ${first ? "first" : ""}`} style={{ gridRow: gr }}><PosTag text={slot} /></div>
      <div className="mu-cell" style={{ gridRow: gr }}><PlayerCard data={data} r={r?.r} open={open} openGame={openGame} setLock={setLock} side="right" day={them.seg?.date} lane={xs} /></div>
    </React.Fragment>
  );
  const benchAt = L.lines.length + 2, irAt = benchAt + nBench + (nBench ? 1 : 0);
  return (
    <div className="panel matchup" data-testid="my-week" style={{ "--gut": `${gutter}px` }}>
      {tl?.segments.length > 0 && <Timeline tl={tl} nowMs={nowMs} atMs={atMs} setAt={setAt} view={differs ? view : "best"} setView={setView} differs={differs} />}
      {gap && <div className="small muted mu-gap" data-testid="sleeper-gap">Sleeper still shows the day that just ended: the arrows start from that lineup (the one Sleeper carries into the next day), so skip any move you've already made there.</div>}
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
      <div className="mu-grid with-arrows" ref={gridRef} style={{ gridTemplateRows: tracks.join(" "), ...(irRows && { height: `calc(${allRows / (allRows - irRows)} * (100% + 5px) - 5px)` }) }}>
        <SwapArrows pairs={me.pairs} side="left" names={(sid) => data.players[sid]?.name || sid} />
        <SwapArrows pairs={them.pairs} side="right" names={(sid) => data.players[sid]?.name || sid} />
        {tl && lane && xs.xs?.size > 0 && [["l", lane.l], ["r", lane.r]].filter(([, x]) => x != null).map(([k, x]) => (
          <div key={k} className="time-line" data-testid={`time-line-${k}`} style={{ left: x + laneAt(xs.xs, atMs, Date.parse(tl.start), Date.parse(tl.end), lane.w) - 1 }} />
        ))}
        {L.lines.map((l, i) => row(l, R.lines[i], `s${i}`, l.slot, false, i + 1))}
        {Array.from({ length: nBench }, (_, i) => row(L.bench[i], R.bench[i], `b${i}`, "BN", i === 0, benchAt + i))}
        {Array.from({ length: irRows }, (_, i) => row(L.ir[i], R.ir[i], `i${i}`, "IR", i === 0, irAt + i))}
      </div>
      </div>
    </div>
  );
}

// A team's best lineup at `atMs` from its timeline (one lineup per check-in; locked players never move): rows with
// everyone in the slot he should be in then, and the swaps from its Sleeper lineup as it is right now (so the arrows
// are the moves you'd make in Sleeper from where you are, at any point of the timeline).
// asIs (rivals): rows stay their real Sleeper lineup; the arrows still show the moves to the best one.
const GAME_MS = 135 * 60000;   // a game counts as under way this long after its tip (as the backend's timeline does)
function bestLineup(team, atMs, positions, asIs, games = {}) {
  const tl = team?.timeline, players = team?.players || [];
  const seg = tl?.segments[Math.max(0, tl.segments.findIndex((s) => atMs < Date.parse(s.to)))];
  const seats = seg ? seg.seats : team?.today?.seats;
  if (!seats) return { seg, rows: players, pairs: [] };
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
  return { seg, rows: asIs ? players : rows, pairs: swapSteps(now, after, pos, !asIs) };
}

// The arrows, in a lane beside a team's cards (left of the left team, right of the right team, mirrored by CSS): one
// per Sleeper swap (swapSteps), joining the two players who trade places (a head at both ends), numbered in the order
// to make them and coloured by the starting slot it fills. Measured from the cards on screen; redrawn when the grid
// changes size.
const ARROW_GUTTER = 80;
function SwapArrows({ pairs, side, names, gutter = ARROW_GUTTER }) {
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
  const step = Math.min(13, (gutter - 24) / Math.max(1, lines.length));
  // the steps whose order matters (sharing a player with another step: a chain), numbered 1, 2, ... in step order
  const label = {};
  for (const s of pairs) {
    if (pairs.some((o) => o.n !== s.n && [o.in, o.out].some((x) => x === s.in || x === s.out))) label[s.n] = Object.keys(label).length + 1;
  }
  const end = gutter - 6;   // just left of the cards
  return (
    <svg ref={svgRef} className={`swap-arrows ${side}`} width={gutter} data-testid={`swap-arrows-${side}`}>
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

function Timeline({ tl, nowMs, atMs, setAt, view, setView, differs }) {
  const start = Date.parse(tl.start), end = Date.parse(tl.end);
  const frac = (ms) => Math.min(1, Math.max(0, (ms - start) / (end - start)));
  const at = (ms) => `calc(${frac(ms)} * (100% - 16px) + 8px)`;   // where the 16px dot's centre sits for that time
  const days = Array.from({ length: 7 }, (_, i) => start + i * 86400000 + 12 * 3600000);   // noon of each day
  // the next purple mark still ahead: when to open Sleeper next ("in 1 day, 4 hours")
  const next = tl.segments.slice(0, -1).map((s) => Date.parse(s.to)).find((ms) => ms > nowMs);
  const mins = next ? Math.ceil((next - nowMs) / 60000) : 0;
  const d = Math.floor(mins / 1440), h = Math.floor((mins % 1440) / 60), m = mins % 60;
  const until = d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
  return (
    <div className="timeline" data-testid="timeline">
      <button className="tl-next" onClick={() => setView(view === "best" ? "sleeper" : "best")} disabled={!differs} data-testid="lineup-toggle"
        data-tip={differs ? "Switch between the best lineup and the lineup you have in Sleeper now." : "Your Sleeper lineup is already the best one."}>
        <span className="tl-next-head"><span className="tl-next-label">Current lineup</span></span>
        <strong>{view === "best" ? "Best" : "In Sleeper"}</strong>
      </button>
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
        <span className="tl-next-head"><span className="tl-next-label">Next check-in</span>{next && <span className="tl-next-in">in {until}</span>}</span>
        {!next && <span className="small muted">None left this week</span>}
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
        {n.team && <span className="small muted"><TeamLink abbr={n.team} /></span>}
        {owner && <span className="small muted">· {n.owner}</span>}
        <span className="small muted news-time">{newsTime(n.published)}</span>
      </div>
      <div className="news-title">{title}</div>
      {n.story && <div className="small news-story">{n.story}</div>}
    </div>
  );
}

const LEAGUE_NEWS = 80;   // newest league-wide notes shown (after filtering)

// Beside the news: every NBA team with injured players right now (Sleeper's tags, backend injury_report), most starters
// out first; red counts out / IR, yellow questionable / day-to-day, the names under it (starters bold, first). A team
// opens its Team card on the right, a name its player card.
function TeamsReport({ leagueId, open, refreshKey }) {
  const [r, setR] = useState(null);
  const openTeam = useContext(TeamLinkContext);
  useEffect(() => { api.get(`/leagues/${leagueId}/season/injuries`).then(setR).catch(() => setR({ teams: [], names: {} })); }, [leagueId, refreshKey]);
  return (
    <div className="panel news-teams" data-testid="teams-report">
      <h3>Teams report <span className="small muted">most starters out first</span></h3>
      {!r ? <div className="muted">Loading injuries…</div> : r.teams.map((t, i) => (
        <div key={t.abbr} className="tr-team clickable" onClick={() => openTeam?.(t.abbr)} data-testid={`report-${t.abbr}`}>
          <span className="muted tr-rank">{i + 1}</span>
          <img src={teamLogo(t.abbr)} alt="" width={24} height={24} />
          <div className="tr-body">
            <div className="tr-top"><strong>{r.names[t.abbr] || t.abbr}</strong>
              <span className="tr-counts">
                {t.starters_out > 0 && <span className="health-out">{t.starters_out} starter{t.starters_out > 1 ? "s" : ""} out</span>}
                {t.starters_q > 0 && <span className="health-q">{t.starters_q} starter{t.starters_q > 1 ? "s" : ""} ?</span>}
              </span></div>
            <div className="small tr-names">{t.players.map((h, j) => (
              <span key={h.sid}>{j ? ", " : ""}<span className={`health-${h.group} ${h.starter ? "tr-starter" : ""} ${h.player_id ? "clickable" : ""}`} title={h.starter ? "starter" : undefined}
                onClick={h.player_id ? (e) => { e.stopPropagation(); open(h.player_id); } : undefined}>{h.name}</span></span>))}
              <span className="muted"> · {[t.out && `${t.out} out`, t.q && `${t.q} questionable`].filter(Boolean).join(", ")}</span></div>
          </div>
        </div>
      ))}
    </div>
  );
}

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
    <div className="news-wrap">
    <TeamsReport leagueId={leagueId} open={open} refreshKey={refreshKey} />
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
            <tr key={t.roster_id} className={t.is_user ? "you-need" : ""}><td>{i + 1}</td><td className="clickable" onClick={() => show(t.roster_id)}><TeamName t={t} size={22} record={false} /></td><td className="num">{t.wins}</td><td className="num">{t.losses}</td>
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
  // claims land at the next run (backend next_waiver_run): "Sun 2:00 AM · in 7h 20m"
  const mins = Math.max(0, Math.round((Date.parse(w.next_run) - Date.now()) / 60000));
  const until = mins >= 1440 ? `${Math.floor(mins / 1440)}d ${Math.floor((mins % 1440) / 60)}h` : `${Math.floor(mins / 60)}h ${mins % 60}m`;
  const runDay = fmt(w.next_run, { weekday: "short" });
  const hour = `${w.run_hour % 12 || 12} ${w.run_hour < 12 ? "AM" : "PM"}`;
  return (
    <div className="panel waivers" data-testid="waivers">
      <div className="wv-head">
        <h3>Waiver claims</h3>
        <span className="wv-chip">{faab ? "Blind FAAB" : `${w.type} priority`}</span>
        <span className="wv-chip">Runs {w.runs.join(" & ")} · {hour}</span>
        <span className="wv-next" data-testid="waiver-next">Next run <strong>{runDay} {timeOf(w.next_run)}</strong> <span className="muted">in {until}</span></span>
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
            <th data-tip="Value over your drop candidate.">Upgrade</th>
            <th className="num" data-tip={`A claim lands at the next run (${runDay} ${timeOf(w.next_run)}): his games from then, the rest of this week and next week.`}>Games once he lands</th>
            <th className="num" data-tip="A guide: your FAAB left paced over the weeks left, scaled by the upgrade and by how much more he scores than your drop (under 25 % more: min bid), never over a quarter of what's left. Other bids are hidden.">Bid</th></tr></thead>
          <tbody>{w.claims.map((c) => (
            <tr key={c.player_id} className="clickable" onClick={() => onSelect(c.player_id)}>
              <td><div className="wv-player"><Headshot sleeperId={c.sleeper_id} name={c.name} size={44} />
                <div><strong>{c.name}</strong><InjuryTag tag={c.injury_tag} /><div className="small muted"><TeamLink abbr={c.team} /> · <PosList list={c.pos} /></div>
                  {/* his season so far, per game (finished games, league scoring) */}
                  <div className="wv-stats" data-testid="waiver-stats">{c.season ? <>
                    <span className="wv-fp">{c.season.fp.toFixed(2)} FP/G</span>
                    {[["pts", "PTS"], ["reb", "REB"], ["ast", "AST"], ["stl", "STL"], ["blk", "BLK"], ["tpm", "3PM"]].map(([k, l]) => <span key={k}><strong>{c.season[k]}</strong> {l}</span>)}
                    <span className="muted">{c.season.gp} GP</span>
                  </> : <span className="muted">No games played yet</span>}</div>
                </div></div></td>
              <td className="num">{c.value.toFixed(2)}</td>
              <td><div className="wv-up"><span className="wv-bar"><span style={{ width: `${(c.upgrade / top) * 100}%` }} /></span><span className="ok">+{c.upgrade.toFixed(2)}</span></div></td>
              <td className="num"><strong>{c.games_left}</strong> <span className="muted">this wk</span> · <strong>{c.games_next}</strong> <span className="muted">next</span></td>
              <td className="num">{c.bid != null ? <span className="wv-bid">${c.bid}</span> : <span className="muted">-</span>}</td></tr>))}</tbody>
        </table>
      ) : <div className="muted">No free agent is an upgrade over your weakest player.</div>}
    </div>
  );
}
