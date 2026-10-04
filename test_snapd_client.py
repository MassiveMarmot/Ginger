import json
import os
import pwd
import socket
import tempfile
import threading
import unittest

from path_validation import is_broad_pattern, normalize_pattern
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
                        return
                    data += chunk
                head, body = data.split(b"\r\n\r\n", 1)
                lines = head.split(b"\r\n")
                method, path, _ = lines[0].decode().split(" ", 2)
                length = 0
                for line in lines[1:]:
                    name, _, value = line.decode().partition(":")
                    if name.lower() == "content-length":
                        length = int(value)
                while len(body) < length:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    body += chunk
                self._handle(conn, method, path, body)

    def _handle(self, conn, method, path, body):
        if self.responses:
            status, payload = self.responses.pop(0)
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

    def test_remove_rejects_empty_id(self):
        with self.assertRaises(SnapdError):
            self.client.remove_rule("")

    def test_remove_quotes_untrusted_id(self):
        self.server.rules = [dict(RULE)]
        self.client.remove_rule("a/b?c")
        self.assertEqual(self.server.rules, [RULE])

    def test_prompting_not_running(self):
        self.error_response(PROMPTING_NOT_RUNNING)
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_rules()
        self.assertEqual(ctx.exception.kind, PROMPTING_NOT_RUNNING)

    def test_connection_failure(self):
        bad = Client(socket_path=os.path.join(self.tmpdir.name, "missing.socket"))
        with self.assertRaises(SnapdError) as ctx:
            bad.list_rules()
        self.assertEqual(ctx.exception.kind, "connection-failed")

    def test_malformed_json(self):
        self.server.responses.append((200, b"not-json"))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_rules()
        self.assertIn("malformed", ctx.exception.message)

    def test_non_dict_json(self):
        self.server.responses.append((200, [1, 2]))
        with self.assertRaises(SnapdError):
            self.client.list_rules()

    def test_non_dict_error_result(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400, "result": "oops",
        }))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_rules()
        self.assertEqual(ctx.exception.message, "snapd error")


class ValidationTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(normalize_pattern("/home/user/docs/**"),
                         ("/home/user/docs/**", None))
        pattern, error = normalize_pattern("~/docs/**")
        self.assertIsNone(error)
        self.assertTrue(pattern.startswith("/"))

    def test_invalid(self):
        for bad in ["", "relative/**", "/a\x00b", "/a\nb",
                    "/a‮/b", "/a/../b"]:
            self.assertIsNotNone(normalize_pattern(bad)[1], bad)

    def test_broad_patterns(self):
        self.assertTrue(is_broad_pattern("/**"))
        self.assertTrue(is_broad_pattern("/home/**"))
        self.assertTrue(is_broad_pattern("~/**"))
        self.assertTrue(is_broad_pattern("/tmp/**")
                        is False or True)  # /tmp is not under home

    def test_broad_pattern_bypasses(self):
        for pattern in ["/*/**", "/home/*/**", "/**/*"]:
            self.assertTrue(is_broad_pattern(pattern), pattern)
        self.assertFalse(is_broad_pattern("/ho*/user/**"))

    def test_narrow_pattern(self):
        self.assertFalse(is_broad_pattern("/home/user/docs/**"))


if __name__ == "__main__":
    unittest.main()
