import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import Headshot from "./Headshot.jsx";

// The rankings' NBA Teams view: projected fantasy talent, last season's record, and a rough strength estimate
// (average of the two as z-scores; see GET /leagues/{id}/nba-teams). Click a team to open its best player.
const COLS = [
  ["name", "Team", ""],
  ["strength", "Est strength", "rough estimate of how good the team is: half last season's point differential, half this roster's projected fantasy talent (catches offseason moves). Not a betting-market forecast.", "num"],
  ["talent_fpg", "Est FP gen", "sum of the top 8 players' projected FP/G: how much fantasy production the team generates", "num"],
  ["wins", "Last W-L", "last season's record", "num"],
  ["diff", "Last +/-", "last season's point differential per game", "num"],
  ["best_fpg", "Best player", "", ""],
];

export default function NbaTeamsTable({ leagueId, refreshKey, onSelectPlayer }) {
  const [teams, setTeams] = useState([]);
  const [sort, setSort] = useState({ key: "strength", dir: "desc" });
  useEffect(() => { api.get(`/leagues/${leagueId}/nba-teams`).then(setTeams).catch(() => setTeams([])); }, [leagueId, refreshKey]);
  const rows = teams.slice().sort((a, b) => {
    const x = a[sort.key] ?? -1e9, y = b[sort.key] ?? -1e9;
    return (x < y ? -1 : x > y ? 1 : 0) * (sort.dir === "asc" ? 1 : -1);
  });
  const onSort = (key) => setSort((s) => ({ key, dir: s.key === key ? (s.dir === "asc" ? "desc" : "asc") : key === "name" ? "asc" : "desc" }));

  return (
    <table data-testid="nba-teams-table">
      <thead>
        <tr>
          <th className="num">#</th>
          {COLS.map(([key, label, title, cls]) => (
            <th key={key} className={`${cls} sortable ${sort.key === key ? "sorted" : ""}`} title={title} onClick={() => onSort(key)}>
              {label}<span className="sort-arrow">{sort.key === key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((t, i) => (
          <tr key={t.abbr} className="clickable" onClick={() => t.best_id && onSelectPlayer?.(t.best_id)} title="open his team card">
            <td className="num muted">{i + 1}</td>
            <td><span className="player-cell"><img src={t.logo} alt="" width={30} height={30} className="team-logo-sm" /> <strong>{t.name}</strong></span></td>
            <td className="num"><strong>{t.strength > 0 ? "+" : ""}{t.strength.toFixed(2)}</strong></td>
            <td className="num">{t.talent_fpg.toFixed(1)}</td>
            <td className="num">{t.wins != null ? `${t.wins}-${t.losses}` : "—"}</td>
            <td className={`num ${t.diff > 0 ? "ok" : t.diff < 0 ? "warn-text" : ""}`}>{t.diff != null ? `${t.diff > 0 ? "+" : ""}${t.diff.toFixed(1)}` : "—"}</td>
            <td><span className="player-cell"><Headshot sleeperId={t.best_sleeper_id} name={t.best || ""} size={26} /> {t.best} <span className="muted">{t.best_fpg?.toFixed(1)}</span></span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
