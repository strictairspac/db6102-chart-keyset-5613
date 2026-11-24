import { chromium } from "/tmp/pw/node_modules/playwright/index.mjs";

const EXE = "/home/node/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell";
const BASE = "http://127.0.0.1:18251";
const SHOT = "/tmp/gb6102_verify/shots";
import { mkdirSync } from "node:fs";
mkdirSync(SHOT, { recursive: true });

let passed = 0;
async function check(name, cond, extra = "") {
  if (!cond) throw new Error(`FAIL: ${name} ${extra}`);
  passed++;
  console.log("ok:", name);
}

const browser = await chromium.launch({
  executablePath: EXE, headless: true, chromiumSandbox: false,
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
});

async function login(page, username) {
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.fill('input[name=username]', username);
  await page.fill('input[name=password]', "Demo-DbWorkbench-2026");
  await page.click('button[type=submit]');
  await page.waitForSelector('[data-testid="handover-workspace"]', { timeout: 15000 });
}

// ================================================================ operator
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await ctx.newPage();
page.on("pageerror", e => console.log("PAGEERROR:", e.message));
page.on("console", m => { if (m.type() === "error") console.log("CONSOLE.ERROR:", m.text().slice(0, 200)); });

await login(page, "operator");
await page.screenshot({ path: `${SHOT}/01-overview.png`, fullPage: false });

// open a fresh batch size 2
await page.fill('[data-testid="open-page-size"]', "2");
await page.click('[data-testid="open-batch"]');
await page.waitForSelector('[data-testid="batch-detail"]');
const bid = await page.getAttribute('[data-testid="batch-detail"]', "data-batch-id");
console.log("opened batch", bid);
await check("batch id present", /^\d+$/.test(bid || ""));

// claim first page
await page.click('[data-testid="claim-next"]');
await page.waitForSelector('[data-testid="page-items"]');
let seqs = await page.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("first page 105,104", JSON.stringify(seqs) === JSON.stringify(["105", "104"]), JSON.stringify(seqs));
let progress = await page.textContent('[data-testid="progress"]');
await check("progress 2/5", progress.includes("2/5"), progress);
const cred1 = await page.textContent('[data-testid="credential"]');
await check("credential shown", cred1.length > 20, cred1.slice(0, 30));

// ---- mutate errata book: change date, withdraw, add 106 & 107
await page.fill('[data-testid="date-input-104"]', "2020-01-01");
await page.click('[data-testid="save-date-104"]');
await page.waitForFunction(() => document.querySelector('[data-testid="errata-feedback"]')?.textContent.includes("签发日已改"));

await page.click('[data-testid="withdraw-103"]');
await page.waitForFunction(() => document.querySelector('tr[data-seq="103"]')?.dataset.withdrawn === "true");

async function addNotice(seq, date, chart, text) {
  await page.fill('[data-testid="notice-seq"]', String(seq));
  await page.fill('[data-testid="notice-date"]', date);
  await page.fill('[data-testid="notice-chart"]', chart);
  await page.fill('[data-testid="notice-text"]', text);
  await page.click('[data-testid="add-notice"]');
  await page.waitForFunction(s => document.querySelector(`tr[data-seq="${s}"]`) !== null, seq);
}
await addNotice(106, "2026-11-24", "CN-12311", "新增通航浮标");
await addNotice(107, "2026-11-21", "CN-12311", "补录北港灯塔弧区");
await page.screenshot({ path: `${SHOT}/02-errata-mutated.png` });

// ---- retry original credential: same page, progress unchanged
await page.click('[data-testid="retry-credential"]');
await page.waitForFunction(() => document.querySelector('[data-testid="workspace-note"]')?.textContent.includes("重放"));
seqs = await page.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("retry same page 105,104", JSON.stringify(seqs) === JSON.stringify(["105", "104"]), JSON.stringify(seqs));
progress = await page.textContent('[data-testid="progress"]');
await check("retry does not add progress (still 2/5)", progress.includes("2/5"), progress);
const credAfter = await page.textContent('[data-testid="credential"]');
await check("same credential retained", credAfter === cred1);

// ---- turn remaining pages
await page.click('[data-testid="claim-next"]');
await page.waitForFunction(() => {
  const rows = document.querySelectorAll('[data-testid="page-items"] tbody tr');
  return rows.length === 2 && rows[0].dataset.seq === "103";
});
seqs = await page.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("page2 frozen 103,102 despite withdraw", JSON.stringify(seqs) === JSON.stringify(["103", "102"]), JSON.stringify(seqs));
progress = await page.textContent('[data-testid="progress"]');
await check("progress 4/5", progress.includes("4/5"), progress);

