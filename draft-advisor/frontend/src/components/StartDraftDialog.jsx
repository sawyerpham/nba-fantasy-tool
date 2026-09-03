import React, { useState } from "react";
import { api } from "../api.js";
import PlayerSearch from "./PlayerSearch.jsx";

export default function StartDraftDialog({ leagueId, view, maxKeepers, onClose, onStarted }) {
  const managers = view?.managers || [];
  const [rows, setRows] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const add = () => setRows([...rows, { manager_id: managers[0]?.manager_id || "m1", player_id: null, player_name: "", cost: 1 }]);
  const update = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  const start = async () => {
    setError(""); setBusy(true);
    try {
      const keepers = rows.filter((r) => r.player_id).map((r) => ({ manager_id: r.manager_id, player_id: r.player_id, cost: Number(r.cost) }));
      const v = await api.post(`/leagues/${leagueId}/draft/start`, { keepers });
      onStarted(v);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} data-testid="start-dialog">
        <h3>Start the draft</h3>
        <p className="small">Keepers are recorded as the first picks at their cost (max {maxKeepers} per manager). Leave empty if nobody keeps anyone.</p>
        <table>
          <thead><tr><th>manager</th><th>player</th><th>cost $</th><th></th></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} data-testid={`keeper-row-${i}`}>
                <td>
                  <select value={r.manager_id} onChange={(e) => update(i, { manager_id: e.target.value })} data-testid={`keeper-manager-${i}`}>
                    {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name}</option>)}
                  </select>
                </td>
                <td>
                  {r.player_name ? <strong data-testid={`keeper-player-${i}`}>{r.player_name}</strong> : <em className="muted">none</em>}
                  <PlayerSearch leagueId={leagueId} onSelect={(p) => update(i, { player_id: p.player_id, player_name: p.full_name })} placeholder="find player…" testId={`keeper-search-${i}`} />
                </td>
                <td><input type="number" min="1" value={r.cost} onChange={(e) => update(i, { cost: e.target.value })} data-testid={`keeper-cost-${i}`} /></td>
                <td><button className="danger" onClick={() => setRows(rows.filter((_, j) => j !== i))}>remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={add} data-testid="keeper-add">Add keeper</button>
          <button className="primary" onClick={start} disabled={busy} data-testid="start-confirm">Start draft</button>
          <button onClick={onClose}>Cancel</button>
        </div>
        {error && <div className="error" data-testid="start-error">{error}</div>}
      </div>
    </div>
  );
}
