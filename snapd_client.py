import http.client
import json
import os
import socket

DEFAULT_SOCKET = os.environ.get("SNAPD_SOCKET", "/run/snapd.socket")

# UNVERIFIED: permission names other than "read". Likely "write", "execute".
PERMISSIONS = ("read", "write", "execute")
# UNVERIFIED: lifespan values other than "forever" and "session".
LIFESPANS = ("forever", "session")
# UNVERIFIED: outcome value "deny".
OUTCOMES = ("allow", "deny")

PROMPTING_NOT_RUNNING = "apparmor-prompting-not-running"


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
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class Client:
    def __init__(self, socket_path=DEFAULT_SOCKET):
        self.socket_path = socket_path

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        conn = UnixHTTPConnection(self.socket_path)
        try:
            conn.request(method, path, body=data,
                         headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            raw = resp.read()
        finally:
            conn.close()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise SnapdError("snapd returned malformed JSON", status_code=resp.status)
        if payload.get("type") == "error":
            result = payload.get("result") or {}
            raise SnapdError(result.get("message", "snapd error"),
                             kind=result.get("kind"), status_code=resp.status)
        return payload.get("result")

    def list_rules(self):
        rules = self._request("GET", "/v2/interfaces/requests/rules")
        if not isinstance(rules, list):
            raise SnapdError("unexpected rules response")
        return rules

    def add_rule(self, snap, path_pattern, permission="read",
                 outcome="allow", lifespan="forever"):
        body = {
            "action": "add",
            "rule": {
                "snap": snap,
                "interface": "home",
                "constraints": {
                    "path-pattern": path_pattern,
                    "permissions": {
                        permission: {"outcome": outcome, "lifespan": lifespan},
                    },
                },
            },
        }
        return self._request("POST", "/v2/interfaces/requests/rules", body)

    def remove_rule(self, rule_id):
        return self._request("POST", "/v2/interfaces/requests/rules/%s" % rule_id,
                             {"action": "remove"})

    def list_snaps(self):
        # UNVERIFIED: GET /v2/snaps reachable from inside a Flatpak.
        return self._request("GET", "/v2/snaps")
