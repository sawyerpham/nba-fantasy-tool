import React, { useEffect, useState } from "react";
import { api, qs } from "../api.js";
import Headshot from "./Headshot.jsx";
import { PosList } from "./Pos.jsx";
import { tierHue } from "./RankingsTable.jsx";
import { VerdictBadge } from "./SpendingGuide.jsx";

// Replaces "On the block" while Sleeper sync is on: the player nominated in Sleeper right now, his numbers, the
// live high bid against your limits (pay up to, stretch, walk-away), and the tips (tier, rivals with history).
export default function LiveLot({ leagueId, lot, row, managers, onOpen }) {
  const [spend, setSpend] = useState(null);
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 250); return () => clearInterval(t); }, []);
  useEffect(() => {
    let off = false;
    setSpend(null);
    api.get(`/leagues/${leagueId}/spending` + qs({ player_id: lot.player_id })).then((g) => !off && setSpend(g.focus)).catch(() => {});
    return () => { off = true; };
  }, [leagueId, lot.player_id]);

  const left = lot.timer_end_at ? Math.max(0, Math.ceil((Date.parse(lot.timer_end_at) - now) / 1000)) : null;
  const bid = lot.high_bid ?? 0;
  const payUpTo = spend && spend.verdict !== "cannot" ? spend.suggested : row?.price;
  const fair = spend?.fair_value != null ? Math.round(spend.fair_value) : null;
  // Where the live bid sits against your limits.
  const band = !payUpTo ? null
    : bid <= payUpTo ? { cls: "good", text: `$${payUpTo - bid} under your pay-up-to: still a buy` }
    : spend && bid <= spend.stretch ? { cls: "even", text: `$${bid - payUpTo} over pay-up-to, within your stretch ($${spend.stretch})` }
    : spend && bid <= spend.walk_away ? { cls: "even", text: `past your stretch ($${spend.stretch}); walk away at $${spend.walk_away}` }
    : { cls: "bad", text: `overbid: past your walk-away${spend ? ` ($${spend.walk_away})` : ""}, let it go` };
  const overFair = fair != null ? bid - fair : null;
  const interest = managers.filter((m) => !m.is_user && m.tendency).map((m) => {
    const before = m.tendency.drafted_before?.[String(lot.player_id)];
    const fan = lot.team_abbr && m.tendency.favorite_teams?.includes(lot.team_abbr);
    return before || fan ? `${m.name} (${[before && "drafted him before", fan && `${lot.team_abbr} fan`].filter(Boolean).join(", ")})` : null;
  }).filter(Boolean);
  const leaderCanGo = managers.find((m) => m.name === lot.leader)?.budget.max_bid;

  return (
    <div className="live-lot" data-testid="live-lot">
      <div className="live-lot-head">
        <Headshot sleeperId={lot.sleeper_id} name={lot.full_name} size={56} />
        <div className="live-lot-who">
          <div className="small muted"><span className="live-dot" /> LIVE IN SLEEPER · nominated by {lot.nominated_by || "?"}</div>
          <div className="live-lot-name" onClick={onOpen} title="open his full profile on the right" data-testid="on-the-block">
            {lot.full_name} <span className="muted">{lot.team_abbr}</span>
          </div>
          <div className="small muted">
            {row && <><PosList list={row.eligibility} /> · age {row.age} · <strong style={{ color: "var(--text)" }}>{row.avg_fpts.toFixed(1)}</strong> FP/G · {Math.round(row.availability * 100)}% wks</>}
            {row?.tier != null && <span className={`tier-tag ${row.tier_size >= 3 && row.tier_left <= 2 ? "last" : ""}`} style={tierHue(row.tier)}>T{row.tier} · {row.tier_left - 1 === 0 ? "last in his tier" : `${row.tier_left - 1} more like him`}</span>}
          </div>
        </div>
        <div className={`live-lot-bid ${band?.cls || ""}`}>
          <div className="bid-label">High bid{lot.leader ? ` · ${lot.leader}` : ""}</div>
          <div className="live-lot-price" data-testid="live-bid">${bid}</div>
          {left != null && <div className={`live-clock ${left <= 3 ? "low" : ""}`}>{left}s</div>}
        </div>
      </div>
      <div className="live-lot-limits">
        <span className="lim"><span className="bid-label">Pay up to</span> <strong>{payUpTo != null ? `$${payUpTo}` : "—"}</strong></span>
        <span className="lim"><span className="bid-label">Fair</span> <strong>{fair != null ? `$${fair}` : "—"}</strong></span>
        {spend && spend.verdict !== "cannot" && <span className="lim"><span className="bid-label">Stretch / walk-away</span> <strong>${spend.stretch} / ${spend.walk_away}</strong></span>}
        {row?.fit && <span className="lim"><span className="bid-label">Fit</span> <strong className={`fit-num ${row.fit.score >= 70 ? "hi" : row.fit.score >= 45 ? "mid" : "lo"}`}>{row.fit.score}</strong></span>}
        {spend && <VerdictBadge verdict={spend.verdict} />}
      </div>
      {band && <div className={`live-lot-call ${band.cls}`} data-testid="live-call">{band.text}{overFair != null && overFair > 0 ? ` · bid is $${overFair} over fair value` : ""}</div>}
      <div className="small muted live-lot-tips">
        {interest.length > 0 && <div>Watch out: {interest.join(" · ")}</div>}
        {leaderCanGo != null && <div>{lot.leader} can go to ${leaderCanGo}.</div>}
        {!row && <div>Not in your rankings (unrosterable for you or outside the top list).</div>}
      </div>
    </div>
  );
}
