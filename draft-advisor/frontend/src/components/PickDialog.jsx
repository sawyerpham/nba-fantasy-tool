import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// Record a winning bid: who won, at what price, into which slot (auto by default).
export default function PickDialog({ leagueId, view, player, onClose, onPicked }) {
  const managers = view?.managers || [];
  const user = managers.find((m) => m.is_user);
  const [managerId, setManagerId] = useState(user?.manager_id || managers[0]?.manager_id || "");
  const [price, setPrice] = useState(1);
  const [slot, setSlot] = useState("");
  const [rec, setRec] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const manager = managers.find((m) => m.manager_id === managerId);
  const maxBid = manager?.budget?.max_bid ?? 0;
  const slots = useMemo(() => Object.keys(manager?.open_slots || {}).filter((s) => s !== "IR"), [manager]);
  const clamp = (v) => Math.max(1, Math.min(Number(v) || 1, maxBid || 1));

  useEffect(() => {
    let cancelled = false;
    api.get(`/leagues/${leagueId}/recommend/${player.player_id}`).then((r) => {
      if (cancelled) return;
      setRec(r);
    }).catch(() => setRec(null));
    return () => { cancelled = true; };
  }, [leagueId, player.player_id]);

  useEffect(() => {
    // Prefill with the recommendation, capped by the selected manager's max bid.
    const suggested = rec?.recommended_max ?? 1;
    setPrice(Math.max(1, Math.min(suggested || 1, maxBid || 1)));
  }, [rec, maxBid]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const submit = async (e) => {
    e?.preventDefault();
    setError(""); setBusy(true);
    try {
      const v = await api.post(`/leagues/${leagueId}/draft/pick`, {
        player_id: player.player_id, manager_id: managerId, price: Number(price), slot: slot || null,
      });
      onPicked(v);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit} data-testid="pick-dialog">
        <h3>Mark drafted: {player.full_name} <span className="muted small">{player.team_abbr}</span></h3>
        {rec && (
          <p className="small">
            Pay up to <strong data-testid="pick-recommended">${rec.recommended_max}</strong> (for {user?.name || "you"}) · fair value ${Math.round(rec.fair_value)} · your cap ${rec.my_max_bid}
            {!rec.can_bid && <span className="badge warn">you cannot bid: {rec.rationale[rec.rationale.length - 1]}</span>}
          </p>
        )}
        <div className="grid2">
          <label>Winning manager
            <select value={managerId} onChange={(e) => setManagerId(e.target.value)} data-testid="pick-manager">
              {managers.map((m) => <option key={m.manager_id} value={m.manager_id}>{m.name} (${m.budget.remaining} left, max ${m.budget.max_bid})</option>)}
            </select>
          </label>
          <label>Price $
            <input type="number" min="1" max={maxBid} value={price} onChange={(e) => setPrice(e.target.value)} data-testid="pick-price" autoFocus />
            <span className="small muted"> max for this manager: <span data-testid="pick-max-bid">${maxBid}</span></span>
            <div className="row" style={{ marginTop: 4 }}>
              <button type="button" className="small" onClick={() => setPrice(clamp(rec?.recommended_max ?? 1))} disabled={!rec} title="recommended max">rec</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(maxBid))} title="this manager's max bid">max</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) - 1))}>−1</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) + 1))}>+1</button>
              <button type="button" className="small" onClick={() => setPrice(clamp(Number(price) + 5))}>+5</button>
              <button type="button" className="small" onClick={() => setPrice(1)}>$1</button>
            </div>
          </label>
          <label>Slot
            <select value={slot} onChange={(e) => setSlot(e.target.value)} data-testid="pick-slot">
              <option value="">auto (most specific open slot)</option>
              {slots.map((s) => <option key={s} value={s}>{s} ({manager.open_slots[s]} open)</option>)}
            </select>
          </label>
        </div>
        {error && <div className="error" data-testid="pick-error">{error}</div>}
        <div className="row" style={{ marginTop: 10 }}>
          <button type="submit" className="primary" disabled={busy || !managerId} data-testid="pick-submit">Record pick (Enter)</button>
          <button type="button" onClick={onClose}>Cancel (Esc)</button>
        </div>
      </form>
    </div>
  );
}
