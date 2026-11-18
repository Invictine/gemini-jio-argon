"""Live acceptance checks for the connected Chrome extension bridge.

Run with the bridge venv Python while the bridge and a fresh Gemini tab are
running. Full mode performs at most four generations per model. Requests use a
310-second timeout and are never retried. No credentials or model response text
are printed.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
REQUEST_TIMEOUT_SECONDS = 310


def load_project_env() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def emit(name: str, passed: bool, *, status: int | None = None, error: str | None = None,
         detail: str | None = None) -> None:
    item: dict[str, Any] = {"check": name, "ok": bool(passed)}
    if status is not None:
        item["status"] = int(status)
    if error:
        item["error"] = str(error)[:200]
    if detail:
        item["detail"] = str(detail)[:200]
    print(json.dumps(item, ensure_ascii=True), flush=True)


def json_response(response: httpx.Response) -> dict[str, Any]:
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("json_shape")
    return payload


def choice_content(response: httpx.Response) -> str:
    payload = json_response(response)
    return payload["choices"][0]["message"].get("content") or ""


def http_failure(response: httpx.Response) -> str:
    # Map known safe errors without logging upstream response bodies.
    try:
        detail = json_response(response).get("detail", "")
    except ValueError:
        return "http_error"
    if not isinstance(detail, str):
        return "http_error"
    if detail.startswith("Gemini could not fulfill this request with the selected model"):
        return "model_request_failed"
    if detail.startswith("no eligible gemini tab") or (
        detail.startswith("gemini tab ") and detail.endswith(" disconnected")
    ):
        return "worker_disconnected"
    if detail.startswith(("fresh chat did not become ready", "new-chat control not found")):
        return "fresh_chat_unavailable"
    if detail.startswith("composer did not accept the complete prompt"):
        return "prompt_incomplete"
    if detail.startswith(("no new response appeared", "Gemini response did not stabilize", "Gemini generation remained active")):
        return "response_timeout"
    return "http_error"


def run_plain(client: httpx.Client, base: str, headers: dict[str, str], model: str) -> bool:
    expected = "BRIDGE_PLAIN_" + secrets.token_hex(12)
    response = client.post(f"{base}/v1/chat/completions", headers=headers, json={
        "model": model,
        "messages": [{"role": "user", "content": "Bridge response transmission test.\nDo not run code, use tools, search or browse.\nReply with exactly: " + expected}],
    })
    if response.status_code != 200:
        emit(f"{model}:plain", False, status=response.status_code, error=http_failure(response))
        return False
    try:
        answer = choice_content(response).strip()
    except (ValueError, KeyError, IndexError, TypeError):
        emit(f"{model}:plain", False, status=response.status_code, error="invalid_response")
        return False
    passed = expected in answer
    emit(f"{model}:plain", passed, status=response.status_code,
         error=None if passed else "fresh_marker_missing",
         detail=f"exact_format={answer == expected}")
    return passed


def run_stream(client: httpx.Client, base: str, headers: dict[str, str], model: str) -> bool:
    expected = "BRIDGE_STREAM_" + secrets.token_hex(12)
    response = client.post(f"{base}/v1/chat/completions", headers=headers, json={
        "model": model,
        "stream": True,
        "messages": [{"role": "user", "content": "Bridge streaming transmission test.\nDo not run code, use tools, search or browse.\nReply with exactly: " + expected}],
    })
    if response.status_code != 200:
        emit(f"{model}:stream", False, status=response.status_code, error=http_failure(response))
        return False
    pieces: list[str] = []
    done = False
    error_event = False
    try:
        for line in response.text.splitlines():
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
                error_event = True
            for choice in event.get("choices", []):
                text = choice.get("delta", {}).get("content")
                if isinstance(text, str):
                    pieces.append(text)
    except (ValueError, TypeError):
        emit(f"{model}:stream", False, status=response.status_code, error="invalid_sse")
        return False
    answer = "".join(pieces).strip()
    passed = done and not error_event and expected in answer
    emit(f"{model}:stream", passed, status=response.status_code,
         error=None if passed else "stream_answer_mismatch",
         detail=f"exact_format={answer == expected}")
    return passed


def run_tool_round_trip(client: httpx.Client, base: str, headers: dict[str, str], model: str) -> bool:
    nonce = secrets.token_hex(12)
    messages = [{"role": "user", "content": (
        "Call the get_status tool to retrieve the current status. After receiving its result, "
        "return the nonce from that result verbatim as your entire final answer."
    )}]
    tool_spec = [{"type": "function", "function": {
        "name": "get_status", "description": "Return a generated status nonce.",
        "parameters": {"type": "object", "properties": {}}
    }}]
    first = client.post(f"{base}/v1/chat/completions", headers=headers, json={
        "model": model, "messages": messages, "tool_choice": "required", "tools": tool_spec,
    })
    if first.status_code != 200:
        emit(f"{model}:tool_call", False, status=first.status_code, error=http_failure(first))
        emit(f"{model}:tool_round_trip", False, error="tool_call_unavailable")
        return False
    try:
        payload = json_response(first)
        calls = payload["choices"][0]["message"].get("tool_calls", [])
        tool_call = next((call for call in calls
                          if call.get("function", {}).get("name") == "get_status"), None)
    except (ValueError, KeyError, IndexError, TypeError):
        tool_call = None
    if tool_call is None:
        emit(f"{model}:tool_call", False, status=first.status_code, error="expected_tool_missing")
        emit(f"{model}:tool_round_trip", False, error="tool_call_unavailable")
        return False
    emit(f"{model}:tool_call", True, status=first.status_code)

    messages.extend([
        {"role": "assistant", "content": None, "tool_calls": [tool_call]},
        {"role": "tool", "tool_call_id": tool_call.get("id"), "name": "get_status",
         "content": f"nonce: {nonce}"},
    ])
    final = client.post(f"{base}/v1/chat/completions", headers=headers, json={
        "model": model, "messages": messages,
    })
    if final.status_code != 200:
        emit(f"{model}:tool_round_trip", False, status=final.status_code, error=http_failure(final))
        return False
    try:
        answer = choice_content(final)
    except (ValueError, KeyError, IndexError, TypeError):
        emit(f"{model}:tool_round_trip", False, status=final.status_code, error="invalid_response")
        return False
    passed = nonce in answer
    emit(f"{model}:tool_round_trip", passed, status=final.status_code,
         error=None if passed else "nonce_missing_from_final_answer")
    return passed


def background_check(client: httpx.Client, base: str, headers: dict[str, str], phase: str) -> bool:
    response = client.get(f"{base}/v1/extension/diagnostics", headers=headers, timeout=8)
    worker = response.json().get("worker", {}) if response.status_code == 200 else {}
    passed = worker.get("visibility") == "hidden" and worker.get("focused") is False
    emit(f"bridge:background_{phase}", passed, status=response.status_code,
         detail=f"visibility={worker.get('visibility')} focused={worker.get('focused')}")
    return passed


def run(models: list[str], mode: str, open_worker: bool = False, require_background: bool = False) -> int:
    env = load_project_env()
    host = env.get("GEMINI_API_HOST") or os.environ.get("GEMINI_API_HOST") or "127.0.0.1"
    port = env.get("GEMINI_API_PORT") or os.environ.get("GEMINI_API_PORT") or "8100"
    key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY") or "gemini-local"
    base = f"http://{host}:{port}"
    headers = {"Authorization": f"Bearer {key}"}

    # One timeout applies to each individual HTTP request. httpx has no retry
    # policy configured, so each generation is attempted exactly once.
    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
        if open_worker:
            status = client.get(f"{base}/v1/status", headers=headers, timeout=5)
            status.raise_for_status()
            existing = {tab["tabId"] for tab in status.json().get("tabs", [])}
            queued = client.post(f"{base}/v1/extension/open-worker", headers=headers, timeout=5)
            emit("bridge:open_worker_queued", queued.status_code == 200, status=queued.status_code)
            if queued.status_code != 200:
                return 1
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                candidate = client.get(f"{base}/v1/status", headers=headers, timeout=5)
                if candidate.status_code == 200 and any(
                    tab.get("eligible") is True and tab.get("tabId") not in existing
                    for tab in candidate.json().get("tabs", [])
                ):
                    break
                time.sleep(2)
            else:
                emit("bridge:new_worker", False, error="worker_did_not_connect")
                return 1
        try:
            health = client.get(f"{base}/health", headers=headers)
        except httpx.HTTPError as exc:
            emit("bridge:health", False, error=type(exc).__name__)
            return 1
        if health.status_code != 200:
            emit("bridge:health", False, status=health.status_code, error="http_error")
            return 1
        try:
            data = json_response(health)
        except (ValueError, TypeError):
            emit("bridge:health", False, status=health.status_code, error="invalid_response")
            return 1
        connected = data.get("active_backend") == "chrome" and data.get("extension_connected") is True
        emit("bridge:extension_connected", connected,
             status=health.status_code,
             error=None if connected else "chrome_extension_not_connected")
        if not connected:
            return 1

        try:
            status = client.get(f"{base}/v1/status", headers=headers)
            if status.status_code == 200:
                status_data = json_response(status)
                if "tabs" in status_data:
                    tabs = status_data["tabs"]
                    capable = isinstance(tabs, list) and any(
                        isinstance(tab, dict) and tab.get("eligible") is True for tab in tabs
                    )
                    emit("bridge:eligible_tab", capable, status=status.status_code,
                         error=None if capable else "no_eligible_tab_reported")
                    if not capable:
                        return 1
                else:
                    emit("bridge:eligible_tab", True, status=status.status_code, detail="tabs_not_reported")
            else:
                emit("bridge:eligible_tab", True, status=status.status_code, detail="optional_status_unavailable")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            emit("bridge:eligible_tab", True, error=type(exc).__name__, detail="optional_status_unavailable")

        if require_background and not background_check(client, base, headers, "before"):
            return 1
        failures = 0
        for model in models:
            model_id = f"gemini-4-{model}"
            checks = [run_plain(client, base, headers, model_id)]
            if mode == "full" and checks[0]:
                checks.append(run_stream(client, base, headers, model_id))
                checks.append(run_tool_round_trip(client, base, headers, model_id))
            failures += sum(not passed for passed in checks)
        if require_background and not background_check(client, base, headers, "after"):
            failures += 1
    emit("summary", failures == 0, detail=f"models={len(models)} mode={mode} failures={failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("argon", "hydrogen", "all"), default="all")
    parser.add_argument("--mode", choices=("plain", "full"), default="full")
    parser.add_argument("--open-worker", action="store_true", help="Ask the installed extension to open a dedicated Gemini tab; wait up to 90 seconds")
    parser.add_argument("--require-background", action="store_true", help="Require a hidden, unfocused Gemini tab before and after live checks")
    args = parser.parse_args()
    models = [args.model] if args.model != "all" else ["argon", "hydrogen"]
    try:
        return run(models, args.mode, args.open_worker, args.require_background)
    except httpx.HTTPError as exc:
        emit("smoke", False, error=type(exc).__name__)
        return 1
    except Exception as exc:  # keep diagnostics sanitized; never print response bodies
        emit("smoke", False, error=type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
