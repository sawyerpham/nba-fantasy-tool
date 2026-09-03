import React, { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";
import RankingsTable from "../components/RankingsTable.jsx";
import PlayerSidebar from "../components/PlayerSidebar.jsx";
import ManagersPanel from "../components/ManagersPanel.jsx";
import PickDialog from "../components/PickDialog.jsx";
import StartDraftDialog from "../components/StartDraftDialog.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";

export default function DraftPage({ leagueId }) {
  const [view, setView] = useState(null);
  const [settings, setSettings] = useState(null);
  const [rankings, setRankings] = useState([]);
  const [showAll, setShowAll] = useState(false);
  const [limit, setLimit] = useState(150);
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState(null);
  const [pick, setPick] = useState(null);
  const [startOpen, setStartOpen] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

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

  if (!leagueId) return <p className="muted">Select or create a league on the League tab first.</p>;
  if (!view) return <p>{error || "Loading…"}</p>;

  const live = view.status === "live";
  const bump = () => setRefreshKey((k) => k + 1);

  const act = async (path, body) => {
    setError(""); setNotice("");
    try {
      const v = await api.post(`/leagues/${leagueId}/draft/${path}`, body || {});
      setView(v);
      await loadRankings();
      bump();
      return v;
    } catch (e) {
      setError(e.message);
      return null;
    }
  };

  const onPicked = async (v) => {
    setPick(null);
    setView(v);
    await loadRankings();
    bump();
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

  const onOverridesChanged = () => { loadRankings(); loadView(); };
  const nominated = view.current_nomination;
  const nominatedName = nominated ? (rankings.find((r) => r.player_id === nominated.player_id)?.full_name || `#${nominated.player_id}`) : null;
  const visible = filter ? rankings.filter((r) => r.full_name.toLowerCase().includes(filter.toLowerCase())) : rankings;

  return (
    <div>
      <div className="panel">
        <div className="row">
          <strong>Draft: <span data-testid="draft-status">{view.status}</span></strong>
          <span className="small">progress {(view.progress * 100).toFixed(1)}% · {view.picks.length} picks · {view.available_count} available</span>
          {live && <span>Nominates next: <strong data-testid="next-nominator">{view.next_nominator || "—"}</strong></span>}
          {view.status === "setup" && <button className="primary" onClick={() => setStartOpen(true)} data-testid="btn-start">Start draft…</button>}
          {live && <button onClick={() => act("undo")} disabled={!view.picks.some((p) => !p.is_keeper)} data-testid="btn-undo">Undo last pick</button>}
          {live && <button onClick={() => window.confirm("Complete the draft?") && act("complete")} data-testid="btn-complete">Complete draft</button>}
          {view.status !== "setup" && <button className="danger" onClick={() => window.confirm("Reset the draft? All picks are removed.") && act("reset")} data-testid="btn-reset">Reset</button>}
          <button onClick={exportLeague} data-testid="btn-export">Export JSON</button>
        </div>
        {live && (
          <div className="row" style={{ marginTop: 6 }}>
            <span>On the block:</span>
            {nominated ? (
              <>
                <strong data-testid="on-the-block">{nominatedName}</strong>
                <span className="small muted">nominated by {nominated.nominated_by}</span>
                <button className="primary" onClick={() => setPick({ player_id: nominated.player_id, full_name: nominatedName })} data-testid="btn-record-bid">Record winning bid…</button>
              </>
            ) : <span className="muted">nobody — nominate from the table, or mark a drafted player via search</span>}
            <span style={{ marginLeft: 12 }}>Mark drafted:</span>
            <PlayerSearch leagueId={leagueId} onSelect={(p) => (p.drafted_by ? setError(`${p.full_name} is already drafted by ${p.drafted_by}`) : setPick(p))} placeholder="type a name…" />
          </div>
        )}
        {error && <div className="error" data-testid="draft-error">{error}</div>}
        {notice && <div className="ok" data-testid="draft-notice">{notice}</div>}
      </div>

      <div className="cols">
        <div>
          <div className="row" style={{ marginBottom: 6 }}>
            <h3 style={{ margin: 0 }}>Rankings (for {view.managers.find((m) => m.is_user)?.name || "you"})</h3>
            <input type="text" placeholder="filter…" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="rank-filter" />
            <label className="inline"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> include players I cannot roster</label>
            <label className="inline">show <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}><option>50</option><option>150</option><option>300</option><option>1000</option></select></label>
            <button onClick={() => { loadRankings(); loadView(); }}>Refresh</button>
          </div>
          <div className="panel scroll" style={{ padding: 0 }}>
            <RankingsTable
              rows={visible}
              selectedId={selected}
              onSelect={setSelected}
              onNominate={(r) => act("nominate", { player_id: r.player_id })}
              onDraft={(r) => setPick(r)}
              live={live}
            />
          </div>
        </div>
        <div>
          <PlayerSidebar leagueId={leagueId} playerId={selected} live={live} refreshKey={refreshKey} onOverridesChanged={onOverridesChanged} onDraft={(p) => setPick(p)} />
          <ManagersPanel managers={view.managers} />
        </div>
      </div>

      {pick && <PickDialog leagueId={leagueId} view={view} player={pick} onClose={() => setPick(null)} onPicked={onPicked} />}
      {startOpen && (
        <StartDraftDialog leagueId={leagueId} view={view} maxKeepers={settings?.keeper?.max_per_manager ?? 1} onClose={() => setStartOpen(false)}
          onStarted={async (v) => { setStartOpen(false); setView(v); await loadRankings(); bump(); }} />
      )}
    </div>
  );
}
