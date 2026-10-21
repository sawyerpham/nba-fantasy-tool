// Lineup changes for the move arrows (plain JS, no JSX, so `node src/lockin/swaps.check.mjs` can run it).

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

// One arrow per player who changes slot from lineup `before` to `after` (sid -> slot): from the row of the slot he
// leaves to the row of the slot he takes. A slot's row is the player shown in it: with the `before` lineup on screen
// that's whoever holds the slot now (and leaves it); with `after` on screen, whoever takes it. Leavers and takers of
// each slot are paired in order, so a chain draws as a loop (Kyrie -> DeRozan's SG row, DeRozan -> Nesmith's SF row,
// Nesmith -> Kyrie's bench row). No order to follow: every move lands in a slot he can play (reseat), and Sleeper takes
// them in whatever order works. IR never moves here.
// ponytail: a move into an empty slot (no one leaving it) has no row to point at and isn't drawn.
// move: { sid, from: row sid, to: row sid, was: his slot now, slot: his slot after }
export function moveArrows(before, after, shownAfter) {
  const moving = Object.keys(before).filter((s) => before[s] !== after[s] && before[s] !== "IR" && after[s] !== "IR");
  const leaver = {}, taker = {};   // sid -> his partner in the slot he leaves / takes
  for (const slot of new Set(moving.flatMap((s) => [before[s], after[s]]))) {
    const out = moving.filter((s) => before[s] === slot), inn = moving.filter((s) => after[s] === slot);
    out.forEach((s, i) => { if (inn[i]) { taker[s] = inn[i]; leaver[inn[i]] = s; } });
  }
  return moving.flatMap((sid) => {
    const from = shownAfter ? taker[sid] : sid, to = shownAfter ? sid : leaver[sid];
    return from && to ? [{ sid, from, to, was: before[sid], slot: after[sid] }] : [];
  });
}
