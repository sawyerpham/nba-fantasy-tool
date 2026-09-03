import React, { useEffect, useRef, useState } from "react";
import { api, qs } from "../api.js";

// Autocomplete over the player pool. onSelect(player) receives the API's brief row.
export default function PlayerSearch({ leagueId, onSelect, placeholder = "Search player…", testId = "search-input", autoFocus = false }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [open, setOpen] = useState(false);
  const timer = useRef(null);

  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return undefined;
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      api.get("/players" + qs({ q, limit: 12, league_id: leagueId })).then((rows) => {
        setHits(rows);
        setOpen(true);
      }).catch(() => setHits([]));
    }, 150);
    return () => clearTimeout(timer.current);
  }, [q, leagueId]);

  const choose = (p) => {
    setOpen(false);
    setQ("");
    onSelect(p);
  };

  return (
    <div className="search-wrap">
      <input
        type="text"
        value={q}
        placeholder={placeholder}
        autoFocus={autoFocus}
        data-testid={testId}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits.length) choose(hits[0]);
          if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && hits.length > 0 && (
        <div className="dropdown" onMouseLeave={() => setOpen(false)}>
          {hits.map((p) => (
            <div key={p.player_id} onClick={() => choose(p)} data-testid={`search-result-${p.player_id}`}>
              {p.full_name} <span className="muted">{p.team_abbr || "FA"} · {p.eligibility.join("/") || "no elig"}</span>
              {p.drafted_by && <span className="badge">drafted: {p.drafted_by}</span>}
              {!p.has_stats && <span className="badge warn">no stats</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
