import React, { useEffect, useMemo, useState } from "react";
import HomePage from "../core/HomePage.jsx";
import DraftPage from "../draft/DraftPage.jsx";
import Headshot from "../core/Headshot.jsx";
import Icon from "../core/Icon.jsx";
import DragScroll from "../core/DragScroll.jsx";
import InjuryTag, { isDoubt, isOut } from "../core/InjuryTag.jsx";
import { PosList, PosTag } from "../core/Pos.jsx";
import { TipLayer } from "../core/Terms.jsx";
import { TeamLinkContext } from "../core/TeamLink.jsx";
import { SEASON_VIEWS, SettingsModal, TABS, useAppState } from "../core/Shell.jsx";
import useSeason from "../lockin/useSeason.js";
import { CardNav, CurrentCard, SeasonTools, WeekNav, callsOf, nextCheckIn, nowOf, slate } from "../lockin/seasonBits.jsx";
import { LeagueView, LockIcon, LockinGuide, NewsView, WaiversView, bestLineup, bySlot, dayName, fp, pct, quarters, shortQuarter, teamLogo, untilText } from "../lockin/SeasonPage.jsx";
import { fmt, timeOf } from "../lockin/tz.js";

// Broadcast (Settings > UI): game night on TV. A scoreboard band on top, a ticker of tonight's games, the week as a grid
// of roster spots by day (one cell per game: points, projection, live state, lock), the analysis desk (Week Stats) on the
// right and a chyron of calls along the bottom. Player / team / game cards open as a sheet over the page.

/** "2026-10-20" -> "10/20". */
const md = (d) => d.slice(5).replace("-", "/");
/** "Mon 7:30 PM" for the next check-in. */
const whenText = (ms) => fmt(ms, { weekday: "short", hour: "numeric", minute: "2-digit" });

/** Root of the Broadcast UI: the network bar (league, tabs, settings) and the open page. */
export default function App() {
  const app = useAppState();
  const { tab, setTab, leagueId, health } = app;
  return (
    <>
      <header className="bc-top">
        <button className="bc-brand" onClick={() => setTab("home")} data-testid="home"><span className="bc-logo"><Icon name="ball" /></span><span>{app.leagueName || "NBA Fantasy Tool"}</span></button>
        <nav className="bc-nav">
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`tab-${id}`}>{id === "season" ? "Week" : label}</button>
          ))}
        </nav>
        <span className="bc-top-gap" />
        {health && !health.ok && <span className="small warn-text" data-testid="health">API unreachable</span>}
        <button className={`bc-cog icon-btn ${app.settingsOpen ? "active" : ""}`} onClick={() => app.setSettingsOpen(true)} data-testid="tab-settings" aria-label="Settings"><Icon name="settings" /></button>
      </header>
      <main className="bc-main">
        {tab === "home" && <HomePage setLeagueId={app.setLeagueId} setTab={app.goTab} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {SEASON_VIEWS[tab] && <BroadcastSeason leagueId={leagueId} view={SEASON_VIEWS[tab]} />}
      </main>
      <SettingsModal app={app} />
      <TipLayer />
    </>
  );
}

