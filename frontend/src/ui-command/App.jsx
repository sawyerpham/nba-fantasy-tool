import React, { useEffect, useState } from "react";
import HomePage from "../core/HomePage.jsx";
import DraftPage from "../draft/DraftPage.jsx";
import Headshot from "../core/Headshot.jsx";
import Icon from "../core/Icon.jsx";
import { TipLayer } from "../core/Terms.jsx";
import { TeamLinkContext } from "../core/TeamLink.jsx";
import { SEASON_VIEWS, SettingsModal, useAppState } from "../core/Shell.jsx";
import useSeason from "../lockin/useSeason.js";
import { CardNav, CurrentCard, SeasonTools, WeekNav, callsOf, nextCheckIn, nowOf, slate } from "../lockin/seasonBits.jsx";
import { LeagueView, LockinGuide, NewsView, WaiversView, WeekView, dayName, fp, pct, quarters, untilText } from "../lockin/SeasonPage.jsx";
import { fmt, timeOf } from "../lockin/tz.js";

// Command Center (Settings > UI): decisions first. An icon rail replaces the header; the Season tab opens on what needs you
// now (the calls list), with the lineup grid under it and the week's numbers on the right; player / team / game cards
// slide in over the right column instead of replacing it.

const RAIL = [["season", "calendar", "Today"], ["standings", "trophy", "League"], ["news", "news", "News"], ["waivers", "user-plus", "Waivers"], ["draft", "gavel", "Draft"]];
const TITLES = { week: "Today", league: "League", news: "News", waivers: "Waivers" };
const CALL_ICON = { swap: "swap", gtd: "alert", out: "alert", lock: "lock", alert: "alert" };

