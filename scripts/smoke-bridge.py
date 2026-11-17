"""Run from the bridge venv. --live verifies Google and exercises entitled models.

Only status and model availability are printed; upstream logs are captured so
credentials, responses and account details cannot appear in the report.
For each entitled model, live mode uses at most four generations: plain,
streamed, tool request, and tool-result follow-up. Unavailable models use none.
"""
import argparse
import asyncio
import contextlib
import io
import json
import os
from pathlib import Path
import secrets
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
            if not any(available.values()):
                report["live_status"] = "session verified; no advertised target models available"
                return report
            await srv.webapi_manager.apply_session(psid, psidts)
            shared_client = await srv.webapi_manager.get()
            from gemini_webapi.constants import AccountStatus
            account_status = getattr(shared_client.account_status, "name", str(shared_client.account_status))
            report["account_status"] = account_status
            checks["account_available"] = shared_client.account_status == AccountStatus.AVAILABLE
            if not checks["account_available"]:
                report["live_status"] = "session verified; shared manager account unavailable"
                return report
            report["live_status"] = "session verified"
        except Exception as exc:
            report["live_status"] = f"session verification or manager initialization failed: {type(exc).__name__}"
            return report
        try:
            for alias, entitled in available.items():
                if not entitled:
                    checks[f"{alias}_generation"] = "blocked: account does not offer model"
                    continue
                resolved = shared_client.resolve_model(f"gemini-4-{alias}")
                model_info = {
                    "model_id": resolved.model_id,
                    "model_name": resolved.model_name,
                    "display_name": resolved.display_name,
                    "is_available": bool(resolved.is_available),
                }
                report.setdefault("resolved_models", {})[alias] = model_info
                checks[f"{alias}_resolved_available"] = model_info["is_available"]
                if not model_info["is_available"]:
                    checks[f"{alias}_generation"] = False
                    checks[f"{alias}_stream"] = False
                    checks[f"{alias}_tool_call"] = False
                    checks[f"{alias}_tool_round_trip"] = False
                    continue

                body = {"model": f"gemini-4-{alias}", "messages": [{"role": "user", "content": "Reply with exactly BRIDGE_OK"}]}
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                try:
                    payload = r.json()
                    plain = payload["choices"][0]["message"].get("content") or ""
                except (ValueError, KeyError, IndexError, TypeError):
                    plain = ""
                checks[f"{alias}_generation"] = r.status_code == 200 and "BRIDGE_OK" in plain

                body["stream"] = True
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                stream_text = []
                stream_error = False
                done = False
                if r.status_code == 200:
                    for line in r.text.splitlines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            done = True
                            continue
                        try:
                            event = json.loads(data)
                        except ValueError:
                            continue
                        if "error" in event:
                            stream_error = True
                        for choice in event.get("choices", []):
                            delta = choice.get("delta", {}).get("content")
                            if isinstance(delta, str):
                                stream_text.append(delta)
                checks[f"{alias}_stream"] = r.status_code == 200 and done and not stream_error and "BRIDGE_OK" in "".join(stream_text)

                nonce = secrets.token_hex(12)
                body.update(stream=False, messages=[{"role": "user", "content":
                    "Call the get_status tool to retrieve the current status. After receiving its result, "
                    "return the nonce from that result verbatim as your entire final answer."}],
                    tool_choice="required", tools=[{"type": "function", "function": {
                        "name": "get_status", "description": "Return a generated status nonce.",
                        "parameters": {"type": "object", "properties": {}}}}])
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=body), timeout=90)
                tool_call = None
                if r.status_code == 200:
                    try:
                        first = r.json()["choices"][0]["message"].get("tool_calls", [])
                        tool_call = next((tc for tc in first if tc.get("function", {}).get("name") == "get_status"), None)
                    except (ValueError, KeyError, IndexError, TypeError):
                        pass
                checks[f"{alias}_tool_call"] = tool_call is not None
                if tool_call is None:
                    checks[f"{alias}_tool_round_trip"] = False
                    continue

                followup = {
                    "model": body["model"],
                    "messages": [
                        *body["messages"],
                        {"role": "assistant", "content": None, "tool_calls": [tool_call]},
                        {"role": "tool", "tool_call_id": tool_call.get("id"), "name": "get_status", "content": f"nonce: {nonce}"},
                    ],
                }
                r = await asyncio.wait_for(client.post("/v1/chat/completions", json=followup), timeout=90)
                answer = ""
                if r.status_code == 200:
                    try:
                        answer = r.json()["choices"][0]["message"].get("content") or ""
                    except (ValueError, KeyError, IndexError, TypeError):
                        pass
                checks[f"{alias}_tool_round_trip"] = r.status_code == 200 and nonce in answer
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
