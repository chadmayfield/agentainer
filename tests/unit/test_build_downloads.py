"""Exercise build downloads against local failures without upstream services."""
import hashlib
import http.server
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[2]
BODY = b"agentainer release archive fixture\n"


@unittest.skipUnless(shutil.which("curl") and shutil.which("openssl"), "curl and openssl required")
class CurlTransferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.certificates = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.certificates.cleanup)
        root = Path(cls.certificates.name)
        cls.cert = root / "cert.pem"
        cls.key = root / "key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-days", "1", "-subj", "/CN=localhost", "-addext",
            "subjectAltName=IP:127.0.0.1", "-keyout", str(cls.key), "-out", str(cls.cert),
        ], check=True, capture_output=True)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "archive"
        self.requests = 0
        self.failures = 1
        self.body = BODY
        case = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                case.requests += 1
                interrupted = case.requests <= case.failures
                self.send_response(200)
                self.send_header("Content-Length", str(len(case.body)))
                self.end_headers()
                self.wfile.write(case.body[:5] if interrupted else case.body)
                self.wfile.flush()
                self.close_connection = True

            def log_message(self, *args):
                pass

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def fetch(self):
        env = dict(os.environ, CURL_CA_BUNDLE=str(self.cert), NO_PROXY="127.0.0.1")
        url = "https://127.0.0.1:%d/archive" % self.server.server_port
        return subprocess.run([
            "sh", str(ROOT / "build/fetch.sh"), url, "sha256",
            hashlib.sha256(BODY).hexdigest(), str(self.output),
        ], env=env, capture_output=True, text=True, timeout=30)

    def test_interrupted_transfer_retries_without_appending_partial_bytes(self):
        result = self.fetch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.requests, 2)
        self.assertEqual(self.output.read_bytes(), BODY)

    def test_retried_transfer_still_requires_the_pinned_checksum(self):
        self.body = b"different release archive bytes\n"
        result = self.fetch()
        self.assertEqual(self.requests, 2, result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)
        self.assertFalse(self.output.exists())

    def test_repeated_transfer_failures_stop_and_remove_partial_output(self):
        self.failures = 10
        result = self.fetch()
        self.assertEqual(self.requests, 4, result.stderr)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("download failed", result.stderr)
        self.assertFalse(self.output.exists())


@unittest.skipUnless(shutil.which("apt-get"), "APT required")
class AptIndexTests(unittest.TestCase):
    def test_snapshot_index_failure_returns_failure(self):
        text = (ROOT / "Containerfile").read_text()
        apt = shlex.split(re.search(r'&& APT="([^"]+)"', text)[1])
        update = shlex.split(re.search(r'&& \$APT (update[^\n]*)', text)[1].rstrip(" \\\t"))
        with tempfile.TemporaryDirectory() as directory, socket.socket() as unavailable:
            root = Path(directory)
            for name in ("parts", "lists", "lists/partial", "cache", "log"):
                (root / name).mkdir(exist_ok=True)
            (root / "status").write_text("")
            unavailable.bind(("127.0.0.1", 0))
            port = unavailable.getsockname()[1]
            (root / "sources.list").write_text(
                "deb http://127.0.0.1:%d fixture main\n" % port)
            config = root / "apt.conf"
            config.write_text("\n".join(
                '%s "%s";' % (key, root / value) for key, value in (
                    ("Dir::Etc::Parts", "parts"), ("Dir::Etc::main", "empty.conf"),
                    ("Dir::Etc::sourcelist", "sources.list"), ("Dir::Etc::sourceparts", "parts"),
                    ("Dir::State::lists", "lists"), ("Dir::State::status", "status"),
                    ("Dir::Cache", "cache"), ("Dir::Log", "log"),
                )) + "\n")
            # Disable retry delays for a permanently unavailable local fixture.
            command = apt + ["-o", "Acquire::Retries=0"] + update
            result = subprocess.run(command, env=dict(os.environ, APT_CONFIG=str(config)),
                                    capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Failed to fetch", result.stderr)


if __name__ == "__main__":
    unittest.main()
