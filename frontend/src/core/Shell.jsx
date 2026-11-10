import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import DataPage from "./DataPage.jsx";
import LeaguePage from "./LeaguePage.jsx";
import SettingsPage from "./SettingsPage.jsx";
import Icon from "./Icon.jsx";

// What every UI's shell shares (src/App.jsx, src/ui-command, src/ui-broadcast): the app state kept in localStorage and the Settings popup.

/** Settings > Appearance > UI: id ("" = New) and label; main.jsx loads the matching App and stylesheet. */
export const UIS = [["", "New"], ["command", "Command Center"], ["broadcast", "Broadcast"], ["classic", "Classic (backup, Nov 2026)"]];
// design presets (themes.css): fonts, surfaces, corners and effects; the first is the default
const THEMES = [["courtside", "Courtside: broadcast scoreboard"], ["office", "Front Office: analyst terminal"], ["locker", "Locker Room: light"]];
// pixelated photos behind the page (public/wallpapers, made by backgroundimages/pixelate.py)
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
/** The top-level pages; "settings" is the popup, not a page. */
export const TABS = [["season", "Season"], ["standings", "League"], ["news", "News"], ["waivers", "Waivers"], ["draft", "Draft"]];
/** Which Season view each Season-side tab shows. */
export const SEASON_VIEWS = { season: "week", news: "news", standings: "league", waivers: "waivers" };

/** The UI this page loaded with (see UIS). */
const UI = (() => { try { return localStorage.getItem("da.ui") || ""; } catch { return ""; } })();
/** Switch UI: remember the choice and reload, since each UI brings its own global stylesheet. */
const setUi = (v) => { try { localStorage.setItem("da.ui", v); } catch { } location.reload(); };

/**
 * The app state every shell needs: the open tab, the league (and its name), theme, wallpaper, API health and the Settings popup.
 * Persists the tab, league, theme and wallpaper in localStorage and polls /health every 15 s.
 */
export function useAppState() {
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
  const [theme, setTheme] = useState(() => THEMES.some(([id]) => id === localStorage.getItem("da.theme")) ? localStorage.getItem("da.theme") : THEMES[0][0]);
  const [health, setHealth] = useState(null);

  /** Select a league (a falsy id clears it) and remember the choice in localStorage. */
  const setLeagueId = useCallback((id) => {
    setLeagueIdState(id || "");
    if (id) localStorage.setItem("da.league", id);
    else localStorage.removeItem("da.league");
  }, []);

  useEffect(() => { localStorage.setItem("da.tab", tab); }, [tab]);

  // the header shows the chosen league's name (re-read on tab change, so a Sleeper rename picked up by Sync shows up)
  const [leagueName, setLeagueName] = useState("");
  useEffect(() => {
    if (!leagueId) return setLeagueName("");
    api.get("/leagues").then((ls) => setLeagueName(ls.find((l) => l.league_id === leagueId)?.name || "")).catch(() => {});
  }, [leagueId, tab]);

  useEffect(() => {
    document.documentElement.style.setProperty("--wall", wall ? `url(/wallpapers/${wall}.png)` : "none");
    document.documentElement.dataset.wall = wall;   // styles.css darkens content panels over a photo
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

  return { tab, setTab, goTab, settingsOpen, setSettingsOpen, leagueId, setLeagueId, leagueName, wall, setWall, theme, setTheme, health, refreshHealth };
}

/** The Settings popup (Appearance: UI, theme, wallpaper; League: league, its settings, the data pull). `app` is useAppState()'s result. */
export function SettingsModal({ app }) {
  if (!app.settingsOpen) return null;
  const close = () => app.setSettingsOpen(false);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()} data-testid="settings-modal">
      <div className="modal settings-modal">
        <button className="small settings-close" onClick={close} aria-label="Close settings" data-testid="settings-close"><Icon name="x" /></button>
      <div className="panel section-card" data-testid="section-appearance"><h2>Appearance</h2>
      <div className="panel wall-pick"><h3>UI</h3>
        <select value={UI} onChange={(e) => setUi(e.target.value)} data-testid="ui">
          {UIS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      <div className="panel wall-pick"><h3>Theme</h3>
        <select value={app.theme} onChange={(e) => app.setTheme(e.target.value)} data-testid="theme">
          {THEMES.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      <div className="panel wall-pick"><h3>Wallpaper</h3>
        <select value={app.wall} onChange={(e) => app.setWall(e.target.value)} data-testid="wallpaper">
          {WALLPAPERS.map(([id, label]) => <option key={id} value={id}>{label}</option>)}
        </select>
      </div>
      </div>
      <div className="panel section-card" data-testid="section-league"><h2>League</h2>
        <LeaguePage leagueId={app.leagueId} setLeagueId={app.setLeagueId} />
        {app.leagueId && <SettingsPage leagueId={app.leagueId} />}
        <DataPage onPoolChanged={app.refreshHealth} />
      </div>
      </div>
    </div>
  );
}
