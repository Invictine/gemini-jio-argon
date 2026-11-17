"""Run from the bridge venv. --live verifies Google and exercises entitled models.

Only status and model availability are printed; upstream logs are captured so
credentials, responses and account details cannot appear in the report.
"""
import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor" / "gemini-web-api"))


async def run(live):
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip().strip("\"'")
    # A diagnostic must not rotate the Chrome-owned session or use another backend.
    os.environ["GEMINI_AUTO_REFRESH"] = "0"
    os.environ["GEMINI_BACKEND"] = "webapi"
    os.environ["GEMINI_ENV_FILE"] = str(env_file)
    from gemini_openai import server as srv
    import httpx

    report = {"live_requested": live, "checks": {}}
    checks = report["checks"]
    headers = {"Authorization": f"Bearer {srv.config.API_KEY}"} if srv.config.API_KEY else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=srv.app), base_url="http://test", headers=headers) as client:
        checks["health"] = (await client.get("/health")).status_code == 200
        models = await client.get("/v1/models")
        checks["models_endpoint"] = models.status_code == 200
        if not live:
            report["live_status"] = "not requested"
            return report
        psid, psidts = os.getenv("GEMINI_1PSID"), os.getenv("GEMINI_1PSIDTS")
        if not psid or not psidts:
            report["live_status"] = "blocked: saved session cookies missing"
            return report
        try:
            available = await srv.webapi_manager.verify_session(psid, psidts, timeout=15)
            report["account_models"] = available
            report["live_status"] = "session verified"
        except Exception as exc:
            report["live_status"] = f"session verification failed: {type(exc).__name__}"
            return report
        try:
            for alias, entitled in available.items():
                if not entitled:
                    checks[f"{alias}_generation"] = "blocked: account does not offer model"
                    continue
                body = {"model": alias, "messages": [{"role": "user", "content": "Reply with exactly BRIDGE_OK"}]}
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                checks[f"{alias}_generation"] = r.status_code == 200 and "BRIDGE_OK" in r.text
                body["stream"] = True
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                checks[f"{alias}_stream"] = r.status_code == 200 and '"error"' not in r.text and "[DONE]" in r.text
                body.update(stream=False, tool_choice="required", tools=[{"type": "function", "function": {
                    "name": "get_status", "parameters": {"type": "object", "properties": {}}}}])
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                checks[f"{alias}_tool_call"] = r.status_code == 200 and '"name":"get_status"' in r.text.replace(" ", "")
        finally:
            await srv.webapi_manager.reset()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            report = asyncio.run(run(args.live))
        except Exception as exc:
            report = {"error": type(exc).__name__}
    print(json.dumps(report, indent=2))
    failed = "error" in report or any(value is not True for value in report.get("checks", {}).values())
    if args.live and report.get("live_status") != "session verified":
        failed = True
    sys.exit(1 if failed else 0)
