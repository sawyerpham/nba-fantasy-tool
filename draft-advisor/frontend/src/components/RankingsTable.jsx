import React, { useState } from "react";
import Headshot from "./Headshot.jsx";

const INJ = { healthy: "", day_to_day: "DTD", out_short_term: "OUT", out_long_term: "OUT-LT", out_season: "SEASON" };
const CEILING_LABEL = { weekly_best: "Wk-best", best_game: "Best", top_quarter: "Top25%" };

// Column order matters to e2e/mock-draft.mjs: [3] is eligibility, [5] is the ceiling.
const COLS = [
  ["rank", "#", "rank by value", "num"], ["full_name", "Player", "team · age · games played"], ["team_abbr", "Tm", ""],
  ["pos", "Pos", "fantasy positions (Sleeper, editable)"],
  ["avg_fpts", "FP/G", "expected fantasy points per game: Sleeper projection blended with last season", "num"], ["ceiling", "CEILING", "", "num"],
  ["availability", "Avail", "weeks with a game / season weeks", "num"],
  ["min", "Min", "projected minutes per game (Sleeper); grey = last season's, no projection", "num"],
  ["value", "Value", "ranking score in FP units", "num"],
  ["price", "$", "pay up to: the record bar's recommended max for you right now", "num"],
  [null, "Slot", "slot this player would fill for you"], [null, "", ""],
];

// ▲ / ▼ when Sleeper's projection is at least half a point of FP/G away from last season.
const trend = (r) => (r.proj_fpts == null || !r.last_fpts ? "" : r.proj_fpts - r.last_fpts >= 0.5 ? "up" : r.last_fpts - r.proj_fpts >= 0.5 ? "down" : "");

