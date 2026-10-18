import React from "react";
import { PosList, posClass, tierHue } from "../core/Pos.jsx";
import { Term, TERMS } from "../core/Terms.jsx";
import Headshot from "../core/Headshot.jsx";

const INJ = { healthy: "", day_to_day: "DTD", out_short_term: "OUT", out_long_term: "OUT-LT", out_season: "SEASON" };

// Column order matters to e2e/mock-draft.mjs: [3] is eligibility, [4] is Proj FP/G.
// [sort key, glossary term (or plain label), class]; hover a header for the term's definition.
const COLS = [
  ["rank", "rank", "num"], ["full_name", "Player"], ["team_abbr", "Tm", "col-narrow-hide"], ["pos", "pos_rank"],
  ["avg_fpts", "fpg", "num"], ["owned_pct", "rost", "num col-narrow-hide"], ["availability", "avail", "num"],
  ["min", "min", "num col-narrow-hide"], ["fit", "fit", "num"], ["worth", "worth", "num"], ["max", "max", "num"], ["r_value", "r_value", "num"],
];
const HEAD = { rank: "#", pos_rank: "Pos" };

// ▲ / ▼ when Sleeper's projection is at least half a point of FP/G away from last season.
// Hover text for the Value cell: every factor that moved this player away from plain FP.
const valueWhy = (r) => [
  r.confidence !== 1 && `× ${r.confidence} games confidence`,
  r.injury_multiplier !== 1 && `× ${r.injury_multiplier} injury`,
  r.age_multiplier !== 1 && `× ${r.age_multiplier} age`,
  r.availability_factor !== 1 && `× ${r.availability_factor} availability`,
  r.schedule_factor && r.schedule_factor !== 1 && `${r.team_abbr} schedule ${r.schedule_factor > 1 ? "+" : ""}${Math.round((r.schedule_factor - 1) * 100)}% on the Lock-In edge`,
  r.scarcity && `${r.scarcity > 0 ? "+" : ""}${r.scarcity.toFixed(2)} position scarcity`,
].filter(Boolean).join(" · ");

// Projection vs last season: one arrow per step (0.5 / 1.5 / 3 FP/G), green up, red down.
const trend = (r) => {
  if (r.proj_fpts == null || !r.last_fpts) return { dir: "", n: 0, diff: 0 };
  const diff = r.proj_fpts - r.last_fpts, a = Math.abs(diff);
  return { dir: diff > 0 ? "up" : "down", n: a >= 3 ? 3 : a >= 1.5 ? 2 : a >= 0.5 ? 1 : 0, diff };
};

// Tier colour: T1 red (best) fading to green by T15 (about the last drafted player in a 12-team league).

