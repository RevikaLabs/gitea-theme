// Layout and contrast audit over the main pages: `SCHEME=light node dev/audit.mjs`.
// Reports horizontal overflow, header/content edge mismatch, radii and button heights outside
// the system, and text below WCAG AA contrast against its effective background.
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";

const BASE = "http://localhost:3300";
const scheme = process.env.SCHEME || "dark";
const PAGES = [
  "/", "/explore/repos", "/revika", "/revikalabs",
  "/revikalabs/web", "/revikalabs/infra/src/branch/main/README.md", "/revikalabs/web/commits/branch/main",
  "/revikalabs/web/issues", "/revikalabs/web/issues/1", "/revikalabs/web/pulls",
  "/revikalabs/web/pulls/11", "/revikalabs/web/pulls/11/files", "/revikalabs/web/projects/1",
  "/revikalabs/web/milestones", "/revikalabs/web/labels", "/revikalabs/web/branches",
  "/revikalabs/api/activity", "/revikalabs/web/settings", "/user/settings", "/repo/create",
  "/explore/users", "/explore/organizations", "/revikalabs/-/projects", "/revika?tab=stars",
  "/revikalabs/web/releases", "/revikalabs/web/wiki", "/revikalabs/web/actions",
  "/revikalabs/web/compare/main...main", "/notifications", "/user/settings/appearance", "/-/admin",
];