/** The Season side of Broadcast: score bug (Week), the games ticker with search and Sync, then the view; cards open in a sheet. */
function BroadcastSeason({ leagueId, view }) {
  const s = useSeason(leagueId);
  useEffect(() => {
    if (!s.cur) return undefined;
    /** Escape closes the sheet. */
    const k = (e) => e.key === "Escape" && s.close();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  });
  if (!leagueId) return <div className="panel muted" data-testid="no-league">No Sleeper league selected! Pick one in Settings.</div>;
  if (s.error && !s.data) return <div className="panel error">{s.error}</div>;
  if (!s.data || !s.plan) return <div className="panel">Loading the week from Sleeper…</div>;
  const { data, plan } = s;
  return (
    <TeamLinkContext.Provider value={s.openTeam}>
      <div className={`bc-season bc-view-${view}`}>
        {view === "week" && <ScoreBug s={s} />}
        <div className="bc-strip">
          <Ticker data={data} s={s} />
          {view === "league" && <WeekNav s={s} />}
          {s.error && <span className="small warn-text">{s.error}</span>}
          <SeasonTools s={s} leagueId={leagueId} />
        </div>
        {view === "week" && (
          <div className="bc-desk">
            <Matrix data={data} plan={plan} s={s} />
            <aside className="bc-analysis"><LockinGuide data={data} plan={plan} leagueId={leagueId} setLock={s.setLock} open={s.open} /></aside>
          </div>
        )}
        {view === "news" && <div className="bc-fill"><NewsView leagueId={leagueId} open={s.openPid} refreshKey={s.tick} /></div>}
        {view === "league" && <div className="bc-body"><LeagueView data={data} leagueId={leagueId} open={s.open} /></div>}
        {view === "waivers" && <div className="bc-body"><WaiversView leagueId={leagueId} onSelect={s.openPid} /></div>}
      </div>
      {view === "week" && <Chyron data={data} plan={plan} s={s} />}
      {s.cur && (
        <div className="bc-sheet-wrap" onMouseDown={(e) => e.target === e.currentTarget && s.close()}>
          <div className="bc-sheet" data-testid="card-sheet">
            <CardNav s={s} />
            <CurrentCard s={s} leagueId={leagueId} />
          </div>
        </div>
      )}
    </TeamLinkContext.Provider>
  );
}

/** The scoreboard band: both teams' banked points and projections either side of the week, the win-chance bar and the next check-in. */
function ScoreBug({ s }) {
  const { data, plan } = s;
  const o = plan.opponent, nowMs = nowOf(data), next = nextCheckIn(plan, nowMs);
  /** One team's end of the bug (`right`: the opponent's, mirrored). */
  const side = (t, right) => (
    <div className={`bc-bug-team ${right ? "right" : "me"}`}>
      {t?.avatar && <img className="bc-bug-avatar" src={t.avatar} alt="" width={52} height={52} onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />}
      <div className="bc-bug-name">
        <strong>{t ? t.name : "No opponent"}</strong>
        {t && <span>{t.user && t.user !== t.name ? `${t.user} · ` : ""}{t.wins}-{t.losses} · {t.games_left} games left</span>}
      </div>
      <div className="bc-bug-score"><strong>{t ? fp(t.points) : "—"}</strong><span>proj {t ? Math.round(t.expected) : "—"}</span></div>
    </div>
  );
  return (
    <div className="bc-bug" data-testid="score-bug">
      {side(plan)}
      <div className="bc-bug-mid">
        <WeekNav s={s} />
        <div className="bc-winbar" title="Win chance"><span style={{ width: pct(plan.win_chance) }} /></div>
        <div className="bc-win-nums"><strong>{pct(plan.win_chance)}</strong><span>win chance</span><strong>{pct(1 - (plan.win_chance ?? 0))}</strong></div>
        <div className="bc-next">{next ? <>Next check-in <strong>{whenText(next)}</strong> · in {untilText(Math.ceil((next - nowMs) / 60000))}</> : "No check-ins left this week"}</div>
      </div>
      {side(o, true)}
    </div>
  );
}

/** Tonight's games (the league's players' games, yours counted) as a ticker; a click opens the game card. */
function Ticker({ data, s }) {
  const { date, list } = slate(data);
  return (
    <div className="bc-ticker" data-testid="ticker">
      <span className="bc-ticker-label">{date === data.today ? "Tonight" : dayName(date)}</span>
      <DragScroll className="bc-ticker-list">
        {list.map((g) => (
          <button key={g.event} className={`bc-tick ${g.state}`} onClick={() => s.openGame(g.sel)}>
            {[[g.away, g.awayScore], [g.home, g.homeScore]].map(([abbr, pts]) => (
              <span key={abbr} className="bc-tick-row"><img src={teamLogo(abbr)} alt="" width={16} height={16} />{abbr}<b>{pts ?? ""}</b></span>
            ))}
            <span className="bc-tick-st">{g.state === "in" ? quarters(g.detail) : g.state === "post" ? "Final" : timeOf(g.tip)}{g.mine > 0 && <em>{g.mine} yours</em>}</span>
          </button>
        ))}
        {!list.length && <span className="small muted">No games left this week.</span>}
      </DragScroll>
    </div>
  );
}

