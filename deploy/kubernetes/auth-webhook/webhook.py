#!/usr/bin/env python3
"""ContainerSSH auth and config webhook for one Agentainer user.

POST /pubkey   accepts the configured user with a key from AUTHORIZED_KEYS
POST /password always rejects
POST /config   sends the user to the persistent agentainer pod, with SFTP and local
               forwarding set from the switch file FEATURES_FILE (closed by default)
Standard library only. Formats follow ContainerSSH v0.6.0 containerssh-authconfig-openapi.json.
"""
import json
import os
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# The key types sshd(8) of OpenSSH 10.4 lists under AUTHORIZED_KEYS FILE FORMAT. Certificate types
# (*-cert-v01@openssh.com) are left out: sshd trusts a certificate only through a
# cert-authority line, so a certificate listed as a plain key must not grant access.
KEY_TYPES = frozenset((
    "sk-ecdsa-sha2-nistp256@openssh.com", "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com", "ssh-ed25519", "ssh-rsa",
))
MAX_BODY = 64 * 1024
# Connections handled at once. Each one holds a thread until it closes, so the cap
# bounds memory under the Deployment's 128Mi limit when a client opens many idle
# connections.
MAX_WORKERS = 16
REJECT_TIMEOUT = 1
MAX_REJECT_DRAIN = MAX_BODY + 16 * 1024
_BUSY_BODY = b'{"message": "too busy"}'
BUSY = (b"HTTP/1.0 503 Service Unavailable\r\nContent-Type: application/json\r\n"
        b"Content-Length: %d\r\nConnection: close\r\n\r\n" % len(_BUSY_BODY) + _BUSY_BODY)


DEFAULT_FEATURES = "/etc/agentainer-features/features"
# Largest switch file, in bytes, that load_features parses. The file holds two short
# lines plus comments, so 4096 bytes is ample. The cap bounds the read and parse work
# done on every /config request, and a larger file closes both switches.
MAX_FEATURES = 4096
# Each switch name maps its allowed values to on (True) or off (False).
FEATURE_VALUES = {
    "sftp": {"on": True, "off": False},
    "forwarding": {"local": True, "off": False},
}
# Container paths for /config. ContainerSSH v0.6.0 config/kubernetes.go KubernetesPodConfig:
# agentPath (json "agentPath") runs "forward-server" for port forwarding, and subsystems
# (json "subsystems") maps a subsystem name to the program it starts.
AGENT_PATH = "/usr/local/bin/containerssh-agent"
SUBSYSTEMS = {"sftp": "/usr/lib/openssh/sftp-server"}


class Settings:
    def __init__(self, user, keys_path, pod, namespace, features_path=DEFAULT_FEATURES):
        self.user, self.keys_path, self.pod, self.namespace = user, keys_path, pod, namespace
        self.features_path = features_path


def log(msg):
    print("webhook: " + msg, file=sys.stderr, flush=True)


def _closed(problem):
    # The message names the problem only. The file's content never reaches the log.
    log("features file %s; SFTP and forwarding closed" % problem)
    return {name: False for name in FEATURE_VALUES}


def load_features(path):
    """Return {"sftp": bool, "forwarding": bool} from the switch file. Read on every
    /config request, so a ConfigMap update applies to the next connection without a
    restart.

    Each line is "name=value". Blank lines and lines starting with "#" are ignored. A
    name that is absent is off and is logged by name. A malformed line, an unknown name
    or value, a duplicate name, undecodable bytes, a file over MAX_FEATURES bytes or any
    read error turns both off."""
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_FEATURES + 1)
    except FileNotFoundError:
        return _closed("missing")
    except Exception:  # noqa: BLE001 - any read failure must close, never open
        return _closed("unreadable")
    if len(data) > MAX_FEATURES:
        return _closed("too large")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _closed("is not UTF-8")
    found = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not name or "=" in value:
            return _closed("line %d is not name=value" % number)
        if name not in FEATURE_VALUES:
            return _closed("line %d has an unknown name" % number)
        if name in found:
            return _closed("line %d repeats a name" % number)
        if value not in FEATURE_VALUES[name]:
            return _closed("line %d has an unknown value" % number)
        found[name] = FEATURE_VALUES[name][value]
    for name in FEATURE_VALUES:
        if name not in found:
            # name comes from FEATURE_VALUES, not from the file.
            log("features file does not set %s; %s closed" % (name, name))
    return {name: found.get(name, False) for name in FEATURE_VALUES}


