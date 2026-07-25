// Dev-only: screenshot the preview dashboard built by scripts/dash_preview.py.
//   node scripts/dash_shot.mjs <dashboard.html> <out-prefix> [--dark] [--expand]
import {chromium} from "playwright";

const [file, prefix, ...flags] = process.argv.slice(2);
const dark = flags.includes("--dark");
const expand = flags.includes("--expand");

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: {width: 420, height: 900},
  deviceScaleFactor: 2,
  colorScheme: dark ? "dark" : "light",
});
page.on("console", m => {
  if (m.type() === "error") console.error("[console]", m.text());
});
page.on("pageerror", e => console.error("[pageerror]", e.message));
await page.goto("file://" + file);
// render() replaces the "טוען…" placeholder with real cards
await page.waitForFunction(
  () => document.querySelectorAll("#dash .card, #dash .dtab").length > 0,
  null, {timeout: 15000});
await page.waitForTimeout(400);
const tab = (flags.find(f => f.startsWith("--tab=")) || "").slice(6);
if (tab) {
  await page.click(`[data-tab="${tab}"]`);
  await page.waitForTimeout(300);
}
if (expand) {
  await page.evaluate(() => {
    document.querySelectorAll("details").forEach(d => (d.open = true));
  });
  await page.waitForTimeout(300);
}
// The bottom nav is position:fixed, so in a fullPage capture it paints once
// over the middle of the tall image. Drop it for the screenshot -- body
// already reserves its height, so nothing reflows.
if (flags.includes("--nonav")) {
  await page.evaluate(() => {
    const n = document.getElementById("gnav");
    if (n) n.remove();
  });
}
const sel = (flags.find(f => f.startsWith("--sel=")) || "").slice(6);
if (sel) {
  await page.locator(sel).first().screenshot({path: `${prefix}.png`});
} else {
  await page.screenshot({path: `${prefix}.png`, fullPage: true});
}
console.log(`${prefix}.png`);
await browser.close();
