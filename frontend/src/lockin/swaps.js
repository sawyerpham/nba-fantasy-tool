// Lineup changes as Sleeper swaps (plain JS, no JSX, so `node src/lockin/swaps.check.mjs` can run it).

// Can a player with positions `pos` sit in `slot`? (Sleeper NBA slots: the positions, G, F, UTIL, BN.)
export const fits = (pos, slot) => slot === "BN" || slot === "UTIL" ? true : slot === "G" ? pos.some((p) => p === "PG" || p === "SG")
  : slot === "F" ? pos.some((p) => p === "SF" || p === "PF") : pos.includes(slot);

// `after`'s starters, seated with as few moves from `before` as possible: whoever already starts keeps his slot, each
// newcomer takes an open slot he can play, else the shortest chain of starters sliding to other slots they can play
// (breadth-first: Kyrie in at SG with DeRozan sliding SG -> SF beats Kyrie at PG pushing Haliburton to SG pushing
// DeRozan to SF). The plan only decides who starts; which slots is ours to pick. Bench / IR untouched.
// positions: the league's roster slots ("PG", "PG", ..., "BN", "IR").
export function reseat(before, after, pos, positions) {
  const seats = positions.filter((s) => s !== "BN" && s !== "IR"), who = Array(seats.length).fill(null);
  const starts = (slot) => slot && slot !== "BN" && slot !== "IR";
  const starters = Object.keys(after).filter((sid) => starts(after[sid]));
  for (const sid of starters.filter((s) => starts(before[s]))) {   // stay put
    const i = seats.findIndex((t, k) => t === before[sid] && who[k] == null);
    if (i >= 0) who[i] = sid;
  }
  const seatsFor = (sid) => seats.map((t, k) => k).filter((k) => fits(pos[sid] || [], seats[k]));
  const place = (sid) => {   // shortest augmenting path, breadth-first over seats; prev: seat -> the seat whose
    const prev = new Map(seatsFor(sid).map((k) => [k, -1])), queue = [...prev.keys()];   // occupant slides into it
    while (queue.length) {
      let k = queue.shift();
      if (who[k] == null) {   // open seat: slide everyone along the path, the newcomer into the first seat
        for (; prev.get(k) !== -1; k = prev.get(k)) who[k] = who[prev.get(k)];
        who[k] = sid;
        return true;
      }
      for (const j of seatsFor(who[k])) if (!prev.has(j)) { prev.set(j, k); queue.push(j); }
    }
    return false;
  };
  for (const sid of starters.filter((s) => !who.includes(s))) if (!place(sid)) return after;   // can't: keep the plan's
  const out = { ...after };
  who.forEach((sid, k) => { if (sid) out[sid] = seats[k]; });
  return out;
}

// The moves from lineup `before` to `after` (sid -> slot) as Sleeper swaps, in order: each step trades two players'
// slots and only ever puts a player in a slot he can play, so following them one by one reaches `after` (e.g. Sabonis
// BN <-> Wiggins PF, then Wiggins BN <-> Coward SG; doing it as "Sabonis for Coward" isn't possible: Coward can't play
// PF). Bench players go first; a swap that settles both players beats one that settles one. IR never moves here.
// step: { in, out: the two players trading places, slot: the starting slot it fills, n: its order, from / to: in's
// slot before and after the swap, a / b: the cards (sids) in's and out's slots show on screen at that step }
// Cards stand for slots, and earlier steps are taken as done: after "Kyrie <-> DeRozan", Kyrie is in DeRozan's card
// and DeRozan in Kyrie's, so "DeRozan <-> Nesmith" runs from Kyrie's card to Nesmith's. shownAfter: the cards show
// `after` (your best lineup), so each slot's card is the player who ends up in it, not the one who holds it now.
export function swapSteps(before, after, pos, shownAfter = false) {
  const cur = { ...before }, steps = [];
  const open = (sid) => cur[sid] !== after[sid] && cur[sid] !== "IR" && after[sid] !== "IR";
  for (let guard = 0; guard < 60; guard++) {
    // the player the last swap moved goes next (a chain's steps stay together), then bench players
    const last = steps.at(-1)?.out;
    const todo = Object.keys(cur).filter(open).sort((a, b) => (b === last) - (a === last) || (cur[b] === "BN") - (cur[a] === "BN"));
    let done = false;
    for (const p of todo) {
      const qs = Object.keys(cur).filter((q) => q !== p && open(q) && cur[q] === after[p] && fits(pos[q] || [], cur[p]));
      const q = qs.find((x) => after[x] === cur[p]) || qs[0];
      if (!q) continue;
      steps.push({ in: p, out: q, slot: after[p] === "BN" ? cur[p] : after[p], n: steps.length + 1, from: cur[p], to: cur[q] });
      [cur[p], cur[q]] = [cur[q], cur[p]];
      done = true;
      break;
    }
    if (!done) break;   // ponytail: a move into an empty starting slot (no one to trade with) isn't drawn
  }
  // slot each player holds, named by the player who held it at the start (= its card in the `before` lineup)
  const holds = Object.fromEntries(Object.keys(before).map((s) => [s, s]));
  for (const s of steps) {
    s.a = holds[s.in]; s.b = holds[s.out];
    [holds[s.in], holds[s.out]] = [holds[s.out], holds[s.in]];
  }
  if (shownAfter) {   // each slot's card is its final holder
    const card = Object.fromEntries(Object.entries(holds).map(([sid, slot]) => [slot, sid]));
    for (const s of steps) { s.a = card[s.a]; s.b = card[s.b]; }
  }
  return steps;
}
