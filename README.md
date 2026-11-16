<img src="assets/icon.svg" width="64" height="64" alt="">

# gemini-jio-argon

Run Google Gemini 4 **Argon** / **Hydrogen** (the models from the gemini.google.com web app) as a local provider in T3 Code — no paid API key. A small local bridge reuses your Chrome web session and exposes it as an OpenAI-compatible API.

## Architecture

```
T3 Code (provider: "Gemini")
  -> Local ACP command: opencode.exe acp
      -> OpenCode V2 "gemini-app" provider  (config forced via env vars)
          -> local bridge  http://127.0.0.1:8100/v1  (vendor/gemini-web-api)
              -> gemini.google.com  (your Chrome cookies)
```

`opencode.exe acp` speaks the Agent Client Protocol to T3. Its config is **forced** through environment variables, so it only ever talks to the local bridge and cannot reach any other provider. The bridge maps `argon`/`hydrogen` to the internal Gemini 4 model IDs and emulates tool calling.

## ⚠️ Read this first

- This is **unofficial, reverse-engineered** access to the Gemini web app. It may **violate Google's Terms of Service** and can lead to **account restrictions or termination**.
- Use a **secondary / throwaway Google account** if at all possible.
- **Web-app quotas and rate limits apply** (not API quotas). Heavy use can trip abuse detection.
- Google deploys changes constantly: **RPC IDs and cookie handling can break without notice**. When that happens, update the vendored bridge (see Maintenance).

## Prerequisites

- **Python 3.12 + uv** — already installed and synced at `vendor\gemini-web-api\.venv`.
- **Opencode CLI native exe** at exactly:
  `C:\Users\aniru\AppData\Local\hermes\node\node_modules\@opencode\cli\bin\opencode.exe`
- **T3 Code** (the host application).
- **Chrome**, logged into <https://gemini.google.com> with an account whose model picker actually offers **Gemini 4 Argon / Hydrogen**. Entitlement matters — an unentitled account silently falls back to `gemini-3-flash`.

## Setup

### 1. Sign in from T3 Code (recommended)

Once the provider is registered (step 3), use **Settings → Providers → Gemini → Sign in** and paste the two cookies. The dialog POSTs them to `POST http://127.0.0.1:<port>/v1/auth/session` with `Authorization: Bearer gemini-local`. A running bridge applies them to its shared client **immediately, without a restart**, and merges them into this project's `.env` so the next restart keeps them. Cookie values are never returned in the response or written to logs.

If the bridge is stopped, the dialog still saves the cookies into T3's provider settings and shows the "bridge is not reachable" notice — the next sign-in attempt pushes them. A bridge error is shown in the dialog instead of being silently saved.

**Manual fallback (or when T3 is unavailable):** put the cookies in `.env` yourself:

1. Copy `.env.example` → `.env` in this folder.
2. In Chrome, open <https://gemini.google.com> and sign in.
3. Press **F12** (DevTools) → **Application** → **Storage → Cookies → https://gemini.google.com**.
4. Find `__Secure-1PSID` and `__Secure-1PSIDTS`; double-click each **Value** and copy it.
5. In `.env` set:
   - `GEMINI_1PSID=<value of __Secure-1PSID>`
   - `GEMINI_1PSIDTS=<value of __Secure-1PSIDTS>`
6. See `docs/cookie-capture.md` for exact steps and alternatives. Restart the bridge after an edit made by hand.

> `.env` holds **session cookies = full account credentials**. Never commit, share, or paste it into a chat. It is gitignored. The auth endpoint uses the same `GEMINI_API_KEY` as `/v1/models`; CORS is restricted to loopback HTTP origins plus T3's `t3code://app` / `t3code-dev://app` webview origin (not arbitrary websites). Override the credentials file location with `GEMINI_ENV_FILE` if you relocate it.

### 2. Start and verify the bridge

