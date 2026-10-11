import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const index = await readFile(new URL("../frontend/index.html", import.meta.url), "utf8");
const script = await readFile(new URL("../frontend/viewer.js", import.meta.url), "utf8");

async function makeViewer(list, details = {}) {
  const dom = new JSDOM(index, { url: "http://localhost/viewer", runScripts: "outside-only" });
  dom.window.__ARTIFACT_VIEWER_DISABLE_AUTO_INIT__ = true;
  dom.window.eval(script);
  const calls = [];
  const fetcher = async (path) => {
    calls.push(path);
    if (path === "/api/artifacts") return { ok: true, json: async () => list };
    const id = path.slice("/api/artifacts/".length);
    return details[id]
      ? { ok: true, json: async () => details[id] }
      : { ok: false, json: async () => ({}) };
  };
  await dom.window.ArtifactViewer.init(fetcher);
  return { dom, calls };
}

test("empty state is shown when there is no selected saved artifact", async () => {
  const { dom } = await makeViewer([]);
  assert.equal(dom.window.document.getElementById("empty-state").hidden, false);
  assert.equal(dom.window.document.getElementById("artifact-panel").hidden, true);
  assert.match(dom.window.document.getElementById("empty-state").textContent, /No artifact selected/);
  dom.window.close();
});

test("Markdown preview renders safe headings, lists, links, and code", async () => {
  const detail = {
    id: "m1", title: "Markdown example", format: "markdown", content: "# Heading",
    rendered_html: "<h1>Heading</h1><ul><li>Item</li></ul><p><a href=\"https://example.test\">Link</a></p><pre><code>print(1)</code></pre>",
  };
  const { dom } = await makeViewer([{ id: "m1", title: detail.title, format: detail.format }], { m1: detail });
  const { document } = dom.window;
  document.getElementById("artifact-select").value = "m1";
  document.getElementById("artifact-select").dispatchEvent(new dom.window.Event("change"));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const preview = document.getElementById("markdown-preview");
  assert.equal(preview.querySelector("h1")?.textContent, "Heading");
  assert.equal(preview.querySelector("li")?.textContent, "Item");
  assert.equal(preview.querySelector("a")?.href, "https://example.test/");
  assert.equal(preview.querySelector("pre code")?.textContent, "print(1)");
  dom.window.close();
});

test("source and preview controls switch views and source is text-only", async () => {
  const detail = {
    id: "m2", title: "Source toggle", format: "markdown", content: "<img src=x onerror=alert(1)>", rendered_html: "&lt;img src=x onerror=alert(1)&gt;",
  };
  const { dom } = await makeViewer([{ id: "m2", title: detail.title, format: detail.format }], { m2: detail });
  const { document } = dom.window;
  document.getElementById("artifact-select").value = "m2";
  document.getElementById("artifact-select").dispatchEvent(new dom.window.Event("change"));
  await new Promise((resolve) => setTimeout(resolve, 0));
  document.getElementById("source-button").click();
  assert.equal(document.getElementById("source-view").hidden, false);
  assert.equal(document.getElementById("preview-view").hidden, true);
  assert.equal(document.querySelector("#source-code img"), null);
  assert.equal(document.getElementById("source-code").textContent, detail.content);
  document.getElementById("preview-button").click();
  assert.equal(document.getElementById("preview-view").hidden, false);
  assert.equal(document.getElementById("source-view").hidden, true);
  dom.window.close();
});

test("HTML preview uses an empty sandbox and restrictive CSP without script or same-origin grants", async () => {
  const { dom } = await makeViewer([]);
  await dom.window.ArtifactViewer.loadArtifact("sample:html");
  const frame = dom.window.document.getElementById("html-preview");
  const srcdoc = frame.srcdoc;
  assert.equal(frame.getAttribute("sandbox"), "");
  assert.match(srcdoc, /Content-Security-Policy/);
  assert.match(srcdoc, /script-src 'none'/);
  assert.match(srcdoc, /connect-src 'none'/);
  assert.doesNotMatch(frame.getAttribute("sandbox"), /allow-scripts|allow-same-origin/);
  assert.match(srcdoc, /parent\.__artifactViewerPwned = true/);
  assert.equal(dom.window.__artifactViewerPwned, undefined);
  dom.window.close();
});
