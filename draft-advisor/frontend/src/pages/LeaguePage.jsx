import React, { useCallback, useEffect, useState } from "react";
import { api } from "../api.js";
import PlayerSearch from "../components/PlayerSearch.jsx";

const PACES = ["early", "even", "late"];

function ManagersEditor({ leagueId, managers, draftStatus, reload }) {
  const [rows, setRows] = useState(managers);
  const [msg, setMsg] = useState("");
  useEffect(() => setRows(managers), [managers]);

  const update = (i, patch) => setRows(rows.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  const saveRow = async (m) => {
    setMsg("");
    try {
      await api.patch(`/leagues/${leagueId}/managers/${m.manager_id}`, {
        name: m.name, is_user: m.is_user, budget_total: Number(m.budget_total), behavior: m.behavior,
      });
      setMsg(`Saved ${m.manager_id}`);
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };

  const setCount = async (n) => {
    setMsg("");
    const budget = rows[0]?.budget_total ?? 200;
    const next = Array.from({ length: n }, (_, i) => rows[i] || {
      manager_id: `m${i + 1}`, name: `Manager ${i + 1}`, is_user: false, budget_total: budget,
      behavior: { spend_pace: "even", aggression: 1.0 },
    });
    if (!next.some((m) => m.is_user)) next[0].is_user = true;
    try {
      await api.put(`/leagues/${leagueId}/managers`, next);
      setMsg(`Now ${n} managers`);
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };

  return (
    <div className="panel">
      <h3>Managers ({rows.length})</h3>
      {draftStatus === "setup" && (
        <div className="row small">
          Number of managers: <input type="number" min="2" max="30" defaultValue={rows.length} data-testid="manager-count"
            onBlur={(e) => Number(e.target.value) !== rows.length && setCount(Number(e.target.value))} />
          <span className="muted">(only while the draft is in setup)</span>
        </div>
      )}
      <table>
        <thead><tr><th>id</th><th>name</th><th>you</th><th>budget</th><th>spend pace</th><th>aggression</th><th></th></tr></thead>
        <tbody>
          {rows.map((m, i) => (
            <tr key={m.manager_id} data-testid={`manager-row-${m.manager_id}`}>
              <td>{m.manager_id}</td>
              <td><input type="text" value={m.name} onChange={(e) => update(i, { name: e.target.value })} /></td>
              <td><input type="radio" name="is_user" checked={!!m.is_user} onChange={() => setRows(rows.map((x, j) => ({ ...x, is_user: j === i })))} /></td>
              <td><input type="number" value={m.budget_total} onChange={(e) => update(i, { budget_total: e.target.value })} /></td>
              <td>
                <select value={m.behavior?.spend_pace || "even"} onChange={(e) => update(i, { behavior: { ...m.behavior, spend_pace: e.target.value } })}>
                  {PACES.map((p) => <option key={p}>{p}</option>)}
                </select>
              </td>
              <td><input type="number" step="0.1" value={m.behavior?.aggression ?? 1} onChange={(e) => update(i, { behavior: { ...m.behavior, aggression: Number(e.target.value) } })} /></td>
              <td><button onClick={() => saveRow(m)}>Save</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {msg && <div className="small">{msg}</div>}
    </div>
  );
}

function KeeperHistoryEditor({ leagueId, history, reload }) {
  const [rows, setRows] = useState(history);
  const [msg, setMsg] = useState("");
  useEffect(() => setRows(history), [history]);
  const update = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const add = () => setRows([...rows, { season: "2025-26", manager_id: "m1", player_id: 0, player_name: "", cost: { type: "auction", amount: 1, round: null, pick: null } }]);
  const save = async () => {
    setMsg("");
    try {
      await api.put(`/leagues/${leagueId}/keepers/history`, { records: rows });
      setMsg("Keeper history saved");
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };
  return (
    <div className="panel">
      <h3>Keeper history (prior seasons)</h3>
      <table>
        <thead><tr><th>season</th><th>manager</th><th>player</th><th>cost type</th><th>$ / round</th><th>pick</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input type="text" value={r.season} onChange={(e) => update(i, { season: e.target.value })} style={{ width: 80 }} /></td>
              <td><input type="text" value={r.manager_id} onChange={(e) => update(i, { manager_id: e.target.value })} style={{ width: 60 }} /></td>
              <td>
                {r.player_name || <em className="muted">pick a player</em>} <span className="muted small">#{r.player_id || "?"}</span>
                <PlayerSearch onSelect={(p) => update(i, { player_id: p.player_id, player_name: p.full_name })} placeholder="find…" testId={`keeper-history-search-${i}`} />
              </td>
              <td>
                <select value={r.cost.type} onChange={(e) => update(i, { cost: { ...r.cost, type: e.target.value } })}>
                  <option value="auction">auction $</option><option value="draft">draft round/pick</option>
                </select>
              </td>
              <td>
                {r.cost.type === "auction"
                  ? <input type="number" value={r.cost.amount ?? ""} onChange={(e) => update(i, { cost: { ...r.cost, amount: Number(e.target.value) } })} />
                  : <input type="number" value={r.cost.round ?? ""} onChange={(e) => update(i, { cost: { ...r.cost, round: Number(e.target.value) } })} />}
              </td>
              <td>{r.cost.type === "draft" && <input type="number" value={r.cost.pick ?? ""} onChange={(e) => update(i, { cost: { ...r.cost, pick: Number(e.target.value) } })} />}</td>
              <td><button className="danger" onClick={() => setRows(rows.filter((_, j) => j !== i))}>remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row"><button onClick={add}>Add row</button><button className="primary" onClick={save}>Save history</button>{msg && <span className="small">{msg}</span>}</div>
    </div>
  );
}

export default function LeaguePage({ leagueId, setLeagueId }) {
  const [leagues, setLeagues] = useState([]);
  const [doc, setDoc] = useState(null);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");

  const loadList = useCallback(() => api.get("/leagues").then(setLeagues).catch((e) => setError(e.message)), []);
  const loadDoc = useCallback(() => {
    if (!leagueId) return setDoc(null);
    return api.get(`/leagues/${leagueId}`).then(setDoc).catch((e) => { setError(e.message); setDoc(null); });
  }, [leagueId]);

  useEffect(() => { loadList(); }, [loadList]);
  useEffect(() => { loadDoc(); }, [loadDoc]);

  const create = async () => {
    setError("");
    try {
      await api.post("/leagues", { league_id: newId.trim(), name: newName.trim() || newId.trim() });
      setNewId(""); setNewName("");
      await loadList();
      setLeagueId(newId.trim());
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async (id) => {
    if (!window.confirm(`Delete league ${id}?`)) return;
    await api.del(`/leagues/${id}`);
    if (id === leagueId) setLeagueId("");
    loadList();
  };

  return (
    <div>
      <h2>Leagues</h2>
      {error && <div className="error">{error}</div>}
      <div className="panel">
        <table>
          <thead><tr><th>id</th><th>name</th><th>status</th><th>managers</th><th>picks</th><th>season</th><th></th></tr></thead>
          <tbody>
            {leagues.map((l) => (
              <tr key={l.league_id} className={l.league_id === leagueId ? "selected" : ""}>
                <td>{l.league_id}</td><td>{l.name}</td><td>{l.status}</td><td>{l.managers}</td><td>{l.picks}</td><td>{l.roster_season}</td>
                <td>
                  <button onClick={() => setLeagueId(l.league_id)} data-testid={`select-league-${l.league_id}`}>Select</button>{" "}
                  <button className="danger" onClick={() => remove(l.league_id)}>Delete</button>
                </td>
              </tr>
            ))}
            {!leagues.length && <tr><td colSpan="7" className="muted">No leagues yet — create one below.</td></tr>}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <input type="text" placeholder="league id (letters, digits, - _ .)" value={newId} onChange={(e) => setNewId(e.target.value)} data-testid="create-league-id" />
          <input type="text" placeholder="name" value={newName} onChange={(e) => setNewName(e.target.value)} data-testid="create-league-name" />
          <button className="primary" onClick={create} disabled={!newId.trim()} data-testid="create-league-submit">Create league (12 managers, SPEC defaults)</button>
        </div>
      </div>

      {doc && (
        <>
          <h2>{doc.league.name} <span className="muted small">({doc.league.league_id}, draft {doc.draft.status})</span></h2>
          <ManagersEditor leagueId={leagueId} managers={doc.managers} draftStatus={doc.draft.status} reload={loadDoc} />
          <KeeperHistoryEditor leagueId={leagueId} history={doc.keepers.history} reload={loadDoc} />
        </>
      )}
    </div>
  );
}
