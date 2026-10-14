import React, { useEffect, useState } from "react";
import { PosTag } from "./Pos.jsx";
import { api } from "../api.js";
import { CallBadge, Term, liveCall } from "./Terms.jsx";

export const ordinal = (n) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

const readOpen = () => { try { return localStorage.getItem("da.spending.open") !== "0"; } catch { return true; } };

// Your money against the room, the live call on the nominee, your best fits, the ideal team and everyone's money.
export default function SpendingGuide({ leagueId, live, refreshKey, onSelect, lot, rankings }) {
  const [g, setG] = useState(null);
  const [open, setOpen] = useState(readOpen);

  useEffect(() => {
    if (!live) { setG(null); return; }
    api.get(`/leagues/${leagueId}/spending` + (lot ? `?player_id=${lot.player_id}` : "")).then(setG).catch(() => setG(null));
  }, [leagueId, live, refreshKey, lot?.player_id]);

  if (!live || !g) return null;
  const me = g.me;
  const toggle = () => {
    setOpen(!open);
    try { localStorage.setItem("da.spending.open", open ? "0" : "1"); } catch { /* ignore */ }
  };
  const bestFits = (rankings || []).filter((r) => r.fit && r.call && r.call !== "cannot")
    .sort((a, b) => b.fit.score - a.fit.score).slice(0, 5);

  return (
    <div className="panel" data-testid="spending-guide">
      <div className="row">
        <h3 style={{ margin: 0 }}>Spending guide <span className="badge info">for {g.name}</span></h3>
        {!open && <span className="small muted">${me.remaining} · {me.open_mandatory} open · price level {g.inflation.toFixed(2)}×</span>}
        <button className="small ghost" onClick={toggle} data-testid="toggle-spending" style={{ marginLeft: "auto" }}>{open ? "▾ hide" : "▸ show"}</button>
      </div>
      {open && (
        <>
          {lot && g.focus && g.focus.player_id === lot.player_id && (() => {
            const f = g.focus, c = liveCall(lot.high_bid ?? 0, f);
            return (
              <div className={`guide-now ${c.cls === "good" ? "go" : c.cls === "even" ? "maybe" : "stop"}`} data-testid="guide-now">
                <div className="bid-label">Right now · {lot.full_name}</div>
                <div className="guide-now-call"><CallBadge call={f.verdict} /> {c.text}</div>
              </div>
            );
          })()}
          <div className="bid-grid">
            <div className="bid-cell primary">
              <div className="bid-label"><Term k="left">You</Term></div>
              <div className="bid-num">${me.remaining}</div>
              <div className="small muted"><Term k="per_slot">${me.per_slot}/slot</Term> · {ordinal(g.money_rank)}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label"><Term k="room" /></div>
              <div className="bid-num">${g.room_per_slot}<span className="small muted">/slot</span></div>
            </div>
            <div className="bid-cell">
              <div className="bid-label"><Term k="price_level" /></div>
              <div className="bid-num">{g.inflation.toFixed(2)}×</div>
            </div>
          </div>
          {g.nominations?.length > 0 && (
            <div className="nom-ideas" data-testid="nominations">
              <span className="bid-label">Nominate</span>
              {g.nominations.slice(0, 3).map((n) => (
                <div key={`${n.kind}-${n.player_id}`} className="nom-row clickable" onClick={() => onSelect?.(n.player_id)}>
                  <Term k={n.kind} className={`verdict ${n.kind === "drain" ? "even" : "good"}`} />
                  <strong data-tip={n.reason}>{n.name}</strong> <span className="muted" data-tip="his market price">~${n.price}</span>
                </div>
              ))}
            </div>
          )}
          {bestFits.length > 0 && (
            <table className="small" data-testid="best-fits">
              <thead><tr><th><Term k="best_fits" /></th><th className="num"><Term k="fit" /></th><th className="num"><Term k="your_max" /></th><th><Term k="call" /></th></tr></thead>
              <tbody>
                {bestFits.map((r) => (
                  <tr key={r.player_id} className="clickable" onClick={() => onSelect?.(r.player_id)} data-testid={`best-fit-${r.player_id}`}>
                    <td>{r.full_name}</td>
                    <td className="num"><strong className={`fit-num ${r.fit.score >= 70 ? "hi" : r.fit.score >= 45 ? "mid" : "lo"}`}>{r.fit.score}</strong></td>
                    <td className="num"><strong>${r.price}</strong></td>
                    <td><CallBadge call={r.call} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {g.plan.length > 0 && <div className="bid-label" style={{ marginTop: 10 }}><Term k="ideal" /> for your open spots</div>}
          {g.plan.length > 0 && (
            <table className="small ideal-team" data-testid="ideal-team">
              <thead><tr><th>Slot</th><th>Best available</th><th><Term k="even_split">Even split ${g.allowance}</Term></th></tr></thead>
              <tbody>
                {g.plan.map((p, i) => (
                  <tr key={i}>
                    <td><PosTag text={p.slot} /></td>
                    <td>{p.best_name ? `${p.best_name} $${p.best_price}` : "—"}</td>
                    <td>{p.fit_name ? `${p.fit_name} $${p.fit_price}` : "nobody"}</td>
                  </tr>
                ))}
                <tr><td>BN ×{me.open_bench}</td><td colSpan="2">${g.bench_total} at the minimum</td></tr>
                <tr><th>Total</th><th>${g.plan_best_total} ({g.slack_best >= 0 ? `$${g.slack_best} spare` : `$${-g.slack_best} short`})</th><th>${g.plan_fit_total} ({g.slack_fit >= 0 ? `$${g.slack_fit} spare` : `$${-g.slack_fit} short`})</th></tr>
              </tbody>
            </table>
          )}
          <div className="bid-label" style={{ marginTop: 10 }}>Everyone's money</div>
          <table className="small" data-testid="everyones-money">
            <thead><tr><th>Manager</th><th><Term k="left" /></th><th><Term k="open" /></th><th><Term k="per_slot" /></th><th><Term k="cap" /></th></tr></thead>
            <tbody>
              {g.managers.map((m) => (
                <tr key={m.manager_id} className={m.is_user ? "selected" : ""}>
                  <td>{m.name}</td><td>${m.remaining}</td><td>{m.open_mandatory}</td><td>${m.per_slot}</td><td>${m.max_bid}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
