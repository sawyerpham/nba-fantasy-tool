import React, { useEffect, useState } from "react";

// The site's vocabulary: one word, one meaning, everywhere. Wrap a term in <Term k="..."> (dotted underline)
// and hovering it shows the definition. Any element with data-tip gets the same tooltip.
export const TERMS = {
  worth: ["Worth", "What he's worth in this room: $1 + his value above replacement × the room's $ per point of value. Same for every manager; shifts as money and talent leave. Bid up to this freely."],
  max: ["Max", "Worth plus up to 15% when rivals can afford him and have a spot: where bidding will likely end. Past it, someone is overpaying; don't be you."],
  comfort: ["Comfort limit", "Pay up to this and you keep at least 80% of the room's average $ per open starting spot."],
  walk: ["Walk-away", "Never pay more. Past this you'd have under half the room's average $ per open starting spot."],
  cap: ["Cap", "The most a manager can bid: money left minus $1 per other open roster spot."],
  call: ["Call", "Whether his Max fits your budget: BUY, STAR ONLY, TOO PRICEY or CAN'T."],
  buy: ["BUY", "His Max is within your comfort limit: you can afford to win him."],
  star: ["STAR ONLY", "His Max is between your comfort limit and walk-away: go that high only for a star you build around."],
  pricey: ["TOO PRICEY", "His Max is past your walk-away: bid to your walk-away at most."],
  cannot: ["CAN'T", "You can't bid: no open spot he fits, or not enough money (cap)."],
  fit: ["Fit", "0-100, how much he helps your team: his value as a % of the best value left × role (starter 1, bench 0.6, no spot 0) × call (BUY 1, STAR ONLY 0.85, TOO PRICEY 0.4, CAN'T 0). 70+ strong, 45-69 decent, under 45 weak."],
  value: ["Value", "Ranking score in fantasy points: projected FP/G blended with his expected best game of the week, adjusted for games, availability, injury, age and schedule, plus position scarcity."],
  fpg: ["Proj FP/G", "Projected fantasy points per game (Sleeper). Arrows: change vs last season, one per 0.5 / 1.5 / 3 FP/G."],
  avail: ["Avail", "Share of fantasy weeks he played, over the last 3 seasons weighted 50/30/20. One lost season (under 50%) from an otherwise 80%+ player is forgiven: fully under 30, half at 32, a quarter from 34. Two is a pattern, never forgiven. Under 75% is flagged."],
  tier: ["Tier", "Players of similar value; T1 is best. 'N more like him' = how many in his tier are left; the last one means the next is a step down."],
  pos_rank: ["Pos rank", "Sleeper's positional rank by average draft position, e.g. #2 SG. Shows what other managers think, not value."],
  rank: ["Rank", "Tier and overall rank by value for your team; players you can't roster sink to the bottom."],
  rost: ["Rost%", "Share of Sleeper leagues where he's rostered."],
  min: ["Min", "Projected minutes per game (Sleeper). Grey = last season's."],
  left: ["$ left", "Budget not yet spent."],
  per_slot: ["$/slot", "Money left ÷ open roster spots (bench included)."],
  open: ["Open", "Roster spots still to fill, bench included."],
  room: ["Room", "Average $ per open roster spot across every manager."],
  even_split: ["Even split", "Your money spread evenly over open starting spots, bench spots at $1."],
  ideal: ["Ideal team", "For each open starting spot: the best player left who fits, and the best within your even split. No repeats."],
  best_fits: ["Best fits", "Available players with the highest Fit for your team."],
  drain: ["DRAIN", "Nominate to drain rivals' money: several can pay a lot and you won't (no spot, over cap, or TOO PRICEY)."],
  sneak: ["SNEAK", "Nominate to buy cheap: a BUY for you that few rivals can afford now."],
  win_score: ["Win score", "Projected weekly Lock-In score of the finished lineup: each starter's expected best game × availability, empty spots filled with what your money buys. Higher = more likely to win."],
  est_fpg: ["Est FP/G", "Projected FP/G of players in starting spots now."],
  open_starters: ["Open starters", "Starting spots still empty."],
  need: ["Need", "Open starting spots for this position across the room."],
  supply: ["Left", "Starter-quality players left at this position: available players in the top N by value, N = open starting spots in the room. Each counts once, where he'll be used (a PF/C at whichever has more open spots)."],
  pos_status: ["Market", "Scarce: fewer starter-quality players than open spots, prices will rise, buy early. Tight: under 1.3 per spot. Plenty: wait for value."],
  tier_cliff: ["Top tier", "Best tier left here, how many remain, and how far the next tier's best drops in fantasy points. Last in a tier = buy now or drop a level."],
  chasing: ["Chasing", "Rivals with an open spot here who can afford the best player left. More chasers = bidding wars."],
  room_trend: ["Room trend", "How the room is spending, over the last sales: + = buyer paid above Worth, − = below."],
  keeper_outlook: ["Keeper next year", "If you buy him at his Max: next year's keeper price (+$1 per full $5) vs his projected worth next year (healthy, a year older, at draft-start prices). GOOD / EVEN / BAD keep use the keeper menu's thresholds. Never part of Fit."],
  stash: ["STASH", "Out now, so little help this season, but at this price he'd be a GOOD keep next year. Only with money and a spot to spare."],
  overpaid: ["Overpaid / bargain", "Sale price vs his Worth at that point. Within $2 is about right."],
  live_call: ["Live call", "Where the high bid sits for you. BID: under his Worth, raise. STRETCH: past Worth but under Max and walk-away, only if you need him. STOP: at or past Max or walk-away. CAN'T: you can't bid. LEADING: you hold the bid."],
  keep_call: ["Keep call", "GOOD keep: keeper price is under his draft-start worth by at least $2 and 10%. BAD keep: over by that much. EVEN: between."],
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
