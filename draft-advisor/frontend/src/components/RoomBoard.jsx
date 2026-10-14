import React, { useEffect, useState } from "react";
import { PosList, PosTag } from "./Pos.jsx";
import { api } from "../api.js";
import Headshot from "./Headshot.jsx";

// Page 2 of the draft: one card per manager with money, roster by spot, needs and habits.
// Click a player for his profile; ✎ edits the pick; drag it onto another card to move it.
export default function RoomBoard({ leagueId, rosterSlots, refreshKey, onEditPick, onMovePick, onSelectPlayer }) {
  const [room, setRoom] = useState(null);
  const [dragging, setDragging] = useState(null);
  const [over, setOver] = useState(null);

  useEffect(() => { api.get(`/leagues/${leagueId}/room`).then(setRoom).catch(() => setRoom(null)); }, [leagueId, refreshKey]);
  if (!room) return null;
  const slots = (rosterSlots || []).filter((s) => s.slot !== "IR");

  return (
    <div className="room-grid" data-testid="room-board">
      {room.map((m) => {
        const b = m.budget;
        const t = m.tendency || {};
        const bySlot = {};
        for (const p of m.picks) (bySlot[p.slot] ||= []).push(p);
        const needs = Object.entries(m.open_slots).filter(([s, n]) => n > 0 && s !== "BN" && s !== "IR").map(([s, n]) => `${s}${n > 1 ? "×" + n : ""}`).join(" ");
        const canDrop = dragging && dragging.manager_id !== m.manager_id;
        return (
          <div key={m.manager_id}
            className={`room-card ${m.is_user ? "user" : ""} ${m.is_next_nominator ? "next" : ""} ${over === m.manager_id && canDrop ? "over" : ""}`}
            onDragOver={(e) => { if (canDrop) { e.preventDefault(); if (over !== m.manager_id) setOver(m.manager_id); } }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => { e.preventDefault(); if (canDrop) onMovePick?.(dragging, m.manager_id); setDragging(null); setOver(null); }}
            data-testid={`manager-card-${m.manager_id}`}>
            <div className="room-head">
              <strong>{m.name}</strong>
              {m.is_user && <span className="badge info">YOU</span>}
              {m.is_next_nominator && <span className="badge">nominating</span>}
              {t.style === "star chaser" && <span className="badge warn" data-testid={`tendency-${m.manager_id}`}>star chaser</span>}
              {t.style === "spreads money" && <span className="badge">spreads money</span>}
              {t.style === "new" && <span className="badge info">new</span>}
              {m.outbids_me && <span className="badge warn" title="their max bid is higher than yours">can outbid you</span>}
            </div>
            <div className="room-money">
              <span><span className="big" data-testid={`remaining-${m.manager_id}`}>${b.remaining}</span> <span className="muted">left</span></span>
              <span className="muted">max bid <strong style={{ color: "var(--text)" }} data-testid={`maxbid-${m.manager_id}`}>${b.max_bid}</strong></span>
              <span className="muted">{b.open_mandatory} open</span>
            </div>
            <div className="room-slots">
              {slots.flatMap((s) => Array.from({ length: s.count }, (_, i) => {
                const p = (bySlot[s.slot] || [])[i];
                return (
                  <div key={`${s.slot}-${i}`} className={`room-slot ${p ? "filled" : ""} ${s.slot === "BN" ? "bench" : ""}`}>
                    <PosTag className="room-slot-pos" text={s.slot} />
                    {p ? (
                      <span className="room-slot-player" draggable={Boolean(onEditPick)}
                        onDragStart={(e) => { setDragging(p); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(p.pick_number)); }}
                        onDragEnd={() => { setDragging(null); setOver(null); }}
                        onClick={() => onSelectPlayer?.(p.player_id)}
                        title={`${p.player_name} ${p.team_abbr || ""} · ${p.fpg ?? "?"} FP/G · $${p.price}${p.is_keeper ? " (keeper)" : ""} · click for his profile${onEditPick ? ", drag to move, ✎ to edit" : ""}`}>
                        <Headshot sleeperId={p.sleeper_id} name={p.player_name} size={30} />
                        <span className="room-slot-who">
                          <span className="room-slot-name">{p.player_name}</span>
                          <span className="room-slot-sub">{p.team_abbr || "FA"} · <PosList list={p.pos} />{p.age ? ` · ${p.age}` : ""}{p.is_keeper ? " · keeper" : ""}</span>
                        </span>
                        <span className="room-slot-fpg" title="projected FP/G">{p.fpg != null ? p.fpg.toFixed(1) : ""}</span>
                        <strong className="room-slot-price">${p.price}</strong>
                        {onEditPick && <button type="button" className="pick-edit" title="edit or remove this pick"
                          onClick={(e) => { e.stopPropagation(); onEditPick(p); }} data-testid={`pick-chip-${p.pick_number}`}>✎</button>}
                      </span>
                    ) : <span className="muted">—</span>}
                  </div>
                );
              }))}
            </div>
            <div className="small muted">Needs: {needs ? needs.split(" ").map((n, i) => <React.Fragment key={i}>{i > 0 && " "}<PosTag text={n} /></React.Fragment>) : "bench only"}</div>
            {(t.top_buys?.length > 0 || t.favorite_teams?.length > 0 || t.lean) && (
              <div className="small muted room-habits">
                {t.top_buys?.length > 0 && <>Last year: {t.top_buys.map((x) => `${x.name.split(" ").slice(-1)[0]} $${x.price}`).join(", ")}</>}
                {t.favorite_teams?.length > 0 && <> · {t.favorite_teams.join("/")} fan</>}
                {t.lean && <> · likes {t.lean}</>}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
