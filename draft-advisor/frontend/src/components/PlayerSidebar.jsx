import React, { useCallback, useEffect, useRef, useState } from "react";
import { PosList, PosTag, posClass } from "./Pos.jsx";
import { tierHue } from "./RankingsTable.jsx";
import { api, qs } from "../api.js";
import { CallBadge, Term, TERMS } from "./Terms.jsx";
import Headshot from "./Headshot.jsx";
import InjuryTag from "./InjuryTag.jsx";


// season: the in-season profile (Season tab): no draft parts (Fit, Worth, bid guide, keeper outlook, tier); adds the
// fantasy owner, this week's games, the game log, news, overall + position rank and the depth-chart grid.
export default function PlayerSidebar({ leagueId, playerId, live, refreshKey, onOverridesChanged, userName, onBlock, rankings, onSelectPlayer, season, plan, onClose }) {
  const [data, setData] = useState(null);
  const [rec, setRec] = useState(null);
  const [spend, setSpend] = useState(null);
  const [fit, setFit] = useState(null);
  const [error, setError] = useState("");
  const [notes, setNotes] = useState("");
  const [sea, setSea] = useState(null);

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

  return (
    <div className="panel scroll" data-testid="player-sidebar" style={{ position: "relative" }}>
      {onClose && <button className="sidebar-close" onClick={onClose} title="Close profile" data-testid="sidebar-close">✕</button>}
      <h3>
        <Headshot sleeperId={rec_.sleeper_id} name={rec_.full_name} size={64} />
        {rec_.full_name} <span className="muted">{rec_.team_abbr || "FA"}</span>
        <span className="profile-tags">
          <span>{ov.eligibility.length ? <PosList list={ov.eligibility} /> : "no position"} · age {bio.age ?? "?"}</span>
          {season && sea && sea.player_id === shownId && (
            <span className="profile-ranks">
              {data.team?.role && <span className={`role-tag ${data.team.role.star ? "star" : ""}`} data-testid="team-role">{data.team.role.star ? "★ " : ""}{data.team.role.label}</span>}
              {sea.pos_rank && <span className={`pos-c ${posClass(sea.pos_rank)}`} data-tip={TERMS.pos_rank[1]}>{sea.pos_rank}</span>}
              {sea.overall_rank && <span className="pos-c" data-tip="Overall rank by Sleeper's average draft position.">#{sea.overall_rank} overall</span>}
            </span>
          )}
          {!season && (row?.pos_rank || row?.tier != null || data.team?.role) && (
            <span className="profile-ranks">
              {data.team?.role && (() => {
                const r = data.team.role;
                return <span className={`role-tag ${r.star ? "star" : ""}`} data-testid="team-role"
                  data-tip={`${r.label} on ${data.team.abbr}: ${r.fpg} projected FP/G, #${r.rank} on the team, ${Math.round(r.share * 100)}% of the top 8's production${r.vs ? `; ${r.star ? "next best" : "the #1 is"} ${r.vs.name} at ${r.vs.fpg}` : ""}. Based on Sleeper's projection, which includes usage and minutes.`}>
                  {r.star ? "★ " : ""}{r.label}</span>;
              })()}
              {row?.pos_rank && <span className={`pos-c ${posClass(row.pos_rank)}`} data-tip={TERMS.pos_rank[1]}>{row.pos_rank}</span>}
              {row?.tier != null && <span className={`tier-cell ${row.tier_size >= 3 && row.tier_left <= 2 ? "last" : ""}`} style={tierHue(row.tier)} data-tip={`Tier ${row.tier}: ${row.tier_left} of ${row.tier_size} still available. ${TERMS.tier[1]}`}>T{row.tier}</span>}
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
      {season && sea && sea.player_id === shownId && <SeasonBlock sea={sea} plan={plan} />}

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
        {season && sea && sea.player_id === shownId ? (
          sea.retired ? <strong className="warn-text">retired (always 0)</strong>
            : sea.injury_tag ? <><InjuryTag tag={sea.injury_tag} />{sea.injury_note && <span className="muted"> · {sea.injury_note}</span>}</>
            : <strong>healthy</strong>
        ) : (
          <><strong className={ov.injury_status === "healthy" ? "" : "warn-text"}>{ov.injury_status.replace(/_/g, " ")}</strong>
            {ov.injury_note && <span className="muted"> · {ov.injury_note}</span>}</>
        )}
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
          {season && data.team.depth_grid ? <DepthGrid grid={data.team.depth_grid} onSelectPlayer={onSelectPlayer} /> : (
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
          </div>)}
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

const ctTime = (iso) => (iso ? new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "numeric", minute: "2-digit" }) : "");
const dayName = (d) => new Date(`${d}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });

// Season profile: owner, your call on him this week, his games this week, game log and news.
function SeasonBlock({ sea, plan }) {
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
              {a.when && <span className="muted"> · {new Date(a.when).toLocaleDateString("en-US", { timeZone: "America/Chicago", month: "2-digit", day: "2-digit", year: "2-digit" })}</span>}
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
          <thead><tr><th>Day</th><th>Opp</th><th>Tip (CT)</th><th className="num">Proj</th><th className="num">FP</th><th className="num">Min</th></tr></thead>
          <tbody>{sea.games.map((g) => (
            <tr key={g.date} className={g.date === sea.today ? "you-need" : ""}><td>{dayName(g.date)} {g.date.slice(5)}</td><td>{g.home ? "vs" : "@"} {g.opp}</td>
              <td>{g.state === "in" ? <span className="warn-text">live</span> : g.state === "post" ? "final" : ctTime(g.tip)}</td>
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

// His NBA team's depth chart (Sleeper): PG to C down the side, 1st / 2nd / 3rd option across the top.
function DepthGrid({ grid, onSelectPlayer }) {
  return (
    <table className="depth-grid small" data-testid="depth-grid">
      <thead><tr><th></th><th>1st</th><th>2nd</th><th>3rd</th></tr></thead>
      <tbody>{["PG", "SG", "SF", "PF", "C"].map((pos) => (
        <tr key={pos}><td><PosTag text={pos} /></td>
          {[0, 1, 2].map((i) => {
            const m = grid[pos]?.[i];
            return <td key={i} className={m ? `dg-cell ${m.is_self ? "self" : "clickable"}` : "muted"} onClick={() => m && !m.is_self && onSelectPlayer?.(m.player_id)}
              data-tip={m ? `${m.name} · ${m.fpg} FP/G${m.drafted_by ? ` · ${m.drafted_by}` : ""}` : ""}>
              {m ? <><Headshot sleeperId={m.sleeper_id} name={m.name} size={22} /> <span className="dg-name">{m.name.split(" ")[0][0]}. {m.name.split(" ").slice(1).join(" ")}</span></> : "—"}
            </td>;
          })}
        </tr>))}</tbody>
    </table>
  );
}