const browser = await chromium.launch();
let issues = 0;
for (const width of [1024, 1440]) {
  const ctx = await browser.newContext({ viewport: { width, height: 900 } });
  if (scheme !== "dark") {
    await ctx.route("**/theme-revika-dark.css*", (r) =>
      r.fulfill({ path: fileURLToPath(new URL(`../dist/theme-revika-${scheme}.css`, import.meta.url)) }));
  }
  const page = await ctx.newPage();
  await page.goto(`${BASE}/user/login`);
  await page.fill("#user_name", "revika");
  await page.fill("#password", "revika-dev-pass");
  await page.click("form button.primary");
  await page.waitForURL((u) => !u.pathname.startsWith("/user/login"));
  // The served page follows the account theme (shots.mjs may have left it on another scheme),
  // so pin it before auditing; the CSS route above is only a fallback for stale caches.
  const csrf = await page.evaluate(() => document.querySelector('meta[name="_csrf"]')?.content);
  await page.request.post(`${BASE}/user/settings/appearance/theme`, { form: { _csrf: csrf, theme: `revika-${scheme}` } });
  await page.reload({ waitUntil: "load" });
  const served = await page.evaluate(
    (name) =>
      [...document.querySelectorAll("link[rel=stylesheet], style")].some((el) =>
        (el.href || el.textContent || "").includes(`theme-revika-${name}.css`),
      ),
    scheme,
  );
  if (!served) throw new Error(`theme revika-${scheme} is not served; check that the theme exists`);

  for (const path of PAGES) {
    await page.goto(BASE + path, { waitUntil: "load" });
    // Audit the expanded state too: open every <details> (merge instructions, settings groups).
    // Click the summary like a user would; setting .open directly can leave a stale layout box.
    for (const s of await page.locator("details:not([open]) > summary:visible").all()) await s.click().catch(() => {});
    await page.waitForTimeout(300);
    const r = await page.evaluate(() => {
      const visible = (e) => e.offsetParent !== null && e.getBoundingClientRect().width > 0;
      const name = (e) => `${e.tagName.toLowerCase()}.${[...e.classList].slice(0, 3).join(".")}`;
      const out = { overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth, radius: new Set(), height: new Set(), contrast: new Set() };

      const head = document.querySelector(".secondary-nav .repo-header");
      const content = document.querySelector(".page-content > .ui.container:not(.secondary-nav *)");
      if (head && content && visible(head)) {
        const d = Math.round(head.getBoundingClientRect().left - content.getBoundingClientRect().left);
        if (d) out.edge = d;
      }

      const ok = new Set(["0px", "6px", "8px", "12px", "50%", "99999px", "7000px"]);
      for (const e of document.querySelectorAll(".ui.button, .ui.label, .ui.menu .item, .ui.segment, input:not([type=checkbox], [type=radio], [type=hidden])")) {
        if (!visible(e)) continue;
        const s = getComputedStyle(e);
        const rs = [s.borderTopLeftRadius, s.borderTopRightRadius, s.borderBottomRightRadius, s.borderBottomLeftRadius];
        if (rs.some((x) => !ok.has(x))) out.radius.add(`${name(e)} ${rs.join("/")}`);
      }
      for (const e of document.querySelectorAll(".ui.button")) {
        if (!visible(e) || e.matches(".add-code-comment, .ellipsis-button")) continue;
        if (Number(getComputedStyle(e).opacity) === 0) continue;
        const h = Math.round(e.getBoundingClientRect().height);
        if (![28, 32, 44].includes(h)) out.height.add(`${name(e)} h=${h}`);
      }

      // Collisions: controls/blocks that overlap or touch (gap < 2px) without being one group.
      out.collide = new Set();
      const boxes = [...document.querySelectorAll(".page-content :is(.ui.button, .ui.label, .ui.input, .ui.selection.dropdown, img.avatar, .ui.segment, .ui.message, overflow-menu, .ui.menu, h1, h2, h3, .ui.header, .issue-card)")]
        // Hover-only gutter buttons (add-code-comment) sit over the line number by design.
        .filter((e) => visible(e) && !e.matches(".add-code-comment") && !e.closest(".ui.buttons, .ui.action.input, .ui.labeled.button, .menu .menu, .tippy-box, .tw-hidden, details:not([open]) > :not(summary)"))
        .map((e) => ({ e, r: e.getBoundingClientRect() }));
      for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
          const a = boxes[i], b = boxes[j];
          if (a.e.contains(b.e) || b.e.contains(a.e)) continue;
          const ox = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
          const oy = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
          // Attached stacks (header + segment + table, diff header + body) are one card and may share a 1px seam.
          const stack = ".attached, .diff-file-header, .diff-file-body, .collapsible-comment-box, .collapsible-comment-box ~ .segment";
          if (a.e.closest(stack) && b.e.closest(stack) && Math.min(ox, oy) <= 1) continue;
          if (ox > 2 && oy > 2) out.collide.add(`overlap ${name(a.e)} × ${name(b.e)}`);
          else if ((ox > 8 && oy > -2 && oy <= 0) || (oy > 8 && ox > -2 && ox <= 0)) out.collide.add(`touch ${name(a.e)} × ${name(b.e)}`);
        }
      }

      const rgb = (c) => { const m = c.match(/[\d.]+/g); return m ? m.map(Number) : null; };
      const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
      const bgOf = (e) => {
        const layers = [];
        for (let n = e; n; n = n.parentElement) {
          const c = rgb(getComputedStyle(n).backgroundColor);
          if (c && (c[3] ?? 1) > 0) { layers.push(c); if ((c[3] ?? 1) >= 1) break; }
        }
        // Body may be transparent with the canvas painted on <html>; fall back to it, then to white.
        const rootBg = [document.body, document.documentElement].map((n) => rgb(getComputedStyle(n).backgroundColor)).find((c) => c && (c[3] ?? 1) > 0);
        let base = (rootBg || [255, 255, 255]).slice(0, 3);
        for (const c of layers.reverse()) { const a = c[3] ?? 1; base = base.map((v, i) => v * (1 - a) + c[i] * a); }
        return base;
      };
      const walker = document.createTreeWalker(document.querySelector(".page-content") || document.body, NodeFilter.SHOW_TEXT);
      const seen = new Set();
      while (walker.nextNode()) {
        const el = walker.currentNode.parentElement;
        if (!el || seen.has(el) || !walker.currentNode.textContent.trim() || !visible(el)) continue;
        seen.add(el);
        const s = getComputedStyle(el);
        // Placeholder-like text (.default.text of dropdowns) follows the 3:1 placeholder budget, not body text.
        if (s.visibility === "hidden" || Number(s.opacity) < 1 || el.closest("[disabled], .disabled, .code-diff, .chroma, pre, code, .ui.label[style], .default.text, kbd")) continue;
        const fg = rgb(s.color); if (!fg) continue;
        const bg = bgOf(el); const a = fg[3] ?? 1;
        const f = fg.slice(0, 3).map((v, i) => v * a + bg[i] * (1 - a));
        const [l1, l2] = [lum(f), lum(bg)].sort((x, y) => y - x);
        const ratio = (l1 + 0.05) / (l2 + 0.05);
        // WCAG large text: >=24px in any weight, or >=18.66px bold (weight >= 700).
        const large = parseFloat(s.fontSize) >= 24 || (parseFloat(s.fontSize) >= 18.66 && Number(s.fontWeight) >= 700);
        if (ratio < (large ? 3 : 4.5)) out.contrast.add(`${name(el)} ${ratio.toFixed(2)}`);
      }
      return { ...out, radius: [...out.radius].slice(0, 6), height: [...out.height].slice(0, 6), contrast: [...out.contrast].slice(0, 8), collide: [...out.collide].slice(0, 10) };
    });
    const bad = r.overflow || r.edge || r.radius.length || r.height.length || r.contrast.length || r.collide.length;
    if (bad) { issues++; console.log(`## ${scheme} ${width} ${path}`, JSON.stringify(r)); }
  }
  await ctx.close();
}
await browser.close();
console.log(issues ? `${issues} page(s) with findings` : "clean");
