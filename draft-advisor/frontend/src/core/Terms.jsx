import React, { useEffect, useState } from "react";

// The site's vocabulary: one word, one meaning, everywhere. Wrap a term in <Term k="..."> (dotted underline)
// and hovering it shows the definition. Any element with data-tip gets the same tooltip.
export const TERMS = {
  worth: ["Worth", "What he's actually worth in this room: $1 + his value above a replacement player × the room's dollars per point of value. The same for every manager. It moves during the draft as money and talent leave the room. Bid up to this with no doubts."],
  r_value: ["R value", "Your formula, from Sleeper's projected FP/G only: player #180 on the board (keepers excluded) is replacement level; value above replacement = FP/G - his FP/G; the $1903 in the room is split by each player's share of the top 180's value above replacement. At or below replacement: $1. Fixed for the whole draft."],
  max: ["Max", "Worth plus up to 15% when rivals can afford him and have a spot for him: where the bidding will likely end. Past his Max, someone is overpaying; don't let it be you."],
  comfort: ["Comfort limit", "Pay up to this and you still have at least 80% of the room's average $ per open starting spot for the rest of your team."],
  walk: ["Walk-away", "Never pay more. Past this you'd have under half the room's average $ per open starting spot for the rest of your team."],
  cap: ["Cap", "The most a manager is allowed to bid: money left minus $1 for each of their other open roster spots."],
  call: ["Call", "Whether his Max fits your budget: BUY, STAR ONLY, TOO PRICEY or CAN'T. It compares his Max with your comfort limit and walk-away."],
  buy: ["BUY", "His Max is within your comfort limit: you can afford to win him even if the bidding goes all the way."],
  star: ["STAR ONLY", "His Max is between your comfort limit and your walk-away: go that high only if he's the star you build around."],
  pricey: ["TOO PRICEY", "His Max is past your walk-away: bid up to your walk-away at most and let someone else overpay."],
  cannot: ["CAN'T", "You can't bid on him: no open roster spot he fits, or not enough money (cap)."],
  fit: ["Fit", "0-100, how much he helps your team: his value as a % of the best value left × role (starter 1, bench only 0.6, no spot 0) × call (BUY 1, STAR ONLY 0.85, TOO PRICEY 0.4, CAN'T 0). 70+ strong, 45-69 decent, under 45 weak."],
  value: ["Value", "The tool's ranking score in fantasy points: projected FP/G blended with his expected best game of the week (Lock-In), adjusted for games played, availability, injury, age and schedule, plus position scarcity."],
  fpg: ["Proj FP/G", "Projected fantasy points per game this season (Sleeper). Arrows: change vs last season, one arrow per 0.5 / 1.5 / 3 FP/G."],
  avail: ["Avail", "Availability: share of fantasy weeks he played at least one game, over the last 3 seasons weighted 50/30/20 (seasons before his NBA career skipped). One lost season (under 50%) from a player whose other seasons average 80%+ is a one-off: forgiven fully under age 30, half at 32, a quarter from 34. Two lost seasons is a pattern and is never forgiven. Under 75% is flagged."],
  tier: ["Tier", "Players of similar value; T1 is best. 'N more like him' counts how many in his tier are still available. When he's the last one, the next player is a step down."],
  pos_rank: ["Pos rank", "Sleeper's positional rank by average draft position, e.g. #2 SG. It shows what other managers think, not value."],
  rank: ["Rank", "Tier and overall rank by value for your team; players you can't roster sink to the bottom."],
  rost: ["Rost%", "Share of Sleeper leagues where he's on a roster."],
  min: ["Min", "Projected minutes per game (Sleeper). Grey = last season's, no projection."],
  left: ["$ left", "Budget not yet spent."],
  per_slot: ["$/slot", "Money left ÷ open roster spots (bench included)."],
  open: ["Open", "Roster spots still to fill, bench included."],
  room: ["Room", "The average $ per open roster spot across every manager."],
  even_split: ["Even split", "Your money spread evenly over your open starting spots, with bench spots at $1."],
  ideal: ["Ideal team", "For each open starting spot: the best player left who fits it, and the best one within your even split. Nobody appears twice."],
  best_fits: ["Best fits", "The available players with the highest Fit for your team right now."],
  drain: ["DRAIN", "Nominate him to drain rivals' money: several can pay a lot for him and you won't (no spot, over your cap, or TOO PRICEY)."],
  sneak: ["SNEAK", "Nominate him to buy cheap: a BUY for you that few rivals can afford right now."],
  win_score: ["Win score", "Projected weekly Lock-In score of the finished lineup: each starter's expected best game of the week × availability, empty starting spots filled with what the team's money buys. Higher = more likely to win the league."],
  est_fpg: ["Est FP/G", "Projected FP/G of the players in starting spots now."],
  open_starters: ["Open starters", "Starting spots still empty."],
  need: ["Need", "Open starting spots for this position across the whole room."],
  supply: ["Left", "Starter-quality players left who can play it: available players among the top N by value, N = open starting spots in the room. Each player counts once, where he'll be used: a PF/C counts at whichever of PF or C has more unfilled spots."],
  pos_status: ["Market", "Scarce: fewer starter-quality players left than open spots, so prices will rise: buy early. Tight: under 1.3 per spot. Plenty: more than enough, wait for value."],
  tier_cliff: ["Top tier", "The best tier left at this position, how many players are left in it, and how much lower in value (fantasy points) the next tier's best player is. Last one in a tier = buy now or drop a level."],
  chasing: ["Chasing", "Rivals with an open spot here who can afford the best player left here. More chasers = bidding wars."],
  room_trend: ["Room trend", "How the room is spending: the last sales, + means the buyer paid more than his Worth at that point, − less."],
  keeper_outlook: ["Keeper next year", "If you buy him now at his Max, next year's keeper price (league rule: +$1 per full $5) vs what he'd be worth next year if healthy (this year's projection, current injury removed, a year older, at draft-start prices). GOOD keep / EVEN / BAD keep use the same thresholds as the keeper menu. Never part of Fit: winning this season comes first."],
  stash: ["STASH", "Out now, so he helps little this season, but at this price he'd be a GOOD keep next year. Only worth it with money and a roster spot to spare."],
  overpaid: ["Overpaid / bargain", "What he sold for vs his Worth at that point. Within $2 counts as about right."],
  live_call: ["Live call", "Where the high bid sits for you. BID: under his Worth, raise. STRETCH: past his Worth but under his Max and your walk-away, only if you need him. STOP: at or past his Max or your walk-away. CAN'T: you can't bid on him. LEADING: you hold the high bid."],
  keep_call: ["Keep call", "GOOD keep: this year's keeper price is under his worth at draft start by at least $2 and 10%. BAD keep: over it by that much. EVEN: in between."],
};

