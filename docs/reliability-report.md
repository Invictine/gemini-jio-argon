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
