# SPDX-License-Identifier: GPL-3.0-or-later
import http.client
import json
import os
import socket


DEFAULT_SOCKET = "/run/snapd.socket"


class SnapdError(Exception):
    def __init__(self, message, kind=None, status_code=None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.status_code = status_code


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path, timeout=10):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(self.timeout)
            sock.connect(self.socket_path)
        except OSError:
            sock.close()
            raise
        self.sock = sock


class Client:
    def __init__(self, socket_path=None):
        self.socket_path = socket_path or os.environ.get("SNAPD_SOCKET",
                                                         DEFAULT_SOCKET)

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        conn = UnixHTTPConnection(self.socket_path)
        try:
            conn.request(method, path, body=data,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
        except OSError as e:
            raise SnapdError(str(e), kind="connection-failed")
        finally:
            conn.close()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise SnapdError("snapd returned malformed JSON",
                             status_code=resp.status)
        if not isinstance(payload, dict):
            raise SnapdError("unexpected snapd response",
                             status_code=resp.status)
        if payload.get("type") == "error":
            result = payload.get("result")
            if not isinstance(result, dict):
                result = {}
            raise SnapdError(result.get("message", "snapd error"),
                             kind=result.get("kind"), status_code=resp.status)
        return payload.get("result")

    def list_snaps(self):
        return self._request("GET", "/v2/snaps")
