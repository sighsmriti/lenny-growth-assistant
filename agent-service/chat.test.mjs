import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { JSDOM } from "jsdom";

const html = await readFile(new URL("../frontend/chat.html", import.meta.url), "utf8");
const script = await readFile(new URL("../frontend/chat.js", import.meta.url), "utf8");

async function makeChat(fetcher) {
  const dom = new JSDOM(html, { url: "http://localhost/", runScripts: "outside-only" });
  dom.window.__GROWTH_CHAT_DISABLE_AUTO_INIT__ = true;
  dom.window.eval(script);
  dom.window.GrowthChat.init(fetcher);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return dom;
}

function response(data, ok = true, status = 200) { return { ok, status, json: async () => data }; }

test("loads provider configuration and existing saved session history", async () => {
  const calls = [];
  const dom = await makeChat(async (url) => {
    calls.push(url);
    if (url === "/api/config") return response({ llm: { provider: "ollama", model: "qwen2.5:3b", ready: true } });
    if (url === "/api/sessions") return response([{ id: "session-1" }]);
    if (url.endsWith("/messages")) return response([{ role: "user", content: "Retention" }, { role: "assistant", content: "A grounded answer." }]);
    throw new Error(`Unexpected request ${url}`);
  });
  assert.match(dom.window.document.getElementById("model-status").textContent, /ollama · qwen2.5:3b/);
  assert.equal(dom.window.document.querySelectorAll(".message").length, 2);
  assert.equal(dom.window.document.querySelector(".session-item.active").dataset.sessionId, "session-1");
  assert.ok(calls.includes("/api/config"));
  dom.window.close();
});

test("new session and chat use the actual API payloads and show citations", async () => {
  const calls = [];
  let created = false;
  const dom = await makeChat(async (url, options = {}) => {
    calls.push({ url, options });
    if (url === "/api/config") return response({ llm: { provider: "openai", model: "gpt-4o-mini", ready: true } });
    if (url === "/api/sessions" && options.method === "POST") { created = true; return response({ id: "session-2" }); }
    if (url === "/api/sessions") return response(created ? [{ id: "session-2" }] : []);
    if (url === "/api/sessions/session-2/messages") return response(created && calls.some((call) => call.url === "/api/chat")
      ? [{ role: "user", content: "Retention" }, { role: "assistant", content: "Use cohorts." }]
      : []);
    if (url === "/api/chat") return response({ reply: "Use cohorts.", provider: "openai", model: "gpt-4o-mini", citations: [{ title: "Retention transcript", excerpt: "Compare retained users.", url: "https://example.test/source" }] });
    throw new Error(`Unexpected request ${url}`);
  });
  dom.window.document.getElementById("new-chat").click();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const input = dom.window.document.getElementById("message-input");
  input.value = "Retention";
  dom.window.document.getElementById("composer").dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const chatCall = calls.find((call) => call.url === "/api/chat");
  assert.equal(chatCall.options.method, "POST");
  assert.deepEqual(JSON.parse(chatCall.options.body), { session_id: "session-2", message: "Retention" });
  assert.match(dom.window.document.getElementById("model-status").textContent, /openai · gpt-4o-mini/);
  assert.equal(dom.window.document.querySelector(".citations summary")?.textContent, "Sources · 1");
  assert.equal(dom.window.document.querySelector(".citations a")?.href, "https://example.test/source");
  dom.window.close();
});

test("API errors are displayed as readable alerts", async () => {
  const dom = await makeChat(async (url) => url === "/api/config"
    ? response({ llm: { provider: "openai", model: "gpt-4o-mini", ready: false } })
    : url === "/api/sessions" ? response({ detail: "Database is unavailable" }, false, 503)
      : response([]));
  assert.equal(dom.window.document.getElementById("model-status").textContent, "openai · gpt-4o-mini · API key required");
  assert.match(dom.window.document.getElementById("request-error").textContent, /Database is unavailable/);
  dom.window.close();
});

test("unsupported answers get an explicit state without losing the response", async () => {
  let calls = 0;
  const dom = await makeChat(async (url, options = {}) => {
    if (url === "/api/config") return response({ llm: { provider: "ollama", model: "qwen2.5:3b", ready: true } });
    if (url === "/api/sessions" && options.method === "POST") return response({ id: "session-3" });
    if (url === "/api/sessions") return response([{ id: "session-3" }]);
    if (url.endsWith("/messages")) return response(calls ? [
      { role: "user", content: "A question outside the corpus" },
      { role: "assistant", content: "The available transcripts do not support an answer to this question." },
    ] : []);
    if (url === "/api/chat") { calls++; return response({ reply: "The available transcripts do not support an answer to this question.", citations: [] }); }
    throw new Error(`Unexpected request ${url}`);
  });
  await dom.window.GrowthChat.newSession();
  dom.window.document.getElementById("message-input").value = "A question outside the corpus";
  await dom.window.GrowthChat.sendMessage({ preventDefault() {} });
  assert.equal(dom.window.document.getElementById("unsupported-note").hidden, false);
  assert.match(dom.window.document.querySelector(".message.assistant .message-content").textContent, /do not support an answer/);
  dom.window.close();
});

test("essay action calls the existing Pi skill endpoint and opens the saved artifact", async () => {
  let submitted;
  let opened;
  const dom = await makeChat(async (url, options = {}) => {
    if (url === "/api/config") return response({ llm: { provider: "ollama", model: "qwen2.5:3b", ready: true } });
    if (url === "/api/sessions") return response([]);
    if (url === "/api/agent/skills/ship-30-for-30-essay/run") { submitted = JSON.parse(options.body); return response({ artifact_id: "artifact-1", reply: "Essay" }); }
    throw new Error(`Unexpected request ${url}`);
  });
  dom.window.prompt = () => "An essay about retention";
  dom.window.document.getElementById("artifact-frame").contentWindow.ArtifactViewer = { showArtifact: async (id) => { opened = id; } };
  await dom.window.GrowthChat.generateEssay();
  assert.deepEqual(submitted, { task: "An essay about retention" });
  assert.equal(opened, "artifact-1");
  dom.window.close();
});
