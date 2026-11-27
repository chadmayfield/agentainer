"""Exercise resolver redirects without contacting upstream services."""
import email.message
import importlib.util
import io
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import urllib.response
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("download_bump", ROOT / "scripts/bump_versions.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


class RedirectPolicyTests(unittest.TestCase):
    def redirect(self, destination):
        request = urllib.request.Request("https://api.github.com/example", headers={"Authorization": "Bearer fake"})
        return bump.HTTPSRedirectHandler().redirect_request(request, None, 302, "redirect", {}, destination)

    def test_downgrade_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.redirect("http://example.com/file")

    def test_cross_origin_does_not_receive_authorization(self):
        for url in ("https://example.com/file", "https://api.github.com:444/file"):
            self.assertIsNone(self.redirect(url).get_header("Authorization"))

    def test_same_origin_keeps_authorization(self):
        self.assertEqual(self.redirect("https://api.github.com/next").get_header("Authorization"), "Bearer fake")


class FetchRedirectTests(unittest.TestCase):
    """Drive the fetchers through a fake HTTP and HTTPS transport that answers with redirects."""

    def serve(self, routes):
        seen = []

        def transport(handler, request):
            seen.append((request.full_url, request.get_header("Authorization")))
            code, location = routes.get(request.full_url, (200, None))
            headers = email.message.Message()
            if location:
                headers["Location"] = location
            response = urllib.response.addinfourl(io.BytesIO(b"body"), headers, request.full_url, code)
            response.msg = "Found" if location else "OK"
            return response

        for handler, method in ((urllib.request.HTTPSHandler, "https_open"),
                                (urllib.request.HTTPHandler, "http_open")):
            patch = mock.patch.object(handler, method, transport)
            patch.start()
            self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ, {"GITHUB_TOKEN": "fake"})
        env.start()
        self.addCleanup(env.stop)
        return seen

    def test_cross_origin_redirect_drops_authorization(self):
        seen = self.serve({"https://api.github.com/start": (302, "https://example.com/file")})
        self.assertEqual(bump.fetch("https://api.github.com/start"), "body")
        self.assertEqual(seen, [("https://api.github.com/start", "Bearer fake"),
                                ("https://example.com/file", None)])

    def test_same_origin_redirect_keeps_authorization(self):
        seen = self.serve({"https://api.github.com/start": (302, "https://api.github.com/next")})
        self.assertEqual(bump.fetch("https://api.github.com/start"), "body")
        self.assertEqual(seen[-1], ("https://api.github.com/next", "Bearer fake"))

    def test_downgrade_redirect_fails_both_fetchers(self):
        seen = self.serve({"https://example.com/start": (302, "http://example.com/file")})
        for fetcher in (bump.fetch, bump.fetch_bytes):
            with self.subTest(fetcher=fetcher.__name__):
                with self.assertRaises(bump.LookupFailed):
                    fetcher("https://example.com/start")
        self.assertNotIn("http://example.com/file", [url for url, _ in seen])