/**
 * The week as a grid: a row per roster spot (your best lineup now, or the opponent's Sleeper lineup), a column per day,
 * one cell per game. A cell shows the opponent, the points (or, before / during the game, the projection or live pace) and
 * the status; a locked game is filled, a game that can't count any more is struck out (the same rules as the lineup
 * grid's game chips). On your rows the corner padlock locks a final game or unlocks the locked one; ⇄ marks a player the
 * best lineup moves (his Sleeper slot → the slot he should be in).
 */
function Matrix({ data, plan, s }) {
  const [side, setSide] = useState("me");
  const gamesOf = useMemo(() => Object.fromEntries(Object.entries(data.players).map(([sid, p]) => [sid, p.games])), [data.players]);
  const mine = side === "me" || !plan.opponent;
  const team = mine ? plan : plan.opponent;
  const { rows } = bestLineup(team, nowOf(data), data.roster_positions, !mine, gamesOf);
  const from = Object.fromEntries(team.players.map((r) => [r.sid, r.slot]));
  const { lines, bench, ir } = bySlot(rows, data.roster_positions, data.reserve_slots);
  const cols = data.dates.length + 3;
  return (
    <section className="panel bc-matrix-wrap" data-testid="lineup-matrix">
      <div className="bc-matrix-head">
        <div className="bc-seg">
          <button className={mine ? "active" : ""} onClick={() => setSide("me")}>Your lineup</button>
          {plan.opponent && <button className={mine ? "" : "active"} onClick={() => setSide("opp")} data-testid="matrix-opp">{plan.opponent.user || plan.opponent.name}</button>}
        </div>
        <span className="small muted">{mine ? "Best lineup right now. Click a game for its box score." : "Their lineup in Sleeper now."}</span>
      </div>
      <div className="bc-matrix-scroll">
        <table className="bc-matrix">
          <thead><tr>
            <th className="bc-slot-h">Slot</th><th className="bc-player-h">Player</th>
            {data.dates.map((d) => <th key={d} className={`bc-day ${d === data.today ? "today" : ""}`}>{dayName(d)}<span>{md(d)}</span></th>)}
            <th className="bc-week-h">Week</th>
          </tr></thead>
          {[["", lines], ["Bench", bench], ["IR", ir]].filter(([, l]) => l.length).map(([label, list]) => (
            <tbody key={label || "starters"}>
              {label && <tr className="bc-sep"><td colSpan={cols}>{label}</td></tr>}
              {list.map((line, i) => <MatrixRow key={line.r?.sid || `${label}${i}`} data={data} line={line} from={from[line.r?.sid]} mine={mine} s={s} />)}
            </tbody>
          ))}
        </table>
      </div>
    </section>
  );
}