export default function RankingsTable({ rows, selectedId, onSelect, onBlock, live, sort, onSort, posFilter }) {
  // Fixed-width arrow slot on every sortable header, so nothing shifts when the sort changes.
  const arrow = (key) => <span className="sort-arrow">{sort && sort.key === key ? (sort.dir === "asc" ? "↑" : "↓") : ""}</span>;
  const byRank = !sort || sort.key === "rank";
  return (
    <table data-testid="rankings-table">
      <thead>
        <tr>
          {COLS.map(([key, term, cls]) => {
            const label = TERMS[term] ? <Term k={term}>{HEAD[term]}</Term> : term;
            return (
              <th key={key} className={`${cls || ""} ${onSort ? "sortable" : ""} ${sort?.key === key ? "sorted" : ""}`} onClick={() => onSort && onSort(key)}>
                {key === "rank" ? <span data-testid="rank-sort">{label}{arrow(key)}</span> : <>{label}{arrow(key)}</>}
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
              onDoubleClick={() => live && onBlock(r)}
              data-testid={`rank-row-${r.player_id}`}
            >
              <td className="rank-cell">
                {r.tier != null && <span className={`tier-cell ${r.tier_size >= 3 && r.tier_left <= 2 ? "last" : ""}`} style={tierHue(r.tier)} data-tip={`Tier ${r.tier}: ${r.tier_left} of ${r.tier_size} still available. ${TERMS.tier[1]}`}>T{r.tier}</span>}
                {" "}<span className="rank-num muted">{r.rank}</span>
              </td>
              <td>
                <div className="player-cell">
                <Headshot sleeperId={r.sleeper_id} name={r.full_name} size={34} />
                <div>
                <div className="player-name">
                  {r.full_name}
                  {inj && <span className={`inj ${inj === "DTD" ? "" : "out"}`} data-tip={r.injury_note || r.injury_status}>{inj}</span>}
                  {!r.has_stats && <span className="badge warn" data-tip="no NBA.com stats (Sleeper-only player)">no stats</span>}
                  {r.unsigned_per_sleeper && <span className="badge" data-tip="Sleeper lists this player as unsigned">FA?</span>}
                  {r.team_conflict && <span className="badge info" data-tip={`NBA.com ${r.team_conflict.nba_api} vs Sleeper ${r.team_conflict.sleeper}`}>team?</span>}
                  {r.eligibility_source === "none" && <span className="badge none" data-tip="eligibility not set — edit in the sidebar">elig?</span>}
                </div>
                <div className="player-sub">
                  <span className="sub-team">{r.team_abbr || "FA"} · </span>age {r.age ?? "?"} · {r.games_played} GP · last yr {r.last_fpts.toFixed(1)}{r.proj_fpts == null && <span className="badge" data-tip="Sleeper has no projection; last season only">no proj</span>}
                  {r.stack_if_added > 1 && <span className="badge" data-tip="players from this NBA team you would have">{r.team_abbr} ×{r.stack_if_added}</span>}
                </div>
                </div>
                </div>
              </td>
              <td className="muted col-narrow-hide">{r.team_abbr || "FA"}</td>
              <td><PosList list={r.eligibility} />{(posFilter ? r.pos_ranks?.[posFilter] : r.pos_rank) && <div className={`pos-rank ${posClass(posFilter ? r.pos_ranks[posFilter] : r.pos_rank)}`} data-tip={posFilter ? `Rank among every ${posFilter}-eligible player by Sleeper average draft position.` : TERMS.pos_rank[1]}>{posFilter ? r.pos_ranks[posFilter] : r.pos_rank}</div>}</td>
              <td className="num" data-tip={r.proj_fpts != null ? `projected ${r.proj_fpts.toFixed(1)} · last season ${r.last_fpts.toFixed(1)}` : "no projection: last season only"}>
                <strong>{r.avg_fpts.toFixed(1)}</strong>
                {(({ dir, n, diff }) => <span className={`trend ${dir}`} data-tip={n ? `${diff > 0 ? "+" : ""}${diff.toFixed(1)} FP/G vs last season${r.fpg_reason && r.fpg_reason.reason !== "steady" ? ` · ${r.fpg_reason.reason}` : ""}` : ""}>{(dir === "up" ? "▲" : "▼").repeat(n)}</span>)(trend(r))}
              </td>
              <td className="num col-narrow-hide">{r.owned_pct != null ? `${Math.round(r.owned_pct)}%` : "—"}</td>
              <td className={`num ${r.availability < 0.7 ? "warn-text" : "muted"}`}>{Math.round(r.availability * 100)}%</td>
              <td className={`num col-narrow-hide ${r.proj_min == null ? "muted" : ""}`}>{(r.proj_min ?? r.last_min)?.toFixed(1) ?? "-"}</td>
              <td className="num" data-tip={[r.fit?.why, valueWhy(r) && `Value: ${valueWhy(r)}`].filter(Boolean).join(" ")}>
                <strong className={`fit-num ${!r.fit ? "" : r.fit.score >= 70 ? "hi" : r.fit.score >= 45 ? "mid" : "lo"}`}>{r.fit ? r.fit.score : "—"}</strong>
              </td>
              <td className="num" data-tip={r.worth != null ? TERMS.worth[1] : "Shows once the draft is live."}>
                {r.worth != null ? <strong data-testid="worth">${r.worth}</strong> : <span className="muted">—</span>}
              </td>
              <td className="num" data-tip={r.call ? `${TERMS[r.call][0]}: ${TERMS[r.call][1]}` : "Shows once the draft is live."}>
                {r.max != null ? <strong className={`call-${r.call}`} data-testid="your-max">${r.max}</strong> : <span className="muted">{r.call === "cannot" ? "CAN'T" : "—"}</span>}
              </td>
              <td className="num" data-testid="r-value">{r.r_value != null ? `$${r.r_value}` : <span className="muted">—</span>}</td>
            </tr>
          );
        })}
        {!rows.length && <tr><td colSpan={COLS.length} className="muted" style={{ textAlign: "center", padding: 32 }}>No players to show.</td></tr>}
      </tbody>
    </table>
  );
}
