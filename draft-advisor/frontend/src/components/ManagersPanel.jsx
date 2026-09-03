import React, { useState } from "react";

// Managers with budgets, open slots, stacks and picks. Picks are chips: drag one onto another manager's
// card to change who drafted the player; click it to edit the manager, price or slot, or remove it.
export default function ManagersPanel({ managers, onEditPick, onMovePick }) {
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);
  if (!managers) return null;
  const editable = Boolean(onEditPick);

  return (
    <div className="panel scroll" data-testid="managers-panel">
      <h3>Managers {editable && <span className="small muted">(drag a pick to another manager to move it, click it to edit)</span>}</h3>
      {managers.map((m) => {
        const b = m.budget;
        const openSlots = Object.entries(m.open_slots).filter(([, n]) => n > 0).map(([s, n]) => `${s}${n > 1 ? "×" + n : ""}`).join(" ");
        const stacks = Object.entries(m.stack).sort((a, b2) => b2[1] - a[1]);
        const canDrop = dragging && dragging.manager_id !== m.manager_id;
        return (
          <div
            key={m.manager_id}
            className={`manager-card ${m.is_next_nominator ? "next" : ""} ${m.is_user ? "user" : ""} ${over === m.manager_id && canDrop ? "over" : ""}`}
            data-testid={`manager-card-${m.manager_id}`}
            onDragOver={(e) => { if (canDrop) { e.preventDefault(); if (over !== m.manager_id) setOver(m.manager_id); } }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); if (canDrop) onMovePick?.(dragging, m.manager_id); setDragging(null); setOver(null); }}
          >
            <div className="row">
              <strong>{m.name}</strong> <span className="muted small">{m.manager_id}</span>
              {m.is_user && <span className="badge info">YOU</span>}
              {m.is_next_nominator && <span className="badge">nominates next</span>}
              <span className="small muted">{m.behavior.spend_pace}{m.behavior.aggression !== 1 ? ` ×${m.behavior.aggression}` : ""}</span>
            </div>
            <div className="small">
              <span data-testid={`remaining-${m.manager_id}`}>${b.remaining}</span> left · max bid <strong data-testid={`maxbid-${m.manager_id}`}>${b.max_bid}</strong> · {b.open_mandatory} mandatory slot{b.open_mandatory === 1 ? "" : "s"} open (${b.reserved} reserved)
            </div>
            <div className="small">Open: {openSlots || "none"}</div>
            {stacks.length > 0 && (
              <div className="small">Stacks: {stacks.map(([t, n]) => <span key={t} className={`badge ${n >= 3 ? "warn" : ""}`}>{t} ×{n}</span>)}</div>
            )}
            {m.picks.length > 0 && (
              <div className="small">
                {m.picks.map((p) => (
                  <span
                    key={p.pick_number}
                    className={`pick-chip ${editable ? "editable" : ""} ${dragging?.pick_number === p.pick_number ? "dragging" : ""}`}
                    draggable={editable}
                    title={editable ? "drag to another manager to move · click to edit" : ""}
                    onDragStart={(e) => { setDragging(p); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(p.pick_number)); }}
                    onDragEnd={() => { setDragging(null); setOver(null); }}
                    onClick={() => editable && onEditPick(p)}
                    data-testid={`pick-chip-${p.pick_number}`}
                  >
                    <span className="muted">{p.slot}</span> {p.player_name} <span className="muted">{p.team_abbr}</span> ${p.price}{p.is_keeper ? " (K)" : ""}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
