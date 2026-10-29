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
  ["season", "Season"],      // these are SeasonPage's views (Settings is the cogwheel at the top right)
  ["news", "News"],
  ["standings", "League"],
  ["waivers", "Waivers"],
];
const TAB_COLORS = { season: "#3b82f6", news: "#f59e0b", standings: "#10b981", waivers: "#ec4899" };   // each tab's own hue (see header.top nav button in styles.css)
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

export default function App() {
  const [tab, setTab] = useState(() => {
    const t = localStorage.getItem("da.tab");
    return !t ? "home" : t === "data" || t === "league" ? "settings" : t;   // Data and the old League tab now live on Settings
  });
  const [leagueId, setLeagueIdState] = useState(() => localStorage.getItem("da.league") || "");
  const [wall, setWall] = useState(() => { const w = localStorage.getItem("da.wall") || ""; return WALLPAPERS.some(([id]) => id === w) ? w : ""; });
  const [theme, setTheme] = useState(() => localStorage.getItem("da.theme") || "");
  const [health, setHealth] = useState(null);

  const setLeagueId = useCallback((id) => {
    setLeagueIdState(id || "");
    if (id) localStorage.setItem("da.league", id);
    else localStorage.removeItem("da.league");
  }, []);

  useEffect(() => {
    localStorage.setItem("da.tab", tab);
  }, [tab]);

  useEffect(() => {
    document.documentElement.style.setProperty("--wall", wall ? `url(/wallpapers/${wall}.png)` : "none");
    localStorage.setItem("da.wall", wall);
  }, [wall]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("da.theme", theme);
  }, [theme]);

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
        <span className="brand" onClick={() => setTab("home")} title="Home" data-testid="home"><span className="logo">🏀</span>NBA Fantasy Tool</span>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} style={{ "--c": TAB_COLORS[id] }} data-testid={`tab-${id}`}>
              {label}
            </button>
          ))}
        </nav>
        <div id="header-slot" className="header-slot" />   {/* pages can put their own bar here (Season: week bar) */}
        {health && !health.ok && <span className="meta"><span className="small warn-text" data-testid="health">API unreachable</span></span>}
        {/* the league's managers, keepers, settings, data pull and wallpaper */}
        <button className={`cog ${tab === "settings" ? "active" : ""}`} onClick={() => setTab("settings")} data-testid="tab-settings" aria-label="Settings" title="Settings">⚙&#xFE0E;</button>
      </header>
      <main>
        {tab === "home" && <HomePage setLeagueId={setLeagueId} setTab={setTab} />}
        {tab === "settings" && <>
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
        </>}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {SEASON_VIEWS[tab] && <SeasonPage leagueId={leagueId} view={SEASON_VIEWS[tab]} />}
      </main>
      <TipLayer />
    </>
  );
}
