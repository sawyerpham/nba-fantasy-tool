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
// A plain bench-for-starter swap stays one step; nothing to do = no steps.
assert.deepEqual(replay({ grant: "PF", sabonis: "BN" }, { grant: "BN", sabonis: "PF" }, pos), ["sabonis<>grant"]);
assert.deepEqual(swapSteps({ grant: "PF" }, { grant: "PF" }, pos), []);
