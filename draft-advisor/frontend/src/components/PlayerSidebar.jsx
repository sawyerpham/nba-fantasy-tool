import React, { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";

const POSITIONS = ["PG", "SG", "SF", "PF", "C"];
const INJURY_STATUSES = ["healthy", "day_to_day", "out_short_term", "out_long_term", "out_season"];

function SourceBadge({ source }) {
  return <span className={`badge ${source}`} data-testid={`source-${source}`}>{source}</span>;
}

export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, onDraft }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
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
    if (live) {
      api.get(`/leagues/${leagueId}/recommend/${playerId}`).then(setRec).catch(() => setRec(null));
    } else {
      setRec(null);
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

      <h3>Valuation <span className="muted small">({data.scoring_hash})</span></h3>
      {val ? (
        <div className="small">
          {val.games_played} games · avg <strong>{val.avg_fpts}</strong> · best game <strong>{val.best_game_fpts}</strong> · {val.minutes_avg} min · teams {val.teams_played_for.join(", ") || "-"}
          <div>Bonuses: {Object.entries(val.bonus_counts).filter(([, n]) => n).map(([k, n]) => `${k}×${n}`).join(", ") || "none"}</div>
          <div className="muted">Per game: {val.per_game_fpts.slice(-15).join(", ")}{val.per_game_fpts.length > 15 ? " (last 15)" : ""}</div>
        </div>
      ) : <p className="muted small">No game logs for the stats season.</p>}

      {rec && (
        <div data-testid="recommendation">
          <h3>Bid recommendation</h3>
          <div className="small">
            Fair value <strong>${rec.fair_value}</strong> · recommended max <strong data-testid="rec-max">${rec.recommended_max}</strong> · your max bid ${rec.my_max_bid} (${rec.my_budget_remaining} left, {rec.my_open_mandatory} mandatory open)
            {!rec.can_bid && <span className="badge warn">cannot bid</span>}
          </div>
          <div className="small">Competitors ({rec.competitors.length}): {rec.competitors.map((c) => `${c.name} ≤$${c.max_bid}×${c.weight}`).join(", ") || "none"}</div>
          <ul className="small">{rec.rationale.map((line, i) => <li key={i}>{line}</li>)}</ul>
          {live && <button className="primary" onClick={() => onDraft({ player_id: rec_.player_id, full_name: rec_.full_name, team_abbr: rec_.team_abbr })} data-testid="sidebar-draft">Drafted…</button>}
        </div>
      )}

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
