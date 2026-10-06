# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
import socket
import tempfile
import threading
import unittest

from snapd_client import Client, SnapdError


class MockSnapd:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self.snaps = []
        self.posts = []  # (path, parsed_json_body) in order
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
        elif method == "GET" and path == "/v2/snaps":
            status, payload = 200, {"type": "sync", "status-code": 200,
                                    "result": self.snaps}
        else:
            status, payload = 404, {"type": "error", "status-code": 404,
                                    "result": {"message": "not found",
                                               "kind": "not-found"}}
        wire = payload if isinstance(payload, bytes) else \
            json.dumps(payload).encode()
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

    def test_list_snaps(self):
        self.server.snaps = [{"name": "firefox", "type": "app",
                              "version": "1.0", "summary": "browser"},
                             {"name": "core24", "type": "base"}]
        snaps = self.client.list_snaps()
        self.assertEqual(len(snaps), 2)
        self.assertEqual(snaps[0]["name"], "firefox")

    def test_error_with_kind(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400,
            "result": {"message": "conflict", "kind": "some-kind"},
        }))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_snaps()
        self.assertEqual(ctx.exception.kind, "some-kind")
        self.assertEqual(ctx.exception.message, "conflict")

    def test_connection_failure(self):
        bad = Client(socket_path=os.path.join(self.tmpdir.name,
                                              "missing.socket"))
        with self.assertRaises(SnapdError) as ctx:
            bad.list_snaps()
        self.assertEqual(ctx.exception.kind, "connection-failed")

    def test_malformed_json(self):
        self.server.responses.append((200, b"not-json"))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_snaps()
        self.assertIn("malformed", ctx.exception.message)

    def test_non_dict_json(self):
        self.server.responses.append((200, [1, 2]))
        with self.assertRaises(SnapdError):
            self.client.list_snaps()

    def test_non_dict_error_result(self):
        self.server.responses.append((400, {
            "type": "error", "status-code": 400, "result": "oops",
        }))
        with self.assertRaises(SnapdError) as ctx:
            self.client.list_snaps()
        self.assertEqual(ctx.exception.message, "snapd error")


if __name__ == "__main__":
    unittest.main()
