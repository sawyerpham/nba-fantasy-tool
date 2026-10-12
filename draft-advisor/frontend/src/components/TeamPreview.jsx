import React, { useState } from "react";

// One manager's roster laid out slot by slot (PG, PG, SG, ... BN), empty spots shown as dashes.
// Click a filled spot to edit that pick; drag it onto a manager row (Managers panel) to move it.
export default function TeamPreview({ managers, rosterSlots, managerId, onPick, onEditPick, onDragPick }) {
  const [dragging, setDragging] = useState(null);
  const m = managers?.find((x) => x.manager_id === managerId) || managers?.find((x) => x.is_user);
  if (!m) return null;
  const slots = (rosterSlots || []).filter((s) => s.slot !== "IR");
  const bySlot = {};
  for (const p of m.picks) (bySlot[p.slot] ||= []).push(p);
  const b = m.budget;

  return (
    <div className="panel" data-testid="team-preview">
      <div className="row" style={{ marginBottom: 6 }}>
        <h3 style={{ margin: 0 }}>Team</h3>
        <select value={m.manager_id} onChange={(e) => onPick(e.target.value)} data-testid="team-preview-manager">
          {managers.map((x) => <option key={x.manager_id} value={x.manager_id}>{x.name}{x.is_user ? " (you)" : ""}</option>)}
        </select>
      </div>
      <div className="small muted" style={{ marginBottom: 6 }}>
        <strong style={{ color: "var(--text)" }}>${b.remaining}</strong> left · max bid <strong style={{ color: "var(--text)" }}>${b.max_bid}</strong> · {b.open_mandatory} open
      </div>
      <div className="team-slots">
        {slots.flatMap((s) => Array.from({ length: s.count }, (_, i) => {
          const p = (bySlot[s.slot] || [])[i];
          return (
            <div key={`${s.slot}-${i}`} className={`team-slot ${p ? "filled" : ""} ${s.slot === "BN" ? "bench" : ""}`}>
              <span className="team-slot-pos">{s.slot}</span>
              {p ? (
                <span
                  className={`team-slot-player ${onEditPick ? "editable" : ""} ${dragging === p.pick_number ? "dragging" : ""}`}
                  draggable={Boolean(onEditPick)}
                  onDragStart={(e) => { setDragging(p.pick_number); onDragPick?.(p); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(p.pick_number)); }}
                  onDragEnd={() => { setDragging(null); onDragPick?.(null); }}
                  onClick={() => onEditPick?.(p)}
                  title={onEditPick ? "click to edit · drag onto a manager to move" : ""}
                  data-testid={`pick-chip-${p.pick_number}`}
                >
                  {p.player_name} <span className="muted">{p.team_abbr}</span><span className="spacer" /><strong>${p.price}</strong>{p.is_keeper ? <span className="muted"> K</span> : null}
                </span>
              ) : <span className="muted">—</span>}
            </div>
          );
        }))}
      </div>
    </div>
  );
}
