import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { PosTag } from "../core/Pos.jsx";
import { Term, priceTone } from "../core/Terms.jsx";

const STATUS = { scarce: ["bad", "scarce"], tight: ["even", "tight"], plenty: ["good", "plenty"] };

// Under the spending guide: per position, demand vs supply, the tier cliff and which rivals are chasing it;
// then the room trend (recent sales vs their Worth at the time). See backend engine/market.py.
export default function MarketPanel({ leagueId, live, refreshKey, onSelect }) {
  const [m, setM] = useState(null);
  const [allSales, setAllSales] = useState(false);
  useEffect(() => {
    if (!live) { setM(null); return; }
    api.get(`/leagues/${leagueId}/market`).then(setM).catch(() => setM(null));
  }, [leagueId, live, refreshKey]);
  if (!live || !m) return null;

  return (
    <div className="panel market-panel" data-testid="market-panel">
      <h3 style={{ margin: "0 0 4px" }}>Position market</h3>
      <table className="small market-table">
        <thead><tr><th></th><th className="num"><Term k="need" /></th><th className="num"><Term k="supply" /></th><th><Term k="pos_status">Market</Term></th><th><Term k="tier_cliff">Top tier</Term></th><th className="num"><Term k="chasing">Chase</Term></th></tr></thead>
        <tbody>
          {m.positions.map((p) => {
            const [cls, word] = STATUS[p.status];
            const c = p.cliff;
            return (
              <tr key={p.pos} className={p.my_open ? "you-need" : ""}>
                <td><PosTag text={p.pos} />{p.my_open > 0 && <span className="need-dot" data-tip={`You have ${p.my_open} open ${p.pos} spot${p.my_open > 1 ? "s" : ""}.`} />}</td>
                <td className="num">{p.need}</td>
                <td className="num" data-tip={`Starter-quality players counted at ${p.pos}${p.also ? `; ${p.also} more can also play it but were counted where they're needed more` : ""}.`}>{p.left}</td>
                <td><span className={`verdict ${cls}`}>{word}</span></td>
                <td className="clip" data-tip={c ? `${c.names.join(", ")}${c.left > c.names.length ? " …" : ""}${c.drop != null ? `. T${c.next_tier}'s best is ${c.drop} value points lower.` : ""}` : ""}>
                  {c ? <>T{c.tier} ×{c.left}{c.drop != null && <span className="muted"> · −{c.drop}</span>}</> : "—"}
                </td>
                <td className="num" data-tip={p.chasers.length ? `Can afford ${p.best} (worth $${p.best_fair}): ${p.chasers.map((x) => `${x.name} (cap $${x.cap})`).join(", ")}` : `No rival with an open ${p.pos} spot can pay $${p.best_fair ?? "?"} for ${p.best || "the best left"}.`}>
                  <strong>{p.chasers.length}</strong>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="sold-tracker" data-testid="sold-tracker">
        <span data-tip="Bought at auction; keepers don't count."><span className="bid-label">Sold</span> <strong>{m.sold}</strong></span>
        <span data-tip={`Across every team, bench included; ${m.starters_left} are starting spots.`}><strong>{m.spots_left}</strong> <span className="muted">spots left</span></span>
        <span data-tip="Who the room's money is still for. When this runs low, the rest go for $1-3.">
          <strong className={m.good_left <= 10 ? "warn-text" : ""}>{m.good_left}</strong> <span className="muted">left worth ${m.good_worth}+</span>
        </span>
      </div>
      <div className="trend-head">
        <span className="bid-label"><Term k="room_trend" /></span>
        {m.recent_diff != null && (
          <span className={`small ${m.recent_diff > 2 ? "warn-text" : m.recent_diff < -2 ? "ok" : "muted"}`} data-tip="Average over the last 10 sales.">
            {m.recent_diff > 0 ? "+" : m.recent_diff < 0 ? "−" : ""}${Math.abs(m.recent_diff)} vs worth lately
          </span>
        )}
      </div>
      {!m.sales.length && <div className="small muted">No sales yet (keepers don't count): fills in as players are bought.</div>}
      <div className={allSales ? "sales-all" : ""}>
      {(allSales ? m.sales : m.sales.slice(0, 4)).map((s) => (
        <div key={`${s.player_id}-${s.price}`} className="sale-row clickable" onClick={() => onSelect?.(s.player_id)}>
          <span className="clip">{s.player}</span>
          {(() => { const t = priceTone(s.price, s.fair); return <strong><span className={t.cls} data-tip={t.tip}>${s.price}</span></strong>; })()}
          <span className={`sale-diff ${s.diff > 2 ? "over" : s.diff < -2 ? "under" : ""}`} data-tip={`Worth $${s.fair} when he sold`}>
            {s.diff > 0 ? "+" : ""}{s.diff}
          </span>
          <span className="muted clip sale-mgr">{s.manager}</span>
        </div>
      ))}
      </div>
      {m.sales.length > 4 && (
        <button className="small ghost" onClick={() => setAllSales(!allSales)} data-testid="toggle-sales">
          {allSales ? "▾ last 4 only" : `▸ show all ${m.sales.length} sold`}
        </button>
      )}
    </div>
  );
}
