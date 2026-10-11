import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import test from "node:test";
import { chromium } from "playwright-core";

const chromePath = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
const viewerUrl = process.env.ARTIFACT_VIEWER_URL || "http://127.0.0.1:8000/viewer";

test("real Chromium renders both previews and blocks malicious HTML from the parent", { skip: !existsSync(chromePath) }, async () => {
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  try {
    const page = await browser.newPage();
    await page.goto(viewerUrl);
    await page.waitForFunction(() => window.ArtifactViewer && document.querySelector("#empty-state"));
    await page.getByRole("button", { name: "Try Markdown sample" }).click();
    assert.equal(await page.locator("#markdown-preview h1").textContent(), "A Useful Customer Interview");
    assert.equal(await page.locator("#markdown-preview li").count(), 3);
    await page.getByRole("button", { name: "Source", exact: true }).click();
    assert.match(await page.locator("#source-code").textContent(), /A Useful Customer Interview/);
    await page.getByRole("button", { name: "Preview", exact: true }).click();

    await page.getByRole("button", { name: "Try HTML/CSS sample" }).click();
    const frame = page.frameLocator("#html-preview");
    assert.equal(await frame.locator("h1").textContent(), "HTML and CSS preview");
    assert.equal(await frame.locator(".card").evaluate((node) => getComputedStyle(node).borderRadius), "12px");
    await frame.getByRole("button", { name: "Script test button" }).click();
    assert.equal(await page.evaluate(() => window.__artifactViewerPwned), undefined);
    assert.equal(await frame.locator("body").evaluate(() => {
      try { return window.parent.document.title; }
      catch { return "blocked"; }
    }), "blocked");
    assert.equal(await page.locator("#html-preview").getAttribute("sandbox"), "");
    const srcdoc = await page.locator("#html-preview").getAttribute("srcdoc");
    assert.match(srcdoc, /script-src 'none'/);
    assert.doesNotMatch(await page.locator("#html-preview").getAttribute("sandbox"), /allow-scripts|allow-same-origin/);
  } finally {
    await browser.close();
  }
});
