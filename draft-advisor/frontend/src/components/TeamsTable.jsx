import React, { useEffect, useState } from "react";
import { api } from "../api.js";

// The rankings' Managers view: every fantasy team's money and two strength estimates (see backend engine/room.py).
const COLS = [
  ["name", "Manager", ""],
  ["fp_gen", "Est FP/G", "projected FP/G of the players in starting spots now", "num"],
  ["win_score", "Win score", "projected weekly Lock-In score of the finished lineup: starters' expected best game of the week × availability, empty starting spots filled with what the team's money buys (higher = more likely to win the league)", "num"],
  ["remaining", "$ left", "", "num"],
  ["per_slot", "$/slot", "money per open roster spot", "num"],
  ["max_bid", "Max bid", "", "num"],
  ["empty_starters", "Open starters", "starting spots still empty", "num"],
];

export default function TeamsTable({ leagueId, refreshKey, onOpenRoom }) {
  const [teams, setTeams] = useState([]);
  const [sort, setSort] = useState({ key: "win_score", dir: "desc" });
  useEffect(() => { api.get(`/leagues/${leagueId}/room`).then(setTeams).catch(() => setTeams([])); }, [leagueId, refreshKey]);

  const val = (t, key) => (key === "remaining" || key === "max_bid" ? t.budget[key] : t[key]);
  const rows = teams.slice().sort((a, b) => {
    const x = val(a, sort.key), y = val(b, sort.key);
    return (x < y ? -1 : x > y ? 1 : 0) * (sort.dir === "asc" ? 1 : -1);
  });
  const byWin = teams.slice().sort((a, b) => b.win_score - a.win_score).map((t) => t.manager_id);
  const onSort = (key) => setSort((s) => ({ key, dir: s.key === key ? (s.dir === "asc" ? "desc" : "asc") : key === "name" ? "asc" : "desc" }));

  return (
    <table data-testid="teams-table">
      <thead>
        <tr>
          <th className="num" title="rank by win score">#</th>
          {COLS.map(([key, label, title, cls]) => (
            <th key={key} className={`${cls || ""} sortable ${sort.key === key ? "sorted" : ""}`} title={title} onClick={() => onSort(key)}>
              {label}<span className="sort-arrow">{sort.key === key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((t) => (
          <tr key={t.manager_id} className={`clickable ${t.is_user ? "selected" : ""}`} onClick={() => onOpenRoom?.()} title="open the room">
            <td className="num muted">{byWin.indexOf(t.manager_id) + 1}</td>
            <td><strong>{t.name}</strong>{t.is_user && <span className="muted"> (you)</span>}{t.tendency?.style === "star chaser" && <span className="badge warn">star chaser</span>}</td>
            <td className="num">{t.fp_gen.toFixed(1)}</td>
            <td className="num"><strong>{t.win_score.toFixed(1)}</strong></td>
            <td className="num">${t.budget.remaining}</td>
            <td className="num">${t.per_slot}</td>
            <td className="num">${t.budget.max_bid}</td>
            <td className="num">{t.empty_starters}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