def security_config(features):
    """The config.security block for /config. Field names and modes follow ContainerSSH
    v0.6.0 config/security.go: SubsystemConfig (mode, allow) and ForwardingConfig.
    Mode "filter" runs only the subsystems in allow, and "disable" refuses them all
    (internal/security/handler_session.go OnSubsystem). forwardingMode covers local
    forwarding (ssh -L and ssh -D). Reverse, socket and X11 forwarding are always off."""
    sftp = features.get("sftp") is True
    forwarding = features.get("forwarding") is True
    return {
        "subsystem": {"mode": "filter", "allow": ["sftp"]} if sftp else {"mode": "disable"},
        "forwarding": {
            "forwardingMode": "enable" if forwarding else "disable",
            "reverseForwardingMode": "disable",
            "socketForwardingMode": "disable",
            "socketListenMode": "disable",
            "x11ForwardingMode": "disable",
        },
    }


def load_keys(path):
    """Return the set of 'type base64' pairs from an authorized_keys file. Read on every
    request, so a Secret update takes effect without a restart. A line with options
    ("restrict ssh-ed25519 AAAA...") is skipped: the webhook cannot enforce from=,
    command= or restrict, and accepting the key without them would widen access."""
    keys = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 2 and parts[0] in KEY_TYPES:
                keys.add(parts[0] + " " + parts[1])
    return keys


def echo(req):
    return {k: req.get(k) for k in ("username", "remoteAddress", "connectionId")}


def make_handler(s):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10
        request_timeout = 10

        def handle(self):
            # A whole-request deadline interrupts buffered header and body reads even
            # when the client keeps sending within the socket timeout.
            def expire():
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            deadline = threading.Timer(self.request_timeout, expire)
            deadline.daemon = True
            deadline.start()
            try:
                super().handle()
            except (ConnectionError, socket.timeout):
                # A disconnected client needs no response or traceback.
                return
            finally:
                deadline.cancel()

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
            except (ValueError, RecursionError):
                # json.loads raises RecursionError for deeply nested input.
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
                features = load_features(s.features_path)
                # "config" holds a partial ContainerSSH configuration with the same
                # structure as the YAML file (ContainerSSH v0.6 configuration server
                # reference). Security settings go under config.security, the
                # AppConfig "security" field (ContainerSSH v0.6.0 config/appconfig.go).
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
                    "agentPath": AGENT_PATH,
                    "subsystems": dict(SUBSYSTEMS),
                }}, "security": security_config(features)}
                self.log_message("config user=%s sftp=%s forwarding=%s", req.get("username"),
                                 features["sftp"], features["forwarding"])
            else:
                return self._reply(404, {"message": "not found"})
            return self._reply(200, out)

    return Handler


class BoundedServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that runs at most max_workers handler threads. A connection
    beyond that gets a 503 with bounded, nonblocking connection teardown."""

    def __init__(self, addr, handler, max_workers):
        self._slots = threading.BoundedSemaphore(max_workers)
        self._max_rejections = max_workers
        self._rejections = {}
        super().__init__(addr, handler)

    def process_request(self, request, client_address):
        self.service_actions()
        if not self._slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(BUSY)
                # Keep reading after the reply so in-flight uploads do not erase
                # the 503 through a TCP reset (RFC 9112, section 9.6).
                request.shutdown(socket.SHUT_WR)
                if len(self._rejections) < self._max_rejections:
                    request.setblocking(False)
                    self._rejections[request] = (time.monotonic() + REJECT_TIMEOUT, MAX_REJECT_DRAIN)
                    return
            except OSError:
                pass
            self.close_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def service_actions(self):
        # serve_forever calls this between accepts and on its poll interval.
        # Both the socket count and bytes read per socket stay bounded, without
        # adding handler threads or waiting for a stalled uploader.
        now = time.monotonic()
        for request, (deadline, remaining) in tuple(self._rejections.items()):
            close = now >= deadline
            if not close:
                try:
                    while remaining:
                        data = request.recv(min(4096, remaining))
                        if not data:
                            close = True
                            break
                        remaining -= len(data)
                    if remaining == 0:
                        close = True
                except BlockingIOError:
                    pass
                except OSError:
                    close = True
            if close:
                del self._rejections[request]
                self.close_request(request)
            else:
                self._rejections[request] = (deadline, remaining)
        super().service_actions()

    def server_close(self):
        for request in self._rejections:
            self.close_request(request)
        self._rejections.clear()
        super().server_close()


def make_server(addr, settings, max_workers=MAX_WORKERS):
    return BoundedServer(addr, make_handler(settings), max_workers)


def main():
    user = os.environ.get("AGENTAINER_USER")
    if not user:
        print("webhook: AGENTAINER_USER is required", file=sys.stderr)
        return 2
    s = Settings(user, os.environ.get("AUTHORIZED_KEYS", "/etc/agentainer-auth/authorized_keys"),
                 os.environ.get("AGENTAINER_POD", "agentainer-0"),
                 os.environ.get("AGENTAINER_NAMESPACE", "agentainer"),
                 os.environ.get("FEATURES_FILE", DEFAULT_FEATURES))
    make_server(("0.0.0.0", int(os.environ.get("LISTEN_PORT", "8080"))), s).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
