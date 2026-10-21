import React, { useEffect, useRef, useState } from "react";
import { api, qs } from "../api.js";
import Headshot from "../core/Headshot.jsx";
import { PosList, PosTag } from "../core/Pos.jsx";
import { tierHue } from "../core/Pos.jsx";
import { CallBadge, Term, TERMS, liveCall } from "../core/Terms.jsx";
import { bidSound, nominationSound } from "../core/sounds.js";

// Replaces "On the block" while Sleeper sync is on: the player nominated in Sleeper right now, his numbers, the
// live high bid against his Worth and Max (and your walk-away) as a one-word call, the bid history down the right
// (each bidder's cap), and below it: what winning him leaves you, the next best players for that spot, his Lock-In numbers, next year's keeper call, team role and injury.
export default function LiveLot({ leagueId, lot, row, rankings, managers, onOpen }) {
  const [spend, setSpend] = useState(null);
  const [extra, setExtra] = useState({});   // team role (player endpoint) and keeper outlook (fit endpoint)
  const [now, setNow] = useState(Date.now());
  const bids = useRef({ id: null, list: [] });   // every new high bid seen for this lot, from the sync polls
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  // A new high bid on the same player: blink the high-bid card and play the bid sound.
  const [flash, setFlash] = useState(0);
  const seen = useRef({ id: lot.player_id, bid: lot.high_bid });
  useEffect(() => { nominationSound(); }, [lot.player_id]);   // a new player on the block (also when the block first appears)
  useEffect(() => {
    const prev = seen.current;
    seen.current = { id: lot.player_id, bid: lot.high_bid };
    if (prev.id !== lot.player_id || lot.high_bid == null || prev.bid === lot.high_bid) return undefined;
    bidSound();
    setFlash((n) => n + 1);
    const t = setTimeout(() => setFlash(0), 900);
    return () => clearTimeout(t);
  }, [lot.player_id, lot.high_bid]);
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
  const interest = managers.filter((m) => !m.is_user && m.tendency).map((m) => {
    const before = m.tendency.drafted_before?.[String(lot.player_id)];
    const fan = lot.team_abbr && m.tendency.favorite_teams?.includes(lot.team_abbr);
    return before || fan ? `${m.name} (${[before && "drafted him before", fan && `${lot.team_abbr} fan`].filter(Boolean).join(", ")})` : null;
  }).filter(Boolean);

  // If you win: the next bid up (you already lead: the current one).
  const me = managers.find((m) => m.is_user);
  const leading = me && lot.leader === me.name;
  // where the live bid sits against your numbers; holding the high bid trumps the rest
  const band = leading ? { cls: "lead", word: "LEADING", text: "you hold the high bid" } : spend ? liveCall(bid, spend) : null;
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
    <div className="live-lot-wrap">
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
            {extra.role && <span className={`role-tag ${extra.role.star ? "star" : ""}`} style={{ marginLeft: 8 }} data-tip={`#${extra.role.rank} on his team by projected FP/G, ${Math.round(extra.role.share * 100)}% of the top 8's production.`}>{extra.role.star ? "★ " : ""}{extra.role.label}</span>}
          </div>
          {inj && <div className="small warn-text" data-testid="live-injury">{inj}</div>}
        </div>
        {band && (
          <div className={`live-big call ${band.cls}`} data-testid="live-call" data-tip={TERMS.live_call[1]}>
            <div className="bid-label">Call</div>
            <div className="live-big-word">{band.word}</div>
            <div className="live-big-sub">{band.text}</div>
          </div>
        )}
        <div className="live-big" data-tip={TERMS.worth[1]}>
          <div className="bid-label">Worth</div>
          <div className="live-lot-price" data-testid="live-worth">{spend ? `$${Math.round(spend.fair_value)}` : "—"}</div>
          <div className="live-big-sub">Max {can ? `$${spend.recommended}` : "—"}</div>
        </div>
        <div key={flash} className={`live-lot-bid ${flash ? "flash" : ""}`} data-testid="live-bid-card" data-tip="Live from Sleeper.">
          <div className="bid-label"><span className="rec-dot" />High bid</div>
          <div className="live-lot-price" data-testid="live-bid">${bid}</div>
          <div className="live-bid-foot"><span className="clip">{lot.leader || "no bids"}</span>{left != null && <span className={`live-clock ${left <= 3 ? "low" : ""}`}>{left}s</span>}</div>
        </div>
      </div>
      <div className="live-lot-limits">
        {can && <span className="lim"><span className="bid-label"><Term k="comfort" /> / <Term k="walk" /></span> <strong>${spend.stretch} / ${spend.walk_away}</strong></span>}
        {row?.fit && <span className="lim"><span className="bid-label"><Term k="fit" /></span> <strong className={`fit-num ${row.fit.score >= 70 ? "hi" : row.fit.score >= 45 ? "mid" : "lo"}`}>{row.fit.score}</strong></span>}
        {spend && <CallBadge call={spend.verdict} />}
      </div>

      <div className="live-lot-more">
        <div className="live-card win" data-testid="live-win">
          <div className="live-card-title">If you win at ${price}</div>
          {!me ? "—" : price > me.budget.max_bid ? <div className="warn-text">Over your <Term k="cap">cap</Term> ${me.budget.max_bid}: you can't bid that.</div> : <>
            <div><strong>${afterMoney}</strong> left for {afterOpen} spot{afterOpen !== 1 ? "s" : ""}{afterOpen > 0 && <span className="muted"> · ${Math.round(afterMoney / afterOpen)}/slot</span>}</div>
            <div className="muted">{slot ? <>fills <PosTag text={slot} /></> : "no open spot"}{stillNeed.length > 0 && <> · still need {stillNeed.map(([s, n]) => `${s}${n > 1 ? `×${n}` : ""}`).join(" ")}</>}</div>
          </>}
        </div>
        <div className="live-card pass" data-testid="live-pass">
          <div className="live-card-title">Next best players</div>
          {next.length ? next.map((r) => <div key={r.player_id} className="clip">{r.full_name} <span className="muted">{r.eligibility.join("/")}</span> <strong>{r.worth != null ? `$${r.worth}` : ""}</strong>{r.fit && <> · <Term k="fit">Fit</Term> <strong className={`fit-num ${r.fit.score >= 70 ? "hi" : r.fit.score >= 45 ? "mid" : "lo"}`}>{r.fit.score}</strong></>}</div>)
            : <div className="muted">Nobody else left for that spot.</div>}
        </div>
        <div className="live-card lockin" data-testid="live-lockin">
          <div className="live-card-title">Lock-In</div>
          {row ? <div><strong>{row.avg_fpts.toFixed(1)}</strong> <Term k="fpg">proj FP/G</Term> · <strong>{bestGame.toFixed(1)}</strong> <span data-tip={row.weekly_best_avg ? "His average best game of the week last season: what Lock-In lets you keep." : "No games last season: estimated from his projection with the league-wide best-game ratio."}>avg best game{row.weekly_best_avg ? "" : " (est.)"}</span></div> : <div className="muted">—</div>}
        </div>
        <div className="live-card keeper" data-testid="live-keeper">
          <div className="live-card-title"><Term k="keeper_outlook" /></div>
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
    <div className="bid-history" data-testid="live-bids">
      <div className="live-card-title">Bid history</div>
      {bids.current.list.length ? bids.current.list.slice().reverse().slice(0, 12).map((b, i) => {
        const mine = me && b.who === me.name;
        const cap = mine ? null : managers.find((m) => m.name === b.who)?.budget.max_bid;
        return (
          <div key={`${b.who}-${b.bid}`} className={`bid-row ${i === 0 ? "top" : ""} ${mine ? "mine" : ""}`}>
            <strong className="bid-row-price">${b.bid}</strong>
            <span className="clip">{mine ? "You" : b.who}</span>
            {cap != null && <span className="muted bid-row-cap" data-tip={TERMS.cap[1]}>cap ${cap}</span>}
          </div>
        );
      }) : <div className="muted small">No bids yet.</div>}
    </div>
    </div>
  );
}
