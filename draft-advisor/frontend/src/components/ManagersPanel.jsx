import React, { useState } from "react";

// Every manager on one compact row: money, max bid, open spots, needs, last year's style.
// Click a row to show that roster in the Team preview; drop a dragged pick on a row to move it there.
export default function ManagersPanel({ managers, selectedId, onSelect, dragging, onMovePick }) {
  const [over, setOver] = useState(null);
  if (!managers) return null;

  return (
    <div className="panel" data-testid="managers-panel">
      <h3 style={{ marginTop: 0 }}>Managers</h3>
      <table className="small managers-table">
        <thead><tr><th>Manager</th><th className="num">$ left</th><th className="num">Max bid</th><th className="num">Open</th><th>Needs</th></tr></thead>
        <tbody>
          {managers.map((m) => {
            const b = m.budget;
            const needs = Object.entries(m.open_slots).filter(([s, n]) => n > 0 && s !== "BN" && s !== "IR").map(([s, n]) => `${s}${n > 1 ? "×" + n : ""}`).join(" ");
            const t = m.tendency;
            const canDrop = dragging && dragging.manager_id !== m.manager_id;
            const traits = t && [
              t.style === "new" ? "new, no history" : `last year: ${t.style}${t.top_buys.length ? " (" + t.top_buys.map((x) => `${x.name} $${x.price}`).join(", ") + ")" : ""}`,
              t.favorite_teams?.length ? `${t.favorite_teams.join("/")} fan` : "",
              t.lean ? `likes ${t.lean}` : "",
            ].filter(Boolean).join(" · ");
            return (
              <tr
                key={m.manager_id}
                className={`clickable ${m.manager_id === selectedId ? "selected" : ""} ${m.is_user ? "user-row" : ""} ${over === m.manager_id && canDrop ? "drop-over" : ""}`}
                onClick={() => onSelect(m.manager_id)}
                onDragOver={(e) => { if (canDrop) { e.preventDefault(); if (over !== m.manager_id) setOver(m.manager_id); } }}
                onDragLeave={() => setOver(null)}
                onDrop={(e) => { e.preventDefault(); if (canDrop) onMovePick?.(dragging, m.manager_id); setOver(null); }}
                title={traits || ""}
                data-testid={`manager-card-${m.manager_id}`}
              >
                <td>
                  {m.is_next_nominator && <span className="nom-dot" title="nominates next">●</span>}
                  <strong>{m.name}</strong>{m.is_user && <span className="muted"> (you)</span>}
                  {t?.style === "star chaser" && <span className="badge warn" data-testid={`tendency-${m.manager_id}`}>star chaser</span>}
                </td>
                <td className="num" data-testid={`remaining-${m.manager_id}`}>${b.remaining}</td>
                <td className="num"><strong data-testid={`maxbid-${m.manager_id}`}>${b.max_bid}</strong></td>
                <td className="num">{b.open_mandatory}</td>
                <td className="muted" title={needs}>{needs || "bench only"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
