import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, qs } from "../api.js";
import RankingsTable from "../components/RankingsTable.jsx";
import PlayerSidebar from "../components/PlayerSidebar.jsx";
import ManagersPanel from "../components/ManagersPanel.jsx";
import PickBar from "../components/PickBar.jsx";
import StartDraftDialog from "../components/StartDraftDialog.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";
import NominationOrderBar from "../components/NominationOrderBar.jsx";
import SpendingGuide from "../components/SpendingGuide.jsx";
import EditPickDialog from "../components/EditPickDialog.jsx";

const POSITIONS = ["PG", "SG", "SF", "PF", "C"];

// A bench spot rarely scores under Lock-In, so in "My team" order a bench-only fit counts for 60 % of its value.
const BENCH_FIT = 0.6;
const teamScore = (r) => r.value * (r.assignable_slot === "BN" ? BENCH_FIT : 1);

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
  const [showManagers, setShowManagers] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  // "My team" ranks players who would only reach your bench lower; "Overall" is the league-wide order.
  const [forTeam, setForTeam] = useState(() => { try { return localStorage.getItem("da.rankFor") === "team"; } catch { return false; } });
  const pickRankFor = (team) => {
    setForTeam(team);
    try { localStorage.setItem("da.rankFor", team ? "team" : "overall"); } catch { /* ignore */ }
  };
  const [sync, setSync] = useState(() => { try { return localStorage.getItem(`da.sync.${leagueId}`) === "1"; } catch { return false; } });
  const [syncInfo, setSyncInfo] = useState(null);
  const syncBusy = useRef(false);
  const SYNC_MS = 3000;

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
        setSyncInfo((old) => ({ ...r, total: r.added.length, lag: r.added.length && r.seconds_since_last_sleeper_pick < 600 ? r.seconds_since_last_sleeper_pick : old?.lag }));
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
    tick();
    const t = setInterval(tick, SYNC_MS);
    return () => clearInterval(t);
  }, [sync, view?.status, leagueId, loadRankings]);

  // Where the two columns start, so they can end at the bottom of the window (see .cols in styles.css).
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
    if (forTeam) {
      const order = rankings.slice().sort((a, b) => teamScore(b) - teamScore(a) || a.rank - b.rank);
      const teamRank = new Map(order.map((r, i) => [r.player_id, i + 1]));
      rows = rows.map((r) => ({ ...r, team_rank: teamRank.get(r.player_id) }));
    }
    if (filter) rows = rows.filter((r) => r.full_name.toLowerCase().includes(filter.toLowerCase()));
    if (posFilter) rows = rows.filter((r) => r.eligibility.includes(posFilter));
    const { key, dir } = sort;
    const sign = dir === "asc" ? 1 : -1;
    return rows.slice().sort((a, b) => {
      const val = (r) => (key === "pos" ? (r.eligibility.length ? Math.min(...r.eligibility.map((p) => POSITIONS.indexOf(p))) : 99)
        : key === "min" ? (r.proj_min ?? r.last_min) : key === "rank" && forTeam ? r.team_rank : r[key]);
      const x = val(a), y = val(b);
      if (x === y) return a.rank - b.rank;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      return (x < y ? -1 : 1) * sign;
    });
  }, [rankings, filter, posFilter, sort, forTeam]);

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

  return (
    <div>
      <div className="panel">
        <div className="draft-head">
          <span className="title">Draft</span>
          <span className={`status-pill ${view.status}`} data-testid="draft-status">{view.status}</span>
          <div className="progress" title={`${(view.progress * 100).toFixed(1)}%`}><div style={{ width: `${view.progress * 100}%` }} /></div>
          <span className="small muted">{view.picks.length} picks · {view.available_count} available</span>
          {live && <span className="small muted">Up next: <strong style={{ color: "var(--text)" }} data-testid="next-nominator" data-manager-id={view.next_nominator || ""}>{nameOf(view.next_nominator) || "—"}</strong></span>}
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
          <button className="ghost" onClick={exportLeague} data-testid="btn-export">Export</button>
          {view.status !== "setup" && <button className="danger" onClick={() => window.confirm("Reset the draft? All picks are removed.") && act("reset")} data-testid="btn-reset">Reset</button>}
        </div>
        <NominationOrderBar
          managers={view.managers}
          order={view.nomination_order}
          nextNominator={view.next_nominator}
          live={live}
          onReorder={(order) => act("nomination-order", { order }, "put")}
          onMakeNext={(manager_id) => act("next-nominator", { manager_id }, "put")}
        />
        {error && <div className="error" data-testid="draft-error">{error}</div>}
        {notice && <div className="ok" data-testid="draft-notice">{notice}</div>}
      </div>

      {live && (
        <div className="block-bar sticky-block">
          {recordTarget ? (
            <PickBar key={recordTarget.player_id} leagueId={leagueId} view={view} player={recordTarget} onPicked={onPicked}
              nominatedBy={!pick && nominated ? nameOf(nominated.nominated_by) : null}
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

      <div className="cols" ref={colsRef}>
        <div>
          <div className="toolbar">
            <h3>Rankings</h3>
            <span className="chips" title="My team: players who would only reach your bench rank lower, so open starting spots come first">
              <button className={`small chip ${!forTeam ? "on" : ""}`} onClick={() => pickRankFor(false)} data-testid="rank-for-overall">Overall</button>
              <button className={`small chip ${forTeam ? "on" : ""}`} onClick={() => pickRankFor(true)} data-testid="rank-for-team">My team</button>
            </span>
            <input type="text" placeholder="Search players…" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="rank-filter" />
            <span className="chips">
              <button className={`small chip ${posFilter === "" ? "on" : ""}`} onClick={() => setPosFilter("")}>All</button>
              {POSITIONS.map((p) => <button key={p} className={`small chip ${posFilter === p ? "on" : ""}`} onClick={() => setPosFilter(posFilter === p ? "" : p)} data-testid={`pos-${p}`}>{p}</button>)}
            </span>
            <span className="spacer" />
            <label className="inline small muted"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> show unrosterable</label>
            <label className="inline small muted">top <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}><option>50</option><option>150</option><option>300</option><option>1000</option></select></label>
            <button className="ghost" onClick={() => { loadRankings(); loadView(); }} title="Refresh">↻</button>
          </div>
          <div className="panel scroll" style={{ padding: "0 4px" }}>
            <RankingsTable
              rows={visible}
              selectedId={selected}
              onSelect={setSelected}
              onBlock={putOnBlock}
              live={live}
              sort={sort}
              onSort={onSort}
            />
          </div>
        </div>
        <div>
          <SpendingGuide leagueId={leagueId} live={live} refreshKey={refreshKey} onSelect={setSelected} />
          <PlayerSidebar leagueId={leagueId} playerId={selected} live={live} refreshKey={refreshKey} onOverridesChanged={onOverridesChanged} onDraft={putOnBlock} scoring={settings?.scoring} userName={userName}
            onBlock={nominated?.player_id === selected} />
          <div className="row" style={{ margin: "4px 0 10px" }}>
            <button className="small ghost" onClick={() => setShowManagers(!showManagers)} data-testid="toggle-managers">{showManagers ? "▾ Hide managers" : "▸ Show managers"}</button>
          </div>
          {showManagers && (
            <ManagersPanel
              managers={view.managers}
              onEditPick={view.status !== "setup" ? setEditPick : undefined}
              onMovePick={(p, managerId) => act(`picks/${p.pick_number}`, { manager_id: managerId }, "patch")}
            />
          )}
        </div>
      </div>

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
