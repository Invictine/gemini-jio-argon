# Reliability validation

This report separates code-level reliability from live Google model behavior.

## Current result

The extension now operates in the background. Requests use the existing Gemini
worker without activating its tab or window, and recovery opens new worker tabs
with `active: false`. The installed worker was live-verified after recovery;
diagnostics showed it hidden and unfocused before and after requests.

On 18 November, both Argon and Hydrogen passed the live plain-generation check
through `/v1/chat/completions` after the service worker timing fix. Each returned
its exact fresh marker from a multiline prompt. Worker diagnostics were hidden
and unfocused before and after the run. An earlier full Hydrogen run also
passed SSE streaming, a required `get_status` tool call, and a tool result with
a fresh nonce in the background.

The subsequent full run on 18 November kept the worker hidden and unfocused.
Argon reached the response deadline on the plain check, so its streaming and
tool checks were skipped. Hydrogen passed plain generation and streaming. The
required tool call was missing in that run, so there was no tool round trip.

Earlier live checks failed intermittently. Argon returned Google's “I'm having
a hard time fulfilling your request” message in one probe and did not finish
before the bridge deadline in another. Both models also hit a fresh-chat error
on a stale worker before their prompts were submitted. These failures remain
relevant to repeatability.

## Local verification

- 100 Python tests passed, including a loopback chat request that waits for
  recovery and completes when a test extension connects.
- 32 extension Node tests passed, including background-only tab creation,
  heartbeat/reload recovery, model selection, fresh-chat isolation, multiline
  prompt insertion, hidden Markdown/code extraction, and tool-result handling.
- 4 PowerShell bridge black-box checks passed.
- OpenAI error-envelope behavior was verified: upstream failures become client
  errors rather than successful assistant text.
- The vendored bridge is pinned to the patched private fork. The bridge's
  [hosted regression run](https://github.com/Invictine/gemini-jio-argon-bridge/actions/runs/44321705150)
  passed on the pinned commit.

These tests do not prove live entitlement, quota, model identity, cookie
longevity, or end-to-end T3 desktop use.

## Important fixes

- Argon/Hydrogen requests fail explicitly when unavailable; the account default
  is never presented under the requested model name.
- Initialization has a bounded retry path with failed-client cleanup and
  protection against an old request resetting a newer client.
- Stream failures, missing required tools, invalid tool arguments, and
  unresolved file placeholders return structured errors.
- Cookie input is validated before use and authentication exceptions are not
  echoed back to callers.
- The launcher pins the project `.env` path, propagates bridge exit status, and
  can start a hidden process with `-Background`. Hidden startup and a second
  invocation reusing the healthy process were verified locally.
- Multiline prompts use a verified synthetic paste path; truncated first-line
  submissions are rejected. Fresh-chat setup waits for the prior turn to clear,
  and response scraping excludes stale nodes while preserving hidden Markdown
  and code blocks.
- The service worker owns the WebSocket heartbeat and recovery polling, so a
  hidden tab can remain connected without foreground UI control.
- A normal chat request in forced Chrome mode queues a missing worker. Calls
  share the recovery window and stop waiting after 85 seconds.
- The service worker runs short UI waits for hidden tabs, and response stability
  is measured by elapsed time. A timed-out chat does not send the prompt again.

## Live limitations

The saved two-cookie session initializes as unauthenticated and discovers only
`gemini-flash-lite`; the signed-in Chrome account's picker offers both `4 Argon`
and `4 Hydrogen`. This is why the current Chrome backend is used for live
checks, rather than treating the cookie-only backend as proof of access.

The native OpenCode CLI directory-list acceptance fixture timed out after 240
seconds and was terminated without an orphan process. T3 desktop sign-in and
tool execution remain unverified. Long-duration endurance, browser
restart/minimize recovery, and quota/rate-limit behavior are also unverified.

## Reproduce

Run the local suites from the project root:

```powershell
Push-Location vendor\gemini-web-api
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/extension_model_test.cjs tests/extension_background_test.cjs
Pop-Location
.\vendor\gemini-web-api\.venv\Scripts\python.exe scripts/test-bridge-scripts.py
```

For a live installed-extension check, start the bridge with the Chrome backend
and run:

```powershell
.\vendor\gemini-web-api\.venv\Scripts\python.exe scripts/smoke-extension.py --model all --mode full --require-background
```

The live command is single-attempt per check, never prints credentials or
generated text, and exits nonzero when a model fails.
