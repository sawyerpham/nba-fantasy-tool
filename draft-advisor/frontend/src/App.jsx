import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import DataPage from "./pages/DataPage.jsx";
import LeaguePage from "./pages/LeaguePage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import DraftPage from "./pages/DraftPage.jsx";
import SeasonPage from "./pages/SeasonPage.jsx";
import { TipLayer } from "./components/Terms.jsx";

const TABS = [
  ["data", "Data"],
  ["league", "League"],
  ["settings", "Settings"],
  ["draft", "Draft"],
  ["season", "Season"],
];

export default function App() {
  const [tab, setTab] = useState(() => localStorage.getItem("da.tab") || "data");
  const [leagueId, setLeagueIdState] = useState(() => localStorage.getItem("da.league") || "");
  const [theme, setTheme] = useState(() => localStorage.getItem("da.theme") || "dark");
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
        <span className="brand" onClick={() => setTab("season")} title="Home (Season)" data-testid="home"><span className="logo">🏀</span>Draft Advisor</span>
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
        {tab === "data" && <DataPage onPoolChanged={refreshHealth} />}
        {tab === "league" && <LeaguePage leagueId={leagueId} setLeagueId={setLeagueId} />}
        {tab === "settings" && <SettingsPage leagueId={leagueId} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {tab === "season" && <SeasonPage leagueId={leagueId} />}
      </main>
      <TipLayer />
    </>
  );
}
