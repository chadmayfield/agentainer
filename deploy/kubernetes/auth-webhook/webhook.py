#!/usr/bin/env python3
"""ContainerSSH auth and config webhook for one Agentainer user (spec 15.2).

POST /pubkey   accepts the configured user with a key from AUTHORIZED_KEYS
POST /password always rejects
POST /config   sends the user to the persistent agentainer pod
Standard library only. Formats follow ContainerSSH v0.6.0 containerssh-authconfig-openapi.json.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The key types sshd(8) of OpenSSH 10.4 lists under AUTHORIZED_KEYS FILE FORMAT. Certificate types
# (*-cert-v01@openssh.com) are left out: sshd trusts a certificate only through a
# cert-authority line, so a certificate listed as a plain key must not grant access.
KEY_TYPES = frozenset((
    "sk-ecdsa-sha2-nistp256@openssh.com", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com", "ssh-ed25519", "ssh-rsa",
))
MAX_BODY = 64 * 1024


class Settings:
    def __init__(self, user, keys_path, pod, namespace):
        self.user, self.keys_path, self.pod, self.namespace = user, keys_path, pod, namespace


def load_keys(path):
    """Return the set of 'type base64' pairs from an authorized_keys file. Read on every
    request, so a Secret update takes effect without a restart. A line with options
    ("restrict ssh-ed25519 AAAA...") is skipped: the webhook cannot enforce from=,
    command= or restrict, and accepting the key without them would widen access."""
    keys = set()
    with open(path) as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[0] in KEY_TYPES:
                keys.add(parts[0] + " " + parts[1])
    return keys


def echo(req):
    return {k: req.get(k) for k in ("username", "remoteAddress", "connectionId")}


def make_handler(s):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10  # seconds per socket read, so a stalled client cannot hold a thread

        def _reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):  # noqa: N802 - name required by BaseHTTPRequestHandler
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = -1
            if length < 0:
                return self._reply(400, {"message": "invalid Content-Length"})
            if length > MAX_BODY:
                return self._reply(413, {"message": "request too large"})
            try:
                req = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(req, dict):
                    raise ValueError("not an object")
            except ValueError:
                return self._reply(400, {"message": "invalid JSON"})
            out = echo(req)
            if self.path == "/pubkey":
                offered = " ".join(str(req.get("publicKey", "")).split()[:2])
                try:
                    ok = req.get("username") == s.user and offered in load_keys(s.keys_path)
                except OSError:
                    ok = False
                out["success"] = ok
                self.log_message("pubkey user=%s success=%s", req.get("username"), ok)
            elif self.path == "/password":
                out["success"] = False
            elif self.path == "/config":
                out["config"] = {"kubernetes": {"pod": {
                    "mode": "persistent",
                    "metadata": {"name": s.pod, "namespace": s.namespace},
                    "createMissingPods": False,
                    "disableAgent": True,
                    # disableAgent drops the client's environment, TERM included
                    # (ContainerSSH v0.6.0 kubernetesPodImpl.go createExecLocked), and
                    # tmux exits with "open terminal failed" when TERM is unset.
                    "shellCommand": ["/usr/bin/env", "TERM=xterm-256color",
                                     "tmux", "new-session", "-A", "-s", "main"],
                }}}
            else:
                return self._reply(404, {"message": "not found"})
            return self._reply(200, out)

    return Handler


def make_server(addr, settings):
    return ThreadingHTTPServer(addr, make_handler(settings))


def main():
    user = os.environ.get("AGENTAINER_USER")
    if not user:
        print("webhook: AGENTAINER_USER is required", file=sys.stderr)
        return 2
    s = Settings(user, os.environ.get("AUTHORIZED_KEYS", "/etc/agentainer-auth/authorized_keys"),
                 os.environ.get("AGENTAINER_POD", "agentainer-0"),
                 os.environ.get("AGENTAINER_NAMESPACE", "agentainer"))
    make_server(("0.0.0.0", int(os.environ.get("LISTEN_PORT", "8080"))), s).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
