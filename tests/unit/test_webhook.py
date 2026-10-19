import importlib.util
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

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
CERT = "ssh-ed25519-cert-v01@openssh.com AAAAIHNzaC1lZDI1NTE5LWNlcnQtdjAxQG9wZW5zc2guY29tExampleCert"


class WebhookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.NamedTemporaryFile("w", delete=False)
        cls.keys.write("# comment\n\n" + KEY + "\nrestrict,no-pty " + OPTKEY + "\n"
                       + ECDSA + " a@example.com\n" + SK + "\n" + RSA + "\n" + CERT + " c@example.com\n")
        cls.keys.close()
        settings = webhook.Settings(user="dev", keys_path=cls.keys.name, pod="agentainer-0", namespace="agentainer")
        cls.server = webhook.make_server(("127.0.0.1", 0), settings)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
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
        for key in (ECDSA, SK, RSA):
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
        r = c.getresponse()
        return r.status

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


if __name__ == "__main__":
    unittest.main()
