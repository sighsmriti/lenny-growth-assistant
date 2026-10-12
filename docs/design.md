# Design: Lenny Growth Assistant

## Design intent and principles

- Make the evidence behind an answer inspectable: citations carry episode, guest, filename, source identity, URL when supplied, chunk index and excerpt.
- Keep the evaluator's next action obvious: API docs are linked from the viewer; the empty state points to the saved-artifact list and available essay skill endpoint.
- Label unsaved examples and saved outputs distinctly.
- Treat generated content as untrusted input. Render Markdown through a server-side allowlist and HTML/CSS in a sandboxed frame.
- Prefer a small, readable local-development interface over implying that a complete chat product exists.

## Information architecture

The implemented browser surface is `/viewer`, a standalone artifact viewer:

- Header: product label, page title and API docs link.
- Toolbar: saved artifact selector, refresh control and Markdown/HTML-CSS sample controls.
- Empty state: explains how to select or create content and repeats sample actions.
- Artifact panel: title, format/sample marker, Preview/Source controls, preview or escaped source text.
- Footer: reminder that generated artifacts are untrusted.

Chat, session management and essay generation are exposed as API routes, not through a chat composer in this page. The viewer does not show chat citations or trigger skill routing.

## Key interaction states

- Initial/empty: no artifact selected; sample actions remain available.
- Loading/refresh failure: an accessible alert displays a concise error; saved list is reset.
- Saved artifact selected: format and title are shown; Markdown or sandboxed markup preview is selected by default.
- Local sample selected: SAMPLE badge and unsaved label distinguish it from a persisted artifact.
- Source mode: content is inserted as text in a `pre`/`code` element.
- Preview mode: Markdown uses API-provided sanitized HTML; HTML/CSS is written into an iframe with an empty sandbox attribute and restrictive CSP.
- API states: FastAPI returns validation errors, 404 for missing sessions/artifacts, 502 for Ollama chat failures, and 503 for Pi/database availability failures where explicitly handled.

## Responsive behavior

The viewer sets a device-width viewport and uses a simple document flow. The UI is static HTML/CSS served by FastAPI without a build step. The layout should be checked at narrow viewport widths before production use; no responsive breakpoint or mobile usability guarantee is covered by automated tests.

## Accessibility

The page uses semantic header, main, sections and footer; form labels; button elements; `aria-label` on controls; an `aria-live` empty state; a `role=alert` error; a labeled iframe; and `aria-pressed` on view toggles. Keyboard access uses native controls. No formal screen-reader or contrast audit has been completed. Focus management after artifact selection and error recovery could be improved.

## Rendering and security decisions

Markdown is parsed as CommonMark with raw HTML disabled, then sanitized to allowlisted tags, attributes and `http`, `https`, and `mailto` URL schemes. HTML/CSS source is never assigned to the outer page DOM. It is placed in an iframe with `sandbox=""` and a CSP that blocks scripts, network access, forms, nested frames and objects. Inline styles and data images remain allowed to support preview. This is a local demo safeguard, not a complete production boundary.

## Known product gaps

There is no integrated chat surface, chat-to-artifact action, provider selector, streaming state, user identity, or production accessibility review. These are explicit follow-up items rather than implemented design behaviors.
