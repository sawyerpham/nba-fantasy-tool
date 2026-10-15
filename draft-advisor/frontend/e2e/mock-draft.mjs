// End-to-end mock auction draft driven entirely through the UI (Phase 1E gate).
//
// Prereqs: backend on http://127.0.0.1:8000 (python -m app.serve), Vite dev server on http://localhost:5173.
// Run:     npm run e2e            (env: DA_URL, DA_API, DA_BROWSER=msedge|chrome|chromium, DA_LEAGUE, DA_SKIP_PULL=1)
//
// Every draft action goes through the browser. The API is only READ here to decide who should win
// the next lot and to verify the final state; it never mutates anything.

import fs from "node:fs";
import { chromium } from "playwright";

const BASE = process.env.DA_URL || "http://localhost:5173";
const API = process.env.DA_API || "http://127.0.0.1:8000/api";
const LEAGUE = process.env.DA_LEAGUE || `mock-${Date.now().toString(36)}`;
const SHOTS = "e2e/screenshots";
const MAX_ITER = 320;
fs.mkdirSync(SHOTS, { recursive: true });

const t0 = Date.now();
const log = (...a) => console.log(`[${((Date.now() - t0) / 1000).toFixed(1)}s]`, ...a);
const assert = (cond, msg) => { if (!cond) throw new Error(`ASSERT: ${msg}`); };
const apiGet = async (path) => { const r = await fetch(API + path); if (!r.ok) throw new Error(`${path}: ${r.status}`); return r.json(); };

