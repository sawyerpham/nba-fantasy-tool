import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { posClass } from "../components/Pos.jsx";
import { api, qs } from "../api.js";
import RankingsTable from "../components/RankingsTable.jsx";
import PlayerSidebar from "../components/PlayerSidebar.jsx";
import RoomBoard from "../components/RoomBoard.jsx";
import LiveLot from "../components/LiveLot.jsx";
import TeamsTable from "../components/TeamsTable.jsx";
import NbaTeamsTable from "../components/NbaTeamsTable.jsx";
import PickBar from "../components/PickBar.jsx";
import StartDraftDialog from "../components/StartDraftDialog.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";
import NominationOrderBar from "../components/NominationOrderBar.jsx";
import SpendingGuide from "../components/SpendingGuide.jsx";
import EditPickDialog from "../components/EditPickDialog.jsx";

const POSITIONS = ["PG", "SG", "SF", "PF", "C"];

export default function DraftPage({ leagueId }) {
  const [view, setView] = useState(null);
  const [settings, setSettings] = useState(null);
  const [rankings, setRankings] = useState([]);
  const [showAll, setShowAll] = useState(false);
  const [limit, setLimit] = useState(150);
  const [filter, setFilter] = useState("");
  const [posFilter, setPosFilter] = useState("");
  const [sort, setSort] = useState({ key: "rank", dir: "asc" });
  const [selected, setSelected] = useState(null);
  const [pick, setPick] = useState(null);
  const [dismissed, setDismissed] = useState(null); // nominated player whose bar was closed
  const [editPick, setEditPick] = useState(null);
  const [startOpen, setStartOpen] = useState(false);
  const [orderOpen, setOrderOpen] = useState(null);
  const [view2, setView2] = useState("players");   // rankings: players | managers (fantasy teams) | nba (NBA teams)   // null = open in setup, closed once live
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [sync, setSync] = useState(() => { try { return localStorage.getItem(`da.sync.${leagueId}`) === "1"; } catch { return false; } });
  const [syncInfo, setSyncInfo] = useState(null);
  const syncBusy = useRef(false);
  const syncSeen = useRef(false);   // false until the first sync of this session has caught up
  const SYNC_MS = 1000;   // Sleeper's public API allows ~1000 requests/min
  const [liveLot, setLiveLot] = useState(null);   // the lot in progress in Sleeper (player, high bid, leader, clock)
  const [toasts, setToasts] = useState([]);       // "X drafted Y for $Z" notices from Sleeper sync
  const toast = (items) => {
    const stamped = items.map((a, i) => ({ ...a, key: `${a.player_id}-${Date.now()}-${i}` }));
    setToasts((t) => [...stamped, ...t].slice(0, 6));
    setTimeout(() => setToasts((t) => t.filter((x) => !stamped.some((s) => s.key === x.key))), 12000);
  };
  const goToManager = (id) => {
    const el = document.querySelector(`[data-testid="manager-card-${id}"]`) || document.getElementById("room");
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.add("flash");
    setTimeout(() => el?.classList.remove("flash"), 1600);
  };

  const loadView = useCallback(() => api.get(`/leagues/${leagueId}/draft`).then(setView), [leagueId]);
  const loadRankings = useCallback(
    () => api.get(`/leagues/${leagueId}/rankings` + qs({ limit, include_unrosterable: showAll })).then(setRankings),
    [leagueId, limit, showAll],
  );

  useEffect(() => {
    if (!leagueId) return;
    setError("");
    Promise.all([loadView(), loadRankings(), api.get(`/leagues/${leagueId}/settings`).then(setSettings)]).catch((e) => setError(e.message));
  }, [leagueId, loadView, loadRankings]);

  // "/" focuses the mark-drafted search box (when not already typing somewhere).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName)) {
        e.preventDefault();
        document.querySelector('[data-testid="search-input"]')?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // Live Sleeper sync: every SYNC_MS, record any pick made in the Sleeper draft that isn't here yet.
  useEffect(() => {
    try { localStorage.setItem(`da.sync.${leagueId}`, sync ? "1" : "0"); } catch { /* ignore */ }
    if (!sync || view?.status !== "live") return undefined;
    const tick = async () => {
      if (syncBusy.current) return;
      syncBusy.current = true;
      try {
        const r = await api.post(`/leagues/${leagueId}/draft/sync`);
        setSyncInfo((old) => ({ ...r, total: (old?.total || 0) + r.added.length, lag: r.added.length && r.seconds_since_last_sleeper_pick < 600 ? r.seconds_since_last_sleeper_pick : old?.lag }));
        setLiveLot(r.live);
        // The first sync after turning it on catches up on every earlier pick: no notifications for those.
        if (r.added.length && syncSeen.current) toast(r.added);
        syncSeen.current = true;
        if (r.added.length) {
          setView(r.view);
          setPick((p) => (p && r.view.picks.some((x) => x.player_id === p.player_id) ? null : p));
          await loadRankings();
          setRefreshKey((k) => k + 1);
        }
      } catch (e) {
        setSyncInfo({ fatal: e.message });
      } finally {
        syncBusy.current = false;
      }
    };
    syncSeen.current = false;
    tick();
    const t = setInterval(tick, SYNC_MS);
    return () => clearInterval(t);
  }, [sync, view?.status, leagueId, loadRankings]);

  // Where the columns start, so they can end at the bottom of the window (see .draft-grid in styles.css).
  const colsRef = useRef(null);
  useLayoutEffect(() => {
    const el = colsRef.current;
    if (!el) return undefined;
    const measure = () => {
      const top = `${Math.round(el.getBoundingClientRect().top + window.scrollY)}px`;
      if (el.style.getPropertyValue("--cols-top") !== top) el.style.setProperty("--cols-top", top);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el.parentElement);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  });

  const visible = useMemo(() => {
    let rows = rankings;
    if (filter) rows = rows.filter((r) => r.full_name.toLowerCase().includes(filter.toLowerCase()));
    if (posFilter) rows = rows.filter((r) => r.eligibility.includes(posFilter));
    const { key, dir } = sort;
    const sign = dir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {
      // Pos sorts by best in role: the positional rank number (#1s first), position order breaking ties.
      const posRank = (r) => {
        const label = posFilter ? r.pos_ranks?.[posFilter] : r.pos_rank;
        const n = label ? Number(label.slice(1).split(" ")[0]) : 9999;
        return n * 10 + (label ? POSITIONS.indexOf(label.split(" ")[1]) : 9);
      };
      const val = (r) => (key === "pos" ? posRank(r)
        : key === "min" ? (r.proj_min ?? r.last_min) : key === "fit" ? r.fit?.score : r[key]);
      const x = val(a), y = val(b);
      if (x === y) return a.rank - b.rank;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * sign;
    });
  }, [rankings, filter, posFilter, sort]);

  if (!leagueId) return <p className="muted">Select or create a league on the League tab first.</p>;
  if (!view) return <p>{error || "Loading…"}</p>;

  const live = view.status === "live";
  const bump = () => setRefreshKey((k) => k + 1);

  const act = async (path, body, method = "post") => {
    setError(""); setNotice("");
    try {
      const v = await api[method](`/leagues/${leagueId}/draft/${path}`, body || {});
      setView(v);
      await loadRankings();
      bump();
      return v;
    } catch (e) {
      setError(e.message);
      return null;
    }
  };

  // One action for "this player is up": nominate him (opens the record bar); if nominating isn't possible,
  // just open the record bar for him.
  const putOnBlock = async (r) => {
    setPick(null);
    setDismissed(null);
    const v = await act("nominate", { player_id: r.player_id });
    if (!v) { setError(""); setPick(r); }
  };

  const onPicked = async (v) => {
    setPick(null);
    setView(v);
    await loadRankings();
    bump();
    setTimeout(() => document.querySelector('[data-testid="search-input"]')?.focus(), 0);
  };

  const exportLeague = async () => {
    setError(""); setNotice("");
    try {
      const r = await api.post(`/leagues/${leagueId}/export`);
      setNotice(`Exported schema_version ${r.document.schema_version} to ${r.path}`);
    } catch (e) {
      setError(e.message);
    }
  };

  // Everything about the draft as Markdown on the clipboard, to paste into a chat with Claude.
  const copyContext = async () => {
    setError(""); setNotice("");
    try {
      const text = await api.get(`/leagues/${leagueId}/context` + qs({ player_id: selected }));
      await navigator.clipboard.writeText(text);
      setNotice(`Copied the draft (${Math.round(text.length / 1000)}k characters) — paste it into Claude and ask your question.`);
    } catch (e) {
      setError(`Copy failed: ${e.message}`);
    }
  };

  const onSort = (key) => setSort((s) => ({ key, dir: s.key === key ? (s.dir === "asc" ? "desc" : "asc") : (["rank", "full_name", "team_abbr", "injury_status", "pos"].includes(key) ? "asc" : "desc") }));
  const onOverridesChanged = () => { loadRankings(); loadView(); };
  const nominated = view.current_nomination;
  const nominatedName = nominated ? (rankings.find((r) => r.player_id === nominated.player_id)?.full_name || `#${nominated.player_id}`) : null;
  const markDrafted = (
    <span className="mark-drafted">
      <span className="small muted">Mark drafted <kbd>/</kbd></span>
      <PlayerSearch leagueId={leagueId} onSelect={(p) => (p.drafted_by ? setError(`${p.full_name} is already drafted by ${p.drafted_by}`) : setPick(p))} placeholder="type a name…" />
    </span>
  );
  const recordTarget = pick || (nominated && dismissed !== nominated.player_id ? { player_id: nominated.player_id, full_name: nominatedName } : null);
  const userName = view.managers.find((m) => m.is_user)?.name || "you";
  const nameOf = (id) => (id ? view.managers.find((m) => m.manager_id === id)?.name || id : null);
  const showOrder = orderOpen ?? !live;
  // The next few nominators in rotation, skipping full rosters.
  const order = view.nomination_order;
  const start = Math.max(0, order.indexOf(view.next_nominator));
  const canNominate = (id) => { const m = view.managers.find((x) => x.manager_id === id); return m && m.budget.open_mandatory > 0; };
  const upcoming = [...order.slice(start), ...order.slice(0, start)].filter(canNominate).slice(1, 3).map(nameOf);

  return (
    <div>
      <div className="panel draft-top">
        <div className="draft-head">
          <span className={`status-pill ${view.status}`} data-testid="draft-status">{view.status}</span>
          <div className="progress" title={`${(view.progress * 100).toFixed(1)}%`}><div style={{ width: `${view.progress * 100}%` }} /></div>
          <span className="small muted">{view.picks.length} picks · {view.available_count} left</span>
          {live && (
            <span className="small muted upcoming">
              Nominating: <strong style={{ color: "var(--text)" }} data-testid="next-nominator" data-manager-id={view.next_nominator || ""}>{nameOf(view.next_nominator) || "—"}</strong>
              {upcoming.length > 0 && <> · then {upcoming.join(", ")}</>}
            </span>
          )}
          <button className="small ghost" onClick={() => document.getElementById("room")?.scrollIntoView({ behavior: "smooth" })} data-testid="btn-room"
            title="every manager's money, roster and who to nominate to make them spend">Room ↓</button>
          <button className={`small ${showOrder ? "" : "ghost"}`} onClick={() => setOrderOpen(!showOrder)} data-testid="btn-order"
            title="change the nomination order or who nominates next">{showOrder ? "▾ Order" : "▸ Order"}</button>
          <span className="spacer" />
          {live && (
            <span className="sync-box" data-testid="sync-box">
              <label className="inline small" title="check the Sleeper draft every 3 s and record new picks automatically">
                <input type="checkbox" checked={sync} onChange={(e) => setSync(e.target.checked)} data-testid="sync-toggle" /> Sleeper sync
              </label>
              {sync && syncInfo && (
                syncInfo.fatal ? <span className="small warn-text" title={syncInfo.fatal}>sync off: {syncInfo.fatal.slice(0, 60)}</span> : (
                  <span className="small muted" title={syncInfo.errors?.join(" · ") || ""}>
                    {syncInfo.total ? `+${syncInfo.total} pick${syncInfo.total === 1 ? "" : "s"}` : "up to date"}
                    {syncInfo.lag != null ? ` · last pick landed ${syncInfo.lag}s after Sleeper` : ""}
                    {syncInfo.errors?.length ? <span className="warn-text"> · {syncInfo.errors.length} need a hand entry</span> : ""}
                  </span>
                )
              )}
            </span>
          )}
          {view.status === "setup" && <button className="primary" onClick={() => setStartOpen(true)} data-testid="btn-start">Start draft…</button>}
          {live && <button onClick={() => act("undo")} disabled={!view.picks.some((p) => !p.is_keeper)} data-testid="btn-undo">↶ Undo</button>}
          {live && <button onClick={() => window.confirm("Complete the draft?") && act("complete")} data-testid="btn-complete">Complete</button>}
          <button onClick={copyContext} data-testid="btn-copy-context"
            title="copy the rules, the draft so far, every manager's money, roster and habits, your money, the best available players and the selected player, ready to paste into Claude">Copy for Claude</button>
          <button className="ghost" onClick={exportLeague} data-testid="btn-export">Export</button>
          {view.status !== "setup" && <button className="danger" onClick={() => window.confirm("Reset the draft? All picks are removed.") && act("reset")} data-testid="btn-reset">Reset</button>}
        </div>
        {showOrder && <NominationOrderBar
          managers={view.managers}
          order={view.nomination_order}
          nextNominator={view.next_nominator}
          live={live}
          onReorder={(order) => act("nomination-order", { order }, "put")}
          onMakeNext={(manager_id) => act("next-nominator", { manager_id }, "put")}
        />}
        {error && <div className="error" data-testid="draft-error">{error}</div>}
        {notice && <div className="ok" data-testid="draft-notice">{notice}</div>}
      </div>

      {toasts.length > 0 && (
        <div className="toasts" data-testid="toasts">
          {toasts.slice(0, 1).map((t) => {
            const over = t.fair != null ? t.price - t.fair : null;
            return (
              <div key={t.key} className={`toast ${over == null ? "" : over > 2 ? "over" : over < -2 ? "under" : ""}`}
                onClick={() => goToManager(t.manager_id)} title="go to his team in the room">
                <strong>{t.manager}</strong> drafted <strong>{t.player}</strong> for <strong>${t.price}</strong>
                {over != null && <span className="toast-tag">{over > 2 ? `overpaid $${over}` : over < -2 ? `bargain, $${-over} under` : "fair price"}</span>}
                <span className="muted"> · ${t.left} left</span>
                {toasts.length > 1 && <span className="muted"> · +{toasts.length - 1} more</span>}
              </div>
            );
          })}
        </div>
      )}

      <div className="draft-grid" ref={colsRef}>
        <section className="dg-left">
          <div className="dg-pane">
            {live ? <SpendingGuide leagueId={leagueId} live={live} refreshKey={refreshKey} onSelect={setSelected}
              lot={sync ? liveLot : null} />
              : <div className="panel muted small">The spending guide appears here once the draft starts.</div>}
          </div>
        </section>
        <section className="dg-rank">
          {live && sync && !pick && (
            <div className="block-bar live-bar">
              {liveLot ? (
                <LiveLot leagueId={leagueId} lot={liveLot} managers={view.managers}
                  row={rankings.find((r) => r.player_id === liveLot.player_id)} onOpen={() => setSelected(liveLot.player_id)} />
              ) : (
                <><span className="live-dot" /><span className="muted">Sleeper sync on: waiting for the next nomination…</span><span className="spacer" />{markDrafted}</>
              )}
            </div>
          )}
          {live && !(sync && !pick) && (
            <div className="block-bar">
              {recordTarget ? (
                <PickBar key={recordTarget.player_id} leagueId={leagueId} view={view} player={recordTarget} onPicked={onPicked}
                  nominatedBy={pick?.fromSleeper ? pick.nominated_by : !pick && nominated ? nameOf(nominated.nominated_by) : null}
                  live={liveLot && liveLot.player_id === recordTarget.player_id ? liveLot : null}
                  tier={rankings.find((r) => r.player_id === recordTarget.player_id)} search={markDrafted}
                  onCancel={() => { if (pick) setPick(null); else setDismissed(nominated?.player_id); }} />
              ) : (
                <>
                  <span className="label">On the block</span>
                  {nominated ? (
                    <>
                      <span className="on-block" data-testid="on-the-block">{nominatedName}</span>
                      <span className="small muted">by {nameOf(nominated.nominated_by)}</span>
                      <button className="primary" onClick={() => setDismissed(null)} data-testid="btn-record-bid">Record winner</button>
                    </>
                  ) : <span className="muted">Nobody yet — click On the block on a player, or turn on Sleeper sync</span>}
                </>
              )}
              {!recordTarget && <><span className="spacer" />{markDrafted}</>}
            </div>
          )}

          <div className="toolbar">
            <h3>Rankings</h3>
            <span className="chips">
              <button className={`small chip ${view2 === "players" ? "on" : ""}`} onClick={() => setView2("players")} data-testid="rank-view-players">Players</button>
              <button className={`small chip ${view2 === "teams" ? "on" : ""}`} onClick={() => setView2("teams")} data-testid="rank-view-teams">Managers</button>
              <button className={`small chip ${view2 === "nba" ? "on" : ""}`} onClick={() => setView2("nba")} data-testid="rank-view-nba">NBA Teams</button>
            </span>
            {view2 === "players" && <>
            <input type="text" placeholder="Search players…" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="rank-filter" />
            <span className="chips">
              <button className={`small chip ${posFilter === "" ? "on" : ""}`} onClick={() => setPosFilter("")}>All</button>
              {POSITIONS.map((p) => <button key={p} className={`small chip ${posClass(p)} ${posFilter === p ? "on" : ""}`} onClick={() => setPosFilter(posFilter === p ? "" : p)} data-testid={`pos-${p}`}>{p}</button>)}
            </span>
            <span className="spacer" />
            <label className="inline small muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show unrosterable</label>
            </>}
            {view2 === "players" && <label className="inline small muted">top <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}><option>50</option><option>150</option><option>300</option><option>1000</option></select></label>}
            <button className="ghost" onClick={() => { loadRankings(); loadView(); }} title="Refresh">↻</button>
          </div>
          <div className="panel scroll" style={{ padding: "0 4px" }}>
            {view2 === "nba" ? <NbaTeamsTable leagueId={leagueId} refreshKey={refreshKey} onSelectPlayer={setSelected} />
              : view2 === "teams" ? <TeamsTable leagueId={leagueId} refreshKey={`${refreshKey}-${view.picks.length}`}
              onOpenRoom={() => document.getElementById("room")?.scrollIntoView({ behavior: "smooth" })} /> : <RankingsTable
              rows={visible}
              selectedId={selected}
              onSelect={setSelected}
              onBlock={putOnBlock}
              live={live}
              sort={sort}
              onSort={onSort}
              posFilter={posFilter}
            />}
          </div>
        </section>
        <section className="dg-side">
          <div className="dg-pane">
          <PlayerSidebar leagueId={leagueId} playerId={selected ?? (sync ? liveLot?.player_id : null)} live={live} refreshKey={refreshKey} onOverridesChanged={onOverridesChanged} userName={userName} onSelectPlayer={setSelected}
            onBlock={nominated?.player_id === selected} rankings={rankings} />
          </div>
        </section>
      </div>

      <section className="room" id="room">
        <div className="room-title">
          <h2 style={{ margin: 0 }}>The room</h2>
          <span className="small muted">every manager's money, max bid, roster and habits · click a player for his profile</span>
          <span className="spacer" />
          <button className="small ghost" onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>↑ Draft</button>
        </div>
        <RoomBoard leagueId={leagueId} rosterSlots={settings?.roster_slots} refreshKey={`${refreshKey}-${view.picks.length}`}
          onEditPick={view.status !== "setup" ? setEditPick : undefined}
          onMovePick={(p, managerId) => act(`picks/${p.pick_number}`, { manager_id: managerId }, "patch")}
          onSelectPlayer={(pid) => { setSelected(pid); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
      </section>

      {editPick && (
        <EditPickDialog leagueId={leagueId} view={view} pick={editPick} minBid={settings?.min_bid ?? 1} onClose={() => setEditPick(null)}
          onSaved={async (v) => { setEditPick(null); setView(v); await loadRankings(); bump(); }} />
      )}
      {startOpen && (
        <StartDraftDialog leagueId={leagueId} view={view} keeperSettings={settings?.keeper} onClose={() => setStartOpen(false)}
          onStarted={async (v) => { setStartOpen(false); setView(v); await loadRankings(); bump(); }} />
      )}
    </div>
  );
}
