"""Verify release gates with real temporary Git repositories and GPG signatures."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("tag_guard", ROOT / "scripts/check_release_tag.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class SignedTagTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory(prefix="cx-tag-fixture-")
        cls.env = dict(os.environ, GNUPGHOME=cls.keys.name, GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_CONFIG_NOSYSTEM="1")
        cls.fingerprints = []
        cls.public = ""
        for name in ("release", "other"):
            uid = "Test %s <%s@example.com>" % (name, name)
            cls.gpg("--quick-gen-key", uid, "ed25519", "sign", "never")
            listing = cls.gpg("--with-colons", "--fingerprint", uid)
            fpr = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
            cls.fingerprints.append(fpr)
            cls.public += cls.gpg("--armor", "--export", fpr)

    @classmethod
    def gpg(cls, *args):
        return subprocess.check_output(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback",
                                        "--passphrase", "", *args], env=cls.env, text=True)

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.repo = tempfile.TemporaryDirectory(prefix="cx-tag-repo-")
        self.addCleanup(self.repo.cleanup)
        self.old_cwd = os.getcwd()
        os.chdir(self.repo.name)
        self.addCleanup(os.chdir, self.old_cwd)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test User")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "gpg.program", shutil.which("gpg"))
        self.git("commit", "--allow-empty", "-m", "base")
        self.git("switch", "-c", "release/example")
        self.git("commit", "--allow-empty", "-m", "release changes")
        self.git("switch", "main")
        self.version = "0.1.0-dev.20261019.1"
        self.tag = "v" + self.version
        self.git("merge", "--no-ff", "-m", "Merge pull request #1 from example/release/" + self.version,
                 "release/example")
        self.sha = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.sha)

    def git(self, *args, input=None):
        return subprocess.run(["git", *args], env=self.env, input=input, check=True,
                              capture_output=True, text=True).stdout.strip()

    def sign(self, key=0):
        self.git("tag", "-s", "-u", self.fingerprints[key], self.tag, "-m", "Test release")

    def check(self, **kwargs):
        return guard.check(kwargs.get("tag", self.tag), kwargs.get("sha", self.sha), "example",
                           self.fingerprints[0], public_key=self.public)

    def test_trusted_signed_merge_tag_passes(self):
        self.sign()
        self.assertEqual(self.check(), self.version)

    def test_lightweight_and_unsigned_annotated_tags_fail(self):
        self.git("tag", self.tag)
        with self.assertRaises(ValueError): self.check()
        self.git("tag", "-d", self.tag)
        self.git("tag", "-a", self.tag, "-m", "unsigned")
        with self.assertRaises(ValueError): self.check()

    def test_other_key_in_imported_keyring_cannot_authorize_release(self):
        self.sign(key=1)
        with self.assertRaises(ValueError): self.check()

    def test_signed_tag_content_tampering_fails(self):
        self.sign()
        content = self.git("cat-file", "-p", "refs/tags/" + self.tag) + "\n"
        altered = content.replace("Test release", "Changed release")
        obj = self.git("hash-object", "-t", "tag", "-w", "--stdin", input=altered)
        self.git("update-ref", "refs/tags/" + self.tag, obj)
        with self.assertRaises(ValueError): self.check()

    def test_wrong_event_commit_and_off_main_commit_fail(self):
        self.sign()
        with self.assertRaises(ValueError): self.check(sha="a" * 40)
        self.git("update-ref", "refs/remotes/origin/main", "HEAD^1")
        with self.assertRaises(ValueError): self.check()

    def test_tag_version_must_match_release_merge(self):
        self.tag = "v0.2.0"
        self.sign()
        with self.assertRaises(ValueError): self.check()

    def test_missing_trusted_fingerprint_fails_closed(self):
        self.sign()
        with self.assertRaises(ValueError):
            guard.check(self.tag, self.sha, "example", "", public_key=self.public)


class ReleaseExistenceTests(unittest.TestCase):
    def test_only_explicit_404_allows_a_new_release(self):
        result = subprocess.CompletedProcess([], 1, "HTTP/2.0 404 Not Found\n", "not found")
        with mock.patch.object(guard.subprocess, "run", return_value=result):
            guard.require_unpublished("example/repo", "v0.1.0")

    def test_existing_release_network_and_authorization_failures_stop_publication(self):
        for status, output in [(0, "HTTP/2.0 200 OK\n"), (1, ""), (1, "HTTP/2.0 403 Forbidden\n")]:
            result = subprocess.CompletedProcess([], status, output, "error")
            with self.subTest(output=output), mock.patch.object(guard.subprocess, "run", return_value=result):
                with self.assertRaises(ValueError):
                    guard.require_unpublished("example/repo", "v0.1.0")
