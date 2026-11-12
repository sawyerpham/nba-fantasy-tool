import { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";
import { setZone } from "./tz.js";

const REFRESH_MS = 60000;   // every minute: live scores feed the KEEP / SWAP calls

/**
 * The Season data and actions for the redesigned UIs (src/ui-*), the same loading SeasonPage does: the shown week and its
 * plan (reloaded every minute and when the tab comes back into view), Sync, lock answers, and the card history (a player
 * { pid }, a game { game: { game, team, sid, name } } or an NBA team { team: abbr }) stepped through with back / forward.
 * `onWeek()` switches the app to the Week view: openMatchup(roster_id) calls it, then shows that team's matchup this week.
 */
export default function useSeason(leagueId, onWeek) {
  const [week, setWeek] = useState(null);
  const [matchup, setMatchup] = useState(null);   // { rid }: the matchup the lineup grid jumps to (a new object per click)
  const [data, setData] = useState(null);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [syncing, setSyncing] = useState(false);
  const [nav, setNav] = useState({ stack: [], i: -1 });

  const load = useCallback(() => {
    if (!leagueId) return;
    Promise.all([api.get(`/leagues/${leagueId}/season/week` + qs({ week })), api.get(`/leagues/${leagueId}/season/plan` + qs({ week }))])
      .then(([w, p]) => { setZone(w.tz); setData(w); setPlan(p); setError(""); })
      .catch((e) => setError(e.message));
  }, [leagueId, week]);
  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    /** Reload when the tab becomes visible again. */
    const back = () => { if (document.visibilityState === "visible") load(); };
    document.addEventListener("visibilitychange", back);
    return () => { clearInterval(t); document.removeEventListener("visibilitychange", back); };
  }, [load, tick]);

  /** Pull the lineup, locks, scores and news from Sleeper now, then reload. */
  const sync = () => {
    setSyncing(true);
    api.post(`/leagues/${leagueId}/season/sync`, {}).then(() => setTick((t) => t + 1)).catch((e) => setError(e.message)).finally(() => setSyncing(false));
  };
  /** Record a lock answer for a player's game (`gameDate`), unlock it ("") or forget it (null), then reload. */
  const setLock = (sid, gameDate) => api.post(`/leagues/${leagueId}/season/locks`, { week: data.week, sleeper_id: sid, game_date: gameDate })
    .then(() => setTick((t) => t + 1)).catch((e) => setError(e.message));

  /** Open a card; repeating the current one changes nothing, a new one drops whatever was ahead in the history. */
  const go = (entry) => setNav(({ stack, i }) => {
    /** Do two history entries show the same player, game or team? */
    const same = (a, b) => (a?.pid && a.pid === b.pid) || (a?.game && a.game.game.event === b.game?.game.event) || (a?.team && a.team === b.team);
    return same(stack[i], entry) ? { stack, i } : { stack: [...stack.slice(0, i + 1), entry], i: i + 1 };
  });
  const close = () => setNav({ stack: [], i: -1 });
  const cur = nav.stack[nav.i] || null;
  /** Open a player's card by profile id (a falsy id closes the cards). */
  const openPid = (pid) => (pid ? go({ pid }) : close());
  /** Open a player's card by Sleeper id. */
  const open = (sid) => { const pid = data?.players[sid]?.player_id; if (pid) go({ pid }); };

  /** Show a fantasy team's matchup this week on the Week view (the cards close so it's in sight). */
  const openMatchup = (rid) => { setWeek(null); setMatchup({ rid }); close(); onWeek?.(); };

  return {
    week, setWeek, data, plan, error, tick, syncing, sync, setLock, matchup, openMatchup,
    cur, go, close, openPid, open, openTeam: (abbr) => go({ team: abbr }), openGame: (g) => go({ game: g }),
    back: nav.i > 0 ? () => setNav((n) => ({ ...n, i: n.i - 1 })) : null,
    forward: nav.i < nav.stack.length - 1 ? () => setNav((n) => ({ ...n, i: n.i + 1 })) : null,
  };
}
