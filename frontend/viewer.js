(() => {
  const STRICT_CSP = "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'; frame-src 'none'";
  const samples = {
    markdown: {
      id: "sample:markdown", title: "A Useful Customer Interview", format: "markdown", sample: true,
      content: "# A Useful Customer Interview\n\nA good interview starts with a **recent behavior**, not a hypothetical promise.\n\n## Three questions to try\n\n- Tell me about the last time you tried to solve this.\n- What did you do next?\n- What was frustrating or surprisingly easy?\n\nRead more at [the project API docs](/docs).\n\n```text\nAsk about the past. Listen for workarounds.\n```",
      rendered_html: "<h1>A Useful Customer Interview</h1>\n<p>A good interview starts with a <strong>recent behavior</strong>, not a hypothetical promise.</p>\n<h2>Three questions to try</h2>\n<ul>\n<li>Tell me about the last time you tried to solve this.</li>\n<li>What did you do next?</li>\n<li>What was frustrating or surprisingly easy?</li>\n</ul>\n<p>Read more at <a href=\"/docs\">the project API docs</a>.</p>\n<pre><code class=\"language-text\">Ask about the past. Listen for workarounds.\n</code></pre>"
    },
    html: {
      id: "sample:html", title: "Sandbox and CSS Preview Check", format: "html", sample: true,
      content: "<style>body{font:16px system-ui;margin:2rem;color:#183d25} .card{padding:1.5rem;border:1px solid #ccd6cd;border-radius:12px}</style><main class=\"card\"><h1>HTML and CSS preview</h1><p>This document is rendered in an isolated frame.</p><button onclick=\"parent.__artifactViewerPwned = true\">Script test button</button></main><script>parent.__artifactViewerPwned = true; document.body.dataset.script = 'ran';</script><img src=x onerror=\"parent.__artifactViewerPwned = true\">"
    }
  };

  let fetcher = (...args) => window.fetch(...args);
  let current = null;
  let mode = "preview";
  let initialized = false;

  const el = (id) => document.getElementById(id);
  const ui = () => ({
    select: el("artifact-select"), empty: el("empty-state"), panel: el("artifact-panel"),
    error: el("error-state"), title: el("artifact-title"), badge: el("artifact-badge"),
    meta: el("artifact-meta"), markdown: el("markdown-preview"), iframe: el("html-preview"),
    source: el("source-view"), code: el("source-code"), preview: el("preview-view"),
    previewButton: el("preview-button"), sourceButton: el("source-button")
  });

  function sandboxDocument(artifact) {
    const body = artifact.format === "css"
      ? `<style>${artifact.content.replace(/</g, "\\3C ")}</style><main><h1>CSS artifact preview</h1><p>Sample content styled by the artifact's CSS.</p></main>`
      : artifact.content;
    return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${STRICT_CSP}"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>${body}</body></html>`;
  }

  function setMode(nextMode) {
    mode = nextMode;
    render();
  }

  function render() {
    const refs = ui();
    const hasArtifact = Boolean(current);
    refs.empty.hidden = hasArtifact;
    refs.panel.hidden = !hasArtifact;
    refs.error.hidden = true;
    if (!hasArtifact) return;

    refs.title.textContent = current.title;
    refs.meta.textContent = `${current.format.toUpperCase()}${current.sample ? " · local sample, not saved" : " · saved artifact"}`;
    refs.badge.textContent = current.sample ? "SAMPLE" : current.format.toUpperCase();
    refs.badge.hidden = !current.sample;
    refs.previewButton.setAttribute("aria-pressed", String(mode === "preview"));
    refs.sourceButton.setAttribute("aria-pressed", String(mode === "source"));
    refs.source.hidden = mode !== "source";
    refs.preview.hidden = mode !== "preview";
    refs.code.textContent = current.content;

    const isMarkup = current.format === "html" || current.format === "css";
    refs.markdown.hidden = isMarkup || mode !== "preview";
    refs.iframe.hidden = !isMarkup || mode !== "preview";
    if (isMarkup && mode === "preview") {
      refs.iframe.setAttribute("sandbox", "");
      refs.iframe.srcdoc = sandboxDocument(current);
    } else if (!isMarkup && mode === "preview") {
      // Only server-rendered, allowlist-sanitized CommonMark reaches innerHTML.
      refs.markdown.innerHTML = current.rendered_html || "";
    }
  }

  async function loadArtifact(id) {
    if (id.startsWith("sample:")) {
      current = { ...samples[id.slice("sample:".length)] };
      mode = "preview";
      render();
      return;
    }
    if (!id) {
      current = null;
      render();
      return;
    }
    const response = await fetcher(`/api/artifacts/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("Could not load this artifact.");
    current = await response.json();
    mode = "preview";
    render();
  }

  async function refresh() {
    const refs = ui();
    refs.error.hidden = true;
    try {
      const response = await fetcher("/api/artifacts");
      if (!response.ok) throw new Error("Could not load saved artifacts.");
      const artifacts = await response.json();
      refs.select.replaceChildren(new Option("Choose an artifact", ""));
      for (const item of artifacts) refs.select.add(new Option(`${item.title} (${item.format})`, item.id));
      refs.select.value = "";
      current = null;
      render();
    } catch (error) {
      current = null;
      render();
      refs.error.textContent = error.message || "Could not load artifacts.";
      refs.error.hidden = false;
    }
  }

  async function init(customFetch) {
    if (customFetch) fetcher = customFetch;
    if (!initialized) {
      el("refresh-button").addEventListener("click", refresh);
      ui().select.addEventListener("change", async (event) => {
        try { await loadArtifact(event.target.value); }
        catch (error) { ui().error.textContent = error.message; ui().error.hidden = false; }
      });
      el("preview-button").addEventListener("click", () => setMode("preview"));
      el("source-button").addEventListener("click", () => setMode("source"));
      el("sample-markdown").addEventListener("click", () => loadArtifact("sample:markdown"));
      el("sample-html").addEventListener("click", () => loadArtifact("sample:html"));
      el("empty-sample-markdown").addEventListener("click", () => loadArtifact("sample:markdown"));
      el("empty-sample-html").addEventListener("click", () => loadArtifact("sample:html"));
      initialized = true;
    }
    await refresh();
  }

  window.ArtifactViewer = { init, refresh, loadArtifact, setMode, sandboxDocument, strictCsp: STRICT_CSP };
  if (!window.__ARTIFACT_VIEWER_DISABLE_AUTO_INIT__) {
    const start = () => init().catch((error) => {
      const errorState = el("error-state");
      errorState.textContent = error.message || "Could not load artifacts.";
      errorState.hidden = false;
    });
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
    else queueMicrotask(start);
  }
})();