/** Root of the Command Center UI: the icon rail and the open page. */
export default function App() {
  const app = useAppState();
  const { tab, setTab, leagueId, health } = app;
  return (
    <div className="cc">
      <aside className="cc-rail">
        <button className={`cc-logo ${tab === "home" ? "active" : ""}`} onClick={() => setTab("home")} data-testid="home" aria-label="Home"><Icon name="ball" /></button>
        {RAIL.map(([id, icon, label]) => (
          <button key={id} className={`cc-rail-btn ${tab === id ? "active" : ""}`} onClick={() => setTab(id)} data-testid={`tab-${id}`}>
            <Icon name={icon} /><span>{label}</span>
          </button>
        ))}
        <span className="cc-rail-gap" />
        {health && !health.ok && <span className="cc-health warn-text" data-testid="health"><Icon name="alert" /><span>API down</span></span>}
        <button className={`cc-rail-btn ${app.settingsOpen ? "active" : ""}`} onClick={() => app.setSettingsOpen(true)} data-testid="tab-settings">
          <Icon name="settings" /><span>Settings</span>
        </button>
      </aside>
      <main className="cc-main">
        {tab === "home" && <HomePage setLeagueId={app.setLeagueId} setTab={app.goTab} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {SEASON_VIEWS[tab] && <CommandSeason leagueId={leagueId} leagueName={app.leagueName} view={SEASON_VIEWS[tab]} onWeek={() => setTab("season")} />}
      </main>
      <SettingsModal app={app} />
      <TipLayer />
    </div>
  );
}

/** The Season side of Command Center: a title bar (week, search, sync), then the view; cards open in a drawer. */
function CommandSeason({ leagueId, leagueName, view, onWeek }) {
  const s = useSeason(leagueId, onWeek);
  const [focusRid, setFocusRid] = useState(null);   // the matchup on the lineup grid: Week Stats follows it
  useEffect(() => {
    if (!s.cur) return undefined;
    /** Escape closes the drawer. */
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
      <div className={`cc-page cc-view-${view}`}>
        <div className="cc-top">
          <h1 className="cc-title">{TITLES[view]}<span className="cc-sub">{leagueName}</span></h1>
          {(view === "week" || view === "league") && <WeekNav s={s} />}
          {s.error && <span className="small warn-text">{s.error}</span>}
          <SeasonTools s={s} leagueId={leagueId} />
        </div>
        {view === "week" && (
          <div className="cc-week">
            <section className="cc-center">
              <StatusTiles data={data} plan={plan} />
              <div className="cc-pair">
                <Calls data={data} plan={plan} s={s} />
                <Slate data={data} s={s} />
              </div>
              <WeekView key={data.week} data={data} plan={plan} open={s.open} openGame={s.openGame} setLock={s.setLock} leagueId={leagueId} onShow={setFocusRid} focus={s.matchup} />
            </section>
            <aside className="cc-side"><LockinGuide data={data} plan={plan} leagueId={leagueId} setLock={s.setLock} open={s.open} focus={focusRid} /></aside>
          </div>
        )}
        {view === "news" && <div className="cc-fill"><NewsView leagueId={leagueId} open={s.openPid} refreshKey={s.tick} /></div>}
        {view === "league" && <div className="cc-scroll"><LeagueView data={data} leagueId={leagueId} open={s.open} openPid={s.openPid} openGame={s.openGame} /></div>}
        {view === "waivers" && <div className="cc-scroll"><WaiversView leagueId={leagueId} onSelect={s.openPid} /></div>}
      </div>
      {s.cur && (
        <div className="cc-drawer-wrap" onMouseDown={(e) => e.target === e.currentTarget && s.close()}>
          <div className="cc-drawer" data-testid="card-drawer">
            <CardNav s={s} />
            <CurrentCard s={s} leagueId={leagueId} />
          </div>
        </div>
      )}
    </TeamLinkContext.Provider>
  );
}

/** The four numbers that say where the week stands: win chance, projected finals, the next check-in and how many calls are open. */
function StatusTiles({ data, plan }) {
  const nowMs = nowOf(data), next = nextCheckIn(plan, nowMs), o = plan.opponent;
  const calls = callsOf(data, plan).length;
  return (
    <div className="cc-tiles" data-testid="status-tiles">
      <div className="cc-tile">
        <span className="cc-tile-label">Win chance</span>
        <strong className="cc-tile-num">{pct(plan.win_chance)}</strong>
        <span className="cc-meter"><span style={{ width: pct(plan.win_chance) }} /></span>
      </div>
      <div className="cc-tile">
        <span className="cc-tile-label">Projected</span>
        <strong className="cc-tile-num">{Math.round(plan.expected)}<span className="cc-vs"> – {o ? Math.round(o.expected) : "—"}</span></strong>
        <span className="small muted">banked {fp(plan.points)} · {plan.games_left} games left</span>
      </div>
      <div className="cc-tile">
        <span className="cc-tile-label">Next check-in</span>
        <strong className="cc-tile-num">{next ? fmt(next, { weekday: "short", hour: "numeric", minute: "2-digit" }) : "None"}</strong>
        <span className="small muted">{next ? `in ${untilText(Math.ceil((next - nowMs) / 60000))}` : "no lineup changes left this week"}</span>
      </div>
      <div className={`cc-tile ${calls ? "hot" : ""}`}>
        <span className="cc-tile-label">Calls</span>
        <strong className="cc-tile-num">{calls}</strong>
        <span className="small muted">{calls ? "need you now" : "all set"}</span>
      </div>
    </div>
  );
}

/** "Do now": every call (callsOf) as a row with its time, headline and the players to open. */
function Calls({ data, plan, s }) {
  const calls = callsOf(data, plan);
  return (
    <section className="panel cc-calls" data-testid="calls">
      <h3>Do now</h3>
      {!calls.length && <div className="cc-empty"><Icon name="check" /> Nothing to do. Your lineup is set until the next check-in.</div>}
      {calls.map((c) => (
        <div key={c.key} className={`cc-call ${c.tone}`} data-testid="watch-line">
          <span className="cc-call-icon"><Icon name={CALL_ICON[c.kind] || "alert"} /></span>
          <span className="cc-call-when">{!c.when || c.when === "now" ? "Now" : timeOf(c.when)}</span>
          <span className="cc-call-body"><strong>{c.title}</strong>{c.text && <span className="small muted">{c.text}</span>}</span>
          <span className="cc-call-who">{[c.sid, c.sid2].filter(Boolean).map((sid) => (
            <button key={sid} className="cc-head-btn" onClick={() => s.open(sid)} title={data.players[sid]?.name}><Headshot sleeperId={sid} name={data.players[sid]?.name || ""} size={28} /></button>
          ))}</span>
        </div>
      ))}
    </section>
  );
}

/** Today's NBA games that involve the league's players (yours counted); a click opens the game card. */
function Slate({ data, s }) {
  const { date, list } = slate(data);
  return (
    <section className="panel cc-slate" data-testid="slate">
      <h3>{date === data.today ? "Tonight" : dayName(date)} <span className="small muted">{list.length} games</span></h3>
      <div className="cc-slate-list">
        {list.map((g) => (
          <button key={g.event} className={`cc-game ${g.state}`} onClick={() => s.openGame(g.sel)}>
            <span className="cc-game-teams"><span>{g.away}</span><b>{g.awayScore ?? ""}</b><span>{g.home}</span><b>{g.homeScore ?? ""}</b></span>
            <span className="cc-game-status">{g.state === "in" ? <><i className="live-dot" />{quarters(g.detail)}</> : g.state === "post" ? "Final" : timeOf(g.tip)}</span>
            {g.mine > 0 && <span className="cc-game-mine">{g.mine} yours</span>}
          </button>
        ))}
        {!list.length && <div className="small muted">No games left this week.</div>}
      </div>
    </section>
  );
}
