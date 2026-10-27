import React, { useState } from "react";
import { api } from "../api.js";

// The site's front door: what it is, what it does (the README's feature lists, the automatic ones first) and a big
// "import your Sleeper league" box. Import = a new league "sleeper-<id>" (or the existing one), Sleeper's name, scoring,
// roster slots, team count and keepers applied, then its managers and keepers synced; then a check mark and the way in.
const FEATURES = {
  Draft: {
    top: ["Live Sleeper draft sync", "Live bid calls on the nominee", "Rival drafting habits from past leagues"],
    rest: ["Auction value rankings", "Worth and max bid per player", "Budget plan for open roster spots", "Position scarcity and tier cliffs",
      "Rival manager money and needs", "Fantasy team strength estimates", "NBA team win totals and fantasy talent", "Keeper keep-or-cut verdicts"],
  },
  Season: {
    top: ["Optimal lineup at any time of the week", "Live keep-or-swap calls", "Swap and lock alarms", "Next Sleeper check-in",
      "Live NBA game cards", "Injury watch"],
    rest: ["Lineup swap instructions", "Lock-or-wait calls", "Win probability by strategy", "Lockable games", "Opponent lineups",
      "Box scores and top performers", "Game stream links", "Player game logs and news", "NBA team offense and defense ranks",
      "NBA depth charts", "League standings and FAAB", "Waiver targets with FAAB bids"],
  },
};
const APPLY = ["name", "scoring", "roster_slots", "num_managers", "keepers"];
// a Sleeper league id, alone or inside a pasted link (sleeper.com/leagues/1234567890123456789/...)
const sleeperId = (text) => (String(text).match(/\d{12,}/) || [])[0] || null;

export default function HomePage({ setLeagueId, setTab }) {
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null);   // { id, name } once imported

  const importLeague = async () => {
    const sid = sleeperId(input);
    if (!sid) return setError("Paste your Sleeper league ID or its link (the long number in sleeper.com/leagues/…).");
    setBusy(true); setError(""); setDone(null);
    const id = `sleeper-${sid}`;
    try {
      let fresh = true;
      try {
        await api.post("/leagues", { league_id: id, name: `Sleeper ${sid}` });
      } catch (e) {
        if (!/already exists/.test(e.message)) throw e;
        fresh = false;   // imported before: refresh it (the team count can't change once its draft started)
      }
      const league = await api.post(`/leagues/${id}/sleeper/apply`, { sleeper_league_id: sid, apply: fresh ? APPLY : APPLY.filter((f) => f !== "num_managers") });
      try { await api.post(`/leagues/${id}/sleeper/sync`); } catch { /* managers and keepers: the League tab's Sync retries */ }
      setLeagueId(id);
      setDone({ id, name: league.name });
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const cards = [
    ["league", "League", "Managers, keepers, rules and settings: pick which team is you."],
    ["draft", "Draft", "Rankings, bid calls and live sync for your auction."],
    ["season", "Season", "Your best lineup, lock calls, alarms and live games each week."],
  ];
  return (
    <div className="home" data-testid="home-page">
      <section className="home-hero">
        <h1>NBA Fantasy Tool</h1>
        <p className="home-pitch">A free tool for Sleeper NBA leagues, forever. No sign-up, no account: paste your league and go.</p>
        <div className="home-import">
          <input type="text" value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && importLeague()}
            placeholder="Import Sleeper league: paste its ID or link" aria-label="Sleeper league ID or link" data-testid="home-import-input" />
          <button className="primary" onClick={importLeague} disabled={busy || !input.trim()} data-testid="home-import">{busy ? "Importing…" : "Import"}</button>
        </div>
        {error && <div className="error">{error}</div>}
        {done && (
          <div className="home-done" data-testid="home-imported">
            <div className="home-check" aria-hidden="true">✓</div>
            <div><strong>{done.name}</strong> imported<div className="small muted">Saved as league “{done.id}”. Pick which team is you on the League tab.</div></div>
          </div>
        )}
        {done && (
          <div className="home-cards">{cards.map(([id, title, text]) => (
            <button key={id} className="home-card" onClick={() => setTab(id)} data-testid={`home-card-${id}`}>
              <strong>{title} →</strong><span className="small muted">{text}</span>
            </button>
          ))}</div>
        )}
      </section>
      <section className="home-features">
        {Object.entries(FEATURES).map(([group, { top, rest }]) => (
          <div key={group} className="panel">
            <h3>{group}</h3>
            <ul className="home-top">{top.map((f) => <li key={f}><strong>{f}</strong></li>)}</ul>
            <ul className="home-rest">{rest.map((f) => <li key={f}>{f}</li>)}</ul>
          </div>
        ))}
      </section>
    </div>
  );
}
