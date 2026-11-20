"""Repeatable black-box checks for check-bridge.ps1 using a local HTTP stub."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = ROOT / "scripts" / "check-bridge.ps1"
API_KEY = "test-key-do-not-print"
REQUIRED_MODELS = ["gemini-4-neon"]


class StubHandler(BaseHTTPRequestHandler):
    models_status = 200
    model_ids = REQUIRED_MODELS
    received_keys: list[str | None] = []

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        key = self.headers.get("Authorization")
        type(self).received_keys.append(key)
        if self.path == "/health":
            status, payload = 200, {"status": "ok"}
        elif self.path == "/v1/models":
            status = type(self).models_status
            payload = {"error": "unauthorized"} if status != 200 else {
                "data": [{"id": item} for item in type(self).model_ids]
            }
        else:
            status, payload = 404, {"error": "not found"}
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class CheckBridgeScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.powershell = shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")
        if not cls.powershell:
            raise unittest.SkipTest("PowerShell is required to run these checks")

    def run_check(self, port: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.powershell, "-NoProfile", "-File", str(CHECK_SCRIPT), "-Port", str(port), "-ApiKey", API_KEY],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )

    def serve(self, status: int = 200, models: list[str] | None = None):
        StubHandler.models_status = status
        StubHandler.model_ids = models if models is not None else REQUIRED_MODELS
        StubHandler.received_keys = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def assert_key_not_leaked(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertNotIn(API_KEY, result.stdout + result.stderr)

    def test_unreachable_bridge_fails(self) -> None:
        probe = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
        port = probe.server_address[1]
        probe.server_close()
        result = self.run_check(port)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Bridge reachable:", result.stdout)
        self.assertIn("NO", result.stdout)
        self.assert_key_not_leaked(result)

    def test_models_unauthorized_fails(self) -> None:
        server, thread = self.serve(status=401)
        try:
            result = self.run_check(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Authenticated models:", result.stdout)
        self.assertIn("NO", result.stdout)
        self.assertEqual(StubHandler.received_keys, [f"Bearer {API_KEY}", f"Bearer {API_KEY}"])
        self.assert_key_not_leaked(result)

    def test_missing_required_model_fails(self) -> None:
        server, thread = self.serve(models=["gemini-4-argon"])
        try:
            result = self.run_check(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("gemini-4-neon", result.stdout + result.stderr)
        self.assert_key_not_leaked(result)

    def test_required_neon_model_succeeds(self) -> None:
        server, thread = self.serve()
        try:
            result = self.run_check(server.server_address[1])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: gemini-4-neon is advertised.", result.stdout)
        self.assert_key_not_leaked(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
