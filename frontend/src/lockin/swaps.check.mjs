// Run: node src/lockin/swaps.check.mjs  (no output = pass)
import assert from "node:assert/strict";
import { fits, moveArrows, reseat } from "./swaps.js";

const arrows = (before, after, shownAfter) => moveArrows(before, after, shownAfter).map((m) => `${m.sid}:${m.from}>${m.to}`);

// JunJun: Kyrie (PG/SG) in for Nesmith (SF, out). reseat puts Kyrie at SG and slides DeRozan SG -> SF (2 players
// move besides Nesmith), not Kyrie at PG pushing Haliburton to SG pushing DeRozan to SF.
const pos = { kyrie: ["PG", "SG"], hali: ["PG", "SG"], derozan: ["SG", "SF", "PF"], nesmith: ["SG", "SF"], murray: ["PG"], bane: ["PG", "SG"] };
const slots = ["PG", "PG", "SG", "SG", "SF", "BN", "BN"];
const was = { murray: "PG", hali: "PG", bane: "SG", derozan: "SG", nesmith: "SF", kyrie: "BN" };
const plan = { murray: "PG", hali: "SG", bane: "SG", derozan: "SF", nesmith: "BN", kyrie: "PG" };   // the plan's slots
const best = reseat(was, plan, pos, slots);
assert.deepEqual(best, { murray: "PG", hali: "PG", bane: "SG", derozan: "SF", nesmith: "BN", kyrie: "SG" });
for (const [sid, slot] of Object.entries(best)) assert.ok(fits(pos[sid], slot), `${sid} can't play ${slot}`);

// The arrows loop: each from the row of the slot he leaves to the row of the slot he takes.
// Sleeper's lineup on screen (rivals): rows are where players are now.
assert.deepEqual(arrows(was, best, false).sort(), ["derozan:derozan>nesmith", "kyrie:kyrie>derozan", "nesmith:nesmith>kyrie"]);
// Best lineup on screen (yours): rows are where players end up, so each arrow starts at whoever took his old slot.
assert.deepEqual(arrows(was, best, true).sort(), ["derozan:kyrie>derozan", "kyrie:nesmith>kyrie", "nesmith:derozan>nesmith"]);
// Nothing changes: no arrows.
assert.deepEqual(arrows(was, was, false), []);