export function Term({ k, children, className = "" }) {
  const [label, tip] = TERMS[k];
  return <span className={`term ${className}`} data-tip={tip}>{children ?? label}</span>;
}

const CALLS = { buy: "good", star: "even", pricey: "bad", cannot: "bad" };

export function CallBadge({ call }) {
  if (!call) return null;
  return <span className={`verdict ${CALLS[call] || ""}`} data-tip={TERMS[call]?.[1]} data-testid="spend-verdict-badge">{TERMS[call]?.[0] || call}</span>;
}

// Where Sleeper's live high bid sits against your numbers for this player (c = the spending guide's call):
// one word (BID / STRETCH / STOP / CAN'T) and a short why.
export function liveCall(bid, c) {
  if (!c || c.verdict === "cannot") return { cls: "bad", word: "CAN'T", text: "no open spot he fits, or over your cap" };
  const worth = Math.round(c.fair_value), max = c.recommended, stop = Math.min(max, c.walk_away);
  if (bid < Math.min(worth, stop)) return { cls: "good", word: "BID", text: `$${bid} is under his Worth $${worth}` };
  if (bid < stop) return { cls: "even", word: "STRETCH", text: `past his Worth $${worth}: only if you need him · stop at $${stop}` };
  return { cls: "bad", word: "STOP", text: bid >= c.walk_away ? `at or past your walk-away $${c.walk_away}` : `at or past his Max $${max}` };
}

// A sale's price against his Worth when he sold (within $2 = about right, as everywhere on the site):
// STEAL $3+ under (blue), FAIR (green), OVER $3-9 over (red), WAY OVER $10+ over (dark red). Keepers aren't sales.
export function priceTone(price, worth, isKeeper) {
  if (isKeeper || worth == null) return { cls: "", tip: isKeeper ? "keeper price" : "" };
  const d = price - worth, tip = `Worth $${worth} when he sold: ${d > 0 ? `$${d} over` : d < 0 ? `$${-d} under` : "right on it"}.`;
  if (d <= -3) return { cls: "tone-steal", tip: `Steal. ${tip}` };
  if (d <= 2) return { cls: "tone-fair", tip: `Fair price. ${tip}` };
  if (d <= 9) return { cls: "tone-over", tip: `Overpaid. ${tip}` };
  return { cls: "tone-way", tip: `Way overpaid. ${tip}` };
}

// One tooltip for every [data-tip] on the page: instant, never clipped by a scrolling panel.
export function TipLayer() {
  const [tip, setTip] = useState(null);
  useEffect(() => {
    const over = (e) => {
      const el = e.target.closest?.("[data-tip]");
      if (!el || !el.dataset.tip) return setTip(null);
      const r = el.getBoundingClientRect();
      setTip({ text: el.dataset.tip, x: r.left + r.width / 2, below: r.bottom + 8, above: r.top - 8 });
    };
    const hide = () => setTip(null);
    document.addEventListener("mouseover", over);
    document.addEventListener("scroll", hide, true);
    return () => { document.removeEventListener("mouseover", over); document.removeEventListener("scroll", hide, true); };
  }, []);
  if (!tip) return null;
  const up = tip.below > window.innerHeight - 160;
  const x = Math.min(Math.max(tip.x, 170), window.innerWidth - 170);
  return <div className={`tip ${up ? "up" : ""}`} style={{ left: x, top: up ? tip.above : tip.below }} role="tooltip">{tip.text}</div>;
}
