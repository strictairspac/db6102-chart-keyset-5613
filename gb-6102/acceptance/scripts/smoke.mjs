import { chromium } from "/tmp/pw/node_modules/playwright/index.mjs";
const EXE = "/home/node/.cache/ms-playwright/chromium_headless_shell-1187/chrome-linux/headless_shell";
const b = await chromium.launch({ executablePath: EXE, headless: true, chromiumSandbox: false,
  args: ["--no-sandbox", "--disable-dev-shm-usage"] });
const p = await b.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
p.on("pageerror", e => errors.push("pageerror: " + e.message));
p.on("console", m => { if (m.type() === "error" && !m.text().includes("favicon")) errors.push("console: " + m.text()); });

await p.goto("http://127.0.0.1:18251/", { waitUntil: "networkidle" });
await p.fill('input[name=username]', "operator");
await p.fill('input[name=password]', "Demo-DbWorkbench-2026");
await p.click('button[type=submit]');
await p.waitForSelector('[data-testid="handover-workspace"]');

await p.evaluate(() => { location.hash = "#cases"; });
await p.waitForSelector('[data-testid="errata-panel"]', { timeout: 8000 });
await p.waitForSelector("#case-form", { timeout: 8000 });
console.log("cases page: errata panel + case form present");
await p.screenshot({ path: "/tmp/gb6102_verify/shots/06-cases.png" });

await p.evaluate(() => { location.hash = "#runs"; });
await p.waitForSelector(".page", { timeout: 8000 });
await p.waitForTimeout(800);
const runsText = await p.textContent("#content");
if (!runsText.includes("翻页") && !runsText.includes("执行批次")) throw new Error("runs page content missing");
console.log("runs page renders");
await p.screenshot({ path: "/tmp/gb6102_verify/shots/07-runs.png" });

await p.evaluate(() => { location.hash = "#overview"; });
await p.waitForSelector('[data-testid="handover-workspace"]');
console.log("back to overview ok");

if (errors.length) { console.log("JS ERRORS:\n" + errors.slice(0, 10).join("\n")); process.exit(1); }
console.log("SMOKE OK: no frontend JS errors");
await b.close();
