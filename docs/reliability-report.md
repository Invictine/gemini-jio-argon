# Reliability validation — 17 November 2026

## Verified locally

- Bridge regression suite: **90 passed**, including a real loopback HTTP/WebSocket fake-extension integration, auth/CORS validation, session persistence, initialization failure/retry, stale-client reset protection, tool parsing and tool-result round trip.
- OpenAI SDK streaming failure test confirms an upstream error raises `APIError`, rather than becoming a successful assistant answer.
- PowerShell health-check black-box suite: **4 passed** (unreachable server, rejected key, missing target model, successful model advertisement).
- In-process HTTP smoke test: health and authenticated model catalogue passed. This does not prove Google authentication.
- `uv sync --locked --group dev` succeeded; bridge and project diffs passed whitespace checks.

## Live result

The smoke test loaded the saved project credentials and attempted a bounded,
non-generating Google session verification. Google rejected the session with
`AuthError`. No saved credentials were changed. Live generation, model entitlement,
streaming and model-generated tools could therefore not be verified.

Refresh the cookies through T3's Gemini sign-in or the documented cookie-capture
flow, then run `scripts/smoke-bridge.py --live` with the bridge venv Python.
The smoke test sends up to three short generations per available model.

## Changes

- Initialization failures enter the one-retry path; failed clients are closed and initialization has a whole-operation deadline.
- A request resetting its failed client cannot tear down a newer client's session.
- Unavailable Argon/Hydrogen requests fail explicitly instead of serving the account default under the requested model name.
- Tool parser handles quoted brackets and nested objects; invalid argument shapes and unresolved code placeholders become structured errors.
- Required-tool requests cannot silently finish as ordinary prose when the model omits the call.
- Stream failures are structured OpenAI errors. Authentication rejection responses do not interpolate upstream exception text.
- Cookie validation rejects non-string values and CR/LF before trimming.
- Launcher pins the credential persistence path and propagates process failure; health checks respect configured connection settings and return failure for rejected authentication or missing models.
- New configuration template leaves Chrome in charge of refreshing shared cookies. Existing `.env` settings were preserved.
- Patched bridge source is pinned as a submodule in a private fork, with an offline regression CI workflow.

## Acceptance still required

These tests do not establish working signed-in T3 desktop use, real shell-tool
execution, long-lived cookie refresh/DBSC behavior, quota endurance, or true
upstream model identity. The model registry is Google's reported availability;
the bridge cannot independently prove which model Google runs internally.
CI was configured; its hosted outcome is separate from local test results.

## Follow-up: signed-in browser acceptance

The shared browser's signed-in Gemini account offers both `4 Hydrogen` and
`4 Argon` in its actual mode picker. This is distinct from the rejected saved
two-cookie session. The saved session initializes as `UNAUTHENTICATED` and
discovers only `gemini-flash-lite` / `Quick answers`.

Using the worker's actual DOM-driving functions in that browser:

- Hydrogen returned `HYDROGEN_BRIDGE_OK_7429`, and a second request returned
  `18` for `7 + 11`. Both responses also contained follow-up suggestions.
- Argon was selected and simple prompts submitted, but no new response was
  rendered within the worker's initial response window. The UI remained on
  `Stop response`. Argon generation is **not verified**.
- Chrome reports Gemini's `local-network-access` permission as `denied`.
  An authenticated page WebSocket to the diagnostic bridge failed before
  reaching the server. The live DOM checks used a test event sink, not a
  working browser-to-bridge socket; these are not end-to-end T3 acceptance.

Live testing found and fixed ignored model hints, a mode-picker SPA timing
race, and previous-chat text being emitted as a new response. Updated workers
advertise model-selection support; the bridge rejects targeted requests from
older workers. Scraping excludes prior response nodes, waits for generation
to finish, and gives Argon up to 120 seconds for its first response within a
290-second overall scrape deadline. Eight Node regression tests cover those
worker behaviors, in addition to the 90 passing Python tests.

The installed signed-in Chrome profiles did not have the bridge extension.
Native Windows browser control was unavailable, and the shared browser cannot
open `chrome://extensions` or site settings. Automatic extension installation
was therefore not completed. No original browser settings or saved cookies
were changed. A working extension connection and live Argon reply remain required.
