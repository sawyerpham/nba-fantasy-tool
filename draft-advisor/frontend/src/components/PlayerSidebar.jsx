import React, { useCallback, useEffect, useRef, useState } from "react";
import { PosList, PosTag, posClass } from "./Pos.jsx";
import { tierHue } from "./RankingsTable.jsx";
import { api, qs } from "../api.js";
import { CallBadge, Term, TERMS } from "./Terms.jsx";
import Headshot from "./Headshot.jsx";


export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, userName, onBlock, rankings, onSelectPlayer }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [spend, setSpend] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");

  // All four requests are fetched together and applied in one update, so the card never rebuilds piece by piece;
  // the previous player stays on screen until the new one is ready, and late answers for an older click are dropped.
  const latest = useRef(0);
  const load = useCallback(() => {
    if (!playerId) return;
    const ticket = ++latest.current;
    const opt = (p) => p.catch(() => null);   // drafted players have no fit / bid guide
    Promise.all([
      api.get(`/players/${playerId}` + qs({ league_id: leagueId })),
      opt(api.get(`/leagues/${leagueId}/fit/${playerId}`)),
      live ? opt(api.get(`/leagues/${leagueId}/recommend/${playerId}`)) : null,
      live ? opt(api.get(`/leagues/${leagueId}/spending` + qs({ player_id: playerId })).then((g) => g.focus)) : null,
    ]).then(([d, f, r, sp]) => {
      if (ticket !== latest.current) return;
      setData(d); setNotes(d.overrides?.notes || ""); setFit(f); setRec(r); setSpend(sp); setError("");
    }).catch((e) => { if (ticket === latest.current) setError(e.message); });
  }, [leagueId, playerId, live]);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (!playerId) return <div className="panel muted">Select a player to see his profile, his Fit for your team and your max.</div>;
  if (!data) return <div className="panel">{error || "Loading…"}</div>;

  const rec_ = data.record;
  const shownId = rec_.player_id;   // the player on screen (the previous one until a new click finishes loading)
  const row = rankings?.find((r) => r.player_id === shownId);
  const bio = rec_.bio;
  const ov = data.overrides || { eligibility: [], eligibility_source: "none", injury_status: "healthy", injury_source: "none" };
  const val = data.valuation;
  const fantasy = rec_.fantasy;

  const patch = async (body) => {
    setError("");
    try {
      await api.patch(`/players/${shownId}/overrides`, body);
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
        <span className="profile-tags">
          <span>{ov.eligibility.length ? <PosList list={ov.eligibility} /> : "no position"} · age {bio.age ?? "?"}</span>
          {(row?.pos_rank || row?.tier != null) && (
            <span className="profile-ranks">
              {row.pos_rank && <span className={`pos-c ${posClass(row.pos_rank)}`} data-tip={TERMS.pos_rank[1]}>{row.pos_rank}</span>}
              {row.tier != null && <span className={`tier-cell ${row.tier_size >= 3 && row.tier_left <= 2 ? "last" : ""}`} style={tierHue(row.tier)} data-tip={`Tier ${row.tier}: ${row.tier_left} of ${row.tier_size} still available. ${TERMS.tier[1]}`}>T{row.tier}</span>}
            </span>
          )}
        </span>
        {rec_.sleeper_status && rec_.sleeper_status !== "ACT" && <span className="badge">{rec_.sleeper_status}</span>}
        {rec_.unsigned_per_sleeper && <span className="badge warn">unsigned per Sleeper</span>}
        {rec_.team_conflict && <span className="badge info">NBA.com {rec_.team_conflict.nba_api} / Sleeper {rec_.team_conflict.sleeper}</span>}
        {!rec_.has_stats && <span className="badge warn">no stats</span>}
      </h3>
      <div className="small muted">
        {bio.height_in ? `${Math.floor(bio.height_in / 12)}'${bio.height_in % 12}"` : "?"} · {bio.weight_lbs ?? "?"} lb
        {bio.years_exp != null ? ` · ${bio.years_exp} yrs exp` : ""}{bio.draft_year ? ` · drafted ${bio.draft_year} R${bio.draft_round} #${bio.draft_number}` : ""}
      </div>
      {error && <div className="error">{error}</div>}

      {fit && fit.player_id === shownId && (
        <div className={`fit-card ${fit.verdict}`} data-testid="team-fit">
          <div className="fit-head"><span className="bid-label"><Term k="fit" /> for your team</span> <strong data-testid="team-fit-headline">{fit.headline}</strong></div>
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
          <div className={`bid-grid ${rec.can_bid ? "four" : ""}`}>
            <div className="bid-cell primary">
              <div className="bid-label"><Term k="your_max" /></div>
              <div className="bid-num" data-testid="rec-max">{spend && spend.verdict !== "cannot" ? `$${spend.suggested}` : "—"}</div>
            </div>
            {rec.can_bid && (
              <div className="bid-cell">
                <div className="bid-label"><Term k="market" /></div>
                <div className="bid-num">${rec.recommended_max}</div>
              </div>
            )}
            <div className="bid-cell">
              <div className="bid-label"><Term k="fair" /></div>
              <div className="bid-num">${Math.round(rec.fair_value)}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label"><Term k="cap">Your cap</Term></div>
              <div className="bid-num">${rec.my_max_bid}</div>
            </div>
          </div>
          {spend && rec.can_bid && (
            <div className="small" style={{ margin: "4px 0" }} data-testid="spend-verdict">
              <CallBadge call={spend.verdict} />
              {spend.verdict !== "cannot" && <span className="muted"> <Term k="comfort">comfort limit</Term> ${spend.stretch} · <Term k="walk">walk-away</Term> ${spend.walk_away}</span>}
            </div>
          )}
          {!rec.can_bid && <div className="warn-text small">You can't bid: {rec.rationale[rec.rationale.length - 1]}</div>}
          <details className="small" style={{ marginTop: 4 }}>
            <summary>show the math</summary>
            <ul>{spend?.text && <li data-testid="call-why">{spend.text}</li>}{rec.rationale.map((line, i) => <li key={i}>{line}</li>)}</ul>
          </details>
        </div>
      )}

      <div className="small" style={{ marginTop: 10 }} data-testid="sleeper-info">
        <span className="muted">Status:</span>{" "}
        <strong className={ov.injury_status === "healthy" ? "" : "warn-text"}>{ov.injury_status.replace(/_/g, " ")}</strong>
        {ov.injury_note && <span className="muted"> · {ov.injury_note}</span>}
      </div>
      <div><textarea rows="1" style={{ width: "100%" }} placeholder="your notes" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (ov.notes || "") && patch({ notes })} /></div>

      {data.team && (
        <div className="team-card" data-testid="team-card">
          <div className="team-card-head">
            <img src={data.team.logo} alt="" width={40} height={40} className="team-logo" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
            <div>
              <div className="team-name">{data.team.name}{data.team.conference && <span className={`conf conf-${data.team.conference}`}>{data.team.conference}</span>}</div>
              <div className="small muted">
                {data.team.player_rank && <><strong style={{ color: "var(--text)" }}>#{data.team.player_rank}</strong> on the team · </>}
                <span title={`sum of the top 8 players' projected FP/G (${data.team.talent_fpg}); a fantasy-talent ranking, not a win projection`}>
                  team <strong style={{ color: "var(--text)" }}>#{data.team.talent_rank}</strong> of {data.team.teams} in projected fantasy talent
                </span>
              </div>
            </div>
          </div>
          <div className="teammates">
            {[["Starters", data.team.teammates.filter((m) => m.starter)], ["Next up", data.team.teammates.filter((m) => !m.starter)]].map(([label, list]) => (
              <div key={label} className="teammate-col">
                <div className="bid-label">{label}</div>
                {list.map((m) => (
                  <div key={m.player_id} className={`teammate ${m.is_self ? "self" : ""} ${m.drafted_by ? "taken" : ""}`}
                    onClick={() => !m.is_self && onSelectPlayer?.(m.player_id)}
                    title={`${m.name} · ${m.pos.join("/")} · ${m.fpg} FP/G${m.min ? ` · ${m.min} min` : ""}${m.drafted_by ? ` · drafted by ${m.drafted_by}` : ""}`}>
                    <PosTag className="teammate-rank" text={m.depth || "—"} />
                    <Headshot sleeperId={m.sleeper_id} name={m.name} size={30} />
                    <span className="teammate-name">{m.name}</span>
                    <span className="teammate-fpg">{m.fpg.toFixed(1)}</span>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <h3>Fantasy points</h3>
      {row && (
        <div className="small" data-testid="fp-this-season">
          This season: <strong>{row.avg_fpts.toFixed(1)} <Term k="fpg">FP/G</Term></strong>{" "}
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
          <div>{val.weeks_played} of {val.season_weeks} fantasy weeks with a game ({val.season_weeks ? Math.round(100 * val.weeks_played / val.season_weeks) : 0}%) · {val.minutes_avg} min · teams {val.teams_played_for.join(", ") || "-"}</div>
          {Object.keys(val.availability_seasons || {}).length > 0 && (
            <div data-testid="avail-seasons"><Term k="avail" />: <strong>{Math.round(val.availability * 100)}%</strong>
              <span className="muted"> = {Object.entries(val.availability_seasons).map(([s, x]) => `${Math.round(x * 100)}% (${s})`).join(" · ")}</span>
            </div>
          )}
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
