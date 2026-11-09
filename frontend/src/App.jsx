import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import DataPage from "./core/DataPage.jsx";
import HomePage from "./core/HomePage.jsx";
import LeaguePage from "./core/LeaguePage.jsx";
import SettingsPage from "./core/SettingsPage.jsx";
import DraftPage from "./draft/DraftPage.jsx";
import SeasonPage from "./lockin/SeasonPage.jsx";
import { TipLayer } from "./core/Terms.jsx";

const TABS = [
  ["season", "Season"],
  ["standings", "League"],
  ["news", "News"],
  ["waivers", "Waivers"],
  ["draft", "Draft"],
];
const TAB_COLORS = { season: "#3b82f6", news: "#f59e0b", standings: "#10b981", waivers: "#ec4899", draft: "#a855f7" };   // each tab's own hue (see header.top nav button in styles.css)
const SEASON_VIEWS = { season: "week", news: "news", standings: "league", waivers: "waivers" };

// pixelated photos behind the page (public/wallpapers, made by backgroundimages/pixelate.py)
const THEMES = [["", "Indigo (default)"], ["ocean", "Ocean"], ["sunset", "Sunset"]];   // accent colour presets, see styles.css

const WALLPAPERS = [
  ["", "No wallpaper"],
  ["kawhi-dagger", "Kawhi dagger"],
  ["wemby-block", "Wemby block"],
  ["lin-calderon", "Lin over Calderón"],
  ["haliburton-msg", "Haliburton at MSG"],
  ["curry-okc", "Curry from deep"],
  ["lebron-block", "LeBron chase-down block"],
  ["lebron-chalk", "LeBron chalk toss"],
];

/**
 * Root component: the header (tabs, settings cog) and the page for the open tab (Home, Settings, Draft or a Season view).
 * Persists the tab, league, theme and wallpaper in localStorage and polls /health every 15 s.
 */
export default function App() {
  const [tab, setTab] = useState(() => {
    const t = localStorage.getItem("da.tab");
    return !t || ["settings", "data", "league"].includes(t) ? "home" : t;   // Settings is a popup now, not a tab
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  /** Switch tab; "settings" opens the settings popup instead. */
  const goTab = (t) => (t === "settings" ? setSettingsOpen(true) : setTab(t));
  useEffect(() => {
    if (!settingsOpen) return undefined;
    /** Close the popup on Escape. */
    const k = (e) => e.key === "Escape" && setSettingsOpen(false);
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [settingsOpen]);
  const [leagueId, setLeagueIdState] = useState(() => localStorage.getItem("da.league") || "");
  const [wall, setWall] = useState(() => { const w = localStorage.getItem("da.wall") || ""; return WALLPAPERS.some(([id]) => id === w) ? w : ""; });
  const [theme, setTheme] = useState(() => localStorage.getItem("da.theme") || "");
  const [health, setHealth] = useState(null);

  /** Select a league (a falsy id clears it) and remember the choice in localStorage. */
  const setLeagueId = useCallback((id) => {
    setLeagueIdState(id || "");
    if (id) localStorage.setItem("da.league", id);
    else localStorage.removeItem("da.league");
  }, []);

  useEffect(() => {
    localStorage.setItem("da.tab", tab);
  }, [tab]);

  // the header shows the chosen league's name (re-read on tab change, so a Sleeper rename picked up by Sync shows up)
  const [leagueName, setLeagueName] = useState("");
  useEffect(() => {
    if (!leagueId) return setLeagueName("");
    api.get("/leagues").then((ls) => setLeagueName(ls.find((l) => l.league_id === leagueId)?.name || "")).catch(() => {});
  }, [leagueId, tab]);

  useEffect(() => {
    document.documentElement.style.setProperty("--wall", wall ? `url(/wallpapers/${wall}.png)` : "none");
    localStorage.setItem("da.wall", wall);
  }, [wall]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("da.theme", theme);
  }, [theme]);

  /** Fetch /health into state; an unreachable API is recorded as { ok: false }. */
  const refreshHealth = useCallback(() => {
    api.get("/health").then(setHealth).catch(() => setHealth({ ok: false }));
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 15000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  return (
    <>
      <header className="top">
        <span className="brand" onClick={() => setTab("home")} title="Home" data-testid="home"><span className="logo">🏀</span>{leagueName || "NBA Fantasy Tool"}</span>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} style={{ "--c": TAB_COLORS[id] }} data-testid={`tab-${id}`}>
              {label}
            </button>
          ))}
        </nav>
        <div id="header-slot" className="header-slot" />   {/* pages can put their own bar here (Season: week bar) */}
        {health && !health.ok && <span className="meta"><span className="small warn-text" data-testid="health">API unreachable</span></span>}
        <button className={`cog ${settingsOpen ? "active" : ""}`} onClick={() => setSettingsOpen(true)} data-testid="tab-settings" aria-label="Settings" title="Settings">⚙&#xFE0E;</button>
      </header>
      <main>
        {tab === "home" && <HomePage setLeagueId={setLeagueId} setTab={goTab} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {SEASON_VIEWS[tab] && <SeasonPage leagueId={leagueId} view={SEASON_VIEWS[tab]} />}
      </main>
      {settingsOpen && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setSettingsOpen(false)} data-testid="settings-modal">
          <div className="modal settings-modal">
            <button className="small settings-close" onClick={() => setSettingsOpen(false)} aria-label="Close settings" data-testid="settings-close">✕</button>
          <div className="panel section-card" data-testid="section-appearance"><h2>Appearance</h2>
          <div className="panel wall-pick"><h3>Theme</h3>
            <select value={theme} onChange={(e) => setTheme(e.target.value)} data-testid="theme">
              {THEMES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </div>
          <div className="panel wall-pick"><h3>Wallpaper</h3>
            <select value={wall} onChange={(e) => setWall(e.target.value)} data-testid="wallpaper">
              {WALLPAPERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </div>
          </div>
          <div className="panel section-card" data-testid="section-league"><h2>League</h2>
            <LeaguePage leagueId={leagueId} setLeagueId={setLeagueId} />
            {leagueId && <SettingsPage leagueId={leagueId} />}
            <DataPage onPoolChanged={refreshHealth} />
          </div>
          </div>
        </div>
      )}
      <TipLayer />
    </>
  );
}
