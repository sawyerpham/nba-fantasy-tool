import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { PosTag } from "./Pos.jsx";
import { Term, TERMS, priceTone } from "./Terms.jsx";

// Your roster beside the live block: every spot (filled or open) with its price coloured against Worth, your money,
// cap and estimated weekly score. Reads the same /room data as the Managers page.
export default function MyTeam({ leagueId, rosterSlots, refreshKey }) {
  const [me, setMe] = useState(null);
  useEffect(() => {
    api.get(`/leagues/${leagueId}/room`).then((room) => setMe(room.find((m) => m.is_user) || null)).catch(() => setMe(null));
  }, [leagueId, refreshKey]);
  if (!me) return null;
  const b = me.budget;
  const bySlot = {};
  for (const p of me.picks) (bySlot[p.slot] ||= []).push(p);
  const slots = (rosterSlots || []).filter((s) => s.slot !== "IR");
  return (
    <div className="my-team" data-testid="my-team">
      <div className="my-team-head">
        <span className="live-card-title" style={{ color: "var(--primary)" }}>My team</span>
        <span><strong>${b.remaining}</strong> <span className="muted">left · <Term k="cap">cap</Term> ${b.max_bid} · {b.open_mandatory} open</span></span>
      </div>
      <div className="my-team-slots">
        {slots.flatMap((s) => {
          const filled = bySlot[s.slot] || [];
          const open = s.count - filled.length;   // open spots of a kind share one row: "BN ×5 open"
          return [
            ...filled.map((p) => {
              const t = priceTone(p.price, p.worth, p.is_keeper);
              return (
                <div key={p.pick_number} className="my-team-slot">
                  <PosTag text={s.slot} />
                  <span className="clip">{p.player_name}</span>
                  <strong className={`my-team-price ${t.cls}`} data-tip={t.tip}>${p.price}</strong>
                </div>
              );
            }),
            open > 0 && <div key={`${s.slot}-open`} className="my-team-slot open"><PosTag text={s.slot} /><span className="muted">{open > 1 ? `×${open} ` : ""}open</span></div>,
          ];
        })}
      </div>
      <div className="room-weekly" data-tip={TERMS.win_score[1]}><span className="muted">est weekly</span> <strong>{Math.round(me.win_score)}</strong> <span className="muted">FP</span></div>
    </div>
  );
}
