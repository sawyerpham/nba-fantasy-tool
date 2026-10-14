import React, { useCallback, useEffect, useState } from "react";
import { api, qs } from "../api.js";
import { VerdictBadge } from "./SpendingGuide.jsx";
import Headshot from "./Headshot.jsx";


export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, userName, onBlock, row }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [spend, setSpend] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");

  const load = useCallback(() => {
    if (!playerId) return;
    api.get(`/players/${playerId}` + qs({ league_id: leagueId })).then((d) => {
      setData(d);
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
      </div>
      {error && <div className="error">{error}</div>}

      {fit && fit.player_id === playerId && (
        <div className={`fit-card ${fit.verdict}`} data-testid="team-fit">
          <div className="fit-head"><span className="bid-label">Fit for your team (same as the Fit column)</span> <strong data-testid="team-fit-headline">{fit.headline}</strong></div>
          <ul className="small guide-lines">{fit.score_lines.map((r, i) => <li key={i}>{r}</li>)}</ul>
          {fit.notes.length > 0 && (
            <>
              <div className="bid-label" style={{ marginTop: 6 }}>Worth knowing (not in the score)</div>
              <ul className="small guide-lines">{fit.notes.map((r, i) => <li key={i}>{r}</li>)}</ul>
            </>
          )}
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
            <div className="small" style={{ margin: "4px 0" }} data-testid="spend-verdict" title={spend.text}>
              <VerdictBadge verdict={spend.verdict} />
              {spend.verdict !== "cannot" && <span className="muted"> stretch ${spend.stretch} · walk-away ${spend.walk_away} · hover for why</span>}
            </div>
          )}
          {!rec.can_bid && <div className="warn-text small">You can't bid: {rec.rationale[rec.rationale.length - 1]}</div>}
          <details className="small" style={{ marginTop: 4 }}>
            <summary>show the math</summary>
            <ul>{rec.rationale.map((line, i) => <li key={i}>{line}</li>)}</ul>
          </details>
        </div>
      )}

      <div className="small" style={{ marginTop: 10 }} data-testid="sleeper-info">
        <span className="muted">Positions (Sleeper):</span> <strong>{ov.eligibility.join(" / ") || "none listed"}</strong>
        {" · "}<span className="muted">Injury:</span>{" "}
        <strong className={ov.injury_status === "healthy" ? "" : "warn-text"}>{ov.injury_status.replace(/_/g, " ")}</strong>
        {ov.injury_note && <span className="muted"> · {ov.injury_note}</span>}
      </div>
      <div><textarea rows="1" style={{ width: "100%" }} placeholder="your notes" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (ov.notes || "") && patch({ notes })} /></div>

      {data.team && (
        <div className="team-card" data-testid="team-card">
          <div className="team-card-head">
            <img src={data.team.logo} alt="" width={40} height={40} className="team-logo" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
            <div>
              <div className="team-name">{data.team.name}</div>
              <div className="small muted">
                {data.team.player_rank && <><strong style={{ color: "var(--text)" }}>#{data.team.player_rank}</strong> on the team · </>}
                <span title={`sum of the top 8 players' projected FP/G (${data.team.talent_fpg}); a fantasy-talent ranking, not a win projection`}>
                  team <strong style={{ color: "var(--text)" }}>#{data.team.talent_rank}</strong> of {data.team.teams} in projected fantasy talent
                </span>
              </div>
            </div>
          </div>
          <div className="teammates">
            {data.team.teammates.map((m, i) => (
              <div key={m.player_id} className={`teammate ${m.is_self ? "self" : ""} ${m.drafted_by ? "taken" : ""}`}
                title={`${m.name} · ${m.pos.join("/")} · ${m.fpg} FP/G${m.min ? ` · ${m.min} min` : ""}${m.drafted_by ? ` · drafted by ${m.drafted_by}` : ""}`}>
                <span className="teammate-rank">{i + 1}</span>
                <Headshot sleeperId={m.sleeper_id} name={m.name} size={30} />
                <span className="teammate-name">{m.name}</span>
                <span className="teammate-fpg">{m.fpg.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <h3>Fantasy points</h3>
      {row && (
        <div className="small" data-testid="fp-this-season">
          This season: <strong>{row.avg_fpts.toFixed(1)} FP/G</strong>{" "}
          {row.proj_fpts != null ? "(Sleeper projection, used by the rankings)" : "(no Sleeper projection, so last season's number)"}
          {row.proj_fpts != null && row.last_fpts ? <span className={row.proj_fpts >= row.last_fpts ? "ok" : "warn-text"}> · {(row.proj_fpts - row.last_fpts) >= 0 ? "+" : ""}{(row.proj_fpts - row.last_fpts).toFixed(1)} vs last season</span> : null}
          {row.fpg_reason && row.fpg_reason.reason !== "steady" && (
            <div data-testid="fpg-reason">
              Why: {row.fpg_reason.detail || row.fpg_reason.reason} <span className="muted">({row.fpg_reason.confidence} confidence)</span>
              {row.fpg_reason.sources?.map((u, i) => <a key={u} href={u} target="_blank" rel="noreferrer" className="muted"> [{i + 1}]</a>)}
            </div>
          )}
        </div>
      )}
      {val && <div className="bid-label" style={{ marginTop: 8 }}>Last season (actual games)</div>}
      {val ? (
        <div className="small">
          <div>
            <strong>{val.avg_fpts} FP/G</strong> over {val.games_played} games · weekly-best avg <strong>{val.weekly_best_avg}</strong> · best game {val.best_game_fpts} · top-25% avg {val.top_quarter_avg} · total {Math.round(val.total_fpts)} FP
          </div>
          <div>{val.weeks_played} of {val.season_weeks} fantasy weeks with a game ({Math.round(val.availability * 100)}%) · {val.minutes_avg} min · teams {val.teams_played_for.join(", ") || "-"}</div>
          <details><summary className="small">Per-game FP (last 15)</summary><div className="muted">{val.per_game_fpts.slice(-15).join(", ")}</div></details>
        </div>
      ) : <p className="muted small">No game logs for the stats season.</p>}

      {data.detail?.season_totals?.length > 0 && (
        <>
          <details><summary className="small">Season history</summary>
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
          </details>
        </>
      )}
    </div>
  );
}