const browser = await chromium.launch({ channel: process.env.DA_BROWSER || "msedge", headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
page.setDefaultTimeout(20000);
page.on("dialog", (d) => d.accept());
page.on("pageerror", (e) => log("PAGE ERROR:", e.message));
const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
const summary = { league: LEAGUE, steps: [], picks: [] };

try {
  await page.goto(BASE);
  await page.getByTestId("health").waitFor();

  // ---------------------------------------------------------------- 1. data pull through the UI
  await page.getByTestId("tab-data").click();
  if (process.env.DA_SKIP_PULL !== "1") {
    await page.getByTestId("pull-button").click();
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="pull-state"]');
      return el && (el.textContent === "done" || el.textContent === "failed");
    }, null, { timeout: 420000, polling: 1000 });
    const state = await page.getByTestId("pull-state").textContent();
    assert(state === "done", `pull ended in state ${state}`);
    log("pull:", (await page.locator("p.ok").first().textContent()).trim());
  } else {
    log("pull skipped (DA_SKIP_PULL=1)");
  }
  await shot("01-data");
  summary.steps.push("data pull done");

  // ---------------------------------------------------------------- 2. league + managers
  await page.getByTestId("tab-league").click();
  await page.getByTestId("create-league-id").fill(LEAGUE);
  await page.getByTestId("create-league-name").fill("Mock Auction 2026-27");
  await page.getByTestId("create-league-submit").click();
  await page.getByTestId(`manager-row-m2`).waitFor();
  // bulk: paste 12 names, set everyone's pace, then one Save all
  const names = ["Sawyer", "Early Eddie", "Manager Three", "Four", "Late Lucy", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve"];
  await page.getByTestId("bulk-names").fill(names.join("\n"));
  await page.getByTestId("bulk-names-apply").click();
  await page.getByTestId("bulk-pace").selectOption("even");
  await page.getByTestId("bulk-apply").click();
  const row2 = page.getByTestId("manager-row-m2");
  await row2.locator("select").selectOption("early");
  const row5 = page.getByTestId("manager-row-m5");
  await row5.locator("select").selectOption("late");
  await page.getByTestId("managers-save-all").click();
  await page.waitForFunction(() => !document.querySelector('[data-testid="managers-save-all"]:not([disabled])'));
  const savedManagers = await apiGet(`/leagues/${LEAGUE}/managers`);
  assert(savedManagers.map((m) => m.name).join(",") === names.join(","), "bulk names saved in one go");
  assert(savedManagers[1].behavior.spend_pace === "early" && savedManagers[4].behavior.spend_pace === "late", "paces saved");
  // theme toggle (dark is the default)
  assert((await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) === "dark", "dark theme by default");
  await page.getByTestId("theme-toggle").click();
  assert((await page.evaluate(() => document.documentElement.getAttribute("data-theme"))) === "light", "theme toggles to light");
  await page.getByTestId("theme-toggle").click();
  await shot("02-league");
  summary.steps.push("league created, 12 managers named/paced in bulk and saved with one click, theme toggled");

  // ---------------------------------------------------------------- 3. settings (defaults, save round trip)
  await page.getByTestId("tab-settings").click();
  await page.getByTestId("budget").waitFor();
  assert((await page.getByTestId("budget").inputValue()) === "200", "budget default 200");
  assert((await page.getByTestId("slot-BN").inputValue()) === "8", "8 bench slots");
  assert((await page.getByTestId("slot-IR").inputValue()) === "2", "2 IR slots");
  assert((await page.getByTestId("max-keepers").inputValue()) === "1", "max keepers 1");
  assert((await page.getByTestId("bonus-pts_50").inputValue()) === "1", "50+ bonus 1");
  await page.getByTestId("settings-save").click();
  await page.locator(".ok").first().waitFor();
  await shot("03-settings");
  summary.steps.push("settings verified and saved");

  // ---------------------------------------------------------------- 4. draft: sidebar overrides, start with keepers
  await page.getByTestId("tab-draft").click();
  await page.getByTestId("rankings-table").waitFor();
  const top = await apiGet(`/leagues/${LEAGUE}/rankings?limit=1`);
  const jokic = top[0].player_id;
  await page.getByTestId(`rank-row-${jokic}`).click();
  await page.getByTestId("player-sidebar").waitFor();
  assert(/C · age \d+/.test(await page.getByTestId("player-sidebar").locator("h3").first().textContent()), "profile header shows positions and age");
  summary.steps.push("sidebar shows Sleeper positions and injury (read-only)");

  await page.getByTestId("btn-start").click();
  await page.getByTestId("start-dialog").waitFor();
  // one row per manager is pre-filled: only the player and LAST year's price are typed;
  // the league rule (+$1 per full $5) computes this year's price
  assert((await page.locator('[data-testid^="keeper-row-"]').count()) === 12, "one keeper row per manager pre-filled");
  const keepers = [["m3", 2, "doncic", 17, 20], ["m7", 6, "gilgeous", 55, 66]];
  let verdictsSeen = 0;
  for (const [mgr, i, q, last, expected] of keepers) {
    assert((await page.getByTestId(`keeper-manager-${i}`).inputValue()) === mgr, `row ${i} belongs to ${mgr}`);
    await page.getByTestId(`keeper-search-${i}`).fill(q);
    await page.locator(`[data-testid^="search-result-"]`).first().click();
    await page.getByTestId(`keeper-player-${i}`).waitFor();
    await page.getByTestId(`keeper-last-${i}`).fill(String(last));
    await page.waitForFunction(([idx, exp]) => document.querySelector(`[data-testid="keeper-cost-${idx}"]`)?.value === String(exp), [i, expected]);
    const verdict = await page.getByTestId("keeper-verdict").nth(verdictsSeen++).textContent();
    log(`keeper ${mgr}: last $${last} -> this year $${expected}; ${verdict.trim()}`);
    assert(/GOOD|EVEN|BAD/.test(verdict), "keeper verdict rendered");
  }
  assert((await page.getByTestId("keepers-entered").textContent()).startsWith("2 keepers"), "entered counter");
  await page.getByTestId("start-confirm").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="draft-status"]')?.textContent === "live");
  const started = await apiGet(`/leagues/${LEAGUE}/draft`);
  assert(started.picks.length === 2 && started.picks.every((p) => p.is_keeper), "two keeper picks recorded");
  assert(started.picks.map((p) => p.price).join(",") === "20,66", `keeper prices follow the rule: ${started.picks.map((p) => p.price)}`);
  log("draft live with keepers:", started.picks.map((p) => `${p.manager_id} $${p.price}`).join(", "));
  await shot("04-started");
  summary.steps.push("draft started with 2 keepers");

  // ---------------------------------------------------------------- 5. nominate -> on the block -> record bid
  const first = (await apiGet(`/leagues/${LEAGUE}/rankings?limit=1`))[0];
  await page.getByTestId(`rank-row-${first.player_id}`).dblclick();   // double-click a row = on the block
  await page.getByTestId("on-the-block").waitFor();
  await page.getByTestId("pick-dialog").waitFor();          // nominating opens the inline record bar by itself
  await page.getByTestId("pick-recommended").waitFor();
  const recText = await page.getByTestId("pick-recommended").textContent();
  const recMax = Number(recText.replace(/[^0-9]/g, ""));
  assert(Number(await page.getByTestId("pick-price").inputValue()) === recMax, "price prefilled with the recommendation");
  await page.getByTestId("pick-mgr-m1").click();               // one click records
  await page.getByTestId("pick-dialog").waitFor({ state: "detached" });
  log(`user (m1) won ${first.full_name} for the recommended $${recMax}`);
  summary.picks.push({ n: 1, player: first.full_name, winner: "m1", price: recMax, rec: recMax, path: "nominate+record" });

  // nomination order on the fly: move m12 to the front with the arrow buttons (next nominator m2 must stay), then make m5 next
  const nextId = () => page.getByTestId("next-nominator").getAttribute("data-manager-id");
  assert((await nextId()) === "m2", "m2 nominates after m1");
  assert((await page.getByTestId("next-nominator").textContent()) === "Early Eddie", "next nominator shown by name, not id");
  if (!(await page.getByTestId("order-bar").isVisible())) await page.getByTestId("btn-order").click();   // order editor is folded away once live
  for (let k = 0; k < 11; k++) await page.getByTestId("order-left-m12").click();  // each click waits for the previous save (arrows disable while busy)
  // wait for the last save to land: the chip shows "1." and the arrows are enabled again (not busy)
  await page.waitForFunction(() => document.querySelector('[data-testid="order-next-m12"]')?.textContent.startsWith("1.")
    && !document.querySelector('[data-testid="order-right-m12"]')?.disabled);
  let order = (await apiGet(`/leagues/${LEAGUE}/draft`)).nomination_order;
  assert(order[0] === "m12" && order[1] === "m1", `m12 moved to the front: ${order}`);
  assert((await nextId()) === "m2", "reordering keeps whose turn it is");
  await page.getByTestId("order-next-m5").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="next-nominator"]')?.getAttribute("data-manager-id") === "m5");
  log("nomination order reordered on the fly (m12 first, m2 kept its turn), then m5 made next");
  summary.steps.push("nomination order reordered on the fly + make-next");
  // rankings QoL: position chip + column sort
  await page.getByTestId("pos-C").click();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid^="rank-row-"]')].every((tr) => tr.children[3].textContent.includes("C")));
  await page.getByTestId("pos-C").click();
  await page.locator('[data-testid="rankings-table"] th', { hasText: "Proj FP/G" }).click();
  await page.waitForFunction(() => {
    const rows = [...document.querySelectorAll('[data-testid^="rank-row-"]')];
    return rows.length > 2 && (parseFloat(rows[0].children[4].textContent) || 0) >= (parseFloat(rows[1].children[4].textContent) || 0);
  });
  assert((await page.locator('[data-testid="value-legend"]').count()) === 0, "formula legend removed from the draft page");
  await page.locator('[data-testid^="rank-row-"]').first().click();
  await page.getByTestId("recommendation").waitFor();
  const guide = await page.getByTestId("recommendation").textContent();
  assert(guide.includes("for Sawyer") && guide.includes("Worth") && guide.includes("Max") && guide.includes("Your cap") && !guide.includes("Market price") && !guide.includes("Fair value"), `bid guide is labelled for the user: ${guide.slice(0, 80)}`);
  await page.getByTestId("spend-verdict").waitFor();
  await page.getByTestId("team-fit").waitFor();
  log("team fit:", (await page.getByTestId("team-fit-headline").textContent()));
  const verdict = await page.getByTestId("spend-verdict").textContent();
  assert(/BUY|STAR ONLY|TOO PRICEY|CAN'T/.test(verdict), `call rendered in the bid guide: ${verdict.slice(0, 60)}`);
  // one "your max" per player: the rankings column and the profile agree
  const firstRow = page.locator('[data-testid^="rank-row-"]').first();
  const colMax = (await firstRow.locator('[data-testid="your-max"]').count()) ? (await firstRow.locator('[data-testid="your-max"]').textContent()) : "—";
  assert(colMax === (await page.getByTestId("rec-max").textContent()), `rankings Max ${colMax} matches the profile`);
  // every defined term explains itself on hover
  await page.locator('[data-testid="rankings-table"] th .term', { hasText: "Fit" }).hover();
  assert((await page.locator(".tip").textContent()).startsWith("0-100, how much he helps your team"), "hovering Fit shows its definition");
  await page.mouse.move(0, 0);
  const spending = await page.getByTestId("spending-guide").textContent();
  assert(spending.includes("for Sawyer") && spending.includes("Room") && spending.includes("Price level"), "spending guide shows you vs the room");
  assert((await page.locator('[data-testid^="best-fit-"]').count()) >= 1, "spending guide lists your best fits");
  log("spending guide:", spending.replace(/\s+/g, " ").slice(0, 160));
  await page.getByTestId("rank-sort").click();             // first column: tier and overall rank side by side ("T2 1")
  await page.waitForFunction(() => /^T\d+ 1$/.test((document.querySelector('[data-testid^="rank-row-"]')?.children[0].textContent || "").trim()));
  log("rankings: position chip filter and column sort work");
  // adjust who drafted whom: Jokić is pick #3 (after two keepers); move it to m2 through the edit dialog, then back
  await page.getByTestId("pick-chip-3").click();
  await page.getByTestId("edit-pick-dialog").waitFor();
  await page.getByTestId("edit-pick-manager").selectOption("m2");
  await page.getByTestId("edit-pick-save").click();
  await page.getByTestId("edit-pick-dialog").waitFor({ state: "detached" });
  let moved = (await apiGet(`/leagues/${LEAGUE}/draft`)).picks.find((p) => p.pick_number === 3);
  assert(moved.manager_id === "m2" && moved.price === recMax, `pick #3 moved to m2 at the same price: ${JSON.stringify(moved)}`);
  await page.getByTestId("pick-chip-3").click();
  await page.getByTestId("edit-pick-manager").selectOption("m1");
  await page.getByTestId("edit-pick-save").click();
  await page.getByTestId("edit-pick-dialog").waitFor({ state: "detached" });
  moved = (await apiGet(`/leagues/${LEAGUE}/draft`)).picks.find((p) => p.pick_number === 3);
  assert(moved.manager_id === "m1", "pick #3 moved back to m1");
  log("who-drafted-whom fixed through the pick chip: #3 m1 -> m2 -> m1");
  summary.steps.push("pick moved between managers via the edit dialog");

  // ---------------------------------------------------------------- 6. full mock auction through the UI
  let n = 1;
  let failures = 0;
  for (let iter = 0; iter < MAX_ITER; iter++) {
    const view = await apiGet(`/leagues/${LEAGUE}/draft`);
    const canDraft = view.managers.filter((m) => m.budget.open_mandatory > 0 && m.budget.max_bid >= 1);
    if (!canDraft.length) break;
    const winner = iter % 3 === 0 && canDraft.some((m) => m.manager_id === view.next_nominator)
      ? view.next_nominator
      : canDraft[iter % canDraft.length].manager_id;
    const winnerBudget = view.managers.find((m) => m.manager_id === winner).budget;
    const cands = await apiGet(`/leagues/${LEAGUE}/rankings?manager_id=${winner}&limit=6`);
    if (!cands.length) { log("no rosterable candidates for", winner); break; }
    const cand = cands[Math.min(iter % 3, cands.length - 1)];

    // open the pick dialog: from the table when the row is visible for the user, else via the search box
    let path = "table";
    const row = page.getByTestId(`rank-row-${cand.player_id}`);
    if (await row.count()) {
      await row.first().dblclick();
    } else {
      path = "search";
      await page.getByTestId("search-input").fill(cand.full_name.split(" ").slice(-1)[0]);
      await page.getByTestId(`search-result-${cand.player_id}`).click();
    }
    await page.getByTestId("pick-dialog").waitFor();
    let rec = 1;
    try {
      await page.getByTestId("pick-recommended").waitFor({ timeout: 4000 });
      rec = Number((await page.getByTestId("pick-recommended").textContent()).replace(/[^0-9]/g, "")) || 1;
    } catch { /* recommendation unavailable: bid the minimum */ }
    const maxBid = Number((await page.getByTestId(`pick-max-${winner}`).textContent()).replace(/[^0-9]/g, ""));
    assert(maxBid === winnerBudget.max_bid, `dialog max bid ${maxBid} == API max bid ${winnerBudget.max_bid}`);
    // late in the draft managers fill bench at $1; otherwise pay up to the recommendation, capped by the reservation rule
    const price = Math.max(1, Math.min(winnerBudget.open_mandatory <= 3 ? 1 : rec, maxBid));
    await page.getByTestId("pick-price").fill(String(price));
    await page.getByTestId(`pick-mgr-${winner}`).click();
    try {
      await page.getByTestId("pick-dialog").waitFor({ state: "detached", timeout: 8000 });
    } catch {
      const err = (await page.getByTestId("pick-error").textContent().catch(() => "unknown")) || "unknown";
      failures++;
      log(`pick rejected (${winner} / ${cand.full_name} / $${price}): ${err}`);
      await page.getByTestId("pick-cancel").click().catch(() => {});
      await page.getByTestId("pick-dialog").waitFor({ state: "detached", timeout: 5000 }).catch(() => {});
      assert(failures < 10, "too many rejected picks");
      continue;
    }
    n++;
    summary.picks.push({ n, player: cand.full_name, winner, price, rec, max: maxBid, path });
    if (n % 20 === 0) {
      log(`pick ${n}: ${winner} paid $${price} for ${cand.full_name} (rec $${rec}, max $${maxBid}, via ${path})`);
    }
    if (n === 40 || n === 120) await shot(`05-picks-${n}`);
  }

  // ---------------------------------------------------------------- 7. verify: every manager filled 15 slots within budget
  const final = await apiGet(`/leagues/${LEAGUE}/draft`);
  const problems = [];
  for (const m of final.managers) {
    const nonIr = m.picks.filter((p) => p.slot !== "IR").length;
    if (nonIr !== 15) problems.push(`${m.manager_id}: ${nonIr} non-IR picks`);
    if (m.budget.remaining < 0) problems.push(`${m.manager_id}: negative budget ${m.budget.remaining}`);
    if (m.budget.open_mandatory !== 0) problems.push(`${m.manager_id}: ${m.budget.open_mandatory} mandatory slots open`);
  }
  assert(problems.length === 0, problems.join("; "));
  assert(final.picks.length === 180, `180 picks expected, got ${final.picks.length}`);
  const spent = final.managers.map((m) => `${m.manager_id}:$${200 - m.budget.remaining}`).join(" ");
  log(`all 12 managers filled 15 mandatory slots; spent -> ${spent}`);
  const stacks = final.managers.flatMap((m) => Object.entries(m.stack).filter(([, c]) => c >= 2).map(([t, c]) => `${m.manager_id} ${t}×${c}`));
  log("stacks of 2+:", stacks.join(", ") || "none");
  summary.steps.push(`180 picks recorded through the UI (${failures} rejected attempts), all rosters full`);

  // ---------------------------------------------------------------- 8. undo + redo, complete, export
  const lastBefore = final.picks[final.picks.length - 1];
  await page.getByTestId("btn-undo").click();
  let afterUndo;
  for (let i = 0; i < 50 && (afterUndo = await apiGet(`/leagues/${LEAGUE}/draft`)).picks.length !== 179; i++) await page.waitForTimeout(100);
  assert(afterUndo.picks.length === 179, "undo removed the last pick");
  await page.getByTestId("search-input").fill(lastBefore.player_id ? (await apiGet(`/players/${lastBefore.player_id}?include_history=false`)).record.last_name : "");
  await page.getByTestId(`search-result-${lastBefore.player_id}`).click();
  await page.getByTestId("pick-dialog").waitFor();
  await page.getByTestId("pick-price").fill(String(lastBefore.price));
  await page.getByTestId(`pick-mgr-${lastBefore.manager_id}`).click();
  await page.getByTestId("pick-dialog").waitFor({ state: "detached" });
  assert((await apiGet(`/leagues/${LEAGUE}/draft`)).picks.length === 180, "re-pick restored 180");
  summary.steps.push("undo + re-pick via search");

  await page.getByTestId("btn-complete").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="draft-status"]')?.textContent === "complete");
  await page.getByTestId("btn-export").click();
  await page.getByTestId("draft-notice").waitFor();
  const notice = await page.getByTestId("draft-notice").textContent();
  assert(notice.includes("schema_version 1"), `export notice: ${notice}`);
  log(notice);
  await shot("06-complete");
  summary.steps.push("draft completed and exported (schema_version 1)");

  const doc = await apiGet(`/leagues/${LEAGUE}`);
  assert(doc.schema_version === 1 && Object.keys(doc.players).length === 180, "export holds 180 drafted players");
  summary.result = "PASS";
  fs.writeFileSync("e2e/last-run.json", JSON.stringify(summary, null, 1));
  log("MOCK DRAFT PASSED");
} catch (err) {
  summary.result = `FAIL: ${err.message}`;
  fs.writeFileSync("e2e/last-run.json", JSON.stringify(summary, null, 1));
  await shot("99-failure").catch(() => {});
  log("MOCK DRAFT FAILED:", err.stack || err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