```powershell
.\scripts\start-bridge.ps1      # starts uvicorn on 127.0.0.1:8100 (leave running)
.\scripts\check-bridge.ps1      # second terminal: health + model list
```

`check-bridge.ps1` should print **Bridge reachable: YES** and list `gemini-4-argon` and `gemini-4-hydrogen`. Keep the bridge terminal open while using T3.

### 3. Register the provider in T3 Code

**Settings → Providers → Add provider → Show more → Local ACP command**

| Field | Value |
| --- | --- |
| Executable | `C:\Users\aniru\AppData\Local\hermes\node\node_modules\@opencode\cli\bin\opencode.exe` |
| Argument row | `acp` |
| Display name | `Gemini` |
| Env `OPENCODE_CONFIG_CONTENT` | exact one-line contents of `config\opencode-gemini.min.json` |
| Env `OPENCODE_CONFIG_PROJECT_DISABLE` | `1` |

These env overrides are set **per provider instance** in T3's UI. If that env field is unavailable, paste the content of `config\opencode-gemini.jsonc` into the provider's config field directly.

### 4. Pick the model

Select provider **Gemini**, then model **Gemini 4 Argon** or **Gemini 4 Hydrogen** in T3's model picker. If they do not appear, use **Add custom model** with slug `gemini-app/argon` or `gemini-app/hydrogen`.

## Verification checklist

- [ ] `.\scripts\check-bridge.ps1` shows the bridge reachable and both model IDs.
- [ ] A test prompt in T3 returns a Gemini answer (watch the bridge terminal for the request).
- [ ] Tool use works — OpenCode emulates tool calling over the bridge; try a harmless command like listing a directory.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| 403 / login page in bridge log | Cookies expired or DBSC — re-capture fresh values from Chrome (see cookie guide). |
| Models fall back to `gemini-3-flash` | Account not entitled, or alias resolution failed — check the bridge log and re-apply the `config.py` patch. |
| Tool-call parse failures | Retry, or use a simpler prompt; emulated tool calling is best-effort. |
| Model missing from picker | Add custom model slug `gemini-app/argon` / `gemini-app/hydrogen`. |
| Port already in use | Change `GEMINI_API_PORT` in `.env` **and** the `baseURL` in both `config\opencode-gemini*.json*`. |

## Maintenance

- **Update the vendored bridge:**
  ```powershell
  git -C vendor\gemini-web-api pull
  git -C vendor\gemini-web-api rev-parse HEAD
  Push-Location vendor\gemini-web-api; uv sync; Pop-Location
  ```
- **Re-apply the `config.py` patch after every update.** In `vendor\gemini-web-api\gemini_openai\config.py` (search for `Gemini 4 App aliases`) it adds:
  ```python
  # in _ALIASES
  "argon": "gemini-4-argon",
  "gemini-4-argon": "gemini-4-argon",
  "hydrogen": "gemini-4-hydrogen",
  "gemini-4-hydrogen": "gemini-4-hydrogen",
  # after _CANON (keeps _HAS_THINKING logic intact)
  _CANON.update({"gemini-4-argon": "gemini-4-argon",
                 "gemini-4-hydrogen": "gemini-4-hydrogen"})
  ```
  Without it, unknown names collapse to `DEFAULT_MODEL` = `gemini-3-flash`.
- **Re-apply the runtime session patch after every upstream update.** It is a second local patch on the vendored bridge (committed in `vendor\gemini-web-api`):
  - `gemini_openai\gemini_pool.py` — `GeminiManager.apply_session()` installs new cookies under the pool lock, clears gemini_webapi's cookie cache, and drops the shared client so the next request re-inits with them.
  - `gemini_openai\server.py` — loopback/T3 CORS middleware, the `.env` merge helper, and `POST /v1/auth/session`.
  - Upstream versions may move these functions; after pulling, re-check that both files still carry the patch before relying on T3 sign-in.
- Google's **RPC IDs** change with web-app deploys. If requests start failing, the upstream bridge usually needs an update — pull frequently and check the upstream repo.
