import React from "react";

export default function ManagersPanel({ managers }) {
  if (!managers) return null;
  return (
    <div className="panel scroll" data-testid="managers-panel">
      <h3>Managers</h3>
      {managers.map((m) => {
        const b = m.budget;
        const openSlots = Object.entries(m.open_slots).filter(([, n]) => n > 0).map(([s, n]) => `${s}${n > 1 ? "×" + n : ""}`).join(" ");
        const stacks = Object.entries(m.stack).sort((a, b2) => b2[1] - a[1]);
        return (
          <div key={m.manager_id} className={`manager-card ${m.is_next_nominator ? "next" : ""} ${m.is_user ? "user" : ""}`} data-testid={`manager-card-${m.manager_id}`}>
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
                  <span key={p.pick_number} style={{ marginRight: 8, whiteSpace: "nowrap" }}>
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
