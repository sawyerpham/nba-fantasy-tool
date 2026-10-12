import React, { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";
import { VerdictBadge } from "./SpendingGuide.jsx";
import Headshot from "./Headshot.jsx";

const POSITIONS = ["PG", "SG", "SF", "PF", "C"];
const INJURY_STATUSES = ["healthy", "day_to_day", "out_short_term", "out_long_term", "out_season"];

function SourceBadge({ source }) {
  return <span className={`badge ${source}`} data-testid={`source-${source}`}>{source}</span>;
}

export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, onDraft, scoring, userName, onBlock, row }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [spend, setSpend] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(() => {
    if (!playerId) return;
    api.get(`/players/${playerId}` + qs({ league_id: leagueId })).then((d) => {
      setData(d);
      setNote(d.overrides?.injury_note || "");
      setNotes(d.overrides?.notes || "");
    }).catch((e) => setError(e.message));
    api.get(`/leagues/${leagueId}/fit/${playerId}`).then(setFit).catch(() => setFit(null));   // drafted players get no fit read
    if (live) {
      api.get(`/leagues/${leagueId}/recommend/${playerId}`).then(setRec).catch(() => setRec(null));
      api.get(`/leagues/${leagueId}/spending` + qs({ player_id: playerId })).then((g) => setSpend(g.focus)).catch(() => setSpend(null));
    } else {
      setRec(null);
      setSpend(null);
    }
  }, [leagueId, playerId, live]);

  useEffect(() => { setError(""); load(); }, [load, refreshKey]);

  if (!playerId) return <div className="panel muted">Select a player to see details, edit eligibility / injury, and get a bid recommendation.</div>;
  if (!data) return <div className="panel">{error || "Loading…"}</div>;

  const rec_ = data.record;
  const bio = rec_.bio;
  const ov = data.overrides || { eligibility: [], eligibility_source: "none", injury_status: "healthy", injury_source: "none" };
  const val = data.valuation;
  const fantasy = rec_.fantasy;

  const patch = async (body) => {
    setError("");
    try {
      await api.patch(`/players/${playerId}/overrides`, body);
      onOverridesChanged?.();
      load();
    } catch (e) {
      setError(e.message);
    }
  };
  const reset = async (field) => {
    setError("");
    try {
      await api.post(`/players/${playerId}/overrides/reset`, { fields: [field] });
      onOverridesChanged?.();
      load();
    } catch (e) {
      setError(e.message);
    }
  };
  const toggleElig = (pos) => {
    const next = ov.eligibility.includes(pos) ? ov.eligibility.filter((p) => p !== pos) : [...POSITIONS.filter((p) => ov.eligibility.includes(p) || p === pos)];
    patch({ eligibility: next });
  };

  return (
    <div className="panel scroll" data-testid="player-sidebar">
      <h3>
        <Headshot sleeperId={rec_.sleeper_id} name={rec_.full_name} size={64} />
        {rec_.full_name} <span className="muted">{rec_.team_abbr || "FA"}</span>
        {rec_.sleeper_status && rec_.sleeper_status !== "ACT" && <span className="badge">{rec_.sleeper_status}</span>}
        {rec_.unsigned_per_sleeper && <span className="badge warn">unsigned per Sleeper</span>}
        {rec_.team_conflict && <span className="badge info">NBA.com {rec_.team_conflict.nba_api} / Sleeper {rec_.team_conflict.sleeper}</span>}
        {!rec_.has_stats && <span className="badge warn">no stats</span>}
      </h3>
      <div className="small muted">
        {bio.position_raw ? `${bio.position_raw} · ` : ""}age {bio.age ?? "?"} · {bio.height_in ? `${Math.floor(bio.height_in / 12)}'${bio.height_in % 12}"` : "?"} · {bio.weight_lbs ?? "?"} lb
        {bio.years_exp != null ? ` · ${bio.years_exp} yrs exp` : ""}{bio.draft_year ? ` · drafted ${bio.draft_year} R${bio.draft_round} #${bio.draft_number}` : ""}
        {" · "}matched via {rec_.match_method}
      </div>
      {error && <div className="error">{error}</div>}

      {fit && fit.player_id === playerId && (
        <div className={`fit-card ${fit.verdict}`} data-testid="team-fit">
          <div className="fit-head"><span className="bid-label">For your team</span> <strong data-testid="team-fit-headline">{fit.headline}</strong></div>
          <ul className="small guide-lines">{fit.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        </div>
      )}

      {rec && (
        <div data-testid="recommendation">
          <h3>Bid guide <span className="badge info">for {userName || "you"}</span>{onBlock && <span className="badge">on the block</span>}</h3>
          <div className={`bid-grid ${spend && spend.verdict !== "cannot" ? "four" : ""}`}>
            <div className="bid-cell primary">
              <div className="bid-label">Pay up to</div>
              <div className="bid-num" data-testid="rec-max">{rec.can_bid ? `$${spend && spend.verdict !== "cannot" ? spend.suggested : rec.recommended_max}` : "—"}</div>
            </div>
            {spend && spend.verdict !== "cannot" && (
              <div className="bid-cell">
                <div className="bid-label">Market max</div>
                <div className="bid-num">${rec.recommended_max}</div>
              </div>
            )}
            <div className="bid-cell">
              <div className="bid-label">Fair value (league)</div>
              <div className="bid-num">${Math.round(rec.fair_value)}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label">Your cap</div>
              <div className="bid-num">${rec.my_max_bid}</div>
            </div>
          </div>
          {spend && rec.can_bid && (
            <div className="small" style={{ margin: "4px 0" }} data-testid="spend-verdict">
              <VerdictBadge verdict={spend.verdict} /> {spend.text}
              {spend.verdict !== "cannot" && (
                <div className="muted">after ${spend.suggested}: ${spend.left_after} left · ${spend.per_starter_after}/starter vs room ${spend.room_per_starter} · stretch ${spend.stretch} · walk-away ${spend.walk_away} · {spend.rivals_above_market} rival{spend.rivals_above_market === 1 ? "" : "s"} can reach the market max</div>
              )}
            </div>
          )}
          {!rec.can_bid && <div className="warn-text small">You can't bid: {rec.rationale[rec.rationale.length - 1]}</div>}
          <div className="small muted">
            ${rec.my_budget_remaining} left · {rec.my_open_mandatory} slot{rec.my_open_mandatory === 1 ? "" : "s"} to fill ·{" "}
            {rec.competitors.length
              ? `${rec.competitors.length} rival${rec.competitors.length === 1 ? "" : "s"} can afford it: ` +
                rec.competitors.slice().sort((a, b) => b.max_bid - a.max_bid).slice(0, 3).map((c) => `${c.name} $${c.max_bid}`).join(", ") +
                (rec.competitors.length > 3 ? ` +${rec.competitors.length - 3} more` : "")
              : "no rival can afford it"}
          </div>
          <details className="small" style={{ marginTop: 4 }}>
            <summary>show the math</summary>
            <ul>{rec.rationale.map((line, i) => <li key={i}>{line}</li>)}</ul>
          </details>
          {live && <button className="primary" style={{ marginTop: 6 }} onClick={() => onDraft({ player_id: rec_.player_id, full_name: rec_.full_name, team_abbr: rec_.team_abbr, sleeper_id: rec_.sleeper_id })} data-testid="sidebar-draft">On the block</button>}
        </div>
      )}

      <h3>Eligibility <SourceBadge source={ov.eligibility_source} /> <button className="small" onClick={() => reset("eligibility")} data-testid="reset-eligibility">reset to Sleeper</button></h3>
      <div className="row">
        {POSITIONS.map((p) => (
          <label key={p} className="inline"><input type="checkbox" checked={ov.eligibility.includes(p)} onChange={() => toggleElig(p)} data-testid={`elig-${p}`} /> {p}</label>
        ))}
        {fantasy?.fantasy_positions_alt && <span className="small muted">Sleeper alt: {fantasy.fantasy_positions_alt.join("/")}</span>}
      </div>

      <h3>Injury <SourceBadge source={ov.injury_source} /> <button className="small" onClick={() => reset("injury")} data-testid="reset-injury">reset to Sleeper</button></h3>
      <div className="row">
        <select value={ov.injury_status} onChange={(e) => patch({ injury_status: e.target.value })} data-testid="injury-select">
          {INJURY_STATUSES.map((s) => <option key={s}>{s}</option>)}
        </select>
        <input type="text" value={note} placeholder="note" onChange={(e) => setNote(e.target.value)} onBlur={() => note !== (ov.injury_note || "") && patch({ injury_note: note })} data-testid="injury-note" />
        {ov.injury_sleeper_raw && <span className="small muted">Sleeper: {ov.injury_sleeper_raw}{fantasy?.injury_body_part ? ` (${fantasy.injury_body_part})` : ""}</span>}
      </div>
      <div><textarea rows="2" style={{ width: "100%" }} placeholder="your notes" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (ov.notes || "") && patch({ notes })} /></div>

      <h3>Fantasy points <span className="muted small">(scoring {data.scoring_hash})</span></h3>
      {row && (
        <div className="small" data-testid="fp-this-season">
          This season: <strong>{row.avg_fpts.toFixed(1)} FP/G</strong>{" "}
          {row.proj_fpts != null ? "(Sleeper's projection, the number the rankings use)" : "(no Sleeper projection, so last season's number)"}
          {row.proj_fpts != null && row.last_fpts ? <span className={row.proj_fpts >= row.last_fpts ? "ok" : "warn-text"}> · {(row.proj_fpts - row.last_fpts) >= 0 ? "+" : ""}{(row.proj_fpts - row.last_fpts).toFixed(1)} vs last season</span> : null}
        </div>
      )}
      {val && <div className="bid-label" style={{ marginTop: 8 }}>Last season (actual games)</div>}
      {val ? (
        <div className="small">
          <div>
            <strong>{val.avg_fpts} FP/G</strong> over {val.games_played} games · weekly-best avg <strong>{val.weekly_best_avg}</strong> · best game {val.best_game_fpts} · top-25% avg {val.top_quarter_avg} · total {Math.round(val.total_fpts)} FP
          </div>
          <div>{val.weeks_played} of {val.season_weeks} fantasy weeks with a game ({Math.round(val.availability * 100)}%) · {val.minutes_avg} min · teams {val.teams_played_for.join(", ") || "-"}</div>
          {scoring && (
            <details style={{ marginTop: 4 }}>
              <summary>How the {val.avg_fpts} FP/G is made</summary>
              <table className="small">
                <thead><tr><th>stat</th><th>avg / game</th><th>× points</th><th>= FP</th></tr></thead>
                <tbody>
                  {Object.entries(scoring.base).map(([k, w]) => {
                    const avg = val.stat_averages?.[k] ?? 0;
                    return <tr key={k}><td>{k}</td><td>{avg.toFixed(1)}</td><td>{w}</td><td>{(avg * w).toFixed(2)}</td></tr>;
                  })}
                  <tr><td>bonuses</td><td colSpan="2">{Object.entries(val.bonus_counts).filter(([, n]) => n).map(([k, n]) => `${k}×${n}`).join(", ") || "none"}</td><td>{val.bonus_fpts_per_game.toFixed(2)}</td></tr>
                  <tr><th colSpan="3">FP per game</th><th>{val.avg_fpts}</th></tr>
                </tbody>
              </table>
            </details>
          )}
          <div className="muted">Per game: {val.per_game_fpts.slice(-15).join(", ")}{val.per_game_fpts.length > 15 ? " (last 15)" : ""}</div>
        </div>
      ) : <p className="muted small">No game logs for the stats season.</p>}

      {data.detail?.season_totals?.length > 0 && (
        <>
          <h3>Season history</h3>
          <table className="small">
            <thead><tr><th>season</th><th>team</th><th>age</th><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>TOV</th></tr></thead>
            <tbody>
              {data.detail.season_totals.slice().reverse().map((t, i) => (
                <tr key={i}><td>{t.season}</td><td>{t.team_abbr}</td><td>{t.age ?? ""}</td><td>{t.gp}</td><td>{t.gp ? (t.minutes / t.gp).toFixed(1) : ""}</td>
                  <td>{t.gp ? (t.pts / t.gp).toFixed(1) : ""}</td><td>{t.gp ? (t.reb / t.gp).toFixed(1) : ""}</td><td>{t.gp ? (t.ast / t.gp).toFixed(1) : ""}</td>
                  <td>{t.gp ? (t.stl / t.gp).toFixed(1) : ""}</td><td>{t.gp ? (t.blk / t.gp).toFixed(1) : ""}</td><td>{t.gp ? (t.tov / t.gp).toFixed(1) : ""}</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
