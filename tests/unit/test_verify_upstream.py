import hashlib
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import verify_upstream as vu


class PublisherVerificationTests(unittest.TestCase):
    def test_attestation_enforces_exact_repository_workflow_and_ref(self):
        data = b"release bytes"
        release = {"tag_name": "0.13.1", "assets": [
            {"name": "uv.tar.gz", "browser_download_url": "https://example.com/uv"}]}
        with patch.object(vu.subprocess, "run") as run:
            vu.verify_asset("astral-sh/uv", release, "uv.tar.gz", hashlib.sha256(data).hexdigest(),
                            lambda url: data)
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["gh", "attestation", "verify"])
        self.assertIn("astral-sh/uv", command)
        self.assertIn("https://github.com/astral-sh/uv/.github/workflows/release.yml@refs/heads/main", command)
        self.assertTrue(run.call_args.kwargs["check"])

    def test_changed_download_is_rejected_before_attestation(self):
        release = {"tag_name": "0.13.1", "assets": [
            {"name": "uv.tar.gz", "browser_download_url": "https://example.com/uv"}]}
        with patch.object(vu.subprocess, "run") as run:
            with self.assertRaises(vu.VerificationFailed):
                vu.verify_asset("astral-sh/uv", release, "uv.tar.gz", "a" * 64, lambda url: b"wrong")
            run.assert_not_called()

    def test_signed_checksum_must_match_selected_pin(self):
        release = {"tag_name": "v4.54.1", "assets": [
            {"name": name, "browser_download_url": "https://example.com/" + name}
            for name in ["checksums-bsd", "checksums-bsd.bundle"]]}
        with patch.object(vu.subprocess, "run") as run:
            with self.assertRaises(vu.VerificationFailed):
                vu.verify_asset("mikefarah/yq", release, "yq_linux_arm64", "a" * 64,
                                lambda url: b"SHA256 (yq_linux_arm64) = " + b"b" * 64)
            run.assert_not_called()

    def test_failed_signature_propagates(self):
        release = {"tag_name": "v4.54.1", "assets": [
            {"name": name, "browser_download_url": "https://example.com/" + name}
            for name in ["checksums-bsd", "checksums-bsd.bundle"]]}
        with patch.object(vu.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "cosign")):
            with self.assertRaises(vu.VerificationFailed):
                vu.verify_asset("mikefarah/yq", release, "yq_linux_arm64", "a" * 64,
                                lambda url: b"SHA256 (yq_linux_arm64) = " + b"a" * 64)

    def test_unverified_publisher_is_reported_as_unsupported(self):
        self.assertFalse(vu.verify_asset("example/unknown", {}, "asset", "a" * 64, None))
