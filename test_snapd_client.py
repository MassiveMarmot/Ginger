import json
import os
import socket
import tempfile
import threading
import unittest

from snapd_client import Client, SnapdError, PROMPTING_NOT_RUNNING

RULE = {
    "id": "1",
    "timestamp": "2026-10-04T00:00:00Z",
    "user": 1000,
    "snap": "firefox",
    "interface": "home",
    "constraints": {
        "path-pattern": "/home/user/docs/**",
        "permissions": {
            "read": {"outcome": "allow", "lifespan": "forever"},
        },
    },
}


class MockSnapd:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.rules = []
        self.responses = []  # (status, body) overrides, consumed in order
        self.running = True
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(socket_path)
        self.listener.listen(4)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.listener.close()
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

    def _serve(self):
        while self.running:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with conn:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                lines = data.split(b"\r\n")
                method, path, _ = lines[0].decode().split(" ", 2)
                length = 0
                for line in lines[1:]:
                    if not line:
                        break
                    name, _, value = line.decode().partition(":")
                    if name.lower() == "content-length":
                        length = int(value)
                body = data.split(b"\r\n\r\n", 1)[1][:length] if length else b""
                self._handle(conn, method, path, body)

    def _handle(self, conn, method, path, body):
        if self.responses:
            status, payload = self.responses.pop(0)
            if isinstance(payload, bytes):
                wire = payload
            else:
                wire = json.dumps(payload).encode()
        elif method == "GET" and path == "/v2/interfaces/requests/rules":
            status, payload = 200, {"type": "sync", "status-code": 200,
                                    "result": self.rules}
        elif method == "POST" and path == "/v2/interfaces/requests/rules":
            rule = json.loads(body)["rule"]
            rule["id"] = str(len(self.rules) + 1)
            self.rules.append(rule)
            status, payload = 200, {"type": "sync", "status-code": 200,
                                    "result": rule}
        elif method == "POST" and path.startswith("/v2/interfaces/requests/rules/"):
            self.rules = [r for r in self.rules
                          if r["id"] != path.rsplit("/", 1)[1]]
            status, payload = 200, {"type": "sync", "status-code": 200,
                                   "result": None}
        else:
            status, payload = 404, {"type": "error", "status-code": 404,
                                    "result": {"message": "not found",
                                               "kind": "not-found"}}
        wire = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        conn.sendall(("HTTP/1.1 %d X\r\nContent-Length: %d\r\n\r\n"
                      % (status, len(wire))).encode())
        conn.sendall(wire)


class SnapdClientTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.socket_path = os.path.join(self.tmpdir.name, "snapd.socket")
        self.server = MockSnapd(self.socket_path)
        self.client = Client(socket_path=self.socket_path)

    def tearDown(self):
        self.server.stop()
        self.tmpdir.cleanup()

    def error_response(self, kind, message="error"):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": message, "kind": kind},
        }))

    def test_list_parsing(self):
        self.server.rules = [RULE]
        rules = self.client.list_rules()
        self.assertEqual(rules, [RULE])

    def test_add_success(self):
        result = self.client.add_rule("firefox", "/home/user/docs/**")
        self.assertEqual(result["snap"], "firefox")
        self.assertEqual(self.server.rules[0]["constraints"]["path-pattern"],
                         "/home/user/docs/**")

    def test_add_error_with_kind(self):
        self.error_response("interfaces-requests-rule-conflict", "conflict")
        with self.assertRaises(SnapdError) as ctx:
            self.client.add_rule("firefox", "/x/**")
        self.assertEqual(ctx.exception.kind, "interfaces-requests-rule-conflict")
        self.assertEqual(ctx.exception.message, "conflict")

    def test_remove_success(self):
        self.server.rules = [dict(RULE)]
        self.client.remove_rule("1")
        self.assertEqual(self.server.rules, [])

    def test_prompting_not_running(self):
        self.error_response(PROMPTING_NOT_RUNNING)
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_rules()
        self.assertEqual(ctx.exception.kind, PROMPTING_NOT_RUNNING)

    def test_malformed_json(self):
        self.server.responses.append((200, b"not-json"))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_rules()
        self.assertIn("malformed", ctx.exception.message)


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        from path_validation import validate_pattern
        self.assertIsNone(validate_pattern("/home/user/docs/**"))
        self.assertIsNone(validate_pattern("~/docs/**"))

    def test_invalid(self):
        from path_validation import validate_pattern
        self.assertIsNotNone(validate_pattern(""))
        self.assertIsNotNone(validate_pattern("relative/**"))
        self.assertIsNotNone(validate_pattern("/a\x00b"))
        self.assertIsNotNone(validate_pattern("/a\nb"))
        self.assertIsNotNone(validate_pattern("/a/../b"))

    def test_broad_patterns(self):
        from path_validation import is_broad_pattern
        import pwd
        home = pwd.getpwuid(os.getuid()).pw_dir
        self.assertTrue(is_broad_pattern("/**"))
        self.assertTrue(is_broad_pattern("/home/**"))
        self.assertTrue(is_broad_pattern("~/**"))
        self.assertFalse(is_broad_pattern("/home/user/docs/**"))


if __name__ == "__main__":
    unittest.main()
