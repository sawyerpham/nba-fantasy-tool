import React, { useEffect, useState } from "react";
import { PosTag } from "./Pos.jsx";
import { api } from "../api.js";
import { CallBadge, Term, TERMS, liveCall } from "./Terms.jsx";

export const ordinal = (n) => {
  const s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
};

const readOpen = () => { try { return localStorage.getItem("da.spending.open") !== "0"; } catch { return true; } };

// Your money against the room, the live call on the nominee, the plan for your open spots and everyone's money.
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

  return (
    <div className="panel" data-testid="spending-guide">
      <div className="row">
        <h3 style={{ margin: 0 }}>Spending guide <span className="badge info">for {g.name}</span></h3>
        {!open && <span className="small muted">${me.remaining} · {me.open_mandatory} open</span>}
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
          <div className="bid-grid two">
            <div className="bid-cell primary">
              <div className="bid-label"><Term k="left">You</Term></div>
              <div className="bid-num">${me.remaining}</div>
              <div className="small muted"><Term k="per_slot">${me.per_slot}/slot</Term> · {ordinal(g.money_rank)}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label"><Term k="room" /></div>
              <div className="bid-num">${g.room_per_slot}<span className="small muted">/slot</span></div>
            </div>
          </div>
          {g.nominations?.length > 0 && (
            <div className="nom-ideas" data-testid="nominations">
              <span className="bid-label">Nominate</span>
              {g.nominations.slice(0, 3).map((n) => (
                <div key={`${n.kind}-${n.player_id}`} className="nom-row clickable" onClick={() => onSelect?.(n.player_id)}>
                  <Term k={n.kind} className={`verdict ${n.kind === "drain" ? "even" : "good"}`} />
                  <strong data-tip={n.reason}>{n.name}</strong>
                </div>
              ))}
            </div>
          )}
          {g.plan.length > 0 && (() => {
            // One row per open starting spot: the best player left for it (his Fit, his Max coloured by the call)
            // and the best one within your even split. Totals use his Max where the rankings have it.
            const row = (id) => (rankings || []).find((r) => r.player_id === id);
            const lines = g.plan.map((p) => ({ p, r: row(p.best_id) }));
            const total = lines.reduce((t, { p, r }) => t + (r?.max ?? p.best_price), 0) + g.bench_total;
            const spare = me.remaining - total;
            return (
              <table className="small plan-table" data-testid="ideal-team">
                <thead><tr><th></th><th><Term k="ideal">Best</Term></th><th className="num"><Term k="fit" /></th><th className="num"><Term k="max" /></th><th><Term k="even_split">≤ ${g.allowance}</Term></th></tr></thead>
                <tbody>
                  {lines.map(({ p, r }, i) => (
                    <tr key={i}>
                      <td><PosTag text={p.slot} /></td>
                      <td className="clip clickable" onClick={() => p.best_id && onSelect?.(p.best_id)} data-testid={p.best_id ? `best-fit-${p.best_id}` : undefined}>{p.best_name || "—"}</td>
                      <td className="num">{r?.fit ? <strong className={`fit-num ${r.fit.score >= 70 ? "hi" : r.fit.score >= 45 ? "mid" : "lo"}`}>{r.fit.score}</strong> : ""}</td>
                      <td className="num">{p.best_name ? <strong className={r?.call ? `call-${r.call}` : ""} data-tip={r?.call ? `${TERMS[r.call][0]}: ${TERMS[r.call][1]}` : "what he'll likely go for"}>${r?.max ?? p.best_price}</strong> : ""}</td>
                      <td className="clip clickable muted" onClick={() => p.fit_id && onSelect?.(p.fit_id)}>{p.fit_name ? `${p.fit_name} $${p.fit_price}` : "nobody"}</td>
                    </tr>
                  ))}
                  <tr><td colSpan="5" className="plan-total">
                    Best: <strong>${total}</strong> <span className={spare >= 0 ? "ok" : "warn-text"}>({spare >= 0 ? `$${spare} spare` : `$${-spare} short`})</span>
                    {" · "}≤ ${g.allowance}: <strong>${g.plan_fit_total}</strong> <span className="muted">· incl. {me.open_bench} BN at $1</span>
                  </td></tr>
                </tbody>
              </table>
            );
          })()}
          <table className="small money-table" data-testid="everyones-money">
            <thead><tr><th>Manager</th><th><Term k="left">Left</Term></th><th><Term k="open" /></th><th><Term k="per_slot">/slot</Term></th><th><Term k="cap" /></th></tr></thead>
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
