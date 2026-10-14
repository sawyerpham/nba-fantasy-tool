import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import SleeperSync from "../components/SleeperSync.jsx";
import PlayerSearch from "../components/PlayerSearch.jsx";
import useSaveShortcut from "../useSaveShortcut.js";

const PACES = ["early", "even", "late"];

function ManagersEditor({ leagueId, managers, draftStatus, reload }) {
  const [rows, setRows] = useState(managers);
  const [msg, setMsg] = useState("");
  const [names, setNames] = useState("");
  const [allBudget, setAllBudget] = useState("");
  const [allPace, setAllPace] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setRows(managers), [managers]);

  const dirty = useMemo(() => JSON.stringify(rows) !== JSON.stringify(managers), [rows, managers]);
  const update = (i, patch) => setRows((rs) => rs.map((m, j) => (j === i ? { ...m, ...patch } : m)));

  const patchBody = (m) => ({ name: m.name, is_user: m.is_user, budget_total: Number(m.budget_total), behavior: m.behavior });

  const saveRow = async (m) => {
    setMsg("");
    try {
      await api.patch(`/leagues/${leagueId}/managers/${m.manager_id}`, patchBody(m));
      setMsg(`Saved ${m.manager_id}`);
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };

  const saveAll = useCallback(async () => {
    if (!dirty || busy) return;
    setMsg(""); setBusy(true);
    try {
      if (draftStatus === "setup") {
        await api.put(`/leagues/${leagueId}/managers`, rows.map((m) => ({ ...m, budget_total: Number(m.budget_total) })));
      } else {
        for (const m of rows) await api.patch(`/leagues/${leagueId}/managers/${m.manager_id}`, patchBody(m));
      }
      setMsg(`Saved all ${rows.length} managers`);
      reload();
    } catch (e) {
      setMsg(e.message);
    } finally {
      setBusy(false);
    }
  }, [dirty, busy, draftStatus, leagueId, rows, reload]);
  useSaveShortcut(saveAll);

  const applyNames = () => {
    const list = names.split(/\r?\n|,|;/).map((s) => s.trim()).filter(Boolean);
    if (!list.length) return;
    setRows((rs) => rs.map((m, i) => (list[i] ? { ...m, name: list[i] } : m)));
    setNames("");
  };
  const applyAll = () => {
    setRows((rs) => rs.map((m) => ({
      ...m,
      budget_total: allBudget !== "" ? Number(allBudget) : m.budget_total,
      behavior: allPace ? { ...m.behavior, spend_pace: allPace } : m.behavior,
    })));
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
      <div className="row sticky-bar">
        <h3 style={{ margin: 0 }}>Managers ({rows.length})</h3>
        <button className="primary" onClick={saveAll} disabled={!dirty || busy} data-testid="managers-save-all">Save all (Ctrl+S)</button>
        {dirty && <span className="badge dirty">unsaved changes</span>}
        {msg && <span className="small">{msg}</span>}
      </div>
      <div className="grid2" style={{ marginBottom: 8 }}>
        <div>
          <div className="small muted">Paste names, one per line (or comma-separated), in manager order:</div>
          <textarea rows="3" style={{ width: "100%" }} value={names} onChange={(e) => setNames(e.target.value)} placeholder={"Bob\nTimmy\nOwen\n…"} data-testid="bulk-names" />
          <button onClick={applyNames} disabled={!names.trim()} data-testid="bulk-names-apply">Apply names</button>
        </div>
        <div>
          <div className="small muted">Set every manager at once:</div>
          <div className="row">
            <label className="inline">budget $<input type="number" value={allBudget} onChange={(e) => setAllBudget(e.target.value)} placeholder="200" data-testid="bulk-budget" /></label>
            <label className="inline">pace <select value={allPace} onChange={(e) => setAllPace(e.target.value)} data-testid="bulk-pace"><option value="">(keep)</option>{PACES.map((p) => <option key={p}>{p}</option>)}</select></label>
            <button onClick={applyAll} disabled={allBudget === "" && !allPace} data-testid="bulk-apply">Apply to all</button>
          </div>
          {draftStatus === "setup" && (
            <div className="row small" style={{ marginTop: 6 }}>
              Number of managers: <input type="number" min="2" max="30" defaultValue={rows.length} data-testid="manager-count"
                onBlur={(e) => Number(e.target.value) !== rows.length && setCount(Number(e.target.value))} />
              <span className="muted">(only while the draft is in setup)</span>
            </div>
          )}
        </div>
      </div>
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
    </div>
  );
}

