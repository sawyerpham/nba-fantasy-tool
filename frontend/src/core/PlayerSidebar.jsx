import React, { useCallback, useEffect, useRef, useState } from "react";
import { PosList, PosTag, posClass, tierHue } from "./Pos.jsx";
import { api, qs } from "../api.js";
import { CallBadge, Term, TERMS } from "./Terms.jsx";
import Headshot from "./Headshot.jsx";
import { ordinal } from "../draft/SpendingGuide.jsx";
import { SeasonHistory, SeasonLog, SeasonSummary } from "../lockin/SeasonProfile.jsx";

// season: the in-season profile (Season tab), like Sleeper's: four tabs under his name. Summary (his live / last game,
// season averages, ranks, ownership, owner, status, news), Game log (every game this season), Team (his team card and
// depth chart) and History (draft, keeper, moves). No draft parts (Fit, Worth, bid guide, keeper outlook, tier).
const TABS = [["summary", "Summary"], ["log", "Game log"], ["team", "Team"], ["history", "History"]];
export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, userName, onBlock, rankings, onSelectPlayer, season, plan, onClose, onOpenGame }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [spend, setSpend] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");
  const [sea, setSea] = useState(null);
  const [tab, setTab] = useState("summary");   // season profile tab; stays put from player to player

  // All four requests are fetched together and applied in one update, so the card never rebuilds piece by piece;
  // the previous player stays on screen until the new one is ready, and late answers for an older click are dropped.
  const latest = useRef(0);
  const load = useCallback(() => {
    if (!playerId) return;
    const ticket = ++latest.current;
    const opt = (p) => p.catch(() => null);   // drafted players have no fit / bid guide
    Promise.all([
      api.get(`/players/${playerId}` + qs({ league_id: leagueId })),
      season ? null : opt(api.get(`/leagues/${leagueId}/fit/${playerId}`)),
      live && !season ? opt(api.get(`/leagues/${leagueId}/recommend/${playerId}`)) : null,
      live && !season ? opt(api.get(`/leagues/${leagueId}/spending` + qs({ player_id: playerId })).then((g) => g.focus)) : null,
      season ? opt(api.get(`/leagues/${leagueId}/season/player/${playerId}`)) : null,
    ]).then(([d, f, r, sp, se]) => {
      if (ticket !== latest.current) return;
      setData(d); setNotes(d.overrides?.notes || ""); setFit(f); setRec(r); setSpend(sp); setSea(se); setError("");
    }).catch((e) => { if (ticket === latest.current) setError(e.message); });
  }, [leagueId, playerId, live, season]);

  useEffect(() => { load(); }, [load, refreshKey]);

  if (!playerId) return season ? null : <div className="panel muted">Select a player to see his profile, his Fit for your team, his Worth and his Max.</div>;
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

  const head = (
    <>
      {onClose && <button className="sidebar-close" onClick={onClose} title="Close profile" data-testid="sidebar-close">✕</button>}
      <h3>
        <Headshot sleeperId={rec_.sleeper_id} name={rec_.full_name} size={64} />
        {rec_.full_name} <span className="muted">{rec_.fantasy?.number != null && `#${rec_.fantasy.number} `}{rec_.team_abbr || "FA"}</span>
        <span className="profile-tags">
          <span>{ov.eligibility.length ? <PosList list={ov.eligibility} /> : "no position"} · age {bio.age ?? "?"}</span>
          {season && data.team?.role && (
            <span className="profile-ranks"><span className={`role-tag ${data.team.role.star ? "star" : ""}`} data-testid="team-role">{data.team.role.star ? "★ " : ""}{data.team.role.label}</span></span>
          )}
          {!season && (row?.pos_rank || row?.tier != null || data.team?.role) && (
            <span className="profile-ranks">
              {data.team?.role && (() => {
                const r = data.team.role;
                return <span className={`role-tag ${r.star ? "star" : ""}`} data-testid="team-role"
                  data-tip={`#${r.rank} on ${data.team.abbr} at ${r.fpg} projected FP/G, ${Math.round(r.share * 100)}% of the top 8's production${r.vs ? `; ${r.star ? "next best" : "the #1 is"} ${r.vs.name} at ${r.vs.fpg}` : ""}. From Sleeper's projection (usage and minutes).`}>
                  {r.star ? "★ " : ""}{r.label}</span>;
              })()}
              {row?.pos_rank && <span className={`pos-c ${posClass(row.pos_rank)}`} data-tip={TERMS.pos_rank[1]}>{row.pos_rank}</span>}
              {row?.tier != null && <span className={`tier-cell ${row.tier_size >= 3 && row.tier_left <= 2 ? "last" : ""}`} style={tierHue(row.tier)} data-tip={`${row.tier_left} of ${row.tier_size} still available. ${TERMS.tier[1]}`}>T{row.tier}</span>}
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
    </>
  );

  // his NBA team: logo, his rank on the team, the team's fantasy-talent rank; the depth chart (season) or teammates
  const teamCard = data.team && (
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
      {season && sea?.team_ranks && <TeamRanks r={sea.team_ranks} />}
      {season && data.team.depth_grid ? <DepthGrid grid={data.team.depth_grid} onSelectPlayer={onSelectPlayer} /> : (
      <div className="teammates">
        {[["Starters", data.team.teammates.filter((m) => m.starter)], ["Next up", data.team.teammates.filter((m) => !m.starter)]].map(([label, list]) => (
          <div key={label} className="teammate-col">
            <div className="bid-label">{label}</div>
            {list.map((m) => (
              <div key={m.player_id} className={`teammate ${m.is_self ? "self" : ""} ${m.drafted_by ? "taken" : ""}`}
                onClick={() => !m.is_self && onSelectPlayer?.(m.player_id)}
                title={[m.pos.join("/"), m.min && `${m.min} min`, m.drafted_by && `drafted by ${m.drafted_by}`].filter(Boolean).join(" · ")}>
                <PosTag className="teammate-rank" text={m.depth || "—"} />
                <Headshot sleeperId={m.sleeper_id} name={m.name} size={30} />
                <span className="teammate-name">{m.name}</span>
                <span className="teammate-fpg">{m.fpg.toFixed(1)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>)}
    </div>
  );

  if (season) {
    const ready = sea && sea.player_id === shownId;
    return (
      <div className="panel scroll" data-testid="player-sidebar" style={{ position: "relative" }}>
        {head}
        <nav className="profile-tabs" data-testid="profile-tabs">
          {TABS.map(([id, label]) => <button key={id} className={tab === id ? "active" : ""} onClick={() => setTab(id)} data-testid={`profile-${id}`}>{label}</button>)}
        </nav>
        {!ready ? <div className="small muted">Loading…</div>
          : tab === "summary" ? <>
            <SeasonSummary sea={sea} onOpenGame={onOpenGame} />
            <textarea rows="1" style={{ width: "100%", marginTop: 10 }} placeholder="your notes" value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => notes !== (ov.notes || "") && patch({ notes })} />
          </>
          : tab === "log" ? <SeasonLog sea={sea} />
          : tab === "team" ? (teamCard || <div className="small muted">No NBA team.</div>)
          : <SeasonHistory sea={sea} />}
      </div>
    );
  }

  return (
    <div className="panel scroll" data-testid="player-sidebar" style={{ position: "relative" }}>
      {head}

      {!season && fit && fit.player_id === shownId && (
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

      {!season && fit?.keeper && fit.player_id === shownId && (() => {
        const k = fit.keeper, cls = { good: "good", even: "even", bad: "bad" }[k.verdict];
        return (
          <div className="small keeper-line" data-testid="keeper-outlook">
            <span className="bid-label"><Term k="keeper_outlook" /></span>{" "}
            <span className={`verdict ${cls}`} data-tip={TERMS.keep_call[1]}>{k.verdict.toUpperCase()} keep</span>
            {k.stash && <> <Term k="stash" className="verdict even" /></>}
            <span className="muted"> at his Max ${k.buy_price} → keep at <strong style={{ color: "var(--text)" }}>${k.next_price}</strong> · worth ~${k.next_worth} ({k.surplus >= 0 ? "+" : "−"}${Math.abs(k.surplus)})</span>
            {k.good_up_to != null && <div className="muted">GOOD keep if you get him for <strong style={{ color: "var(--text)" }}>≤ ${k.good_up_to}</strong></div>}
            {k.young && <span className="muted" data-tip="23 or younger: young players usually improve, which this estimate doesn't model."> · young, may improve</span>}
          </div>
        );
      })()}

      {!season && !live && row?.worth != null && (
        <div className="small" data-testid="pre-worth">
          <span className="bid-label"><Term k="worth" /></span> <strong style={{ fontSize: "1.3em" }}>${row.worth}</strong>
          <span className="muted"> at the first nomination, after keepers. Max and your call show once the draft is live.</span>
        </div>
      )}

      {!season && rec && (
        <div data-testid="recommendation">
          <h3>Bid guide <span className="badge info">for {userName || "you"}</span>{onBlock && <span className="badge">on the block</span>}</h3>
          <div className="bid-grid">
            <div className="bid-cell primary">
              <div className="bid-label"><Term k="worth" /></div>
              <div className="bid-num" data-testid="rec-worth">${Math.round(rec.fair_value)}</div>
            </div>
            <div className="bid-cell">
              <div className="bid-label"><Term k="max" /></div>
              <div className="bid-num" data-testid="rec-max">{rec.can_bid ? `$${rec.recommended_max}` : "—"}</div>
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

      {teamCard}

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

// His NBA team's ranks among the league's teams, per game (backend team_ranks): Offense and Defense side by side, each
// headed by its overall rank (points scored / allowed), then each stat's rank (defense: what it allows). 1 = best;
// the top third green, the bottom third red.
const RANK_STATS = [["reb", "Rebounds"], ["ast", "Assists"], ["blk", "Blocks"], ["stl", "Steals"],
  ["tpm", "3-pointers"], ["fga", "FG attempts"], ["to", "Turnovers"]];
function TeamRanks({ r }) {
  const tone = (rank) => rank <= r.teams / 3 ? "good" : rank > (r.teams * 2) / 3 ? "bad" : "";
  const rank = (x) => <strong className={`rank ${tone(x.rank)}`}>{ordinal(x.rank)}</strong>;
  return (
    <div className="team-ranks" data-testid="team-ranks">
      {[["offense", "Offense"], ["defense", "Defense"]].map(([side, title]) => (
        <div key={side} className="team-ranks-side">
          <div className="team-ranks-head"><span>{title}</span>{rank(r[side].pts)}</div>
          {RANK_STATS.map(([k, label]) => (
            <div key={k} className="team-ranks-row small">
              <span>{side === "offense" ? label : k === "to" ? "Turnovers forced" : `${label} allowed`}</span>{rank(r[side][k])}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// His NBA team's depth chart (Sleeper): PG to C down the side, 1st / 2nd / 3rd option across the top. Also the season game card's.
export function DepthGrid({ grid, onSelectPlayer }) {
  return (
    <table className="depth-grid small" data-testid="depth-grid">
      <thead><tr><th></th><th>1st</th><th>2nd</th><th>3rd</th></tr></thead>
      <tbody>{["PG", "SG", "SF", "PF", "C"].map((pos) => (
        <tr key={pos}><td><PosTag text={pos} /></td>
          {[0, 1, 2].map((i) => {
            const m = grid[pos]?.[i];
            return <td key={i} className={m ? `dg-cell ${m.is_self ? "self" : "clickable"}` : "muted"} onClick={() => m && !m.is_self && onSelectPlayer?.(m.player_id)}
              data-tip={m ? `${m.fpg} FP/G${m.drafted_by ? ` · drafted by ${m.drafted_by}` : ""}` : ""}>
              {m ? <><Headshot sleeperId={m.sleeper_id} name={m.name} size={22} /> <span className="dg-name">{m.name.split(" ")[0][0]}. {m.name.split(" ").slice(1).join(" ")}</span></> : "—"}
            </td>;
          })}
        </tr>))}</tbody>
    </table>
  );
}