export default function RankingsTable({ rows, selectedId, onSelect, onBlock, live, sort, onSort, ceilingMetric = "weekly_best" }) {
  // Fixed-width arrow slot on every sortable header, so nothing shifts when the sort changes.
  const arrow = (key) => <span className="sort-arrow">{sort && sort.key === key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>;
  const ceilingLabel = CEILING_LABEL[ceilingMetric] || "Ceiling";
  const byRank = !sort || sort.key === "rank";
  // The first column shows value tiers (T1, T2 …) or plain rank numbers; remembered per browser.
  const [mode, setMode] = useState(() => { try { return localStorage.getItem("da.rankMode") || "tier"; } catch { return "tier"; } });
  const toggleMode = (e) => {
    e.stopPropagation();
    const next = mode === "tier" ? "num" : "tier";
    setMode(next);
    try { localStorage.setItem("da.rankMode", next); } catch { /* ignore */ }
  };
  return (
    <table data-testid="rankings-table">
      <thead>
        <tr>
          {COLS.map(([key, label, title, cls]) => {
            const text = label === "CEILING" ? ceilingLabel : label;
            const help = label === "CEILING" ? (ceilingMetric === "weekly_best" ? "average of each week's best game (FP) — what Lock-In scores" : title) : title;
            return (
              <th key={label || "actions"} className={`${cls || ""} ${key && onSort ? "sortable" : ""} ${sort?.key === key ? "sorted" : ""}`} onClick={() => key && onSort && onSort(key)} title={help ? `${help}${key ? " · click to sort" : ""}` : (key ? "click to sort" : "")}>
                {key === "rank" ? (
                  <span className="rank-head">
                    <button type="button" className="rank-toggle" onClick={toggleMode} title={mode === "tier" ? "showing tiers · click for rank numbers" : "showing rank numbers · click for tiers"} data-testid="rank-mode-toggle">{mode === "tier" ? "T" : "#"}</button>
                    <span data-testid="rank-sort" title="sort by rank">{arrow(key)}</span>
                  </span>
                ) : <>{text}{key ? arrow(key) : ""}</>}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => {
          const newTier = byRank && i > 0 && r.tier !== rows[i - 1].tier;
          const inj = INJ[r.injury_status] ?? r.injury_status;
          return (
            <tr
              key={r.player_id}
              className={`clickable ${r.player_id === selectedId ? "selected" : ""} ${r.rosterable ? "" : "unrosterable"} ${newTier ? "tier-start" : ""}`}
              onClick={() => onSelect(r.player_id)}
              data-testid={`rank-row-${r.player_id}`}
            >
              <td className="num muted">{mode === "tier" && r.tier != null
                ? <span className={`tier-cell ${r.tier_size >= 3 && r.tier_left <= 2 ? "last" : ""}`} title={`rank #${r.rank} · tier ${r.tier}: ${r.tier_left} of ${r.tier_size} left`}>T{r.tier}</span>
                : r.rank}</td>
              <td>
                <div className="player-cell">
                <Headshot sleeperId={r.sleeper_id} name={r.full_name} size={34} />
                <div>
                <div className="player-name">
                  {r.full_name}
                  {inj && <span className={`inj ${inj === "DTD" ? "" : "out"}`} title={r.injury_note || r.injury_status}>{inj}</span>}
                  {!r.has_stats && <span className="badge warn" title="no NBA.com stats (Sleeper-only player)">no stats</span>}
                  {r.unsigned_per_sleeper && <span className="badge" title="Sleeper lists this player as unsigned">FA?</span>}
                  {r.team_conflict && <span className="badge info" title={`NBA.com ${r.team_conflict.nba_api} vs Sleeper ${r.team_conflict.sleeper}`}>team?</span>}
                  {r.eligibility_source === "none" && <span className="badge none" title="eligibility not set — edit in the sidebar">elig?</span>}
                </div>
                <div className="player-sub">
                  age {r.age ?? "?"} · {r.games_played} GP · last yr {r.last_fpts.toFixed(1)}{r.proj_fpts == null && <span className="badge" title="Sleeper has no projection; last season only">no proj</span>}
                  {r.stack_if_added > 1 && <span className="badge" title="players from this NBA team you would have">{r.team_abbr} ×{r.stack_if_added}</span>}
                </div>
                </div>
                </div>
              </td>
              <td className="muted">{r.team_abbr || "FA"}</td>
              <td>{r.eligibility.join("/")}</td>
              <td className="num" title={r.proj_fpts != null ? `projected ${r.proj_fpts.toFixed(1)} · last season ${r.last_fpts.toFixed(1)}` : "no projection: last season only"}>
                <strong>{r.avg_fpts.toFixed(1)}</strong>
                <span className={`trend ${trend(r)}`}>{{ up: "▲", down: "▼" }[trend(r)] || ""}</span>
              </td>
              <td className="num">{r.ceiling.toFixed(1)}</td>
              <td className={`num ${r.availability < 0.7 ? "warn-text" : "muted"}`}>{Math.round(r.availability * 100)}%</td>
              <td className={`num ${r.proj_min == null ? "muted" : ""}`}>{(r.proj_min ?? r.last_min)?.toFixed(1) ?? "-"}</td>
              <td className="num" title={(r.injury_multiplier !== 1 || r.age_multiplier !== 1 || r.confidence !== 1) ? `× ${r.confidence} games confidence × ${r.injury_multiplier} injury × ${r.age_multiplier} age` : ""}>
                <strong>{r.value.toFixed(1)}</strong>
              </td>
              <td className="num">{r.price != null ? <strong className="price">${r.price}</strong> : <span className="muted">—</span>}</td>
              <td>{r.assignable_slot ? <span className="badge" style={{ margin: 0 }}>{r.assignable_slot}</span> : <span className="muted">—</span>}</td>
              <td onClick={(e) => e.stopPropagation()}>
                {live && (
                  <div className="row-actions">
                    <button className="small primary" onClick={() => onBlock(r)} title="put him on the block and record who wins him" data-testid={`btn-block-${r.player_id}`}>On the block</button>
                  </div>
                )}
              </td>
            </tr>
          );
        })}
        {!rows.length && <tr><td colSpan={COLS.length} className="muted" style={{ textAlign: "center", padding: 32 }}>No players to show.</td></tr>}
      </tbody>
    </table>
  );
}
