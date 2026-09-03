import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// Fix "who drafted whom": move a recorded pick to another manager, change its price or slot, or remove it.
export default function EditPickDialog({ leagueId, view, pick, minBid = 1, onClose, onSaved }) {
  const managers = view?.managers || [];
  const [managerId, setManagerId] = useState(pick.manager_id);
  const [price, setPrice] = useState(pick.price);
  const [slot, setSlot] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Max this manager could pay for this pick: their max bid, plus this pick's own money when it is already theirs.
  const maxFor = (m) => (m.manager_id === pick.manager_id
    ? m.budget.remaining + pick.price - minBid * m.budget.open_mandatory
    : m.budget.max_bid);
  const manager = managers.find((m) => m.manager_id === managerId);
  const maxBid = manager ? Math.max(minBid, maxFor(manager)) : minBid;
  const slots = useMemo(() => {
    if (!manager) return [];
    const open = Object.entries(manager.open_slots).filter(([s, n]) => s !== "IR" && n > 0).map(([s]) => s);
    if (manager.manager_id === pick.manager_id && !open.includes(pick.slot)) open.unshift(pick.slot);
    return open;
  }, [manager, pick]);
  const clamp = (v) => Math.max(minBid, Math.min(Number(v) || minBid, maxBid));

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const save = async (e) => {
    e?.preventDefault();
    setError(""); setBusy(true);
    try {
      const body = { manager_id: managerId, price: Number(price) };
      if (slot) body.slot = slot;
      onSaved(await api.patch(`/leagues/${leagueId}/draft/picks/${pick.pick_number}`, body));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!window.confirm(`Remove pick #${pick.pick_number} (${pick.player_name})? The player becomes available again.`)) return;
    setError(""); setBusy(true);
    try {
      onSaved(await api.del(`/leagues/${leagueId}/draft/picks/${pick.pick_number}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={save} data-testid="edit-pick-dialog">
        <h3>Pick #{pick.pick_number}: {pick.player_name} <span className="muted small">{pick.team_abbr}{pick.is_keeper ? " · keeper" : ""}</span></h3>
        <div className="grid2">
          <label>Drafted by
            <select value={managerId} onChange={(e) => { setManagerId(e.target.value); setSlot(""); }} data-testid="edit-pick-manager">
              {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} (${m.budget.remaining} left, max ${Math.max(minBid, maxFor(m))})</option>)}
            </select>
          </label>
          <label>Price $
            <input type="number" min={minBid} max={maxBid} value={price} onChange={(e) => setPrice(e.target.value)} data-testid="edit-pick-price" autoFocus />
            <span className="small muted"> max for this manager: ${maxBid}</span>
            <div className="row" style={{ marginTop: 4 }}>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) - 1))}>−1</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) + 1))}>+1</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) + 5))}>+5</button>
              <button type="button" className="small" onClick={() => setPrice(minBid)}>${minBid}</button>
            </div>
          </label>
          <label>Slot
            <select value={slot} onChange={(e) => setSlot(e.target.value)} data-testid="edit-pick-slot">
              <option value="">auto (keep {managerId === pick.manager_id ? pick.slot : "the most specific open slot"})</option>
              {slots.map((s) => <option key={s} value={s}>{s}{manager?.open_slots[s] ? ` (${manager.open_slots[s]} open)` : ""}</option>)}
            </select>
          </label>
        </div>
        {error && <div className="error" data-testid="edit-pick-error">{error}</div>}
        <div className="row" style={{ marginTop: 10 }}>
          <button type="submit" className="primary" disabled={busy} data-testid="edit-pick-save">Save (Enter)</button>
          <button type="button" onClick={onClose}>Cancel (Esc)</button>
          <button type="button" className="danger" onClick={remove} disabled={busy} style={{ marginLeft: "auto" }} data-testid="edit-pick-remove">Remove pick</button>
        </div>
      </form>
    </div>
  );
}
