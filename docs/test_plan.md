# Manual UI and API test plan

This plan is for a local evaluation run. It exercises the API-backed session and agent flows through `/docs` because the repository currently has no integrated chat UI. The artifact viewer is available at `/viewer`.

## Preconditions

- Start PostgreSQL, FastAPI, and Ollama with `qwen2.5:3b` for local inference.
- Add and index at least one transcript Markdown file whose title, guest, source URL and content are known to the tester.
- For the essay flow, install the `agent-service` dependencies and have Node.js available.
- Open FastAPI Swagger at `http://127.0.0.1:8000/docs` and the artifact viewer at `http://127.0.0.1:8000/viewer`.
- Optional cloud checks need a valid OpenAI key set in the shell before starting FastAPI. Never paste a real key into a screenshot or saved report.

## 1. Chat sessions and persistence

1. In Swagger, call `POST /api/sessions` twice and record the two returned IDs.
2. Send a message to the first ID with `POST /api/chat`; send a different message to the second ID.
3. Call `GET /api/sessions` and `GET /api/sessions/{session_id}/messages` for both IDs.
4. Restart FastAPI and read both sessions again.

**Expected:** Each session has its own ID and timestamps; messages remain associated with the submitted session; messages survive an API restart because they are stored in PostgreSQL. An unknown session ID returns 404. The current product does not present these flows in a chat page.

## 2. Grounded answer and citations

1. Ask a question whose answer is plainly contained in the indexed transcript.
2. Inspect `reply` and every element of `citations` in the response.
3. Compare a returned excerpt with the known source Markdown file and check title, filename, source identity, URL (when supplied), guest and chunk index.

**Expected:** The cited excerpt comes from the indexed transcript. The selected provider/model are included in the response. A citation is evidence returned by retrieval; manually confirm it supports the generated claim.

## 3. Unsupported question

1. Ask a question unrelated to the indexed collection.
2. Inspect the response and session messages.

**Expected:** When retrieval finds no passage above the configured threshold, the API returns the unsupported-answer text and an empty `citations` array. It does not need to call the model for this response, and both user and assistant messages are persisted.

## 4. Provider selection and error handling

1. With default settings, call `GET /api/config`; confirm provider `ollama`, model `qwen2.5:3b` (unless overridden), and `ready: true`.
2. Set `LLM_PROVIDER=openai` in the process environment and restart FastAPI. Call the same endpoint and confirm the selected model and readiness. Verify that no API key appears in the response.
3. With OpenAI selected but `OPENAI_API_KEY` unset, check `ready: false`. Ask a question known to retrieve evidence; expect a sanitized 503 and no silent Ollama fallback.
4. For a live cloud check, provide a valid key securely, ask the known evidence question, and verify provider/model and citations. Do not record the key in logs or screenshots.
5. To check a provider outage locally, select Ollama and set `OLLAMA_URL` to an unavailable local port, then restart FastAPI and submit an evidence-backed question. Expect 502. A request timeout is covered by automated provider tests; manually forcing the configured 180-second timeout can take several minutes.
6. Set `LLM_PROVIDER=ollama`, restart FastAPI and confirm the local provider is selected again.

**Expected:** `GET /api/config` identifies provider/model/readiness without secrets. Missing cloud key yields a clear configuration error only when generation is needed. Outage and timeout errors are sanitized. There is no automatic provider fallback.

## 5. Ship 30 for 30 essay skill

1. Call `GET /api/agent/skills` and confirm `ship-30-for-30-essay` is listed.
2. Call `POST /api/agent/skills/ship-30-for-30-essay/run` with a short writing task.
3. Confirm response provider/model and `artifact_id`; inspect the saved item using `GET /api/artifacts/{artifact_id}` and in `/viewer`.

**Expected:** The Pi skill returns Markdown and stores it as an artifact. Missing Node/Pi dependencies, model configuration errors, or provider failures return a handled error. The essay workflow does not automatically perform RAG retrieval; check its factual claims against cited transcript material manually.

## 6. Artifact rendering and security

1. Create a Markdown artifact through `POST /api/artifacts`; refresh `/viewer`, select it, and use Preview and Source.
2. Use the local Markdown sample and confirm it is marked as a sample, not saved.
3. Use the HTML/CSS sample, activate its script-test button, and confirm it cannot modify or inspect the parent page.
4. Create HTML containing a script, event handler, external image URL, and form. Preview it and inspect the outer page and network panel.
5. Try keyboard navigation through selector, refresh, sample, and Preview/Source controls.

**Expected:** Markdown is rendered as sanitized CommonMark; source is displayed as text. HTML/CSS runs in an empty-sandbox iframe under restrictive CSP. Script execution, parent access, network requests, forms, nested frames and objects are blocked. Inline styles and data images are allowed. This is a local demo safeguard, not a production isolation boundary.

## 7. Responsive and accessibility smoke check

Resize `/viewer` to a narrow mobile viewport, verify controls remain usable without unintended horizontal overflow, and navigate all controls with the keyboard. Check visible focus, labels, alert messaging and screen-reader announcements for empty/error states. This is a smoke check only; no formal accessibility or responsive audit is currently available.

## Record results

Record date, environment, provider, test data identifiers (not transcript contents or secrets), pass/fail, and any observed issue in the evaluator's own test notes. Keep credentials and private transcript data out of screenshots and committed logs.
