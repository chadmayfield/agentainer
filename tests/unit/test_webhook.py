import importlib.util
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "webhook", os.path.join(HERE, "..", "..", "deploy", "kubernetes", "auth-webhook", "webhook.py"))
webhook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(webhook)

KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyOnlyForTests user@example.com"
OTHER = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDifferentKeyForTests"
OPTKEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKeyWithOptionsForTests"
ECDSA = "ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYExampleEcdsaKey"
SK = "sk-ssh-ed25519@openssh.com AAAAGnNrLXNzaC1lZDI1NTE5QG9wZW5zc2guY29tExampleSkKey"
RSA = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABExampleRsaKey"
ECDSA384 = "ecdsa-sha2-nistp384 AAAAE2VjZHNhLXNoYTItbmlzdHAzODQExampleEcdsa384Key"
ECDSA521 = "ecdsa-sha2-nistp521 AAAAE2VjZHNhLXNoYTItbmlzdHA1MjEExampleEcdsa521Key"
SKECDSA = "sk-ecdsa-sha2-nistp256@openssh.com AAAAInNrLWVjZHNhLXNoYTItbmlzdHAyNTZAb3BlbnNzaC5jb20ExampleSkEcdsa"
CERT = "ssh-ed25519-cert-v01@openssh.com AAAAIHNzaC1lZDI1NTE5LWNlcnQtdjAxQG9wZW5zc2guY29tExampleCert"


