import React from "react";
import TeamLink from "../core/TeamLink.jsx";
import { fmt } from "./tz.js";
import InjuryTag from "../core/InjuryTag.jsx";

// The in-season player profile's tabs (backend season_player): Summary, Game log and History; the Team tab (depth
// chart) is drawn by PlayerSidebar, which already has his team card.

/** One-decimal number, or an em dash for null. */
const f1 = (x) => (x == null ? "—" : Number(x).toFixed(1));
/** Fantasy points to two decimals (like Sleeper), or an em dash for null. */
const f2 = (x) => (x == null ? "—" : Number(x).toFixed(2));
/** "2026-10-23" -> "10/23". */
const mmdd = (d) => d.slice(5).replace("-", "/");
/** A timestamp as "Oct 15 2026" in the league's time zone. */
const longDate = (ms) => fmt(ms, { month: "short", day: "numeric", year: "numeric" }).replace(",", "");
/** ESPN's live game status in quarters: "3:14 - 1st" -> "Q1 3:14", "5:00 - 2OT" -> "2OT 5:00". */
const quarters = (d) => (d || "").replace(/^(.+) - (\d)(?:st|nd|rd|th)$/, "Q$2 $1").replace(/^(.+) - (\d?OT)$/, "$2 $1").replace(/\b(\d)(?:st|nd|rd|th)\b/g, "Q$1");

/**
 * Summary tab: his live or last game (both teams, score, quarter and clock, his FP and line), season averages, then ranks, ownership and FP per game, with owner and injury status under them.
 * `onOpenGame(game)` opens that game's card (GamePanel) on the right when the game box is clicked.
 */
