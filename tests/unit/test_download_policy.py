"""Exercise resolver redirects without contacting upstream services."""
import importlib.util
from pathlib import Path
import urllib.error
import urllib.request
import unittest

ROOT = Path(__file__).resolve().parents[2]
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