await page.click('[data-testid="claim-next"]');
await page.waitForSelector('[data-testid="completed-at"]');
seqs = await page.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("page3 101", JSON.stringify(seqs) === JSON.stringify(["101"]), JSON.stringify(seqs));
const completedText = await page.textContent('[data-testid="completed-at"]');
await check("completed time rendered", /\d{4}[/.-]\d{1,2}[/.-]\d{1,2}/.test(completedText), completedText);
const completedIso = await page.getAttribute('[data-testid="completed-at"]', "datetime");
await check("completed datetime ISO", !Number.isNaN(Date.parse(completedIso)), completedIso);
await page.screenshot({ path: `${SHOT}/03-completed.png` });

// ---- reload: service/browser restart analogue; batch persists & shows completion
await page.reload({ waitUntil: "networkidle" });
await page.waitForSelector('[data-testid="handover-workspace"]');
await page.waitForSelector(`[data-batch-id="${bid}"]`);
// batch should remain selected via sessionStorage
await page.waitForSelector('[data-testid="completed-at"]', { timeout: 8000 }).catch(() => {});
const stillCompleted = await page.$('[data-testid="completed-at"]');
if (!stillCompleted) {
  await page.click(`[data-testid="open-batch-${bid}"]`);
  await page.waitForSelector('[data-testid="completed-at"]');
}
const completedAfterReload = await page.textContent('[data-testid="completed-at"]');
await check("completion survives reload", /\d{4}/.test(completedAfterReload), completedAfterReload);

// ---- receipt page shows when batch finished
await page.click('[data-testid="goto-receipt"]').catch(async () => {
  await page.evaluate(() => { location.hash = "#evidence"; });
});
await page.waitForSelector('[data-testid="handover-receipt"]', { timeout: 8000 });
const receiptCompleted = await page.textContent('[data-testid="handover-receipt"] [data-testid="completed-at"]');
await check("receipt shows completion time", /\d{4}[/.-]\d{1,2}[/.-]\d{1,2}/.test(receiptCompleted), receiptCompleted);
const frozen = await page.$$eval('[data-testid="receipt-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("receipt frozen order", JSON.stringify(frozen) === JSON.stringify(["105", "104", "103", "102", "101"]), JSON.stringify(frozen));
await page.screenshot({ path: `${SHOT}/04-receipt.png`, fullPage: true });

// ================================================================ reviewer (officer 2)
await page.evaluate(() => sessionStorage.clear());
await ctx.clearCookies();
const page2 = await ctx.newPage();
await login(page2, "reviewer");
await page2.fill('[data-testid="open-page-size"]', "2");
await page2.click('[data-testid="open-batch"]');
await page2.waitForSelector('[data-testid="batch-detail"]');
const bid2 = await page2.getAttribute('[data-testid="batch-detail"]', "data-batch-id");
await page2.click('[data-testid="claim-next"]');
await page2.waitForSelector('[data-testid="page-items"]');
let seq2 = await page2.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("officer2 first page reflects current book 106,105", JSON.stringify(seq2) === JSON.stringify(["106", "105"]), JSON.stringify(seq2));
const prog2 = await page2.textContent('[data-testid="progress"]');
await check("officer2 independent progress 2/6", prog2.includes("2/6"), prog2);
// officer1 batch untouched/completed
const opBatchRow = await page2.$(`tr[data-batch-id="${bid}"] td:nth-child(3)`);
const opProgress = opBatchRow ? await opBatchRow.textContent() : "";
await check("officer1 batch still 5/5 in shared list", opProgress.includes("5/5"), opProgress);

// ---- fault injection + original credential retry in UI
await page2.check('[data-testid="fault-toggle"]');
await page2.click('[data-testid="claim-next"]');
await page2.waitForFunction(() => {
  const n = document.querySelector('[data-testid="workspace-note"]');
  return n && n.textContent.includes("翻页失败");
}, { timeout: 8000 });
await page2.click('[data-testid="retry-credential"]');
await page2.waitForFunction(() => document.querySelector('[data-testid="workspace-note"]')?.textContent.includes("重放"));
seq2 = await page2.$$eval('[data-testid="page-items"] tbody tr', trs => trs.map(tr => tr.dataset.seq));
await check("post-fault retry returns same page 107,102", JSON.stringify(seq2) === JSON.stringify(["107", "102"]), JSON.stringify(seq2));
const prog2After = await page2.textContent('[data-testid="progress"]');
await check("post-fault progress exactly 4/6", prog2After.includes("4/6"), prog2After);
await page2.screenshot({ path: `${SHOT}/05-officer2-retry.png` });

console.log(`\nE2E ALL ${passed} CHECKS PASSED; batch ids ${bid}, ${bid2}`);
await browser.close();
