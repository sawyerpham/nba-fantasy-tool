import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const VERDICTS = {
  go: ["good", "GO"], "fair-only": ["good", "BID FAIR"], fits: ["good", "FITS"],
  stretch: ["even", "STRETCH"], pass: ["bad", "WALK-AWAY"], cannot: ["bad", "CAN'T"],
};

export function VerdictBadge({ verdict }) {
  const [cls, label] = VERDICTS[verdict] || ["", verdict];
  return <span className={`verdict ${cls}`} data-testid="spend-verdict-badge">{label}</span>;
}

export const ordinal = (n) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

const readOpen = () => { try { return localStorage.getItem("da.spending.open") !== "0"; } catch { return true; } };

// Your money against the room, price inflation, the plan for your open slots, and targets you can afford.
export default function SpendingGuide({ leagueId, live, refreshKey, onSelect }) {
  const [g, setG] = useState(null);
  const [open, setOpen] = useState(readOpen);

  useEffect(() => {
    if (!live) { setG(null); return; }
    api.get(`/leagues/${leagueId}/spending`).then(setG).catch(() => setG(null));
  }, [leagueId, live, refreshKey]);

  if (!live || !g) return null;
  const me = g.me;
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem("da.spending.open", open ? "0" : "1"); } catch { /* ignore */ }
  };
  const mood = g.inflation >= 1.05 ? "money outpacing talent" : g.inflation <= 0.95 ? "bargains ahead" : "near the opening rate";

  return (
    <div className="panel" data-testid="spending-guide">
      <div className="row">
        <h3 style={{ margin: 0 }}>Spending guide <span className="badge info">for {g.name}</span></h3>
        {!open && <span className="small muted">${me.remaining} · {me.open_mandatory} slots · {ordinal(g.money_rank)} of {g.num_managers} in money · prices {g.inflation.toFixed(2)}×</span>}
        <button className="small ghost" onClick={toggle} data-testid="toggle-spending" style={{ marginLeft: "auto" }}>{open ? "▾ hide" : "▸ show"}</button>
      </div>
      {open && (
        <>
          <div className="bid-grid">
            <div className="bid-cell primary">
              <div className="bid-label">You</div>
              <div className="bid-num">${me.remaining}</div>
              <div className="small muted">{me.open_mandatory} slots · ${me.per_slot}/slot · {ordinal(g.money_rank)} of {g.num_managers}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label">Room</div>
              <div className="bid-num">${g.room_remaining}</div>
              <div className="small muted">{g.room_open_mandatory} slots · ${g.room_per_slot}/slot</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label">Prices vs opening</div>
              <div className="bid-num">{g.inflation.toFixed(2)}×</div>
              <div className="small muted">{mood}</div>
            </div>
          </div>
          <ul className="small guide-lines">{g.advice.slice(1).map((line, i) => <li key={i}>{line}</li>)}</ul>
          {g.nominations?.length > 0 && (
            <div className="nom-ideas" data-testid="nominations">
              <div className="bid-label" style={{ marginBottom: 4 }}>When it's your turn to nominate</div>
              {g.nominations.map((n) => (
                <div key={`${n.kind}-${n.player_id}`} className="nom-row clickable" onClick={() => onSelect?.(n.player_id)} title={n.reason}>
                  <span className={`verdict ${n.kind === "drain" ? "even" : "good"}`}>{n.kind === "drain" ? "DRAIN" : "SNEAK"}</span>
                  <strong>{n.name}</strong> <span className="muted">~${n.price}</span>
                  <span className="small muted nom-why">{n.reason}</span>
                </div>
              ))}
            </div>
          )}
          {g.targets.length > 0 && (
            <>
              <div className="small muted" style={{ marginTop: 4 }}>Targets you can afford (click to open; rivals = managers who can reach the market max; room pays ${g.targets[0].room_per_starter}/starter from here):</div>
              <table className="small" data-testid="spend-targets">
                <thead><tr><th>Player</th><th>Slot</th><th>Go to</th><th>Market</th><th>Rivals</th><th>Left after</th><th>Call</th></tr></thead>
                <tbody>
                  {g.targets.map((t) => (
                    <tr key={t.player_id} className="clickable" onClick={() => onSelect?.(t.player_id)} data-testid={`spend-target-${t.player_id}`}>
                      <td>{t.name}</td>
                      <td>{t.slot}</td>
                      <td><strong>${t.suggested}</strong></td>
                      <td>${t.recommended}</td>
                      <td>{t.rivals_above_market}</td>
                      <td>${t.left_after} <span className="muted">(${t.per_starter_after}/starter)</span></td>
                      <td><VerdictBadge verdict={t.verdict} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          <details className="small" style={{ marginTop: 4 }}>
            <summary>slot plan and everyone's money</summary>
            {g.plan.length > 0 && (
              <table className="small">
                <thead><tr><th>Slot</th><th>Best available</th><th>Within ${g.allowance}</th></tr></thead>
                <tbody>
                  {g.plan.map((p, i) => (
                    <tr key={i}>
                      <td>{p.slot}</td>
                      <td>{p.best_name ? `${p.best_name} $${p.best_price}` : "—"}</td>
                      <td>{p.fit_name ? `${p.fit_name} $${p.fit_price}` : "nobody"}</td>
                    </tr>
                  ))}
                  <tr><td>BN ×{me.open_bench}</td><td colSpan="2">${g.bench_total} at the minimum</td></tr>
                  <tr><th>Total</th><th>${g.plan_best_total} ({g.slack_best >= 0 ? `$${g.slack_best} spare` : `$${-g.slack_best} short`})</th><th>${g.plan_fit_total} ({g.slack_fit >= 0 ? `$${g.slack_fit} spare` : `$${-g.slack_fit} short`})</th></tr>
                </tbody>
              </table>
            )}
            <table className="small" style={{ marginTop: 4 }}>
              <thead><tr><th>Manager</th><th>$ left</th><th>Slots</th><th>$/slot</th><th>Max bid</th></tr></thead>
              <tbody>
                {g.managers.map((m) => (
                  <tr key={m.manager_id} className={m.is_user ? "selected" : ""}>
                    <td>{m.name}</td><td>${m.remaining}</td><td>{m.open_mandatory}</td><td>${m.per_slot}</td><td>${m.max_bid}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </div>
  );
}