function KeeperHistoryEditor({ leagueId, history, managers, reload }) {
  const [rows, setRows] = useState(history);
  const [msg, setMsg] = useState("");
  const [season, setSeason] = useState("2025-26");
  useEffect(() => setRows(history), [history]);
  const dirty = JSON.stringify(rows) !== JSON.stringify(history);
  const update = (i, patch) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const blank = (managerId) => ({ season, manager_id: managerId, player_id: 0, player_name: "", cost: { type: "auction", amount: 1, round: null, pick: null } });
  const add = () => setRows([...rows, blank("m1")]);
  const addAllManagers = () => setRows([...rows, ...managers.filter((m) => !rows.some((r) => r.season === season && r.manager_id === m.manager_id)).map((m) => blank(m.manager_id))]);
  const save = async () => {
    setMsg("");
    try {
      await api.put(`/leagues/${leagueId}/keepers/history`, { records: rows.filter((r) => r.player_id) });
      setMsg("Keeper history saved (rows without a player were dropped)");
      reload();
    } catch (e) {
      setMsg(e.message);
    }
  };
  const managerName = (id) => managers.find((m) => m.manager_id === id)?.name || id;
  return (
    <div className="panel">
      <h3>Keeper history (prior seasons) <span className="muted small">— what each keeper cost in that season; this year's keepers and their prices are entered when you start the draft</span></h3>
      <div className="row small" style={{ marginBottom: 6 }}>
        season <input type="text" value={season} onChange={(e) => setSeason(e.target.value)} style={{ width: 80, minWidth: 0 }} />
        <button onClick={addAllManagers} data-testid="history-add-all">Add a row for every manager</button>
        <span className="muted">then just pick each player and the price; empty rows are ignored</span>
      </div>
      <table>
        <thead><tr><th>season</th><th>manager</th><th>player</th><th>cost type</th><th>$ paid (auction) / round (draft)</th><th>pick</th><th></th></tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td><input type="text" value={r.season} onChange={(e) => update(i, { season: e.target.value })} style={{ width: 80, minWidth: 0 }} /></td>
              <td>
                <select value={r.manager_id} onChange={(e) => update(i, { manager_id: e.target.value })}>
                  {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name}</option>)}
                  {!managers.some((m) => m.manager_id === r.manager_id) && <option value={r.manager_id}>{r.manager_id}</option>}
                </select>
              </td>
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
      <div className="row"><button onClick={add}>Add row</button><button className="primary" onClick={save} disabled={!dirty}>Save history</button>{dirty && <span className="badge dirty">unsaved</span>}{msg && <span className="small">{msg}</span>}</div>
    </div>
  );
}

export default function LeaguePage({ leagueId, setLeagueId }) {
  const [leagues, setLeagues] = useState([]);
  const [doc, setDoc] = useState(null);
  const [newId, setNewId] = useState("");
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(() => new Set());   // leagues ticked for "Delete selected"

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

  const toggle = (id) => setPicked((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const mocks = leagues.filter((l) => l.league_id.startsWith("mock-")).map((l) => l.league_id);
  const removeMany = async () => {
    const ids = [...picked];
    if (!ids.length || !window.confirm(`Delete ${ids.length} league${ids.length > 1 ? "s" : ""}?\n\n${ids.join("\n")}`)) return;
    setError("");
    for (const id of ids) {
      try { await api.del(`/leagues/${id}`); } catch (e) { setError(`${id}: ${e.message}`); }
    }
    if (ids.includes(leagueId)) setLeagueId("");
    setPicked(new Set());
    loadList();
  };

  return (
    <div>
      <h2>Leagues</h2>
      {error && <div className="error">{error}</div>}
      <div className="panel">
        <table>
          <thead><tr>
            <th><input type="checkbox" checked={leagues.length > 0 && picked.size === leagues.length} title="select all"
              onChange={(e) => setPicked(new Set(e.target.checked ? leagues.map((l) => l.league_id) : []))} data-testid="league-pick-all" /></th>
            <th>id</th><th>name</th><th>status</th><th>managers</th><th>picks</th><th>season</th><th></th></tr></thead>
          <tbody>
            {leagues.map((l) => (
              <tr key={l.league_id} className={l.league_id === leagueId ? "selected" : ""}>
                <td><input type="checkbox" checked={picked.has(l.league_id)} onChange={() => toggle(l.league_id)} data-testid={`league-pick-${l.league_id}`} /></td>
                <td>{l.league_id}</td><td>{l.name}</td><td>{l.status}</td><td>{l.managers}</td><td>{l.picks}</td><td>{l.roster_season}</td>
                <td>
                  <button onClick={() => setLeagueId(l.league_id)} data-testid={`select-league-${l.league_id}`}>Select</button>{" "}
                  <button className="danger" onClick={() => remove(l.league_id)}>Delete</button>
                </td>
              </tr>
            ))}
            {!leagues.length && <tr><td colSpan="8" className="muted">No leagues yet — create one below.</td></tr>}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={() => setPicked(new Set(mocks))} disabled={!mocks.length} data-testid="league-pick-mocks">Select mock leagues ({mocks.length})</button>
          <button className="danger" onClick={removeMany} disabled={!picked.size} data-testid="league-delete-selected">Delete selected ({picked.size})</button>
        </div>
        <div className="row" style={{ marginTop: 8 }}>
          <input type="text" placeholder="league id (letters, digits, - _ .)" value={newId} onChange={(e) => setNewId(e.target.value)} data-testid="create-league-id" />
          <input type="text" placeholder="name" value={newName} onChange={(e) => setNewName(e.target.value)} data-testid="create-league-name" />
          <button className="primary" onClick={create} disabled={!newId.trim()} data-testid="create-league-submit">Create league (12 managers, SPEC defaults)</button>
        </div>
      </div>

      {doc && (
        <>
          <h2>{doc.league.name} <span className="muted small">({doc.league.league_id}, draft {doc.draft.status})</span></h2>
          <SleeperSync leagueId={leagueId} sleeperLeagueId={doc.league.sleeper_league_id} onSynced={loadDoc} />
          <ManagersEditor leagueId={leagueId} managers={doc.managers} draftStatus={doc.draft.status} reload={loadDoc} />
          <KeeperHistoryEditor leagueId={leagueId} history={doc.keepers.history} managers={doc.managers} reload={loadDoc} />
        </>
      )}
    </div>
  );
}
