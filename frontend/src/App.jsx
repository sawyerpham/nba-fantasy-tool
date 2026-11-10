import React from "react";
import HomePage from "./core/HomePage.jsx";
import DraftPage from "./draft/DraftPage.jsx";
import SeasonPage from "./lockin/SeasonPage.jsx";
import { TipLayer } from "./core/Terms.jsx";
import Icon from "./core/Icon.jsx";
import { SEASON_VIEWS, SettingsModal, TABS, useAppState } from "./core/Shell.jsx";

const TAB_COLORS = { season: "#3b82f6", news: "#f59e0b", standings: "#10b981", waivers: "#ec4899", draft: "#a855f7" };   // each tab's own hue (see header.top nav button in styles.css)

/** Root component of the "New" UI: the header (tabs, settings cog) and the page for the open tab (Home, Draft or a Season view). State and the Settings popup: core/Shell.jsx. */
export default function App() {
  const app = useAppState();
  const { tab, setTab, goTab, leagueId, health } = app;
  return (
    <>
      <header className="top">
        <div className="header-left">
        <span className="brand" onClick={() => setTab("home")} title="Home" data-testid="home"><span className="logo"><Icon name="ball" /></span>{app.leagueName || "NBA Fantasy Tool"}</span>
        <nav>
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} style={{ "--c": TAB_COLORS[id] }} data-testid={`tab-${id}`}>
              {label}
            </button>
          ))}
        </nav>
        </div>
        <div id="header-slot" className="header-slot" />   {/* pages can put their own bar here (Season: week bar) */}
        {health && !health.ok && <span className="meta"><span className="small warn-text" data-testid="health">API unreachable</span></span>}
        <button className={`cog icon-btn ${app.settingsOpen ? "active" : ""}`} onClick={() => app.setSettingsOpen(true)} data-testid="tab-settings" aria-label="Settings" title="Settings"><Icon name="settings" /></button>
      </header>
      <main>
        {tab === "home" && <HomePage setLeagueId={app.setLeagueId} setTab={goTab} />}
        {tab === "draft" && <DraftPage leagueId={leagueId} />}
        {SEASON_VIEWS[tab] && <SeasonPage leagueId={leagueId} view={SEASON_VIEWS[tab]} />}
      </main>
      <SettingsModal app={app} />
      <TipLayer />
    </>
  );
}
