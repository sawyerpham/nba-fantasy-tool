import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import PlayerSearch from "./PlayerSearch.jsx";

const VERDICT = {
  good: { label: "GOOD keep", cls: "good" },
  even: { label: "EVEN", cls: "even" },
  bad: { label: "BAD keep", cls: "bad" },
};

function Verdict({ ev }) {
  if (!ev) return null;
  const v = VERDICT[ev.verdict] || VERDICT.even;
  return (
    <span className={`verdict ${v.cls}`} data-testid="keeper-verdict" title={ev.note}>
      {v.label}: ${ev.keeper_price} vs fair ${ev.fair_value.toFixed(0)} ({ev.surplus >= 0 ? "+" : "−"}${Math.abs(ev.surplus).toFixed(0)})
      {ev.rank ? ` · rank #${ev.rank}` : ""}{!ev.affordable ? " · over max bid!" : ""}
    </span>
  );
}

const emptyRow = (managerId) => ({ manager_id: managerId, player_id: null, player_name: "", last_price: "", cost: "", costTouched: false, ev: null });

// One row per manager (× keeper limit) is pre-filled: pick the player, type LAST year's price, done.
// This year's price follows the league escalation rule (editable) and gets a keep / let-go verdict.
export default function StartDraftDialog({ leagueId, view, keeperSettings, onClose, onStarted }) {
  const managers = view?.managers || [];
  const perManager = Math.max(1, keeperSettings?.max_per_manager ?? 1);
  const [rows, setRows] = useState(() => managers.flatMap((m) => Array.from({ length: perManager }, () => emptyRow(m.manager_id))));
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);
  const esc = keeperSettings?.escalation;
  const ruleText = esc && esc.enabled ? `+$${esc.increase_per_step} per full $${esc.step_dollars} of last year's price` : "no escalation";
  const entered = rows.filter((r) => r.player_id).length;

  const update = (i, patch) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const focus = (testId) => setTimeout(() => document.querySelector(`[data-testid="${testId}"]`)?.focus(), 0);

  const evaluate = useCallback(async (current) => {
    const candidates = current
      .map((r, i) => ({ i, r }))
      .filter(({ r }) => r.player_id && r.last_price !== "")
      .map(({ i, r }) => ({ i, manager_id: r.manager_id, player_id: r.player_id, last_price: Number(r.last_price),
        keeper_price: r.costTouched && r.cost !== "" ? Number(r.cost) : null }));
    if (!candidates.length) return;
    try {
      const evs = await api.post(`/leagues/${leagueId}/keepers/evaluate`, { candidates: candidates.map(({ i, ...c }) => c) });
      setRows((rs) => rs.map((r, idx) => {
        const k = candidates.findIndex((c) => c.i === idx);
        if (k < 0) return r;
        const ev = evs[k];
        return { ...r, ev, cost: r.costTouched ? r.cost : String(ev.computed_price) };
      }));
    } catch (e) {
      setError(e.message);
    }
  }, [leagueId]);

  const key = rows.map((r) => `${r.manager_id}|${r.player_id}|${r.last_price}|${r.costTouched ? r.cost : ""}`).join(";");
  useEffect(() => {
    clearTimeout(timer.current);
    timer.current = setTimeout(() => evaluate(rows), 250);
    return () => clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, evaluate]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const start = async () => {
    setError(""); setBusy(true);
    try {
      const keepers = rows.filter((r) => r.player_id).map((r) => ({ manager_id: r.manager_id, player_id: r.player_id, cost: Number(r.cost || 1) }));
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
      <div className="modal" style={{ minWidth: 820 }} onClick={(e) => e.stopPropagation()} data-testid="start-dialog">
        <h3>Keepers &amp; start the draft <span className="badge" data-testid="keepers-entered">{entered} keeper{entered === 1 ? "" : "s"} entered</span></h3>
        <p className="small">
          One row per manager{perManager > 1 ? ` (${perManager} each, the league's keeper limit)` : ""}. Find the player, type <strong>last year's price</strong>; this year's price follows the league rule ({ruleText}) and can be overridden. Rows without a player are ignored.
        </p>
        <table>
          <thead><tr><th>manager</th><th>player</th><th>last year $</th><th>this year $</th><th>keep?</th><th></th></tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const m = managers.find((x) => x.manager_id === r.manager_id);
              return (
                <tr key={i} data-testid={`keeper-row-${i}`} className={r.player_id ? "" : "unrosterable"}>
                  <td>
                    <strong>{m?.name || r.manager_id}</strong>
                    <select value={r.manager_id} onChange={(e) => update(i, { manager_id: e.target.value })} data-testid={`keeper-manager-${i}`} className="small" style={{ marginLeft: 4 }} title="change manager">
                      {managers.map((x) => <option key={x.manager_id} value={x.manager_id}>{x.manager_id}</option>)}
                    </select>
                  </td>
                  <td>
                    {r.player_name ? <strong data-testid={`keeper-player-${i}`}>{r.player_name} </strong> : null}
                    <PlayerSearch leagueId={leagueId} onSelect={(p) => { update(i, { player_id: p.player_id, player_name: p.full_name }); focus(`keeper-last-${i}`); }}
                      placeholder={r.player_name ? "change…" : "find player…"} testId={`keeper-search-${i}`} />
                  </td>
                  <td>
                    <input type="number" min="0" value={r.last_price} placeholder="e.g. 17" onChange={(e) => update(i, { last_price: e.target.value })} data-testid={`keeper-last-${i}`}
                      onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); focus(`keeper-search-${i + 1}`); } }} />
                  </td>
                  <td>
                    <input type="number" min="1" value={r.cost} placeholder="auto" onChange={(e) => update(i, { cost: e.target.value, costTouched: true })} data-testid={`keeper-cost-${i}`} />
                    {r.costTouched && r.ev && Number(r.cost) !== r.ev.computed_price && (
                      <button type="button" className="small" title="use the rule's price" onClick={() => update(i, { cost: String(r.ev.computed_price), costTouched: false })}>rule: ${r.ev.computed_price}</button>
                    )}
                  </td>
                  <td><Verdict ev={r.ev} /></td>
                  <td>{r.player_id && <button className="small" onClick={() => update(i, emptyRow(r.manager_id))} title="clear this row">clear</button>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="row" style={{ marginTop: 8 }}>
          <button onClick={() => setRows([...rows, emptyRow(managers[0]?.manager_id || "m1")])} data-testid="keeper-add">Add extra row</button>
          <button className="primary" onClick={start} disabled={busy} data-testid="start-confirm">Start draft{entered ? ` with ${entered} keeper${entered === 1 ? "" : "s"}` : " (no keepers)"}</button>
          <button onClick={onClose}>Cancel (Esc)</button>
        </div>
        {error && <div className="error" data-testid="start-error">{error}</div>}
      </div>
    </div>
  );
}
