import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { PosTag } from "./Pos.jsx";
import { Term } from "./Terms.jsx";

const STATUS = { scarce: ["bad", "scarce"], tight: ["even", "tight"], plenty: ["good", "plenty"] };

// Under the spending guide: per position, demand vs supply, the tier cliff and which rivals are chasing it;
// then the room trend (price level over the draft, recent sales vs what they were expected to go for). See backend engine/market.py.
export default function MarketPanel({ leagueId, live, refreshKey, onSelect }) {
  const [m, setM] = useState(null);
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
                <td className="num" data-tip={`${p.left} starter-quality players counted at ${p.pos}${p.also ? `; ${p.also} more can also play ${p.pos} but were counted at a position that needs them more` : ""}.`}>{p.left}</td>
                <td><span className={`verdict ${cls}`}>{word}</span></td>
                <td className="clip" data-tip={c ? `${c.names.join(", ")}${c.left > c.names.length ? " …" : ""} left in T${c.tier}.${c.drop != null ? ` The next tier's best (T${c.next_tier}) is ${c.drop} value points lower.` : ""}` : ""}>
                  {c ? <>T{c.tier} ×{c.left}{c.drop != null && <span className="muted"> · −{c.drop}</span>}</> : "—"}
                </td>
                <td className="num" data-tip={p.chasers.length ? `Can afford ${p.best} (about $${p.best_fair}): ${p.chasers.map((x) => `${x.name} (cap $${x.cap})`).join(", ")}` : `No rival with an open ${p.pos} spot can pay $${p.best_fair ?? "?"} for ${p.best || "the best left"}.`}>
                  <strong>{p.chasers.length}</strong>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <div className="trend-head">
        <span className="bid-label"><Term k="room_trend" /></span>
        {m.levels.length > 1 && <Spark values={m.levels} />}
        {m.recent_diff != null && (
          <span className={`small ${m.recent_diff > 2 ? "warn-text" : m.recent_diff < -2 ? "ok" : "muted"}`} data-tip="Last 10 sales on average: how much more (+) or less (−) than expected the buyers paid.">
            {m.recent_diff > 0 ? "+" : ""}${m.recent_diff} vs expected lately
          </span>
        )}
      </div>
      {m.levels.length <= 1 && <div className="small muted">No sales yet (keepers don't count): fills in as players are bought.</div>}
      {m.sales.map((s) => (
        <div key={`${s.player_id}-${s.price}`} className="sale-row clickable" onClick={() => onSelect?.(s.player_id)}>
          <span className="clip">{s.player}</span>
          <strong>${s.price}</strong>
          <span className={`sale-diff ${s.diff > 2 ? "over" : s.diff < -2 ? "under" : ""}`} data-tip={`Expected to go for about $${s.fair} at that point; ${s.manager} paid $${s.price}.`}>
            {s.diff > 0 ? "+" : ""}{s.diff}
          </span>
          <span className="muted clip sale-mgr">{s.manager}</span>
        </div>
      ))}
    </div>
  );
}

// Price level after each sale; the dashed line is 1.00× (draft-start prices).
function Spark({ values }) {
  const W = 120, H = 26, lo = Math.min(0.8, ...values), hi = Math.max(1.2, ...values);
  const y = (v) => H - 2 - ((v - lo) / (hi - lo)) * (H - 4);
  const x = (i) => (i / (values.length - 1)) * W;
  const last = values[values.length - 1];
  return (
    <svg className="spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" data-tip={`Price level after each sale: now ${last.toFixed(2)}×, started at 1.00× (dashed).`}>
      <line x1="0" x2={W} y1={y(1)} y2={y(1)} className="spark-base" />
      <polyline points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")} className={`spark-line ${last > 1.05 ? "hot" : last < 0.95 ? "cold" : ""}`} />
    </svg>
  );
}
