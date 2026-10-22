// Run: node src/lockin/swaps.check.mjs  (no output = pass)
import assert from "node:assert/strict";
import { fits, reseat, swapSteps } from "./swaps.js";

// Replays the steps: every swap must be legal for both players, and the end lineup must be `after`.
function replay(before, after, pos) {
  const cur = { ...before }, steps = swapSteps(before, after, pos);
  for (const s of steps) {
    assert.ok(fits(pos[s.in], cur[s.out]) && fits(pos[s.out], cur[s.in]), `illegal step ${JSON.stringify(s)}`);
    [cur[s.in], cur[s.out]] = [cur[s.out], cur[s.in]];
  }
  assert.deepEqual(cur, after);
  return steps.map((s) => `${s.in}<>${s.out}`);
}

// Sabonis (PF/C) starts at PF, Wiggins moves PF -> SG, Coward (SG/SF, can't play PF) sits: two swaps, in that order.
const pos = { coward: ["SG", "SF"], wiggins: ["SG", "SF", "PF"], sabonis: ["PF", "C"], grant: ["SF", "PF"] };
assert.deepEqual(replay({ coward: "SG", wiggins: "PF", sabonis: "BN", grant: "PF" },
                        { coward: "BN", wiggins: "SG", sabonis: "PF", grant: "PF" }, pos), ["sabonis<>wiggins", "wiggins<>coward"]);
// reseat: Kyrie (PG/SG) in for Nesmith (SF, out): Kyrie takes SG and DeRozan slides SG -> SF (2 swaps), not Kyrie at
// PG pushing Haliburton to SG pushing DeRozan to SF (3).
const p2 = { kyrie: ["PG", "SG"], hali: ["PG", "SG"], derozan: ["SG", "SF", "PF"], nesmith: ["SG", "SF"], murray: ["PG"], bane: ["PG", "SG"] };
const slots = ["PG", "PG", "SG", "SG", "SF", "BN", "BN"];
const was = { murray: "PG", hali: "PG", bane: "SG", derozan: "SG", nesmith: "SF", kyrie: "BN" };
const plan = { murray: "PG", hali: "SG", bane: "SG", derozan: "SF", nesmith: "BN", kyrie: "PG" };   // the plan's slots
assert.deepEqual(replay(was, reseat(was, plan, p2, slots), p2), ["kyrie<>derozan", "derozan<>nesmith"]);
// The cards each step's arrow joins, taking earlier steps as done: after Kyrie <-> DeRozan, DeRozan sits in Kyrie's
// (bench) card, so DeRozan <-> Nesmith joins Kyrie's card and Nesmith's. With the best lineup on screen the cards are
// the final holders: Kyrie's SG slot is Kyrie's card, the bench slot Nesmith ends in is Nesmith's.
const cards = (shownAfter) => swapSteps(was, reseat(was, plan, p2, slots), p2, shownAfter).map((s) => `${s.a}-${s.b}`);
assert.deepEqual(cards(false), ["kyrie-derozan", "kyrie-nesmith"]);
assert.deepEqual(cards(true), ["nesmith-kyrie", "nesmith-derozan"]);
// A fixed player (locked in, or mid-game) is never moved: with DeRozan locked at SG (and Bane able to play SF), Kyrie
// takes Bane's SG and Bane slides to SF; DeRozan stays put.
const p3 = { ...p2, bane: ["PG", "SG", "SF"] };
const fixedBest = reseat(was, plan, p3, slots, new Set(["derozan"]));
assert.equal(fixedBest.derozan, "SG");
assert.deepEqual(replay(was, fixedBest, p3).length, 2);   // Kyrie <-> Bane (SG), Bane <-> Nesmith (SF)
// A plain bench-for-starter swap stays one step; nothing to do = no steps.
assert.deepEqual(replay({ grant: "PF", sabonis: "BN" }, { grant: "BN", sabonis: "PF" }, pos), ["sabonis<>grant"]);
assert.deepEqual(swapSteps({ grant: "PF" }, { grant: "PF" }, pos), []);
