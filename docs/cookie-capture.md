# Capturing Gemini cookies

The bridge authenticates by reusing your **gemini.google.com web session**. It needs two cookies: `__Secure-1PSID` and `__Secure-1PSIDTS`.

## Exact Chrome steps

1. Open <https://gemini.google.com> in Chrome and make sure you are signed in — ideally with a **secondary account**.
2. Press **F12** to open DevTools.
3. Select the **Application** tab → left sidebar **Storage → Cookies → https://gemini.google.com**.
   - If the list is empty, refresh the page with DevTools open, and confirm you are on the `gemini.google.com` domain (not `accounts.google.com` or `www.google.com`).
4. In the cookie table find:
   - `__Secure-1PSID`
   - `__Secure-1PSIDTS`
5. Double-click each cookie's **Value** cell, press **Ctrl+C** to copy it, and paste into the matching line of `.env`:
   - `GEMINI_1PSID=` ← value of `__Secure-1PSID`
   - `GEMINI_1PSIDTS=` ← value of `__Secure-1PSIDTS`
6. Save `.env`, then restart the bridge (`.\scripts\start-bridge.ps1`) and verify (`.\scripts\check-bridge.ps1`).

## Important caveats

- These cookies **are your login credential**. Treat `.env` like a password file — never commit or share it.
- Google can **revoke copied cookies at any time**, and copying them may trigger **DBSC** (a broad session-wide logout/invalidation). When auth breaks, re-capture fresh values from a newly signed-in Chrome session.
- Cookie-based access is unofficial and may violate Google's Terms of Service — prefer a secondary account.

## Alternative: Chrome extension backend

If copied cookies keep getting rejected, the vendored bridge includes a **Chrome extension backend** that can drive your existing, logged-in browser session without manual cookie copying:

- Folder: `vendor\gemini-web-api\extension`
- Load it in Chrome via `chrome://extensions` → enable **Developer mode** → **Load unpacked** → select that folder.
- Follow any README inside that folder, then set `GEMINI_BACKEND=chrome` in `.env` (instead of `webapi`) and restart the bridge.

This keeps the session inside Chrome and avoids many DBSC / cookie-copy failures, but still requires a logged-in Google account with the target models available.

Reload the updated extension after pulling changes. Argon/Hydrogen requests now
require its model-selection capability; older workers are rejected rather than
silently using the tab's previous model. The extension selects the exact model
in Gemini's picker before sending each request.

The extension service worker connects to localhost with its host permission.
A script injected directly into Gemini's page is subject to Chrome's Local
Network Access permission and cannot connect if that site permission is denied.
