// Layout probe for the dev Gitea: `node dev/probe.mjs` prints computed geometry and styles of key elements.
import { chromium } from "playwright";

const BASE = "http://localhost:3300";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

const box = (sel, props = []) =>
  page.evaluate(
    ([sel, props]) =>
      [...document.querySelectorAll(sel)].slice(0, 3).map((el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        const out = { sel, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), visible: s.display !== "none" && r.width > 0 };
        for (const p of props) out[p] = s.getPropertyValue(p);
        return out;
      }),
    [sel, props],
  );

const report = async (title, checks) => {
  console.log(`\n## ${title}`);
  for (const [sel, props] of checks) console.log(JSON.stringify(await box(sel, props)));
};

await page.goto(`${BASE}/user/login`);
await report("login", [
  ["#navbar", []],
  [".page-footer", []],
  [".rv-auth-card", []],
  [".rv-auth-mark .rv-mark", ["background-color"]],
  [".rv-auth-title", ["font-size", "color"]],
  ["#user_name", ["border-radius", "background-color", "height"]],
  [".rv-auth-submit", ["background-color", "color", "border-radius"]],
  [".rv-auth-row", []],
]);

await page.fill("#user_name", "revika");
await page.fill("#password", "wrong");
await page.click("form button.primary");
await page.waitForLoadState("load");
await report("login error", [[".flash-message", ["color", "background-color"]], [".field.error input", ["border-color"]]]);

await page.fill("#user_name", "revika");
await page.fill("#password", "revika-dev-pass");
await page.click("form button.primary");
await page.waitForURL((u) => !u.pathname.startsWith("/user/login"));

await page.goto(`${BASE}/revikalabs/web/issues`);
await report("issues", [
  ["#navbar", ["border-bottom-color", "height"]],
  ["#navbar-logo", []],
  ["#navbar-logo img", []],
  [".ui.secondary.pointing.menu .active.item", ["background-color", "border-radius", "color"]],
  [".labels-list .ui.label", ["background-color", "background-image", "border-radius", "box-shadow"]],
  [".labels-list .ui.label .gt-ellipsis", ["color"]],
  [".small-menu-items .item", ["border-radius"]],
  [".ui.primary.button", ["background-color", "color", "height"]],
]);
const dot = await page.evaluate(() => {
  const el = document.querySelector(".labels-list .ui.label");
  const s = getComputedStyle(el, "::before");
  return { content: s.content, w: s.width, bg: s.backgroundColor };
});
console.log("label ::before", JSON.stringify(dot));

await browser.close();
