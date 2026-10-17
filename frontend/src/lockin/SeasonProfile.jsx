import React from "react";
import { fmt, timeOf, tzAbbr } from "./tz.js";

const dayName = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });

// Season profile: owner, your call on him this week, his games this week, game log and news.
export default function SeasonBlock({ sea, plan }) {
  const mine = plan?.players?.find((p) => p.sid === sea.sleeper_id);
  return (
    <div className="season-block" data-testid="season-profile">
      <div className="small" style={{ margin: "6px 0" }}>
        <span className="muted">Owner:</span>{" "}
        {sea.owner ? <strong className={sea.owner.is_user ? "ok" : ""}>{sea.owner.is_user ? "You" : sea.owner.name}{sea.owner.ir ? " (IR)" : ""}</strong> : <strong>Free agent</strong>}
      </div>
      {sea.acquired?.length > 0 && (
        <div className="small" style={{ margin: "0 0 6px" }} data-testid="season-acquired">
          {sea.acquired.map((a, i) => (
            <div key={i}>
              <span className="muted">{a.kind[0].toUpperCase() + a.kind.slice(1)}</span>{" "}
              {a.kind !== "traded to" && "by "}<strong>{a.team || "?"}</strong>
              {a.price != null && <> for <strong>${a.price}</strong></>}
              {a.when && <span className="muted"> · {fmt(a.when, { month: "2-digit", day: "2-digit", year: "2-digit" })}</span>}
            </div>
          ))}
        </div>
      )}
      {mine && (
        <div className="small" style={{ marginBottom: 6 }} data-testid="season-call">
          <span className="verdict info">{mine.action}</span> <span className="muted">{mine.why}</span>
        </div>
      )}
      <div className="bid-label">Week {sea.week} games</div>
      {sea.games.length ? (
        <table className="small">
          <thead><tr><th>Day</th><th>Opp</th><th>Tip ({tzAbbr()})</th><th className="num">Proj</th><th className="num">FP</th><th className="num">Min</th></tr></thead>
          <tbody>{sea.games.map((g) => (
            <tr key={g.date} className={g.date === sea.today ? "you-need" : ""}><td>{dayName(g.date)} {g.date.slice(5)}</td><td>{g.home ? "vs" : "@"} {g.opp}</td>
              <td>{g.state === "in" ? <span className="warn-text">live</span> : g.state === "post" ? "final" : timeOf(g.tip)}</td>
              <td className="num">{g.proj != null ? g.proj.toFixed(1) : ""}</td><td className="num"><strong>{g.fp != null ? g.fp.toFixed(1) : ""}</strong></td>
              <td className="num">{g.min ?? ""}</td></tr>))}</tbody>
        </table>
      ) : <div className="small muted">No games this week.</div>}
      {sea.game_log.length > 0 && (
        <>
          <div className="bid-label" style={{ marginTop: 8 }}>Last {sea.game_log.length} games</div>
          <table className="small">
            <thead><tr><th>Date</th><th>Opp</th><th className="num">FP</th><th className="num">Min</th><th className="num">PTS</th><th className="num">REB</th><th className="num">AST</th><th className="num">STL</th><th className="num">BLK</th><th className="num">TO</th></tr></thead>
            <tbody>{sea.game_log.map((g) => (
              <tr key={g.date}><td>{g.date.slice(5)}</td><td>{g.opp}</td><td className="num"><strong>{g.fp.toFixed(1)}</strong></td><td className="num">{g.min}</td>
                <td className="num">{g.pts}</td><td className="num">{g.reb}</td><td className="num">{g.ast}</td><td className="num">{g.stl}</td><td className="num">{g.blk}</td><td className="num">{g.to}</td></tr>))}</tbody>
          </table>
        </>
      )}
      {sea.news.length > 0 && (
        <>
          <div className="bid-label" style={{ marginTop: 8 }}>Latest news</div>
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
