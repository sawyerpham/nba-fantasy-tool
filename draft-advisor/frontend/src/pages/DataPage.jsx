import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";

function Reports({ reports }) {
  if (!reports || !reports.length) return null;
  return (
    <table>
      <thead>
        <tr><th>source</th><th>operation</th><th>calls</th><th>from cache</th><th>requested</th><th>succeeded</th><th>failed</th></tr>
      </thead>
      <tbody>
        {reports.map((r, i) => (
          <tr key={i}>
            <td>{r.source}</td><td>{r.operation}</td><td>{r.endpoint_calls}</td>
            <td>{r.served_from_cache ? "yes" : "no"}</td><td>{r.requested}</td><td>{r.succeeded}</td>
            <td>{Object.keys(r.failed || {}).length ? <details><summary>{Object.keys(r.failed).length}</summary><pre>{JSON.stringify(r.failed, null, 1)}</pre></details> : 0}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function NameList({ title, rows, fmt }) {
  if (!rows || !rows.length) return <p className="muted">{title}: none</p>;
  return (
    <details open={rows.length <= 12}>
      <summary>{title}: {rows.length}</summary>
      <ul className="small">{rows.map((r, i) => <li key={i}>{fmt(r)}</li>)}</ul>
    </details>
  );
}

export default function DataPage({ onPoolChanged }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState("");
  const [sources, setSources] = useState({ nba_api: true, sleeper: true });
  const [forceSleeper, setForceSleeper] = useState(false);
  const [skipLogs, setSkipLogs] = useState(false);

  const refresh = useCallback(() => api.get("/data/status").then(setStatus).catch((e) => setError(e.message)), []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const running = status?.pull?.state === "running";
  useEffect(() => {
    if (!running) return undefined;
    const t = setInterval(refresh, 1000);
    return () => clearInterval(t);
  }, [running, refresh]);

  useEffect(() => {
    if (status?.pull?.state === "done") onPoolChanged?.();
  }, [status?.pull?.state, onPoolChanged]);

  const startPull = async () => {
    setError("");
    try {
      await api.post("/data/pull", {
        sources: Object.keys(sources).filter((k) => sources[k]),
        force_sleeper: forceSleeper,
        skip_game_logs: skipLogs,
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  };

  const pull = status?.pull || {};
  const prog = pull.progress;
  const rep = status?.reconcile;
  const caches = status?.caches || {};

  return (
    <div>
      <h2>Data pull</h2>
      <div className="panel">
        <div className="row">
          <label className="inline"><input type="checkbox" checked={sources.nba_api} onChange={(e) => setSources({ ...sources, nba_api: e.target.checked })} /> nba_api (pool + game logs)</label>
          <label className="inline"><input type="checkbox" checked={sources.sleeper} onChange={(e) => setSources({ ...sources, sleeper: e.target.checked })} /> Sleeper (eligibility + injuries)</label>
          <label className="inline"><input type="checkbox" checked={forceSleeper} onChange={(e) => setForceSleeper(e.target.checked)} /> force Sleeper re-fetch (bypass 24 h guard)</label>
          <label className="inline"><input type="checkbox" checked={skipLogs} onChange={(e) => setSkipLogs(e.target.checked)} /> skip game logs</label>
          <button className="primary" onClick={startPull} disabled={running} data-testid="pull-button">Pull now</button>
          <button onClick={refresh}>Refresh</button>
        </div>
        {error && <div className="error">{error}</div>}
        <p>
          State: <strong data-testid="pull-state">{pull.state || "idle"}</strong>
          {pull.phase && <> · phase: {pull.phase}</>}
          {pull.error && <span className="error"> · {pull.error}</span>}
        </p>
        {prog && (
          <div className="row">
            <div className="progress"><div style={{ width: `${prog.total ? Math.round((100 * prog.done) / prog.total) : 0}%` }} /></div>
            <span className="small">{prog.done} / {prog.total} {prog.current_label} {prog.failed ? `· ${prog.failed} failed` : ""}</span>
          </div>
        )}
        <Reports reports={pull.reports} />
        {pull.state === "done" && (
          <p className="ok">Done: {pull.records} players reconciled, {pull.game_log_players} with game logs, {pull.seeded_overrides} overrides seeded.</p>
        )}
      </div>

      <h2>Cache status</h2>
      <div className="panel small">
        <div>Roster season {status?.roster_season} · stats season {status?.stats_season} · {status?.players ?? 0} players in pool · {status?.overrides ?? 0} overrides</div>
        <div>
          Ages (hours): nba pool {caches.nba_player_pool_hours ?? "—"} · game logs {caches.game_logs_hours ?? "—"} · Sleeper players {caches.sleeper_players_hours ?? "—"} · reconcile {caches.reconcile_hours ?? "—"}
        </div>
      </div>

      <h2>Reconcile report</h2>
      <div className="panel">
        {!rep && <p className="muted">No pull yet.</p>}
        {rep && (
          <>
            <p className="small">
              Run {rep.run_at} · nba pool {rep.nba_pool_size} · Sleeper file {rep.sleeper_all_size} (rostered {rep.sleeper_rostered_size}) · matches by stage: {Object.entries(rep.counts).map(([k, v]) => `${k}=${v}`).join(", ")}
            </p>
            <NameList title="Team conflicts (Sleeper wins)" rows={rep.team_conflicts} fmt={(r) => `${r.name}: NBA.com ${r.nba_api} vs Sleeper ${r.sleeper}`} />
            <NameList title="Unsigned per Sleeper (NBA.com still lists a team)" rows={rep.unsigned_per_sleeper} fmt={(r) => `${r.name} (${r.nba_team}, Sleeper ${r.sleeper_status})`} />
            <NameList title="Name collisions" rows={rep.collisions} fmt={(r) => `${r.name}: ${r.resolved ? "resolved by birthdate" : "UNRESOLVED"} (${r.candidates.length} candidates)`} />
            <NameList title="NBA.com players without a Sleeper match (no eligibility seed)" rows={rep.unmatched_nba} fmt={(r) => `${r.name} (${r.team}) — ${r.reason}`} />
            <NameList title="Sleeper players without NBA.com stats" rows={rep.unmatched_sleeper} fmt={(r) => `${r.name} (${r.team}, ${r.status}) — ${r.reason}`} />
          </>
        )}
      </div>
    </div>
  );
}
