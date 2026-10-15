import React, { useEffect, useRef, useState } from "react";
import { api, qs } from "../api.js";
import Headshot from "./Headshot.jsx";
import { PosList, PosTag } from "./Pos.jsx";
import { tierHue } from "./RankingsTable.jsx";
import { CallBadge, Term, TERMS, liveCall } from "./Terms.jsx";

// Replaces "On the block" while Sleeper sync is on: the player nominated in Sleeper right now, his numbers, the
// live high bid against his Worth and Max (and your walk-away), and below it: who has bid so far, what winning
// him leaves you, who's next if you pass, his Lock-In numbers, next year's keeper call, team role and injury.
export default function LiveLot({ leagueId, lot, row, rankings, managers, onOpen }) {
  const [spend, setSpend] = useState(null);
  const [extra, setExtra] = useState({});   // team role (player endpoint) and keeper outlook (fit endpoint)
  const [now, setNow] = useState(Date.now());
  const bids = useRef({ id: null, list: [] });   // every new high bid seen for this lot, from the sync polls
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  useEffect(() => {
    let off = false;
    setSpend(null); setExtra({});
    api.get(`/leagues/${leagueId}/spending` + qs({ player_id: lot.player_id })).then((g) => !off && setSpend(g.focus)).catch(() => {});
    Promise.all([
      api.get(`/players/${lot.player_id}` + qs({ league_id: leagueId })).catch(() => null),
      api.get(`/leagues/${leagueId}/fit/${lot.player_id}`).catch(() => null),
    ]).then(([d, f]) => !off && setExtra({ role: d?.team?.role, keeper: f?.keeper }));
    return () => { off = true; };
  }, [leagueId, lot.player_id]);

  if (bids.current.id !== lot.player_id) bids.current = { id: lot.player_id, list: [] };
  const last = bids.current.list[bids.current.list.length - 1];
  if (lot.leader && lot.high_bid != null && (!last || last.bid !== lot.high_bid || last.who !== lot.leader)) {
    bids.current.list.push({ who: lot.leader, bid: lot.high_bid });
  }

  const left = lot.timer_end_at ? Math.max(0, Math.ceil((Date.parse(lot.timer_end_at) - now) / 1000)) : null;
  const bid = lot.high_bid ?? 0;
  const can = spend && spend.verdict !== "cannot";
  const band = spend ? liveCall(bid, spend) : null;   // where the live bid sits against your numbers
  const interest = managers.filter((m) => !m.is_user && m.tendency).map((m) => {
    const before = m.tendency.drafted_before?.[String(lot.player_id)];
    const fan = lot.team_abbr && m.tendency.favorite_teams?.includes(lot.team_abbr);
    return before || fan ? `${m.name} (${[before && "drafted him before", fan && `${lot.team_abbr} fan`].filter(Boolean).join(", ")})` : null;
  }).filter(Boolean);
  const leaderCanGo = managers.find((m) => m.name === lot.leader)?.budget.max_bid;

  // If you win: the next bid up (you already lead: the current one).
  const me = managers.find((m) => m.is_user);
  const leading = me && lot.leader === me.name;
  const price = leading ? bid : Math.max(bid + 1, 1);
  const slot = row?.assignable_slot;
  const afterMoney = me ? me.budget.remaining - price : null;
  const afterOpen = me ? me.budget.open_mandatory - 1 : 0;
  const stillNeed = me ? Object.entries(me.open_slots).filter(([s, n]) => !["BN", "IR"].includes(s) && n - (s === slot ? 1 : 0) > 0)
    .map(([s, n]) => [s, n - (s === slot ? 1 : 0)]) : [];

  // If you pass: the best players left who fit the same spot for you.
  const elig = new Set(slot && slot !== "BN" ? [slot] : row?.eligibility || []);
  const next = (rankings || []).filter((r) => r.player_id !== lot.player_id && r.rosterable && r.eligibility.some((p) => elig.has(p))).slice(0, 2);

  const inj = row && row.injury_status !== "healthy" ? `${row.injury_status.replace(/_/g, " ")}${row.injury_note ? `: ${row.injury_note}` : ""}` : null;
  const bestGame = row ? (row.weekly_best_avg || row.ceiling) : null;
  const k = extra.keeper;

  return (
    <div className="live-lot" data-testid="live-lot">
      <div className="live-lot-head">
        <Headshot sleeperId={lot.sleeper_id} name={lot.full_name} size={56} />
        <div className="live-lot-who">
          <div className="small muted"><span className="live-dot" /> LIVE IN SLEEPER · nominated by {lot.nominated_by || "?"}</div>
          <div className="live-lot-name" onClick={onOpen} data-tip="Open his full profile on the right." data-testid="on-the-block">
            {lot.full_name} <span className="muted">{lot.team_abbr}</span>
          </div>
          <div className="small muted">
            {row && <><PosList list={row.eligibility} /> · age {row.age} · {Math.round(row.availability * 100)}% <Term k="avail">avail</Term></>}
            {row?.tier != null && <span className={`tier-tag ${row.tier_size >= 3 && row.tier_left <= 2 ? "last" : ""}`} style={tierHue(row.tier)} data-tip={TERMS.tier[1]}>T{row.tier} · {row.tier_left - 1 === 0 ? "last in his tier" : `${row.tier_left - 1} more like him`}</span>}
            {extra.role && <span className={`role-tag ${extra.role.star ? "star" : ""}`} style={{ marginLeft: 8 }} data-tip={`${extra.role.label}: #${extra.role.rank} on his team by projected FP/G, ${Math.round(extra.role.share * 100)}% of the top 8's production.`}>{extra.role.star ? "★ " : ""}{extra.role.label}</span>}
          </div>
          {inj && <div className="small warn-text" data-testid="live-injury">{inj}</div>}
        </div>
        <div className={`live-lot-bid ${band?.cls || ""}`} data-tip="Sleeper's current high bid and who holds it; the clock ticks down to the sale.">
          <div className="bid-label">High bid{lot.leader ? ` · ${lot.leader}` : ""}</div>
          <div className="live-lot-price" data-testid="live-bid">${bid}</div>
          {left != null && <div className={`live-clock ${left <= 3 ? "low" : ""}`}>{left}s</div>}
        </div>
      </div>
      <div className="live-lot-limits">
        <span className="lim"><span className="bid-label"><Term k="worth" /></span> <strong>{spend ? `$${Math.round(spend.fair_value)}` : "—"}</strong></span>
        <span className="lim"><span className="bid-label"><Term k="max" /></span> <strong>{can ? `$${spend.recommended}` : "—"}</strong></span>
        {can && <span className="lim"><span className="bid-label"><Term k="comfort" /> / <Term k="walk" /></span> <strong>${spend.stretch} / ${spend.walk_away}</strong></span>}
        {row?.fit && <span className="lim"><span className="bid-label"><Term k="fit" /></span> <strong className={`fit-num ${row.fit.score >= 70 ? "hi" : row.fit.score >= 45 ? "mid" : "lo"}`}>{row.fit.score}</strong></span>}
        {spend && <CallBadge call={spend.verdict} />}
      </div>
      {band && <div className={`live-lot-call ${band.cls}`} data-testid="live-call">{band.text}</div>}

      <div className="live-lot-more">
        <div className="live-card" data-testid="live-win">
          <div className="bid-label">If you win at ${price}</div>
          {!me ? "—" : price > me.budget.max_bid ? <div className="warn-text">Over your <Term k="cap">cap</Term> ${me.budget.max_bid}: you can't bid that.</div> : <>
            <div><strong>${afterMoney}</strong> left for {afterOpen} spot{afterOpen !== 1 ? "s" : ""}{afterOpen > 0 && <span className="muted"> · ${Math.round(afterMoney / afterOpen)}/slot</span>}</div>
            <div className="muted">{slot ? <>fills <PosTag text={slot} /></> : "no open spot"}{stillNeed.length > 0 && <> · still need {stillNeed.map(([s, n]) => `${s}${n > 1 ? `×${n}` : ""}`).join(" ")}</>}</div>
          </>}
        </div>
        <div className="live-card" data-testid="live-pass">
          <div className="bid-label">If you pass</div>
          {next.length ? next.map((r) => <div key={r.player_id} className="clip">{r.full_name} <span className="muted">{r.eligibility.join("/")}</span> <strong>{r.worth != null ? `$${r.worth}` : ""}</strong>{r.fit && <span className="muted"> · Fit {r.fit.score}</span>}</div>)
            : <div className="muted">Nobody else left for that spot.</div>}
        </div>
        <div className="live-card" data-testid="live-bids">
          <div className="bid-label">Bids so far</div>
          {bids.current.list.length ? <div className="clip">{bids.current.list.slice(-6).map((b) => `${b.who} $${b.bid}`).join(" → ")}</div>
            : <div className="muted">No bids yet.</div>}
          {leaderCanGo != null && <div className="muted">{lot.leader}'s <Term k="cap">cap</Term> is ${leaderCanGo}.</div>}
        </div>
        <div className="live-card" data-testid="live-lockin">
          <div className="bid-label">Lock-In</div>
          {row ? <div><strong>{row.avg_fpts.toFixed(1)}</strong> <Term k="fpg">proj FP/G</Term> · <strong>{bestGame.toFixed(1)}</strong> <span data-tip={row.weekly_best_avg ? "His average best game of the week last season: what Lock-In lets you keep." : "No games last season: estimated from his projection with the league-wide best-game ratio."}>avg best game{row.weekly_best_avg ? "" : " (est.)"}</span></div> : <div className="muted">—</div>}
        </div>
        <div className="live-card" data-testid="live-keeper">
          <div className="bid-label"><Term k="keeper_outlook" /></div>
          {k ? <div><span className="muted">at his Max ${k.buy_price}: </span><span className={`verdict ${k.verdict}`}>{k.verdict.toUpperCase()} keep</span>{k.stash && <> <Term k="stash" className="verdict even" /></>}{k.good_up_to != null ? <span className="muted"> · GOOD keep if ≤ <strong style={{ color: "var(--text)" }}>${k.good_up_to}</strong></span> : <span className="muted"> · not a good keep at any price</span>}</div>
            : <div className="muted">—</div>}
        </div>
      </div>

      {(interest.length > 0 || !row) && (
        <div className="small muted live-lot-tips">
          {interest.length > 0 && <div>Watch out: {interest.join(" · ")}</div>}
          {!row && <div>Not in your rankings (unrosterable for you or outside the top list).</div>}
        </div>
      )}
    </div>
  );
}