/** One roster spot in the Matrix: slot, player, a cell per day, and his week (the locked score, else what his games are worth). */
function MatrixRow({ data, line, from, mine, s }) {
  const r = line.r;
  if (!r) return <tr className="bc-row empty"><td className="bc-slot"><PosTag text={line.slot} /></td><td className="small muted" colSpan={data.dates.length + 2}>empty</td></tr>;
  const p = data.players[r.sid] || { games: [] };
  const locked = r.lock_status === "locked" || r.lock_status === "guess";
  const lockDate = locked ? r.lock_date : null, benched = line.slot === "BN" || line.slot === "IR";
  const moved = mine && from && from !== line.slot;
  const games = p.games || [];
  return (
    <tr className={`bc-row ${benched ? "bench" : ""} ${locked ? "done" : ""} ${isOut(p.injury_tag) ? "out" : isDoubt(p.injury_tag) ? "doubt" : ""}`} data-testid={`mu-${r.sid}`}>
      <td className="bc-slot"><PosTag text={line.slot} /></td>
      <td className="bc-player">
        <span className="bc-who clickable" onClick={() => s.open(r.sid)} data-testid={`open-${r.sid}`}>
          <Headshot sleeperId={r.sid} name={r.name} size={30} />
          <span className="bc-who-lines">
            <span className="bc-name">{r.name}<InjuryTag tag={p.injury_tag} note={p.injury_note} /></span>
            <span className="small muted">{p.team || "FA"} <PosList list={r.pos} />{moved && <span className="bc-move" title="Move him in Sleeper"><Icon name="swap" /> {from} → {line.slot}</span>}</span>
          </span>
        </span>
      </td>
      {data.dates.map((d) => {
        const i = games.findIndex((g) => g.date === d);
        if (i < 0) return <td key={d} className={`bc-cell none ${d === data.today ? "today" : ""}`} />;
        const g = games[i];
        // the same rules as SeasonPage's GameChips
        const played = g.fp != null, live = g.state === "in" || (played && g.state !== "post");
        const later = games.slice(i + 1).some((x) => x.state !== "pre" || x.fp != null);
        const dead = lockDate ? g.date !== lockDate : (g.state === "post" && (later || r.x == null)) || (live && benched);
        const toggle = !mine ? null : lockDate === g.date ? "" : g.state === "post" && played && !dead ? g.date : null;
        const exp = live && g.pace != null ? g.pace : g.proj;
        return (
          <td key={d} className={`bc-cell ${live ? "live" : ""} ${played ? "played" : ""} ${lockDate === g.date ? "locked" : ""} ${dead ? "dead" : ""} ${d === data.today ? "today" : ""}`}
            onClick={g.event ? () => s.openGame({ game: g, team: p.team, sid: r.sid, name: r.name }) : undefined}
            title={`${p.team} ${g.home ? "vs" : "@"} ${g.opp}${g.score != null ? ` · ${g.score}-${g.opp_score}` : ""}${g.b2b && g.state === "pre" ? " · back-to-back" : ""}${exp != null ? ` · proj ${fp(exp)}` : ""}`}>
            <span className="bc-opp">{g.home ? "vs" : "@"} {g.opp}</span>
            <span className={`bc-fp ${played ? "" : "proj"}`}>{played ? fp(g.fp) : exp != null ? fp(exp) : "—"}</span>
            <span className="bc-st">{live ? shortQuarter(g.detail) : g.state === "post" ? "Final" : timeOf(g.tip)}</span>
            {toggle != null ? (
              <button className="bc-lockbtn" onClick={(e) => { e.stopPropagation(); s.setLock(r.sid, toggle); }} aria-label={toggle === "" ? "Unlock" : "Lock"}
                data-testid={toggle === "" ? "unlock-game" : "lock-game"}><LockIcon open={toggle !== ""} /></button>
            ) : lockDate === g.date && <span className="bc-lockbtn static"><LockIcon /></span>}
          </td>
        );
      })}
      <td className="bc-week">{locked ? <><strong>{fp(r.locked)}</strong><span>locked{r.lock_status === "guess" ? "?" : ""}</span></>
        : r.w != null ? <><strong className="proj">~{fp(r.w)}</strong><span>worth</span></> : <span>—</span>}</td>
    </tr>
  );
}

/** The bottom chyron: every call (callsOf) in a row; a click opens the player. */
function Chyron({ data, plan, s }) {
  const calls = callsOf(data, plan), nowMs = nowOf(data), next = nextCheckIn(plan, nowMs);
  return (
    <div className={`bc-chyron ${calls.length ? "hot" : ""}`} data-testid="calls">
      <span className="bc-chyron-label">{calls.length ? `Calls · ${calls.length}` : "All set"}</span>
      <div className="bc-chyron-list">
        {calls.length ? calls.map((c) => (
          <button key={c.key} className={`bc-call ${c.tone}`} onClick={c.sid ? () => s.open(c.sid) : undefined} title={c.text} data-testid="watch-line">
            <strong>{!c.when || c.when === "now" ? "Now" : timeOf(c.when)}</strong>{c.title}
          </button>
        )) : <span className="muted">No moves needed{next ? ` until the next check-in, ${whenText(next)}` : " for the rest of the week"}.</span>}
      </div>
    </div>
  );
}
