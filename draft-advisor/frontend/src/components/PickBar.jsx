import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import Headshot from "./Headshot.jsx";
import { tierHue } from "./RankingsTable.jsx";

// Inline "who won it?" bar: price is prefilled with the recommendation, one click on a manager records the pick.
// The slot is assigned automatically (most specific open slot); fix it afterwards from the pick chip if needed.
export default function PickBar({ leagueId, view, player, nominatedBy, tier, search, onCancel, onPicked }) {
  const managers = view?.managers || [];
  const [price, setPrice] = useState("");
  const [rec, setRec] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [fresh, setFresh] = useState(true); // price is still the prefill: the first numpad digit replaces it
  const priceRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setRec(null); setError(""); setPrice(""); setFresh(true);
    api.get(`/leagues/${leagueId}/recommend/${player.player_id}`).then((r) => {
      if (cancelled) return;
      setRec(r);
      setPrice((p) => (p === "" ? String(Math.max(1, r.recommended_max || 1)) : p));
    }).catch(() => !cancelled && setPrice((p) => (p === "" ? "1" : p)));
    priceRef.current?.focus();
    priceRef.current?.select();
    return () => { cancelled = true; };
  }, [leagueId, player.player_id]);

  const n = Math.max(1, Number(price) || 1);
  // Rivals with a history on this player: drafted him before (any linked league) or root for his NBA team.
  const interest = managers.filter((m) => !m.is_user && m.tendency).map((m) => {
    const before = m.tendency.drafted_before?.[String(player.player_id)];
    const fan = tier?.team_abbr && m.tendency.favorite_teams?.includes(tier.team_abbr);
    return before || fan ? { m, why: [before, fan && `${tier.team_abbr} fan`].filter(Boolean).join(" · ") } : null;
  }).filter(Boolean);
  const bump = (d) => { setPrice(String(Math.max(1, n + d))); setFresh(false); };
  const tap = (d) => { setPrice((p) => (fresh ? String(d) : (p + d).replace(/^0+/, "").slice(0, 3))); setFresh(false); };
  const clear = () => { setPrice(""); setFresh(false); };
  const empty = price === "";

  const record = async (managerId) => {
    setError(""); setBusy(true);
    try {
      const v = await api.post(`/leagues/${leagueId}/draft/pick`, { player_id: player.player_id, manager_id: managerId, price: n, slot: null });
      onPicked(v);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="pick-bar" data-testid="pick-dialog">
      <div className="pick-main">
        <div className="pick-bar-head">
          <Headshot sleeperId={player.sleeper_id || tier?.sleeper_id} name={player.full_name} size={48} />
          <span className="label">{nominatedBy ? "On the block" : "Mark drafted"}</span>
          <span className="on-block" data-testid={nominatedBy ? "on-the-block" : undefined}>{player.full_name}</span>
          {nominatedBy && <span className="small muted">by {nominatedBy}</span>}
          {tier && tier.tier_size > 1 && <span className={`tier-tag ${tier.tier_left <= 2 ? "last" : ""}`} style={tierHue(tier.tier)} title="players of similar value still available">T{tier.tier} · {tier.tier_left - 1 === 0 ? "last one in his tier" : `${tier.tier_left - 1} more like him left`}</span>}
          {rec && <span className="small muted">pay up to <strong data-testid="pick-recommended">${rec.recommended_max}</strong> · fair ${Math.round(rec.fair_value)}</span>}
          <span className="spacer" />
          {search}
          <button type="button" className="small ghost" onClick={onCancel} title="close (Esc)" data-testid="pick-cancel">Cancel</button>
        </div>
        <div className="mgr-row">
          <span className="small muted">Winner →</span>
          {managers.map((m) => {
            const tooMuch = n > m.budget.max_bid || m.budget.open_mandatory <= 0;
            return (
              <button
                key={m.manager_id} type="button" className={`mgr-btn ${m.is_user ? "you" : ""}`}
                disabled={busy || empty || tooMuch} onClick={() => record(m.manager_id)}
                title={empty ? "enter a price first" : tooMuch ? `max bid $${m.budget.max_bid}` : `${m.name} wins at $${n}`}
                data-testid={`pick-mgr-${m.manager_id}`}
              >
                {m.name}<span className="mgr-max" data-testid={`pick-max-${m.manager_id}`}>${m.budget.max_bid}</span>
              </button>
            );
          })}
        </div>
        {interest.length > 0 && (
          <div className="small muted" data-testid="pick-interest">
            <span className="label" style={{ marginRight: 6 }}>Watch out</span>
            {interest.map(({ m, why }, i) => <span key={m.manager_id}>{i ? " · " : ""}<strong style={{ color: "var(--text)" }}>{m.name}</strong> ({why})</span>)}
          </div>
        )}
        {error && <div className="error" data-testid="pick-error">{error}</div>}
      </div>
      <div className="numpad-wrap">
        <div className="price-box">
          <span className="small muted">sold for</span>
          <span className="muted">$</span>
          <input
            ref={priceRef} type="number" min="1" value={price} placeholder="0"
            onChange={(e) => { setPrice(e.target.value); setFresh(false); }}
            onKeyDown={(e) => { if (e.key === "Escape") onCancel(); if (e.key === "ArrowUp") { e.preventDefault(); bump(e.shiftKey ? 5 : 1); } if (e.key === "ArrowDown") { e.preventDefault(); bump(e.shiftKey ? -5 : -1); } }}
            className={fresh ? "fresh" : ""} data-testid="pick-price"
          />
        </div>
        <div className="numpad-row">
          <div className="numpad" data-testid="numpad">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((d) => <button key={d} type="button" onClick={() => tap(d)} data-testid={`numpad-${d}`}>{d}</button>)}
            <button type="button" className="zero" onClick={() => tap(0)} data-testid="numpad-0">0</button>
          </div>
          <button type="button" className="numpad-clear" onClick={clear} title="erase the price" data-testid="numpad-clear">✕</button>
        </div>
      </div>
    </div>
  );
}
