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
  const row2 = page.getByTestId("manager-row-m2");
  await row2.locator('input[type="text"]').fill("Early Eddie");
  await row2.locator("select").selectOption("early");
  await row2.getByRole("button", { name: "Save" }).click();
  const row5 = page.getByTestId("manager-row-m5");
  await row5.locator('input[type="text"]').fill("Late Lucy");
  await row5.locator("select").selectOption("late");
  await row5.getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(300);
  await shot("02-league");
  summary.steps.push("league created, managers edited");

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
  await page.getByTestId("injury-select").selectOption("day_to_day");
  await page.getByTestId("source-manual").first().waitFor();
  await page.getByTestId("reset-injury").click();
  await page.waitForFunction(() => [...document.querySelectorAll('[data-testid="source-sleeper"]')].length >= 2);
  summary.steps.push("override edit + reset via sidebar (source badges)");

  await page.getByTestId("btn-start").click();
  await page.getByTestId("start-dialog").waitFor();
  const keepers = [["m3", "doncic", 60], ["m7", "gilgeous", 55]];
  for (let i = 0; i < keepers.length; i++) {
    const [mgr, q, cost] = keepers[i];
    await page.getByTestId("keeper-add").click();
    await page.getByTestId(`keeper-manager-${i}`).selectOption(mgr);
    await page.getByTestId(`keeper-search-${i}`).fill(q);
    await page.locator(`[data-testid^="search-result-"]`).first().click();
    await page.getByTestId(`keeper-player-${i}`).waitFor();
    await page.getByTestId(`keeper-cost-${i}`).fill(String(cost));
  }
  await page.getByTestId("start-confirm").click();
  await page.waitForFunction(() => document.querySelector('[data-testid="draft-status"]')?.textContent === "live");
  const started = await apiGet(`/leagues/${LEAGUE}/draft`);
  assert(started.picks.length === 2 && started.picks.every((p) => p.is_keeper), "two keeper picks recorded");
  log("draft live with keepers:", started.picks.map((p) => `${p.manager_id} $${p.price}`).join(", "));
  await shot("04-started");
  summary.steps.push("draft started with 2 keepers");

  // ---------------------------------------------------------------- 5. nominate -> on the block -> record bid
  const first = (await apiGet(`/leagues/${LEAGUE}/rankings?limit=1`))[0];
  await page.getByTestId(`btn-nominate-${first.player_id}`).click();
  await page.getByTestId("on-the-block").waitFor();
  await page.getByTestId("btn-record-bid").click();
  await page.getByTestId("pick-dialog").waitFor();
  await page.getByTestId("pick-recommended").waitFor();
  const recText = await page.getByTestId("pick-recommended").textContent();
  const recMax = Number(recText.replace(/[^0-9]/g, ""));
  await page.getByTestId("pick-manager").selectOption("m1");
  await page.getByTestId("pick-price").fill(String(recMax));
  await page.getByTestId("pick-submit").click();
  await page.getByTestId("pick-dialog").waitFor({ state: "detached" });
  log(`user (m1) won ${first.full_name} for the recommended $${recMax}`);
  summary.picks.push({ n: 1, player: first.full_name, winner: "m1", price: recMax, rec: recMax, path: "nominate+record" });

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
    const rowBtn = page.getByTestId(`btn-draft-${cand.player_id}`);
    if (await rowBtn.count()) {
      await rowBtn.first().click();
    } else {
      path = "search";
      await page.getByTestId("search-input").fill(cand.full_name.split(" ").slice(-1)[0]);
      await page.getByTestId(`search-result-${cand.player_id}`).click();
    }
    await page.getByTestId("pick-dialog").waitFor();
    await page.getByTestId("pick-manager").selectOption(winner);
    let rec = 1;
    try {
      await page.getByTestId("pick-recommended").waitFor({ timeout: 4000 });
      rec = Number((await page.getByTestId("pick-recommended").textContent()).replace(/[^0-9]/g, "")) || 1;
    } catch { /* recommendation unavailable: bid the minimum */ }
    const maxBid = Number((await page.getByTestId("pick-max-bid").textContent()).replace(/[^0-9]/g, ""));
    assert(maxBid === winnerBudget.max_bid, `dialog max bid ${maxBid} == API max bid ${winnerBudget.max_bid}`);
    // late in the draft managers fill bench at $1; otherwise pay up to the recommendation, capped by the reservation rule
    const price = Math.max(1, Math.min(winnerBudget.open_mandatory <= 3 ? 1 : rec, maxBid));
    await page.getByTestId("pick-price").fill(String(price));
    await page.getByTestId("pick-submit").click();
    try {
      await page.getByTestId("pick-dialog").waitFor({ state: "detached", timeout: 8000 });
    } catch {
      const err = (await page.getByTestId("pick-error").textContent().catch(() => "unknown")) || "unknown";
      failures++;
      log(`pick rejected (${winner} / ${cand.full_name} / $${price}): ${err}`);
      await page.keyboard.press("Escape");
      await page.locator(".modal-backdrop").click({ position: { x: 5, y: 5 } }).catch(() => {});
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
  await page.waitForFunction((n0) => document.querySelector('[data-testid="managers-panel"]') && true, final.picks.length);
  const afterUndo = await apiGet(`/leagues/${LEAGUE}/draft`);
  assert(afterUndo.picks.length === 179, "undo removed the last pick");
  await page.getByTestId("search-input").fill(lastBefore.player_id ? (await apiGet(`/players/${lastBefore.player_id}?include_history=false`)).record.last_name : "");
  await page.getByTestId(`search-result-${lastBefore.player_id}`).click();
  await page.getByTestId("pick-dialog").waitFor();
  await page.getByTestId("pick-manager").selectOption(lastBefore.manager_id);
  await page.getByTestId("pick-price").fill(String(lastBefore.price));
  await page.getByTestId("pick-submit").click();
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
