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
      <h3>Managers</h3>
      {editable && <div className="small muted" style={{ marginTop: -4, marginBottom: 10 }}>Drag a pick to another manager to move it · click to edit</div>}
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
              <strong>{m.name}</strong>
              {m.is_user && <span className="badge info">YOU</span>}
              {m.is_next_nominator && <span className="badge">up next</span>}
              <span className="spacer" />
              <span className="small muted">{m.behavior.spend_pace}{m.behavior.aggression !== 1 ? ` ×${m.behavior.aggression}` : ""}</span>
            </div>
            <div className="manager-money">
              <span><span className="big" data-testid={`remaining-${m.manager_id}`}>${b.remaining}</span> <span className="small muted">left</span></span>
              <span className="small muted">max bid <strong style={{ color: "var(--text)" }} data-testid={`maxbid-${m.manager_id}`}>${b.max_bid}</strong></span>
              <span className="small muted">{b.open_mandatory} slot{b.open_mandatory === 1 ? "" : "s"} open (${b.reserved} reserved)</span>
            </div>
            <div className="small muted">Needs: {openSlots || "none"}</div>
            {m.tendency && (
              <div className="small muted" data-testid={`tendency-${m.manager_id}`} title="how they spent in last season's auction">
                Last year: <span className={`badge ${m.tendency.style === "star chaser" ? "warn" : m.tendency.style === "new" ? "info" : ""}`} style={{ marginLeft: 0 }}>{m.tendency.style === "new" ? "new, no history" : m.tendency.style}</span>
                {m.tendency.top_buys.length > 0 && " " + m.tendency.top_buys.map((t) => `${t.name.split(" ").slice(-1)[0]} $${t.price}`).join(", ")}
                {m.tendency.favorite_teams?.length > 0 && <span className="badge info" title="drafted 5+ players from this team across your linked leagues">{m.tendency.favorite_teams.join("/")} fan</span>}
                {m.tendency.lean && <span className="badge" title="average experience of their earliest picks">likes {m.tendency.lean}</span>}
              </div>
            )}
            {stacks.length > 0 && (
              <div className="small muted">Stacks: {stacks.map(([t, n]) => <span key={t} className={`badge ${n >= 3 ? "warn" : ""}`}>{t} ×{n}</span>)}</div>
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
                    <span className="muted">{p.slot}</span> {p.player_name} <span className="muted">{p.team_abbr}</span> <strong>${p.price}</strong>{p.is_keeper ? " (K)" : ""}
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
