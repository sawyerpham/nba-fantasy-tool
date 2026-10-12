import React, { useEffect, useState } from "react";

// Horizontal, drag-to-reorder nomination rotation. Arrows work too. Click a name to make that manager next.
export default function NominationOrderBar({ managers, order, nextNominator, live, onReorder, onMakeNext }) {
  const [items, setItems] = useState(order);
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (!busy) setItems(order); }, [order, busy]);

  const byId = Object.fromEntries((managers || []).map((m) => [m.manager_id, m]));
  const commit = (next) => {
    setItems(next);
    if (next.join() === order.join()) return;
    setBusy(true);
    Promise.resolve(onReorder(next)).finally(() => setBusy(false));
  };
  const move = (from, to) => {
    if (to < 0 || to >= items.length || from === to) return;
    const next = items.slice();
    const [id] = next.splice(from, 1);
    next.splice(to, 0, id);
    commit(next);
  };

  return (
    <div className="order-bar" data-testid="order-bar">
      <span className="small muted" style={{ marginRight: 6 }} title={`drag to reorder${live ? ", click a name to make them next" : ""}`}>Nomination order</span>
      {items.map((id, i) => {
        const m = byId[id];
        const full = m && (m.budget.open_mandatory === 0 || m.budget.max_bid < 1);
        return (
          <div
            key={id}
            className={`order-chip ${id === nextNominator ? "next" : ""} ${full ? "full" : ""} ${over === i ? "over" : ""} ${dragging === i ? "dragging" : ""}`}
            draggable
            onDragStart={(e) => { setDragging(i); e.dataTransfer.effectAllowed = "move"; }}
            onDragOver={(e) => { e.preventDefault(); if (over !== i) setOver(i); }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); if (dragging !== null) move(dragging, i); setDragging(null); setOver(null); }}
            onDragEnd={() => { setDragging(null); setOver(null); }}
            data-testid={`order-chip-${id}`}
            title={full ? "roster full" : live ? "click to make this manager nominate next" : ""}
          >
            <button className="small arrow" onClick={() => move(i, i - 1)} disabled={busy || i === 0} title="move left" data-testid={`order-left-${id}`}>◀</button>
            <span className="chip-name" onClick={() => live && !full && id !== nextNominator && onMakeNext(id)} data-testid={`order-next-${id}`}>
              <span className="muted small">{i + 1}. </span>{m ? m.name : id}{id === nextNominator ? " ●" : ""}
            </span>
            <button className="small arrow" onClick={() => move(i, i + 1)} disabled={busy || i === items.length - 1} title="move right" data-testid={`order-right-${id}`}>▶</button>
          </div>
        );
      })}
    </div>
  );
}