class WebhookTests(unittest.TestCase):
    def test_non_utf8_key_comment_does_not_disable_valid_keys(self):
        with tempfile.NamedTemporaryFile("wb") as file:
            file.write(KEY.encode() + b" invalid-comment-\xe9\n")
            file.flush()
            self.assertIn(" ".join(KEY.split()[:2]), webhook.load_keys(file.name))
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.NamedTemporaryFile("w", delete=False)
        cls.keys.write("# comment\n\n" + KEY + "\nrestrict,no-pty " + OPTKEY + "\n"
                       + ECDSA + " a@example.com\n" + SK + "\n" + RSA + "\n" + ECDSA384 + "\n" + ECDSA521 + "\n"
                       + SKECDSA + "\n" + CERT + " c@example.com\n")
        cls.keys.close()
        settings = webhook.Settings(user="dev", keys_path=cls.keys.name, pod="agentainer-0", namespace="agentainer")
        cls.server = webhook.make_server(("127.0.0.1", 0), settings)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        os.unlink(cls.keys.name)

    def post(self, path, body):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path),
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def base(self, **kw):
        b = {"username": "dev", "remoteAddress": "203.0.113.5:5000", "connectionId": "abc"}
        b.update(kw)
        return b

    def test_known_key_and_user_accepted(self):
        r = self.post("/pubkey", self.base(publicKey=KEY.rsplit(" ", 1)[0]))
        self.assertTrue(r["success"])
        self.assertEqual((r["username"], r["connectionId"], r["remoteAddress"]), ("dev", "abc", "203.0.113.5:5000"))

    def test_containerssh_key_shape_accepted(self):
        # ContainerSSH v0.6.0 sends strings.TrimSpace(ssh.MarshalAuthorizedKey(key)):
        # "type base64" with no comment and no trailing newline (internal/sshserver/serverImpl.go).
        for key in (ECDSA, SK, RSA, ECDSA384, ECDSA521, SKECDSA):
            with self.subTest(key=key.split()[0]):
                self.assertTrue(self.post("/pubkey", self.base(publicKey=key))["success"])

    def test_certificate_line_is_refused(self):
        # sshd trusts certificates only through a cert-authority line, so a certificate
        # listed as a plain key must not grant access.
        self.assertFalse(self.post("/pubkey", self.base(publicKey=CERT))["success"])

    def test_unknown_path_is_404(self):
        req = urllib.request.Request("http://127.0.0.1:%d/other" % self.port, data=b"{}")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 404)

    def test_key_with_options_is_refused(self):
        # Options such as from=, restrict or command= are not enforced, so such keys are
        # refused instead of being accepted without their restrictions.
        self.assertFalse(self.post("/pubkey", self.base(publicKey=OPTKEY))["success"])

    def raw(self, headers, body=b""):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.putrequest("POST", "/pubkey")
        for k, v in headers.items():
            c.putheader(k, v)
        c.endheaders()
        if body:
            c.send(body)
        try:
            return c.getresponse().status
        finally:
            c.close()

    def test_negative_content_length_is_rejected(self):
        self.assertEqual(self.raw({"Content-Length": "-1"}), 400)

    def test_oversized_body_is_rejected(self):
        self.assertEqual(self.raw({"Content-Length": str(10 * 1024 * 1024)}), 413)

    def test_unknown_key_rejected(self):
        self.assertFalse(self.post("/pubkey", self.base(publicKey=OTHER))["success"])

    def test_wrong_user_rejected(self):
        self.assertFalse(self.post("/pubkey", self.base(username="root", publicKey=KEY))["success"])

    def test_password_always_rejected(self):
        self.assertFalse(self.post("/password", self.base(passwordBase64="cGFzcw=="))["success"])

    def test_config_points_at_persistent_pod(self):
        pod = self.post("/config", self.base())["config"]["kubernetes"]["pod"]
        self.assertEqual(pod["mode"], "persistent")
        self.assertEqual(pod["metadata"], {"name": "agentainer-0", "namespace": "agentainer"})
        self.assertFalse(pod["createMissingPods"])
        self.assertTrue(pod["disableAgent"])
        # disableAgent drops the client's TERM, and tmux 3.6 exits without one.
        self.assertEqual(pod["shellCommand"],
                         ["/usr/bin/env", "TERM=xterm-256color", "tmux", "new-session", "-A", "-s", "main"])
        self.assertNotIn("spec", pod)

    def test_bad_json_is_400(self):
        req = urllib.request.Request("http://127.0.0.1:%d/pubkey" % self.port, data=b"{bad")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 400)

    def test_deeply_nested_json_is_400(self):
        # json.loads raises RecursionError, not ValueError, for deep nesting. The body
        # stays under MAX_BODY, so it reaches the parser.
        for body in (b"[" * 60000, b'{"a":' * 12000):
            with self.subTest(body=body[:5]):
                self.assertLess(len(body), webhook.MAX_BODY)
                self.assertEqual(self.raw({"Content-Length": str(len(body))}, body), 400)


CLOSED = {"sftp": False, "forwarding": False}
# ContainerSSH v0.6.0 config/security.go: SubsystemConfig and ForwardingConfig.
SUBSYSTEM_CLOSED = {"mode": "disable"}
SUBSYSTEM_SFTP = {"mode": "filter", "allow": ["sftp"]}
ALWAYS_OFF = ("reverseForwardingMode", "socketForwardingMode", "socketListenMode", "x11ForwardingMode")


