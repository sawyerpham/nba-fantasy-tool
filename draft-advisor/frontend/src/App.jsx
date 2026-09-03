import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import DataPage from "./pages/DataPage.jsx";
import LeaguePage from "./pages/LeaguePage.jsx";
import SettingsPage from "./pages/SettingsPage.jsx";
import DraftPage from "./pages/DraftPage.jsx";

const TABS = [
  ["data", "Data"],
  ["league", "League"],
  ["settings", "Settings"],
  ["draft", "Draft"],
];

export default function App() {
  const [tab, setTab] = useState(() => localStorage.getItem("da.tab") || "data");
  const [leagueId, setLeagueIdState] = useState(() => localStorage.getItem("da.league") || "");
  const [health, setHealth] = useState(null);

  const setLeagueId = useCallback((id) => {
    setLeagueIdState(id || "");
    if (id) localStorage.setItem("da.league", id);
    else localStorage.removeItem("da.league");
  }, []);

  useEffect(() => {
    localStorage.setItem("da.tab", tab);
  }, [tab]);

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
        <strong>Draft Advisor</strong>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`tab-${id}`}>
              {label}
            </button>
          ))}
        </nav>
        <span className="meta" data-testid="health">
          {health ? (health.ok ? `API ok · ${health.players} players in pool` : "API unreachable") : "…"}
          {leagueId ? ` · league: ${leagueId}` : " · no league selected"}
        </span>
      </header>
      <main>
        {tab === "data" && <DataPage onPoolChanged={refreshHealth} />}
        {tab === "league" && <LeaguePage leagueId={leagueId} setLeagueId={setLeagueId} />}
        {tab === "settings" && <SettingsPage leagueId={leagueId} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
      </main>
    </>
  );
}
