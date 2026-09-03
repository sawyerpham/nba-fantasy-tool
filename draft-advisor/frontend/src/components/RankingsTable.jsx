import React from "react";

const INJ = { healthy: "", day_to_day: "DTD", out_short_term: "OUT", out_long_term: "OUT-LT", out_season: "SEASON" };
const CEILING_LABEL = { weekly_best: "Wk-best", best_game: "Best", top_quarter: "Top25%" };

const COLS = [
  ["rank", "#", "rank by value"], ["full_name", "Player", ""], ["team_abbr", "Tm", ""], [null, "Elig", "fantasy positions (Sleeper, editable)"],
  ["injury_status", "Inj", ""], ["age", "Age", ""], ["games_played", "GP", "games played last season"],
  ["avg_fpts", "FP/G", "fantasy points per game under your scoring"], ["ceiling", "CEILING", ""],
  ["best_game_fpts", "Best", "single best game (FP)"], ["availability", "Avail", "weeks with a game / season weeks"],
  ["total_fpts", "Total FP", "season total fantasy points"], ["value", "Value", "ranking score in FP units (see legend)"],
  ["stack_if_added", "Stack", "players from this NBA team you would have"], [null, "Slot", "slot this player would fill for you"], [null, "", ""],
];

export default function RankingsTable({ rows, selectedId, onSelect, onNominate, onDraft, live, sort, onSort, ceilingMetric = "weekly_best" }) {
  const arrow = (key) => (sort && sort.key === key ? (sort.dir === "asc" ? " ▲" : " ▼") : "");
  const ceilingLabel = CEILING_LABEL[ceilingMetric] || "Ceiling";
  return (
    <table data-testid="rankings-table">
      <thead>
        <tr>
          {COLS.map(([key, label, title]) => {
            const text = label === "CEILING" ? ceilingLabel : label;
            const help = label === "CEILING" ? (ceilingMetric === "weekly_best" ? "average of each week's best game (FP) — what Lock-In scores" : title) : title;
            return (
              <th key={label || "actions"} onClick={() => key && onSort && onSort(key)} style={{ cursor: key && onSort ? "pointer" : "default" }} title={help ? `${help}${key ? " · click to sort" : ""}` : (key ? "click to sort" : "")}>
                {text}{key ? arrow(key) : ""}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.player_id}
            className={`clickable ${r.player_id === selectedId ? "selected" : ""} ${r.rosterable ? "" : "unrosterable"}`}
            onClick={() => onSelect(r.player_id)}
            data-testid={`rank-row-${r.player_id}`}
          >
            <td>{r.rank}</td>
            <td>
              {r.full_name}
              {!r.has_stats && <span className="badge warn" title="no NBA.com stats (Sleeper-only player)">no stats</span>}
              {r.unsigned_per_sleeper && <span className="badge" title="Sleeper lists this player as unsigned">FA?</span>}
              {r.team_conflict && <span className="badge info" title={`NBA.com ${r.team_conflict.nba_api} vs Sleeper ${r.team_conflict.sleeper}`}>team?</span>}
              {r.eligibility_source === "none" && <span className="badge none" title="eligibility not set — edit in the sidebar">elig?</span>}
            </td>
            <td>{r.team_abbr || "-"}</td>
            <td>{r.eligibility.join("/")}</td>
            <td>{INJ[r.injury_status] || r.injury_status}</td>
            <td>{r.age ?? "-"}</td>
            <td>{r.games_played}</td>
            <td><strong>{r.avg_fpts.toFixed(1)}</strong></td>
            <td>{r.ceiling.toFixed(1)}</td>
            <td className="muted">{r.best_game_fpts.toFixed(1)}</td>
            <td className={r.availability < 0.7 ? "warn-text" : ""}>{Math.round(r.availability * 100)}%</td>
            <td className="muted">{Math.round(r.total_fpts)}</td>
            <td><strong>{r.value.toFixed(1)}</strong>{(r.injury_multiplier !== 1 || r.age_multiplier !== 1 || r.confidence !== 1) && <span className="muted small" title={`× ${r.confidence} games confidence × ${r.injury_multiplier} injury × ${r.age_multiplier} age`}>*</span>}</td>
            <td>{r.stack_if_added > 1 ? <span className="badge">{r.team_abbr} ×{r.stack_if_added}</span> : ""}</td>
            <td>{r.assignable_slot || <span className="muted">none</span>}</td>
            <td onClick={(e) => e.stopPropagation()}>
              {live && <button onClick={() => onNominate(r)} data-testid={`btn-nominate-${r.player_id}`}>Nominate</button>}{" "}
              {live && <button className="primary" onClick={() => onDraft(r)} data-testid={`btn-draft-${r.player_id}`}>Drafted…</button>}
            </td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan="16" className="muted">No players to show.</td></tr>}
      </tbody>
    </table>
  );
}