class FeatureSwitchTests(unittest.TestCase):
    """The switch file turns SFTP and local forwarding on per connection. Anything
    other than a well-formed file leaves both closed."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "features")
        self.keys = os.path.join(self.dir.name, "authorized_keys")
        with open(self.keys, "w") as f:
            f.write(KEY + "\n")
        settings = webhook.Settings(user="dev", keys_path=self.keys, pod="agentainer-0",
                                    namespace="agentainer", features_path=self.path)
        self.server = webhook.make_server(("127.0.0.1", 0), settings)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.dir.cleanup()

    def write(self, data):
        with open(self.path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())

    def config(self):
        body = {"username": "dev", "remoteAddress": "203.0.113.5:5000", "connectionId": "abc"}
        req = urllib.request.Request("http://127.0.0.1:%d/config" % self.port,
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def assert_closed_response(self, r):
        sec = r["config"]["security"]
        self.assertEqual(sec["subsystem"], SUBSYSTEM_CLOSED)
        self.assertEqual(sec["forwarding"]["forwardingMode"], "disable")
        for key in ALWAYS_OFF:
            self.assertEqual(sec["forwarding"][key], "disable")

    def test_settings_reads_features_path_default(self):
        s = webhook.Settings(user="dev", keys_path=self.keys, pod="p", namespace="n")
        self.assertEqual(s.features_path, "/etc/agentainer-features/features")

    def test_features_default_closed_without_file(self):
        self.assertEqual(webhook.load_features(self.path), CLOSED)
        self.assert_closed_response(self.config())

    def test_each_key_missing_is_closed(self):
        self.write("sftp=on\n")
        self.assertEqual(webhook.load_features(self.path), {"sftp": True, "forwarding": False})
        self.write("forwarding=local\n")
        self.assertEqual(webhook.load_features(self.path), {"sftp": False, "forwarding": True})
        self.write("# only a comment\n\n")
        self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_blank_lines_and_comments_are_ignored(self):
        self.write("# switch\n\n  # indented comment\r\nsftp=on\r\n\nforwarding=local\n")
        self.assertEqual(webhook.load_features(self.path), {"sftp": True, "forwarding": True})

    def test_malformed_line_closes_all(self):
        for bad in ("sftp\n", "sftp on\n", "=on\n", "sftp=on=on\n", "sftp = on\n", "sftp=on # note\n",
                    "SFTP=on\n", "telnet=on\n"):
            with self.subTest(bad=bad):
                self.write("sftp=on\nforwarding=local\n" + bad)
                self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_duplicate_key_closes_all(self):
        for text in ("sftp=on\nsftp=on\nforwarding=local\n", "sftp=on\nforwarding=local\nforwarding=off\n"):
            with self.subTest(text=text):
                self.write(text)
                self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_unknown_value_closes_all(self):
        for bad in ("sftp=yes", "sftp=true", "sftp=ON", "sftp=", "forwarding=on", "forwarding=remote",
                    "forwarding=all", "sftp=local", "forwarding=enable"):
            with self.subTest(bad=bad):
                other = "forwarding=local" if bad.startswith("sftp") else "sftp=on"
                self.write(other + "\n" + bad + "\n")
                self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_undecodable_bytes_close_all(self):
        self.write(b"sftp=on\nforwarding=local\n# \xff\xfe\n")
        self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_oversized_file_closes_all(self):
        self.write("sftp=on\nforwarding=local\n" + "#" * webhook.MAX_FEATURES + "\n")
        self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_read_error_closes_all(self):
        # Mocking open keeps the test meaningful when it runs as root, which ignores
        # file modes.
        self.write("sftp=on\nforwarding=local\n")
        with mock.patch("builtins.open", side_effect=OSError("denied")):
            self.assertEqual(webhook.load_features(self.path), CLOSED)
        with mock.patch("builtins.open", side_effect=IsADirectoryError("dir")):
            self.assertEqual(webhook.load_features(self.path), CLOSED)

    def test_sftp_on_allows_only_sftp(self):
        self.write("sftp=on\nforwarding=off\n")
        sec = self.config()["config"]["security"]
        self.assertEqual(sec["subsystem"], SUBSYSTEM_SFTP)
        self.assertEqual(sec["forwarding"]["forwardingMode"], "disable")

    def test_forwarding_local_enables_only_local_forwarding(self):
        self.write("sftp=off\nforwarding=local\n")
        sec = self.config()["config"]["security"]
        self.assertEqual(sec["forwarding"]["forwardingMode"], "enable")
        self.assertEqual(sec["subsystem"], SUBSYSTEM_CLOSED)
        for key in ALWAYS_OFF:
            self.assertEqual(sec["forwarding"][key], "disable")

    def test_reverse_socket_x11_always_disabled(self):
        for text in ("", "sftp=on\nforwarding=local\n", "sftp=off\nforwarding=off\n", "bad\n"):
            with self.subTest(text=text):
                self.write(text)
                fwd = self.config()["config"]["security"]["forwarding"]
                self.assertEqual(set(fwd), {"forwardingMode"} | set(ALWAYS_OFF))
                for key in ALWAYS_OFF:
                    self.assertEqual(fwd[key], "disable")

    def test_switch_change_applies_on_next_request(self):
        self.write("sftp=off\nforwarding=off\n")
        self.assert_closed_response(self.config())
        self.write("sftp=on\nforwarding=local\n")
        sec = self.config()["config"]["security"]
        self.assertEqual(sec["subsystem"], SUBSYSTEM_SFTP)
        self.assertEqual(sec["forwarding"]["forwardingMode"], "enable")
        os.unlink(self.path)
        self.assert_closed_response(self.config())

    def test_features_file_contents_not_logged(self):
        marker = "Zq7MarkerX"
        cases = (marker + "=on\n", "sftp=" + marker + "\n", "sftp=on\nsftp=" + marker + "\n",
                 "sftp " + marker + "\n", ("# " + marker + "\n").encode() + b"\xff\n")
        for data in cases:
            with self.subTest(data=data):
                self.write(data)
                with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                    self.assertEqual(webhook.load_features(self.path), CLOSED)
                    self.assert_closed_response(self.config())
                log = err.getvalue()
                # The fixed message proves the log was captured.
                self.assertIn("features file", log)
                self.assertNotIn(marker, log)

    def test_security_lives_under_config(self):
        r = self.config()
        self.assertIn("security", r["config"])
        self.assertNotIn("security", r)
        self.assertEqual(set(r), {"username", "remoteAddress", "connectionId", "config"})

    def test_config_sets_agent_path_and_subsystem(self):
        pod = self.config()["config"]["kubernetes"]["pod"]
        self.assertEqual(pod["agentPath"], "/usr/local/bin/containerssh-agent")
        self.assertEqual(pod["subsystems"], {"sftp": "/usr/lib/openssh/sftp-server"})


class ConcurrencyLimitTests(unittest.TestCase):
    """The server handles at most max_workers connections at once and answers 503
    beyond that, so many idle connections cannot exhaust the pod's memory."""

    def setUp(self):
        self.keys = tempfile.NamedTemporaryFile("w", delete=False)
        self.keys.write(KEY + "\n")
        self.keys.close()
        settings = webhook.Settings(user="dev", keys_path=self.keys.name, pod="agentainer-0", namespace="agentainer")
        self.server = webhook.make_server(("127.0.0.1", 0), settings, max_workers=2)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.idle = []

    def tearDown(self):
        for s in self.idle:
            s.close()
        self.server.shutdown()
        self.server.server_close()
        os.unlink(self.keys.name)

    def status(self):
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            c.request("POST", "/password", body=b"{}")
            return c.getresponse().status
        except (ConnectionError, http.client.HTTPException):
            return None
        finally:
            c.close()

    def test_trickling_headers_and_body_cannot_retain_worker_slots(self):
        import time
        handler = self.server.RequestHandlerClass
        with mock.patch.object(handler, "request_timeout", 0.25, create=True):
            for prefix in (b"POST /password HTTP/1.0\r\nX-Slow: ",
                           b"POST /password HTTP/1.0\r\nContent-Length: 1000\r\n\r\n"):
                clients = [socket.create_connection(("127.0.0.1", self.port)) for _ in range(2)]
                self.idle.extend(clients)
                for client in clients:
                    client.sendall(prefix)
                deadline = time.monotonic() + 0.7
                while time.monotonic() < deadline:
                    for client in clients:
                        try:
                            client.sendall(b" ")
                        except OSError:
                            pass
                    time.sleep(0.04)
                self.assertEqual(self.status(), 200, "trickle retained every worker beyond its deadline")
                for client in clients:
                    client.close()
                self.idle = []

    def test_connections_beyond_the_limit_get_503(self):
        import socket
        import time
        self.assertEqual(self.status(), 200)
        def wait_slots(expected):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                # Observe readiness under the semaphore's own condition lock.
                with self.server._slots._cond:
                    if self.server._slots._value == expected:
                        return
                time.sleep(0.01)
            self.fail("server did not reach %d free worker slots" % expected)

        wait_slots(2)  # the initial request has released its worker
        for _ in range(2):
            self.idle.append(socket.create_connection(("127.0.0.1", self.port), timeout=5))
        wait_slots(0)
        self.assertEqual(self.status(), 503)
        for s in self.idle:
            s.close()
        self.idle = []
        deadline = time.time() + 5
        while self.status() != 200 and time.time() < deadline:
            time.sleep(0.1)
        self.assertEqual(self.status(), 200)