export function SeasonSummary({ sea, onOpenGame }) {
  const g = sea.last_game, a = sea.averages, live = g?.state === "in";
  /** One labelled number in the summary grid. */
  const stat = (label, value) => <div className="sp-stat"><span>{label}</span><strong>{value}</strong></div>;
  const openable = g?.event && onOpenGame;
  return (
    <div data-testid="season-summary">
      {g && (
        <div className={`sp-game ${live ? "live" : ""} ${openable ? "clickable" : ""}`} data-testid="last-game"
          onClick={openable ? () => onOpenGame({ game: g, team: g.team, sid: sea.sleeper_id }) : undefined}
          data-tip={openable ? "Open the game" : undefined}>
          <div className="sp-game-top">
            <span className="small muted">{live ? <span className="sp-live">LIVE</span> : "Last game"} · {mmdd(g.date)}</span>
            <span className="small">{live ? quarters(g.detail) : "Final"}</span>
          </div>
          <div className="sp-game-mid">
            <div className="sp-score"><strong><TeamLink abbr={g.team} /></strong> {g.team_pts ?? "—"} <span className="muted">{g.home ? "vs" : "@"}</span> <strong><TeamLink abbr={g.opp} /></strong> {g.opp_pts ?? "—"}</div>
            <div className="sp-fp"><span>{f2(g.fp)}</span><small>FP</small></div>
          </div>
          <div className="small muted">{g.min} min · {g.pts} pts · {g.reb} reb · {g.ast} ast · {g.stl} stl · {g.blk} blk · {g.to} to{g.fga != null && <> · {g.fgm}/{g.fga} FG · {g.ftm}/{g.fta} FT</>}</div>
        </div>
      )}
      <div className="bid-label sp-head">Season averages <span className="muted">· {sea.games_played} GP</span></div>
      {a ? <div className="sp-grid">{stat("MPG", f1(a.min))}{stat("PTS", f1(a.pts))}{stat("REB", f1(a.reb))}{stat("AST", f1(a.ast))}
        {stat("STL", f1(a.stl))}{stat("BLK", f1(a.blk))}{stat("TO", f1(a.to))}</div> : <div className="small muted">No finished games yet.</div>}
      <div className="sp-grid sp-grid-5">
        {stat("Pos rank", sea.pos_rank || "—")}{stat("Overall", sea.overall_rank ? `#${sea.overall_rank}` : "—")}
        {stat("Owned", sea.owned != null ? `${Math.round(sea.owned)}%` : "—")}{stat("Started", sea.started != null ? `${Math.round(sea.started)}%` : "—")}
        {stat("FP/G", f2(a?.fp))}
      </div>
      <div className="small sp-meta">
        <div><span className="muted">Owner</span> {sea.owner ? <strong className={sea.owner.is_user ? "ok" : ""}>{sea.owner.is_user ? "You" : sea.owner.name}</strong> : <strong>Free agent</strong>}</div>
        {sea.owner && <div><span className="muted">Slot</span> <strong>{sea.owner.slot}</strong></div>}
        <div><span className="muted">Status</span> {sea.retired ? <strong className="warn-text">retired</strong>
          : sea.injury_tag ? <><InjuryTag tag={sea.injury_tag} />{sea.injury_note && <span className="muted"> {sea.injury_note}</span>}</> : <strong>healthy</strong>}</div>
      </div>
      {sea.news.length > 0 && (
        <>
          <div className="bid-label sp-head">Latest news</div>
          {sea.news.map((n, i) => (
            <div key={i} className="news-item small">
              <strong>{n.headline}</strong> <span className="muted">{n.published ? new Date(n.published).toLocaleDateString("en-US", { month: "short", day: "numeric" }) : ""}</span>
              {n.story && n.story !== n.headline && <div className="muted">{n.story}</div>}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// [header, shown value, raw key]
const LOG_COLS = [["FPTS", (r) => f2(r.fp), "fp"], ["MIN", (r) => r.min, "min"], ["PTS", (r) => r.pts, "pts"], ["REB", (r) => r.reb, "reb"],
  ["AST", (r) => r.ast, "ast"], ["STL", (r) => r.stl, "stl"], ["BLK", (r) => r.blk, "blk"], ["TO", (r) => r.to, "to"], ["PF", (r) => r.pf, "pf"],
  ["+/-", (r) => (r.pm > 0 ? `+${r.pm}` : r.pm), "pm"]];
const LESS_IS_BETTER = new Set(["to", "pf"]);
/** Colour band for one game stat against his own season average: "up" at 8% or more above it, "even" within 8%, "down" below (turnovers and fouls the other way round; +/- by its sign, within 1 is even). null when he didn't play. */
function logTone(k, v, avg) {
  if (v == null) return null;
  let rel = k === "pm" ? v / 10 : (v - avg) / Math.max(avg, 1);
  if (LESS_IS_BETTER.has(k)) rel = -rel;
  return rel >= 0.08 ? "up" : rel > -0.08 ? "even" : "down";
}
/** Game-log tab: every game his team plays this season, with his line where he played (blank for games to come or missed), each stat toned against his season average. */
export function SeasonLog({ sea }) {
  const played = sea.season_log.filter((r) => r.fp != null);
  const avg = Object.fromEntries(LOG_COLS.map(([, , k]) => [k, played.reduce((t, r) => t + (r[k] || 0), 0) / (played.length || 1)]));
  return (
    <table className="sp-log" data-testid="season-log">
      <thead><tr><th>WK</th><th>OPP</th><th>DATE</th>{LOG_COLS.map(([h]) => <th key={h} className="log-cell">{h}</th>)}</tr></thead>
      <tbody>{sea.season_log.map((r) => (
        <tr key={r.date} className={`${r.week === sea.week ? "this-week" : ""} ${r.fp == null ? "muted" : ""}`}>
          <td>{r.week}</td><td>{r.home ? "" : "@"}<TeamLink abbr={r.opp} /></td><td>{mmdd(r.date)}</td>
          {LOG_COLS.map(([h, f, k]) => {
            const tone = r.fp == null ? null : logTone(k, r[k], avg[k]);
            return <td key={h} className="num log-cell">
              {r.fp == null ? "" : <span className={`log-box ${tone || ""}`}>{f(r)}</span>}</td>;
          })}
        </tr>
      ))}</tbody>
    </table>
  );
}

const KIND = { drafted: "Drafted", keeper: "Keeper", claimed: "Claimed", "picked up": "Added", "traded to": "Trade", dropped: "Dropped", added: "Added" };
/** History tab: how he changed hands (draft, keeper, claims, pickups, trades, drops), newest first, as Type | what happened | date. A keeper also shows last season's draft. */
export function SeasonHistory({ sea }) {
  /** The sentence for one transaction ("kept by X for $5", "traded to Y", ...). */
  const what = (a) => {
    const by = a.team || "?", price = a.price != null ? ` for $${a.price}` : "";
    return a.kind === "keeper" ? `kept by ${by}${price}` : a.kind === "drafted" ? `drafted by ${by}${price}${a.season ? ` (${a.season})` : ""}`
      : a.kind === "claimed" ? `claimed by ${by}${price}` : a.kind === "traded to" ? `traded to ${by}` : a.kind === "dropped" ? `dropped by ${by}` : `added by ${by}`;
  };
  if (!sea.acquired?.length) return <div className="small muted">No transactions this season: he hasn't been drafted, kept or moved.</div>;
  return (
    <table className="sp-history" data-testid="season-history">
      <tbody>{[...sea.acquired].reverse().map((a, i) => (   /* newest first (the backend sends them oldest first) */
        <tr key={i}><td><strong>{KIND[a.kind] || a.kind}</strong></td><td>{what(a)}</td><td className="muted">{a.when ? longDate(a.when) : ""}</td></tr>
      ))}</tbody>
    </table>
  );
}
