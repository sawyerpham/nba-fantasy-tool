import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import DataPage from "./core/DataPage.jsx";
import LeaguePage from "./core/LeaguePage.jsx";
import SettingsPage from "./core/SettingsPage.jsx";
import DraftPage from "./draft/DraftPage.jsx";
import SeasonPage from "./lockin/SeasonPage.jsx";
import { TipLayer } from "./core/Terms.jsx";

const TABS = [
  ["league", "League"],
  ["settings", "Settings"],
  ["draft", "Draft"],
  ["season", "Season"],
];

// pixelated photos behind the page (public/wallpapers, made by backgroundimages/pixelate.py)
const WALLPAPERS = [
  ["", "No wallpaper"],
  ["kawhi-dagger", "Kawhi dagger"],
  ["wemby-block", "Wemby block"],
  ["wemby-spurs", "Wemby"],
  ["lebron-ft", "LeBron"],
];

export default function App() {
  const [tab, setTab] = useState(() => {
    const t = localStorage.getItem("da.tab");
    return !t || t === "data" ? "settings" : t;   // the Data tab now lives at the top of Settings
  });
  const [leagueId, setLeagueIdState] = useState(() => localStorage.getItem("da.league") || "");
  const [theme, setTheme] = useState(() => localStorage.getItem("da.theme") || "dark");
  const [wall, setWall] = useState(() => localStorage.getItem("da.wall") || "");
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
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("da.theme", theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.style.setProperty("--wall", wall ? `url(/wallpapers/${wall}.png)` : "none");
    localStorage.setItem("da.wall", wall);
  }, [wall]);

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
        <span className="brand" onClick={() => setTab("season")} title="Home (Season)" data-testid="home"><span className="logo">🏀</span>NBA Fantasy Tool</span>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`tab-${id}`}>
              {label}
            </button>
          ))}
        </nav>
        <div id="header-slot" className="header-slot" />   {/* pages can put their own bar here (Season: week bar) */}
        <span className="meta">
          <span data-testid="health">
            {health && <span className={`dot ${health.ok ? "" : "down"}`} />}
            {health ? (health.ok ? `${health.players} players` : "API unreachable") : "…"}
            {leagueId ? ` · ${leagueId}` : " · no league selected"}
          </span>
          <button onClick={() => setTheme(theme === "dark" ? "light" : "dark")} title="toggle theme" data-testid="theme-toggle">
            {theme === "dark" ? "☀ Light" : "☾ Dark"}
          </button>
        </span>
      </header>
      <main>
        {tab === "league" && <LeaguePage leagueId={leagueId} setLeagueId={setLeagueId} />}
        {tab === "settings" && <>
          <div className="panel wall-pick"><h3>Wallpaper</h3>
            <select value={wall} onChange={(e) => setWall(e.target.value)} data-testid="wallpaper">
              {WALLPAPERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </div>
          <DataPage onPoolChanged={refreshHealth} /><SettingsPage leagueId={leagueId} />
        </>}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {tab === "season" && <SeasonPage leagueId={leagueId} />}
      </main>
      <TipLayer />
    </>
  );
}
