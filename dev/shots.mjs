// Logs in to the dev Gitea and screenshots key pages: `node dev/shots.mjs [name...]`.
// Paths assume a freshly seeded instance (dev/seed.py): PR #11, project 1.
// "login" covers both sign-in shots, "twofa" covers the 2FA challenge pair; "branch-menu"
// and "pr-sidebar" are open-dropdown states of repo-home and pr.
import { chromium } from "playwright";
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createHmac } from "node:crypto";

const BASE = "http://localhost:3300";
const PAGES = {
  dashboard: "/",
  "repo-home": "/revikalabs/web",
  issues: "/revikalabs/web/issues",
  issue: "/revikalabs/web/issues/1",
  pulls: "/revikalabs/web/pulls",
  pr: "/revikalabs/web/pulls/11",
  "pr-files": "/revikalabs/web/pulls/11/files",
  project: "/revikalabs/web/projects/1",
  org: "/revikalabs",
  settings: "/user/settings/appearance",
};

// SCHEME=light swaps the served theme file, so screenshots don't depend on the user's theme setting.
const scheme = process.env.SCHEME || "dark";
const only = process.argv.slice(2);
const out = fileURLToPath(new URL(scheme === "dark" ? "../shots/" : `../shots/${scheme}/`, import.meta.url));
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
if (scheme !== "dark") {
  await ctx.route("**/theme-revika-dark.css*", (route) =>
    route.fulfill({ path: fileURLToPath(new URL(`../dist/theme-revika-${scheme}.css`, import.meta.url)) }),
  );
}
const page = await ctx.newPage();

async function getCsrf(p) {
  return p.evaluate(() => {
    const meta = document.querySelector('meta[name="_csrf"]');
    return meta ? meta.content : document.querySelector("input[name=_csrf]")?.value;
  });
}

if (!only.length || only.includes("login")) {
  await page.goto(`${BASE}/user/login`);
  await page.screenshot({ path: `${out}login.png` });
  await page.fill("#user_name", "revika");
  await page.fill("#password", "wrong-password");
  await page.click("form button.primary");
  await page.waitForLoadState("load");
  await page.screenshot({ path: `${out}login-error.png` });
  console.log(`${out}login.png\n${out}login-error.png`);
}

// SCHEME!=dark only swaps the CSS file: the served page still follows the user theme, so
// pin the account theme to match the scheme being captured.
await page.goto(`${BASE}/user/login`);
await page.fill("#user_name", "revika");
await page.fill("#password", "revika-dev-pass");
await page.click("form button.primary");
await page.waitForURL((u) => !u.pathname.startsWith("/user/login"));
await page.request.post(`${BASE}/user/settings/appearance/theme`, { form: { _csrf: await getCsrf(page), theme: `revika-${scheme}` } });
await page.goto(`${BASE}/user/settings/appearance`);
const served = await page.evaluate(
  (name) =>
    [...document.querySelectorAll("link[rel=stylesheet], style")].some((el) =>
      (el.href || el.textContent || "").includes(`theme-revika-${name}.css`),
    ),
  scheme,
);
if (!served) throw new Error(`theme revika-${scheme} is not served; check that the theme exists`);

for (const [name, path] of Object.entries(PAGES)) {
  if (only.length && !only.includes(name)) continue;
  await page.goto(BASE + path, { waitUntil: "load" });
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}${name}.png` });
  console.log(`${out}${name}.png`);
}

if (!only.length || only.includes("branch-menu")) {
  await page.goto(`${BASE}/revikalabs/web`, { waitUntil: "load" });
  await page.click(".branch-dropdown-button");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}branch-menu.png` });
  console.log(`${out}branch-menu.png`);
}

if (!only.length || only.includes("pr-sidebar")) {
  await page.goto(`${BASE}/revikalabs/web/pulls/11`, { waitUntil: "load" });
  await page.click(".issue-content-right .ui.dropdown.full-width");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}pr-sidebar.png` });
  console.log(`${out}pr-sidebar.png`);
}

// 2FA: enroll a seed user (idempotent - re-runs skip the enroll page), then
// capture the TOTP challenge and its scratch-code variant from a fresh session.
if (!only.length || only.includes("twofa")) {
  const b32 = (s) => {
    const A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    let bits = 0, value = 0;
    const bytes = [];
    for (const c of s.replace(/=+$/, "").toUpperCase()) {
      const i = A.indexOf(c);
      if (i < 0) continue;
      value = (value << 5) | i;
      bits += 5;
      if (bits >= 8) {
        bytes.push((value >>> (bits - 8)) & 255);
        bits -= 8;
      }
    }
    return new Uint8Array(bytes);
  };
  const totp = (secret) => {
    const counter = Buffer.alloc(8);
    counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
    const mac = createHmac("sha1", b32(secret)).update(counter).digest();
    const off = mac[mac.length - 1] & 15;
    const num = ((mac[off] & 127) << 24) | (mac[off + 1] << 16) | (mac[off + 2] << 8) | mac[off + 3];
    return String(num % 1_000_000).padStart(6, "0");
  };
  const login = async (user) => {
    await ctx.clearCookies();
    await page.goto(`${BASE}/user/login`);
    await page.fill("#user_name", user);
    await page.fill("#password", "revika-dev-pass");
    await page.click("form button.primary");
    await page.waitForURL((u) => !u.pathname.startsWith("/user/login"));
  };
  await login("andreas");
  await page.goto(`${BASE}/user/settings/security/two_factor/enroll`, { waitUntil: "load" });
  if (page.url().endsWith("/enroll")) {
    const secret = await page.getAttribute("img[alt]", "alt");
    await page.fill("#passcode", totp(secret));
    await page.click("form button.primary");
    await page.waitForLoadState("load");
  }
  await login("andreas");
  await page.screenshot({ path: `${out}twofa.png` });
  await page.goto(`${BASE}/user/two_factor/scratch`);
  await page.waitForTimeout(300);
  await page.screenshot({ path: `${out}twofa-scratch.png` });
  console.log(`${out}twofa.png\n${out}twofa-scratch.png`);
}

await browser.close();
