import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

const when = (iso) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "");
// Sleeper times inside entry text (e.g. "draft scheduled for 2026-10-19T01:00:28+00:00") shown in local time.
const localize = (text) => text.replace(/\d{4}-\d{2}-\d{2}T[\d:.]+\+00:00/g, (iso) => when(iso));
const KIND = { trade: "trade", waiver: "waiver", free_agent: "free agent", commissioner: "commish", keeper: "keeper", member: "member", rules: "rules", draft: "draft" };

// One-click sync with the linked Sleeper league, plus the league's activity log (who did what, when).
export default function SleeperSync({ leagueId, sleeperLeagueId, onSynced }) {
  const [log, setLog] = useState([]);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showAll, setShowAll] = useState(false);

  const loadLog = useCallback(() => api.get(`/leagues/${leagueId}/sleeper/changelog`).then(setLog).catch(() => setLog([])), [leagueId]);
  useEffect(() => { loadLog(); }, [loadLog]);

  const sync = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const r = await api.post(`/leagues/${leagueId}/sleeper/sync`);
      setResult(r);
      await loadLog();
      onSynced?.();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  if (!sleeperLeagueId) {
    return <div className="panel muted small">Link a Sleeper league (Settings → Sleeper league → linked league) to sync managers, keepers and rules, and to see league activity here.</div>;
  }
  const shown = showAll ? log : log.slice(0, 15);
  return (
    <div className="panel" data-testid="sleeper-sync">
      <div className="row">
        <h3 style={{ margin: 0 }}>Sleeper</h3>
        <span className="small muted">league {sleeperLeagueId}</span>
        <span className="spacer" />
        <button className="primary" onClick={sync} disabled={busy} data-testid="sleeper-sync-button"
          title="download the league from Sleeper, then update managers, roster, scoring and keeper limit (before the draft) and refresh projections">
          {busy ? "Syncing…" : "Sync from Sleeper"}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {result && (
        <div className="sync-result" data-testid="sync-result">
          <div className="bid-label">Synced {when(result.synced_at)}</div>
          <ul className="guide-lines">
            {result.changes.map((c, i) => <li key={i}>{c}</li>)}
            <li>{result.keepers_set} keeper{result.keepers_set === 1 ? "" : "s"} set in Sleeper (filled in when you start the draft)</li>
            <li>{result.changelog_new.length ? `${result.changelog_new.length} new league activit${result.changelog_new.length === 1 ? "y" : "ies"} below` : "no new league activity"}</li>
          </ul>
        </div>
      )}
      <h3>League activity</h3>
      {!log.length && <p className="muted small">Nothing yet. Each sync logs Sleeper transactions (with their exact time) and anything that changed since the previous sync.</p>}
      <div className="activity" data-testid="league-activity">
        {shown.map((e) => (
          <div key={e.id} className="activity-row">
            <span className="activity-time" title={e.exact ? "exact time from Sleeper" : `changed sometime between ${when(e.since) || "an earlier sync"} and ${when(e.at)}`}>
              {when(e.at)}{!e.exact && <span className="muted"> · noticed</span>}
            </span>
            <span className={`badge ${e.kind === "trade" ? "warn" : e.kind === "keeper" ? "info" : ""}`} style={{ marginLeft: 0 }}>{KIND[e.kind] || e.kind}</span>
            <span>{e.who && <strong>{e.who} </strong>}{localize(e.text)}</span>
          </div>
        ))}
      </div>
      {log.length > 15 && <button className="small ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show less" : `Show all ${log.length}`}</button>}
    </div>
  );
}
