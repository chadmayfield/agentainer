"""Check container release versions and shared-home upgrade decisions."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "rootfs/usr/local/lib/agentainer/release_version.py"
spec = importlib.util.spec_from_file_location("release_version", HELPER)
version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(version)


class VersionTests(unittest.TestCase):
    def test_semver_precedence(self):
        ordered = ["0.1.0-alpha", "0.1.0-alpha.1", "0.1.0-alpha.beta", "0.1.0-beta",
                   "0.1.0-beta.2", "0.1.0-beta.11", "0.1.0-rc.1", "0.1.0", "0.1.2", "0.1.10", "0.2.0"]
        self.assertEqual(sorted(reversed(ordered), key=version.version_key), ordered)

    def test_dated_builds_sort_numerically_before_target_release(self):
        ordered = ["0.1.0-dev.20261019.2", "0.1.0-dev.20261019.10",
                   "0.1.0-dev.20261020.1", "0.1.0"]
        self.assertEqual(sorted(reversed(ordered), key=version.version_key), ordered)

    def test_rejects_invalid_versions_and_non_container_tags(self):
        values = ["dev", "v0.1.0", "01.1.0", "0.01.0", "0.1.00", "0.1.0-alpha.01",
                  "0.1.0+build", "0.1.0-dev.20260230.1", "0.1.0-dev.20261019.0",
                  "0.1.0-dev.20261019.01", "0.1.0-dev", "0.1.0-dev.20261019",
                  "0.1.0-dev.20261019.1\nINJECTED=true", "0.1.0-" + "a" * 128]
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                version.version_key(value)

    def test_merge_subject_requires_exact_owner_and_release_branch(self):
        subject = "Merge pull request #12 from example/release/0.1.0-dev.20261019.1"
        self.assertEqual(version.from_merge(subject, "example"), "0.1.0-dev.20261019.1")
        for bad in [subject.replace("example/", "other/"), subject.replace("release/", "hotfix/"),
                    subject + " extra", subject + "\nINJECTED=true"]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                version.from_merge(bad, "example")

    def decision(self, candidate, records):
        with tempfile.TemporaryDirectory(prefix="cx-version-") as d:
            ledger = Path(d) / "ledger"
            ledger.write_text("".join("hash" + (" " + value if value else "") + "\n" for value in records))
            return version.newer_default(candidate, "hash", ledger)

    def test_newer_prerelease_can_replace_an_older_prerelease(self):
        self.assertTrue(self.decision("0.1.0-dev.20261019.10", ["0.1.0-dev.20261019.2"]))
        self.assertFalse(self.decision("0.1.0-dev.20261019.2", ["0.1.0-dev.20261019.10"]))

    def test_prerelease_never_replaces_a_stable_default(self):
        self.assertFalse(self.decision("0.2.0-dev.20261019.1", ["0.1.0"]))
        self.assertFalse(self.decision("0.2.0-dev.20261019.1", ["0.1.0", "0.1.0-dev.20261019.1"]))

    def test_stable_can_replace_its_prerelease_and_older_stable(self):
        self.assertTrue(self.decision("0.1.0", ["0.1.0-dev.20261019.1"]))
        self.assertTrue(self.decision("0.1.10", ["0.1.2"]))
        self.assertFalse(self.decision("0.1.2", ["0.1.10"]))

    def test_every_recorded_version_of_current_content_counts(self):
        self.assertFalse(self.decision("0.1.2", ["0.1.0", "0.1.10"]))
        self.assertFalse(self.decision("0.1.0", ["0.2.0-dev.20261019.1"]))

    def test_local_dev_and_unknown_user_content_never_upgrade(self):
        self.assertFalse(self.decision("dev", ["0.1.0"]))
        self.assertFalse(self.decision("0.1.0", []))
        self.assertTrue(self.decision("0.1.0", [""]))
