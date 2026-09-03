import React from "react";

const INJ = { healthy: "", day_to_day: "DTD", out_short_term: "OUT", out_long_term: "OUT-LT", out_season: "SEASON" };

const COLS = [
  ["rank", "#"], ["full_name", "Player"], ["team_abbr", "Tm"], [null, "Elig"], ["injury_status", "Inj"], ["age", "Age"],
  ["games_played", "GP"], ["avg_fpts", "Avg"], ["best_game_fpts", "Best"], ["value", "Value"], ["stack_if_added", "Stack"], [null, "Slot"], [null, ""],
];

export default function RankingsTable({ rows, selectedId, onSelect, onNominate, onDraft, live, sort, onSort }) {
  const arrow = (key) => (sort && sort.key === key ? (sort.dir === "asc" ? " ▲" : " ▼") : "");
  return (
    <table data-testid="rankings-table">
      <thead>
        <tr>
          {COLS.map(([key, label]) => (
            <th key={label || "actions"} onClick={() => key && onSort && onSort(key)} style={{ cursor: key && onSort ? "pointer" : "default" }} title={key ? "click to sort" : ""}>
              {label}{key ? arrow(key) : ""}
            </th>
          ))}
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
            <td>{r.avg_fpts.toFixed(1)}</td>
            <td>{r.best_game_fpts.toFixed(1)}</td>
            <td><strong>{r.value.toFixed(1)}</strong></td>
            <td>{r.stack_if_added > 1 ? <span className="badge">{r.team_abbr} ×{r.stack_if_added}</span> : ""}</td>
            <td>{r.assignable_slot || <span className="muted">none</span>}</td>
            <td onClick={(e) => e.stopPropagation()}>
              {live && <button onClick={() => onNominate(r)} data-testid={`btn-nominate-${r.player_id}`}>Nominate</button>}{" "}
              {live && <button className="primary" onClick={() => onDraft(r)} data-testid={`btn-draft-${r.player_id}`}>Drafted…</button>}
            </td>
          </tr>
        ))}
        {!rows.length && <tr><td colSpan="13" className="muted">No players to show.</td></tr>}
      </tbody>
    </table>
  );
}