class OverloadCloseTests(unittest.TestCase):
    def setUp(self):
        self.server = webhook.BoundedServer(("127.0.0.1", 0), lambda *args: None, max_workers=1)
        self.addCleanup(self.server.server_close)
        self.server._slots.acquire()
        self.addCleanup(self.server._slots.release)

    def reject(self):
        client, accepted = socket.socketpair()
        self.addCleanup(client.close)
        self.addCleanup(accepted.close)
        client.settimeout(2)
        self.server.process_request(accepted, ("127.0.0.1", 0))
        response = b""
        while True:
            data = client.recv(4096)
            if not data:
                break
            response += data
        self.assertEqual(response, webhook.BUSY)
        return client, accepted

    def test_inflight_upload_survives_early_503(self):
        client, accepted = self.reject()
        # Model separate HTTP header/body writes still in flight after an early reply.
        client.sendall(b"POST /password HTTP/1.1\r\nContent-Length: 2\r\n\r\n")
        self.server.service_actions()
        client.sendall(b"{}")
        client.shutdown(socket.SHUT_WR)
        self.server.service_actions()
        self.assertEqual(accepted.fileno(), -1)

    def test_idle_rejection_is_nonblocking_and_expires(self):
        with mock.patch.object(webhook.time, "monotonic", return_value=100):
            client, accepted = self.reject()
            self.assertFalse(accepted.getblocking())
            self.server.service_actions()
            self.assertNotEqual(accepted.fileno(), -1)
        with mock.patch.object(webhook.time, "monotonic", return_value=102):
            self.server.service_actions()
        self.assertEqual(accepted.fileno(), -1)

    def test_rejection_sockets_are_capped_without_starting_threads(self):
        with mock.patch("threading.Thread", side_effect=AssertionError("unexpected worker")):
            first, retained = self.reject()
            second, overflow = self.reject()
        self.assertNotEqual(retained.fileno(), -1)
        self.assertEqual(overflow.fileno(), -1)

    def test_upload_drain_has_a_byte_limit(self):
        with mock.patch.object(webhook.time, "monotonic", return_value=100):
            client, accepted = self.reject()
            remaining = webhook.MAX_REJECT_DRAIN
            # Feed chunks so the check does not depend on the OS socket-buffer size.
            while remaining:
                size = min(4096, remaining)
                client.sendall(b"x" * size)
                self.server.service_actions()
                remaining -= size
        self.assertEqual(accepted.fileno(), -1)

    def test_server_close_releases_idle_rejections(self):
        client, accepted = self.reject()
        self.assertNotEqual(accepted.fileno(), -1)
        self.server.server_close()
        self.assertEqual(accepted.fileno(), -1)

    def test_bind_failure_preserves_the_socket_error(self):
        with self.assertRaises(OSError):
            webhook.BoundedServer(self.server.server_address, lambda *args: None, max_workers=1)


if __name__ == "__main__":
    unittest.main()
