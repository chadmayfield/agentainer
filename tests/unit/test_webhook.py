import importlib.util
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
