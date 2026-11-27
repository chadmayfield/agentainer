import base64
import contextlib
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import call, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import bump_versions as bv  # noqa: E402

# A publish time older than MIN_RELEASE_AGE_HOURS for any run of these tests.
OLD = "2026-01-01T00:00:00Z"


class EnvFileTests(unittest.TestCase):
    def test_failed_publisher_verification_preserves_pins(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "UV_VERSION=0.13.0\n"
            with open(path, "w") as file:
                file.write(original)
            release = {"tag_name": "0.13.1", "published_at": OLD, "assets": [
                {"name": "uv-test.tar.gz", "digest": "sha256:" + "a" * 64}]}
            with patch.object(bv, "gh_latest", return_value=release), \
                    patch.object(bv, "verify_asset", side_effect=bv.VerificationFailed("wrong signer")):
                resolver = lambda: bv.github_tool("UV", "astral-sh/uv", {"AMD64": lambda v: "uv-test.tar.gz"})
                self.assertNotEqual(bv.main(["--file", path], resolvers=[resolver]), 0)
            with open(path) as file:
                self.assertEqual(file.read(), original)

    def test_resolver_downgrade_preserves_the_pin_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "HELM_VERSION=4.3.1\n"
            with open(path, "w") as file:
                file.write(original)
            rc = bv.main(["--file", path], resolvers=[lambda: {"HELM_VERSION": "3.22.1"}])
            self.assertNotEqual(rc, 0)
            with open(path) as file:
                self.assertEqual(file.read(), original)

    def test_round_trip_keeps_comments_and_order(self):
        text = "# header\nA=1\n\n# note\nB=2\n"
        lines = bv.parse_env(text)
        out = bv.render_env(lines, {"B": "3", "C": "4"})
        self.assertEqual(out, "# header\nA=1\n\n# note\nB=3\nC=4\n")

    def test_values_reads_keys(self):
        self.assertEqual(bv.values(bv.parse_env("A=1\n#x\nB=two\n")), {"A": "1", "B": "two"})


class ParserTests(unittest.TestCase):
    def test_abtop_resolver_checks_both_published_archive_checksums(self):
        names = ["abtop-x86_64-unknown-linux-gnu.tar.xz", "abtop-aarch64-unknown-linux-gnu.tar.xz"]
        assets = []
        responses = {}
        for name, letter in zip(names, "ab"):
            assets.extend([{"name": name, "digest": "sha256:" + letter * 64},
                           {"name": name + ".sha256", "browser_download_url": "https://example.com/" + name}])
            responses["https://example.com/" + name] = letter * 64 + " *" + name + "\n"
        release = {"tag_name": "v0.5.5", "published_at": OLD, "assets": assets}
        with patch.object(bv, "gh_latest", return_value=release) as latest, \
                patch.object(bv, "fetch", side_effect=responses.__getitem__) as fetched, \
                patch.object(bv, "verify_asset", return_value=False):
            pins = bv.r_abtop()
        latest.assert_called_once_with("graykode/abtop")
        self.assertEqual(fetched.call_count, 2)
        self.assertEqual(pins, {"ABTOP_VERSION": "0.5.5", "ABTOP_SHA256_AMD64": "a" * 64,
                                "ABTOP_SHA256_ARM64": "b" * 64})
        self.assertIn(bv.r_abtop, bv.RESOLVERS)

    def test_ruff_resolver_selects_both_official_archives_and_verifies_publisher(self):
        names = ["ruff-x86_64-unknown-linux-gnu.tar.gz", "ruff-aarch64-unknown-linux-gnu.tar.gz"]
        release = {"tag_name": "0.17.1", "published_at": OLD, "assets": [
            {"name": name, "digest": "sha256:" + letter * 64}
            for name, letter in zip(names, "ab")]}
        with patch.object(bv, "gh_latest", return_value=release), \
                patch.object(bv, "verify_asset", return_value=True) as verify:
            pins = bv.r_ruff()
        self.assertEqual(pins, {"RUFF_VERSION": "0.17.1", "RUFF_SHA256_AMD64": "a" * 64,
                                "RUFF_SHA256_ARM64": "b" * 64})
        self.assertEqual([call.args[2] for call in verify.call_args_list], names)

    @staticmethod
    def _release(version, names, sums_name, with_sums=True):
        """A release whose archives are covered by a published checksum list; returns it and the list text."""
        letters = "ab"
        assets = [{"name": n, "digest": "sha256:" + l * 64} for n, l in zip(names, letters)]
        text = "".join("%s  %s\n" % (l * 64, n) for n, l in zip(names, letters))
        if with_sums:
            assets.append({"name": sums_name, "digest": None, "browser_download_url": "https://example.com/" + sums_name})
        return {"tag_name": "v" + version, "prerelease": False, "published_at": OLD, "assets": assets}, text

    def _resolve(self, resolver, release, text, **extra):
        with patch.object(bv, "gh_latest", return_value=release), \
                patch.object(bv, "fetch", return_value=text) as fetched, \
                patch.object(bv, "verify_asset", return_value=False) as verify:
            pins = resolver()
        return pins, fetched, verify

    def test_gosec_resolver_requires_the_published_checksum_list(self):
        names = ["gosec_2.30.0_linux_amd64.tar.gz", "gosec_2.30.0_linux_arm64.tar.gz"]
        release, text = self._release("2.30.0", names, "gosec_2.30.0_checksums.txt")
        pins, fetched, verify = self._resolve(bv.r_gosec, release, text)
        self.assertEqual(pins, {"GOSEC_VERSION": "2.30.0", "GOSEC_SHA256_AMD64": "a" * 64,
                                "GOSEC_SHA256_ARM64": "b" * 64})
        self.assertEqual([c.args[2] for c in verify.call_args_list], names)
        self.assertEqual(fetched.call_count, 2)
        self.assertIn(bv.r_gosec, bv.RESOLVERS)
        release, text = self._release("2.30.0", names, "gosec_2.30.0_checksums.txt", with_sums=False)
        with self.assertRaises(bv.LookupFailed):
            self._resolve(bv.r_gosec, release, text)

    def test_gitleaks_resolver_uses_x64_for_amd64_and_requires_the_checksum_list(self):
        names = ["gitleaks_8.30.1_linux_x64.tar.gz", "gitleaks_8.30.1_linux_arm64.tar.gz"]
        release, text = self._release("8.30.1", names, "gitleaks_8.30.1_checksums.txt")
        pins, _, verify = self._resolve(bv.r_gitleaks, release, text)
        self.assertEqual(pins, {"GITLEAKS_VERSION": "8.30.1", "GITLEAKS_SHA256_AMD64": "a" * 64,
                                "GITLEAKS_SHA256_ARM64": "b" * 64})
        self.assertEqual([c.args[2] for c in verify.call_args_list], names)
        self.assertIn(bv.r_gitleaks, bv.RESOLVERS)
        release, text = self._release("8.30.1", names, "gitleaks_8.30.1_checksums.txt", with_sums=False)
        with self.assertRaises(bv.LookupFailed):
            self._resolve(bv.r_gitleaks, release, text)

    # Asset and checksum-list names copied from each project's latest release on 2026-11-26.
    PUBLISHED_LIST_RESOLVERS = (
        ("r_crane", "CRANE", "0.22.1", ["go-containerregistry_Linux_x86_64.tar.gz",
                                         "go-containerregistry_Linux_arm64.tar.gz"], "checksums.txt"),
        ("r_kyverno", "KYVERNO", "1.20.0", ["kyverno-cli_v1.20.0_linux_x86_64.tar.gz",
                                             "kyverno-cli_v1.20.0_linux_arm64.tar.gz"], "checksums.txt"),
        ("r_actionlint", "ACTIONLINT", "1.7.12", ["actionlint_1.7.12_linux_amd64.tar.gz",
                                                  "actionlint_1.7.12_linux_arm64.tar.gz"],
         "actionlint_1.7.12_checksums.txt"),
        ("r_hadolint", "HADOLINT", "2.15.1", ["hadolint-linux-x86_64", "hadolint-linux-arm64"], "checksums.sha256"),
        ("r_scc", "SCC", "4.1.0", ["scc_Linux_x86_64.tar.gz", "scc_Linux_arm64.tar.gz"], "checksums.txt"),
        ("r_lazygit", "LAZYGIT", "0.66.3", ["lazygit_0.66.3_linux_x86_64.tar.gz",
                                             "lazygit_0.66.3_linux_arm64.tar.gz"], "checksums.txt"),
        ("r_glow", "GLOW", "3.0.0", ["glow_3.0.0_Linux_x86_64.tar.gz", "glow_3.0.0_Linux_arm64.tar.gz"],
         "checksums.txt"),
        ("r_syft", "SYFT", "1.57.2", ["syft_1.57.2_linux_amd64.tar.gz", "syft_1.57.2_linux_arm64.tar.gz"],
         "syft_1.57.2_checksums.txt"),
        ("r_grype", "GRYPE", "0.122.1", ["grype_0.122.1_linux_amd64.tar.gz", "grype_0.122.1_linux_arm64.tar.gz"],
         "grype_0.122.1_checksums.txt"),
    )

    def test_cli_tool_resolvers_require_their_published_checksum_list(self):
        for name, prefix, version, names, sums in self.PUBLISHED_LIST_RESOLVERS:
            with self.subTest(resolver=name):
                resolver = getattr(bv, name)
                release, text = self._release(version, names, sums)
                pins, _, verify = self._resolve(resolver, release, text)
                self.assertEqual(pins, {prefix + "_VERSION": version, prefix + "_SHA256_AMD64": "a" * 64,
                                        prefix + "_SHA256_ARM64": "b" * 64})
                self.assertEqual([c.args[2] for c in verify.call_args_list], names)
                self.assertIn(resolver, bv.RESOLVERS)
                release, text = self._release(version, names, sums, with_sums=False)
                with self.assertRaises(bv.LookupFailed):
                    self._resolve(resolver, release, text)

    # These projects publish no checksum list, so github_tool uses GitHub's asset digest.
    DIGEST_ONLY_RESOLVERS = (
        ("r_zizmor", "ZIZMOR", "1.33.1", ["zizmor-x86_64-unknown-linux-gnu.tar.gz",
                                           "zizmor-aarch64-unknown-linux-gnu.tar.gz"]),
        ("r_ast_grep", "AST_GREP", "0.51.3", ["app-x86_64-unknown-linux-gnu.zip", "app-aarch64-unknown-linux-gnu.zip"]),
        ("r_difftastic", "DIFFTASTIC", "0.72.0", ["difft-0.72.0-x86_64-unknown-linux-gnu.tar.gz",
                                                   "difft-0.72.0-aarch64-unknown-linux-gnu.tar.gz"]),
        ("r_delta", "DELTA", "0.22.0", ["delta-0.22.0-x86_64-unknown-linux-gnu.tar.gz",
                                         "delta-0.22.0-aarch64-unknown-linux-gnu.tar.gz"]),
        ("r_hyperfine", "HYPERFINE", "2.0.0", ["hyperfine-v2.0.0-x86_64-unknown-linux-gnu.tar.gz",
                                                "hyperfine-v2.0.0-aarch64-unknown-linux-gnu.tar.gz"]),
    )

    def test_cli_tool_resolvers_without_a_list_use_the_asset_digest(self):
        for name, prefix, version, names in self.DIGEST_ONLY_RESOLVERS:
            with self.subTest(resolver=name):
                resolver = getattr(bv, name)
                release, text = self._release(version, names, "unused", with_sums=False)
                pins, fetched, _ = self._resolve(resolver, release, text)
                self.assertEqual(pins, {prefix + "_VERSION": version, prefix + "_SHA256_AMD64": "a" * 64,
                                        prefix + "_SHA256_ARM64": "b" * 64})
                self.assertEqual(fetched.call_count, 0)
                self.assertIn(resolver, bv.RESOLVERS)

    def test_fj_resolver_hashes_the_codeberg_archives(self):
        release = {"tag_name": "v0.7.0", "published_at": OLD, "assets": [
            {"name": "forgejo-cli-x86_64-linux.tar.gz", "browser_download_url": "https://example.com/amd64"},
            {"name": "forgejo-cli-aarch64-linux.tar.gz", "browser_download_url": "https://example.com/arm64"}]}
        blobs = {"https://example.com/amd64": b"amd64 archive", "https://example.com/arm64": b"arm64 archive"}
        with patch.object(bv, "fetch_json", return_value=release) as fetched, \
                patch.object(bv, "fetch_bytes", side_effect=blobs.__getitem__):
            pins = bv.r_fj()
        fetched.assert_called_once_with(bv.FJ_RELEASES)
        self.assertEqual(pins, {"FJ_VERSION": "0.7.0",
                                "FJ_SHA256_AMD64": hashlib.sha256(b"amd64 archive").hexdigest(),
                                "FJ_SHA256_ARM64": hashlib.sha256(b"arm64 archive").hexdigest()})
        self.assertIn(bv.r_fj, bv.RESOLVERS)
        release["assets"] = release["assets"][:1]
        with patch.object(bv, "fetch_json", return_value=release), \
                patch.object(bv, "fetch_bytes", side_effect=blobs.__getitem__):
            with self.assertRaises(bv.LookupFailed):
                bv.r_fj()

    def test_checksum_list_must_be_the_named_file(self):
        # A different list in the release does not stand in for gosec_<version>_checksums.txt.
        names = ["gosec_2.30.0_linux_amd64.tar.gz", "gosec_2.30.0_linux_arm64.tar.gz"]
        release, text = self._release("2.30.0", names, "other_checksums.txt")
        with self.assertRaises(bv.LookupFailed):
            self._resolve(bv.r_gosec, release, text)

    def _agent_release(self, version, with_sums=True):
        names = ["agent_%s_linux_amd64.tar.gz" % version, "agent_%s_linux_arm64.tar.gz" % version]
        return self._release(version, names, "agent_%s_checksums.txt" % version, with_sums)

    def _agent(self, releases, **kw):
        # releases: list of (release, checksum text)
        by_url = {}
        for rel, text in releases:
            for a in rel["assets"]:
                if a.get("browser_download_url"):
                    by_url[a["browser_download_url"]] = text
        with patch.object(bv, "fetch_json", return_value=[r for r, _ in releases]) as fj, \
                patch.object(bv, "fetch", side_effect=by_url.__getitem__), \
                patch.object(bv, "verify_asset", return_value=False):
            return bv.r_containerssh_agent(), fj

    def test_agent_series_follows_server_series(self):
        releases = [self._agent_release(v) for v in ("0.12.0", "0.11.2", "0.11.1", "0.10.9")]
        pins, fj = self._agent(releases)
        self.assertIn("containerssh/agent", fj.call_args.args[0])
        self.assertEqual(pins, {"CONTAINERSSH_AGENT_VERSION": "0.11.2",
                                "CONTAINERSSH_AGENT_SHA256_AMD64": "a" * 64,
                                "CONTAINERSSH_AGENT_SHA256_ARM64": "b" * 64})
        self.assertIn(bv.r_containerssh_agent, bv.RESOLVERS)

    def test_agent_series_skips_prereleases(self):
        pre = self._agent_release("0.11.3")
        pre[0]["prerelease"] = True
        pins, _ = self._agent([pre, self._agent_release("0.11.2")])
        self.assertEqual(pins["CONTAINERSSH_AGENT_VERSION"], "0.11.2")

    def test_agent_requires_the_published_checksum_list(self):
        with self.assertRaises(bv.LookupFailed):
            self._agent([self._agent_release("0.11.2", with_sums=False)])

    def test_agent_held_when_server_series_unmapped(self):
        images = (("CONTAINERSSH_IMAGE", "containerssh/containerssh", "v0.7", "x.yaml"),)
        err = io.StringIO()
        with patch.object(bv, "K8S_IMAGES", images), \
                patch.object(bv, "fetch_json", side_effect=AssertionError("must not fetch")), \
                contextlib.redirect_stderr(err):
            pins = bv.r_containerssh_agent()
        self.assertEqual(pins, {})
        self.assertIn("v0.7", err.getvalue())

    def test_agent_without_a_release_in_the_series_is_refused(self):
        with patch.object(bv, "fetch_json", return_value=[self._agent_release("0.12.0")[0]]):
            with self.assertRaises(bv.LookupFailed):
                bv.r_containerssh_agent()

    def test_pinned_containerssh_pair_is_the_cluster_verified_pair(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        with open(os.path.join(root, "versions.env")) as f:
            pins = bv.values(bv.parse_env(f.read()))
        verified = bv.VERIFIED_CONTAINERSSH_PAIR
        self.assertEqual(
            (pins["CONTAINERSSH_IMAGE"], pins["CONTAINERSSH_AGENT_VERSION"]),
            (verified["server_image"], verified["agent_version"]),
            "CONTAINERSSH_IMAGE or CONTAINERSSH_AGENT_VERSION no longer matches the pair verified in a "
            "cluster. Re-verify before merging: with the new pair deployed and the features ConfigMap set "
            "to sftp=on and forwarding=local, run an sftp put and get, then ssh -L and ssh -D, as "
            "docs/kubernetes.md describes. Then update VERIFIED_CONTAINERSSH_PAIR in "
            "scripts/bump_versions.py and the pair in docs/versions.md.")

    def test_k8s_containerssh_tag_is_mapped(self):
        tags = [tag for key, _, tag, _ in bv.K8S_IMAGES if key == "CONTAINERSSH_IMAGE"]
        self.assertEqual(len(tags), 1)
        self.assertIn(tags[0], bv.CONTAINERSSH_AGENT_SERIES)

    def test_new_tool_pins_match_value_patterns(self):
        for prefix in ("GOSEC", "GITLEAKS", "CONTAINERSSH_AGENT", "FJ", "CRANE", "KYVERNO", "ACTIONLINT", "ZIZMOR",
                       "HADOLINT", "AST_GREP", "DIFFTASTIC", "DELTA", "SCC", "HYPERFINE", "LAZYGIT", "GLOW", "SYFT",
                       "GRYPE"):
            self.assertIsNone(bv.invalid(prefix + "_VERSION", "1.2.3"))
            for arch in ("AMD64", "ARM64"):
                self.assertIsNone(bv.invalid("%s_SHA256_%s" % (prefix, arch), "a" * 64))

    def test_bsd_and_per_asset_published_checksums(self):
        checksum = "a" * 64
        for filename, contents in (("checksums-bsd", "SHA256 (tool.tar.gz) = " + checksum),
                                   ("tool.tar.gz.sha256", checksum + "  tool.tar.gz"),
                                   ("codex-package_SHA256SUMS", checksum + "  tool.tar.gz"),
                                   ("checksums.sha256", checksum + " *tool.tar.gz")):
            release = {"tag_name": "v1", "assets": [
                {"name": "tool.tar.gz", "digest": "sha256:" + checksum},
                {"name": filename, "browser_download_url": "https://example.com/sums"}]}
            self.assertEqual(bv.asset_sha256(release, "tool.tar.gz", fetch_text=lambda url: contents), checksum)

    def test_published_checksum_must_agree_with_asset_digest(self):
        release = {"tag_name": "v1", "assets": [
            {"name": "tool.tar.gz", "digest": "sha256:" + "a" * 64},
            {"name": "checksums.txt", "browser_download_url": "https://example.com/checksums.txt"}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "tool.tar.gz", fetch_text=lambda url: "b" * 64 + "  tool.tar.gz\n")

    def test_buildkit_skips_frontend_tags_and_prereleases(self):
        releases = [
            {"tag_name": "dockerfile/1.28.0", "prerelease": False},
            {"tag_name": "v0.35.0-rc1", "prerelease": True},
            {"tag_name": "v0.34.0", "prerelease": False},
            {"tag_name": "v0.33.1", "prerelease": False},
        ]
        self.assertEqual(bv.buildkit_tag(releases), "v0.34.0")

    def test_buildkit_without_a_release_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.buildkit_tag([{"tag_name": "dockerfile/1.28.0", "prerelease": False}])

    def test_go_picks_first_stable_linux_archives(self):
        data = [
            {"version": "go1.28rc1", "stable": False, "files": []},
            {"version": "go1.27.2", "stable": True, "files": [
                {"os": "linux", "arch": "amd64", "kind": "archive", "sha256": "aa"},
                {"os": "linux", "arch": "arm64", "kind": "archive", "sha256": "bb"},
                {"os": "darwin", "arch": "arm64", "kind": "archive", "sha256": "cc"},
            ]},
        ]
        self.assertEqual(bv.parse_go(data), {
            "GO_VERSION": "1.27.2", "GO_SHA256_AMD64": "aa", "GO_SHA256_ARM64": "bb"})

    def test_rust_version_from_channel(self):
        text = '[pkg.rustc]\nversion = "1.99.0 (b940084d7 2026-09-28)"\n'
        self.assertEqual(bv.parse_rust_channel(text), "1.99.0")

    def test_rust_manifest_url(self):
        self.assertEqual(bv.rust_manifest_url("1.99.0"),
                         "https://static.rust-lang.org/dist/channel-rust-1.99.0.toml")

    def test_rustup_version(self):
        self.assertEqual(bv.parse_rustup_release("schema-version = '1'\nversion = '1.28.2'\n"), "1.28.2")

    def test_github_asset_digest(self):
        release = {"tag_name": "v4.54.1", "assets": [
            {"name": "yq_linux_amd64", "digest": "sha256:" + "1" * 64},
            {"name": "yq_linux_arm64", "digest": "sha256:" + "2" * 64}]}
        self.assertEqual(bv.asset_sha256(release, "yq_linux_arm64"), "2" * 64)

    def test_github_asset_without_digest_uses_release_checksums_file(self):
        release = {"tag_name": "v1.0.0", "assets": [
            {"name": "tool_1.0.0_linux_arm64.tar.gz", "digest": None},
            {"name": "tool_1.0.0_checksums.txt", "digest": None,
             "browser_download_url": "https://example.com/tool_1.0.0_checksums.txt"}]}
        a, b = "a" * 64, "b" * 64
        text = "%s  tool_1.0.0_linux_amd64.tar.gz\n%s  tool_1.0.0_linux_arm64.tar.gz\n" % (a, b)
        got = bv.asset_sha256(release, "tool_1.0.0_linux_arm64.tar.gz", fetch_text=lambda url: text)
        self.assertEqual(got, b)

    def test_github_asset_without_any_checksum_raises(self):
        release = {"tag_name": "v1", "assets": [{"name": "x.tar.gz", "digest": None}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "x.tar.gz", fetch_text=lambda url: "")

    def test_github_asset_missing_raises(self):
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256({"tag_name": "v1", "assets": []}, "nope")

    def test_checksum_file_line(self):
        h = "0123456789abcdef" * 4
        self.assertEqual(bv.parse_checksum_file(h + "  tea-0.16.0-linux-amd64.xz\n"), h)

    def test_agy_manifest(self):
        url = "https://storage.googleapis.com/antigravity-public/antigravity-cli/1.3.2-1/linux-x64/cli.tar.gz"
        m = {"version": "1.3.2", "url": url, "sha512": "f" * 128}
        self.assertEqual(bv.parse_agy(m), ("1.3.2", url, "f" * 128))

    def claude_manifest(self, **over):
        doc = {"version": "2.1.292", "platforms": {
            "linux-x64": {"binary": "claude", "checksum": "a" * 64, "size": 1},
            "linux-arm64": {"binary": "claude", "checksum": "b" * 64, "size": 1},
            "darwin-arm64": {"binary": "claude", "checksum": "c" * 64, "size": 1}}}
        doc.update(over)
        return doc

    def test_claude_manifest_gives_both_linux_checksums(self):
        self.assertEqual(bv.parse_claude_manifest(self.claude_manifest(), "2.1.292"), {
            "CLAUDE_CODE_VERSION": "2.1.292",
            "CLAUDE_CODE_SHA256_AMD64": "a" * 64, "CLAUDE_CODE_SHA256_ARM64": "b" * 64})

    def test_claude_manifest_for_another_version_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(self.claude_manifest(version="2.1.291"), "2.1.292")

    def test_claude_manifest_without_a_platform_is_refused(self):
        doc = self.claude_manifest()
        del doc["platforms"]["linux-arm64"]
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(doc, "2.1.292")

    def test_claude_manifest_with_a_bad_checksum_is_refused(self):
        doc = self.claude_manifest()
        doc["platforms"]["linux-x64"]["checksum"] = "A" * 64
        with self.assertRaises(bv.LookupFailed):
            bv.parse_claude_manifest(doc, "2.1.292")

    def test_node_index_picks_newest_of_the_major(self):
        doc = [{"version": "v28.0.0"}, {"version": "v26.14.0-rc.1"}, {"version": "v26.9.1"},
               {"version": "v26.13.0"}, {"version": "v24.22.2"}, {"version": "v26.99.0\n"}]
        self.assertEqual(bv.parse_node_index(doc, 26), "26.13.0")

    def test_node_index_with_an_unexpected_shape_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index({"version": "v26.13.0"}, 26)
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index(["v26.13.0"], 26)

    def test_node_index_skips_entries_that_are_not_objects(self):
        self.assertEqual(bv.parse_node_index(["junk", {"version": "v26.13.0"}], 26), "26.13.0")

    def test_node_index_without_the_major_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index([{"version": "v24.22.2"}], 26)

    def test_node_shasums_gives_both_linux_hashes(self):
        text = ("%s  node-v26.13.0-linux-arm64.tar.xz\n%s  node-v26.13.0-linux-x64.tar.xz\n"
                "%s  node-v26.13.0-darwin-arm64.tar.gz\n"
                "%s  node-v26.13.0-linux-x64-musl.tar.xz\n%s  node-v26.13.0-linux-x64.tar.xz.sig\n"
                "%s  node-v26.13.01-linux-x64.tar.xz\n%s  *node-v26.13.0-linux-x64.tar.xz\n"
                ) % ("a" * 64, "b" * 64, "c" * 64, "d" * 64, "d" * 64, "d" * 64, "d" * 64)
        self.assertEqual(bv.parse_node_shasums(text, "26.13.0"),
                         {"NODE_VERSION": "26.13.0", "NODE_SHA256_AMD64": "b" * 64, "NODE_SHA256_ARM64": "a" * 64})

    def test_node_shasums_missing_an_arch_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_shasums("%s  node-v26.13.0-linux-x64.tar.xz\n" % ("b" * 64), "26.13.0")

    def test_node_shasums_with_a_bad_hash_is_refused(self):
        text = "%s  node-v26.13.0-linux-x64.tar.xz\n%s  node-v26.13.0-linux-arm64.tar.xz\n" % ("B" * 64, "a" * 64)
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_shasums(text, "26.13.0")

    def test_node_resolver_is_registered(self):
        self.assertIn(bv.r_node, bv.RESOLVERS)


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class SignatureTests(unittest.TestCase):
    """verify_signature against two keys made for the test: "release" is the pinned key."""

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.env = dict(os.environ, GNUPGHOME=cls.home)
        cls.data = b'{"version": "2.1.292"}'
        cls.data_file = os.path.join(cls.home, "data")
        with open(cls.data_file, "wb") as f:
            f.write(cls.data)
        cls.fpr, cls.key, cls.sig = {}, {}, {}
        for name in ("release", "other"):
            cls.fpr[name] = cls.make_key(name)
            cls.key[name] = cls.gpg("--armor", "--export", cls.fpr[name])
            cls.sig[name] = cls.gpg("--local-user", cls.fpr[name], "--detach-sign", "--output", "-",
                                    cls.data_file)

    @classmethod
    def gpg(cls, *args):
        cmd = ["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", ""] + list(args)
        return subprocess.run(cmd, env=cls.env, check=True, capture_output=True).stdout

    @classmethod
    def make_key(cls, name):
        uid = "Test %s <%s@example.com>" % (name, name)
        cls.gpg("--quick-gen-key", uid, "ed25519", "sign", "never")
        out = cls.gpg("--with-colons", "--fingerprint", uid).decode()
        return [line.split(":")[9] for line in out.splitlines() if line.startswith("fpr")][0]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def test_good_signature_passes(self):
        bv.verify_signature(self.data, self.sig["release"], self.key["release"], self.fpr["release"])

    def test_changed_data_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data + b" ", self.sig["release"], self.key["release"], self.fpr["release"])

    def test_key_with_another_fingerprint_fails(self):
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], self.key["release"], "0" * 40)

    def test_signature_by_a_second_key_in_the_key_file_fails(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["other"], keys, self.fpr["release"])

    def test_key_file_with_two_keys_fails(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], keys, self.fpr["release"])

    def test_any_key_in_the_set_may_sign(self):
        keys = self.key["release"] + self.key["other"]
        both = (self.fpr["release"], self.fpr["other"])
        bv.verify_signature(self.data, self.sig["other"], keys, both)

    def test_key_file_must_hold_exactly_the_set(self):
        keys = self.key["release"] + self.key["other"]
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, self.sig["release"], keys, (self.fpr["release"], "0" * 40))

    def test_signature_by_a_key_outside_the_file_fails(self):
        # gpg refuses it for lack of the public key, before the signer-in-set check runs.
        keys = self.key["release"] + self.key["other"]
        third = self.make_key("third")
        sig = self.gpg("--local-user", third, "--detach-sign", "--output", "-", self.data_file)
        with self.assertRaises(bv.LookupFailed):
            bv.verify_signature(self.data, sig, keys, (self.fpr["release"], self.fpr["other"]))

    def test_expired_key_is_refused_naming_expkeysig(self):
        at = "20200101T000000!"
        uid = "Test expired <expired@example.com>"
        self.gpg("--faked-system-time", at, "--quick-gen-key", uid, "ed25519", "sign", "1d")
        out = self.gpg("--with-colons", "--fingerprint", uid).decode()
        fpr = [l.split(":")[9] for l in out.splitlines() if l.startswith("fpr")][0]
        sig = self.gpg("--faked-system-time", at, "--local-user", fpr, "--detach-sign", "--output", "-",
                       self.data_file)
        with self.assertRaises(bv.LookupFailed) as ctx:
            bv.verify_signature(self.data, sig, self.gpg("--armor", "--export", fpr), (fpr,))
        self.assertIn("EXPKEYSIG", str(ctx.exception))

    def test_signing_subkey_reports_its_primary(self):
        # Some Node releasers sign with a subkey (release-keys README).
        primary = self.make_key("withsub")
        self.gpg("--quick-add-key", primary, "ed25519", "sign", "never")
        sub = [l.split(":")[4] for l in self.gpg("--with-colons", "--list-keys", primary).decode().splitlines()
               if l.startswith("sub")][0]
        sig = self.gpg("--local-user", sub + "!", "--detach-sign", "--output", "-", self.data_file)
        bv.verify_signature(self.data, sig, self.gpg("--armor", "--export", primary), (primary,))


def primary_fingerprints(path):
    """Primary key fingerprints of a key file, listed from a temporary GNUPGHOME."""
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, GNUPGHOME=home)
        gpg = ["gpg", "--batch", "--no-tty"]
        subprocess.run(gpg + ["--import", path], env=env, check=True, capture_output=True)
        out = subprocess.run(gpg + ["--with-colons", "--fingerprint"], env=env, check=True,
                             capture_output=True, text=True).stdout
    lines = out.splitlines()
    return [lines[i + 1].split(":")[9] for i, line in enumerate(lines)
            if line.startswith("pub:") and i + 1 < len(lines) and lines[i + 1].startswith("fpr:")]


class HelperTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_node_keyring_holds_exactly_the_pinned_fingerprints(self):
        # Imports NODE_KEYRING into a temporary GNUPGHOME and lists its primary fingerprints.
        self.assertEqual(sorted(primary_fingerprints(bv.NODE_KEYRING)), sorted(bv.NODE_KEY_FINGERPRINTS))

    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_aws_cli_key_holds_exactly_the_pinned_fingerprint(self):
        self.assertEqual(primary_fingerprints(bv.AWSCLI_KEY), [bv.AWSCLI_KEY_FINGERPRINT])

    def test_codex_uses_the_complete_package_asset(self):
        self.assertEqual(bv.codex_asset("aarch64"), "codex-package-aarch64-unknown-linux-musl.tar.gz")

    def test_hub_ref(self):
        self.assertEqual(bv.hub_ref("library/python", "3.14-slim", {"digest": "sha256:" + "a" * 64}),
                         "docker.io/library/python:3.14-slim@sha256:" + "a" * 64)

    def test_rewrite_image_ref_in_manifest(self):
        old = "docker.io/library/python:3.14-slim@sha256:" + "a" * 64
        new = "docker.io/library/python:3.14-slim@sha256:" + "b" * 64
        text = "      containers:\n        - image: %s\n          command: [x]\n" % old
        self.assertEqual(bv.rewrite_image_ref(text, new), text.replace(old, new))

    def test_k8s_images_rewrites_filebrowser_in_statefulset(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        rel = os.path.join("deploy", "kubernetes", "agentainer", "statefulset.yaml")
        with open(os.path.join(root, "versions.env")) as f:
            env_text = f.read()
        with open(os.path.join(root, rel)) as f:
            manifest = f.read()
        old = bv.values(bv.parse_env(env_text))["FILEBROWSER_IMAGE"]
        self.assertEqual(manifest.count(old), 1)
        new = old.split("@")[0] + "@sha256:" + "c" * 64
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, "versions.env")
            with open(env, "w") as f:
                f.write(env_text)
            for _, _, _, path in bv.K8S_IMAGES:
                os.makedirs(os.path.join(d, os.path.dirname(path)), exist_ok=True)
                shutil.copyfile(os.path.join(root, path), os.path.join(d, path))
            with patch.object(bv, "fetch_json", return_value={"digest": "sha256:" + "c" * 64}) as fj, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bv.main(["--file", env, "--only", "r_k8s_images"]), 0)
            fj.assert_any_call("https://hub.docker.com/v2/repositories/gtstef/filebrowser/tags/2.0-stable-slim")
            with open(os.path.join(d, rel)) as f:
                self.assertEqual(f.read(), manifest.replace(old, new))
            with open(env) as f:
                self.assertEqual(bv.values(bv.parse_env(f.read()))["FILEBROWSER_IMAGE"], new)

    def test_agentainer_release_is_the_highest_published_version(self):
        releases = [{"tag_name": "v0.1.0-dev.20261104.2", "draft": True},
                    {"tag_name": "v0.1.0-dev.20261104.1", "prerelease": True},
                    {"tag_name": "v0.1.0-dev.20261024.10", "prerelease": True},
                    {"tag_name": "v0.1.0-dev.20261024.2", "prerelease": True},
                    {"tag_name": "kelos-1.0.0"}, {"tag_name": "v0.01.0"}, {"tag_name": "v0.1.0-dev.20260230.1"},
                    {"tag_name": "0.9.0"}, {}]
        self.assertEqual(bv.agentainer_release(releases), "0.1.0-dev.20261104.1")
        self.assertEqual(bv.agentainer_release(releases[2:4]), "0.1.0-dev.20261024.10")
        stable = [{"tag_name": "v0.1.0"}, {"tag_name": "v0.1.0-dev.20261104.1", "prerelease": True}]
        self.assertEqual(bv.agentainer_release(stable), "0.1.0")

    def test_agentainer_release_without_a_release_fails(self):
        for releases in ([], [{"tag_name": "v1.0.0", "draft": True}], [{"tag_name": "nightly"}]):
            with self.subTest(releases=releases):
                with self.assertRaises(bv.LookupFailed):
                    bv.agentainer_release(releases)

    def test_agentainer_release_resolver_lists_releases_with_prereleases(self):
        with patch.object(bv, "fetch_json", return_value=[{"tag_name": "v0.1.0-dev.20261104.1", "prerelease": True}]) as fj:
            self.assertEqual(bv.r_agentainer_release(), {"AGENTAINER_RELEASE_VERSION": "0.1.0-dev.20261104.1"})
        fj.assert_called_once_with("https://api.github.com/repos/chadmayfield/agentainer/releases?per_page=100")
        self.assertIn(bv.r_agentainer_release, bv.RESOLVERS)
        self.assertIsNone(bv.invalid("AGENTAINER_RELEASE_VERSION", "0.1.0-dev.20261104.1"))

    def test_release_ref_rewrite_keeps_longer_versions(self):
        old, new = "0.1.0-dev.20261104.1", "0.1.0-dev.20261201.1"
        image = bv.AGENTAINER_IMAGE + ":"
        text = "%s%s\n%s%s0\n%s%s-x\nrun %s%s.\n" % (image, old, image, old, image, old, image, old)
        self.assertEqual(bv.rewrite_release_ref(text, image, old, new),
                         "%s%s\n%s%s0\n%s%s-x\nrun %s%s.\n" % (image, new, image, old, image, old, image, new))

    def test_release_refs_hold_the_current_pin(self):
        # The resolver rewrites only text that holds the current pin, so every entry must.
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        with open(os.path.join(root, "versions.env")) as f:
            pin = bv.values(bv.parse_env(f.read()))["AGENTAINER_RELEASE_VERSION"]
        for rel, prefix in bv.RELEASE_REFS:
            with self.subTest(rel=rel, prefix=prefix):
                with open(os.path.join(root, rel)) as f:
                    text = f.read()
                self.assertIn(prefix + pin, text)
                if prefix.startswith(bv.AGENTAINER_IMAGE):
                    tags = re.findall(re.escape(prefix) + r"([0-9A-Za-z._-]+)", text)
                    self.assertEqual(sorted(set(tags)), [pin], "every %s tag in %s must be the pin" % (prefix, rel))

    def test_release_pin_bump_rewrites_every_release_ref(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        with open(os.path.join(root, "versions.env")) as f:
            env_text = f.read()
        old = bv.values(bv.parse_env(env_text))["AGENTAINER_RELEASE_VERSION"]
        new = "0.1.0-dev.20991231.1"
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, "versions.env")
            with open(env, "w") as f:
                f.write(env_text)
            originals = {}
            for rel in {rel for rel, _ in bv.RELEASE_REFS}:
                os.makedirs(os.path.join(d, os.path.dirname(rel)), exist_ok=True)
                shutil.copy2(os.path.join(root, rel), os.path.join(d, rel))
                with open(os.path.join(root, rel)) as f:
                    originals[rel] = f.read()
            with patch.object(bv, "fetch_json", return_value=[{"tag_name": "v" + new, "prerelease": True}]), \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bv.main(["--file", env, "--only", "r_agentainer_release"]), 0)
            for rel, prefix in bv.RELEASE_REFS:
                with self.subTest(rel=rel, prefix=prefix):
                    with open(os.path.join(d, rel)) as f:
                        text = f.read()
                    self.assertNotIn(prefix + old, text)
                    self.assertIn(prefix + new, text)
            for rel, original in originals.items():
                with open(os.path.join(d, rel)) as f:
                    self.assertEqual(f.read(), original.replace(old, new), rel)
            self.assertTrue(os.access(os.path.join(d, "bin", "agentainer"), os.X_OK))
            with open(env) as f:
                self.assertEqual(bv.values(bv.parse_env(f.read()))["AGENTAINER_RELEASE_VERSION"], new)

    def test_release_pin_is_never_downgraded(self):
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, "versions.env")
            with open(env, "w") as f:
                f.write("AGENTAINER_RELEASE_VERSION=0.1.0-dev.20261104.1\n")
            with patch.object(bv, "fetch_json", return_value=[{"tag_name": "v0.1.0-dev.20261024.1"}]), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(bv.main(["--file", env, "--only", "r_agentainer_release"]), 0)
            with open(env) as f:
                self.assertEqual(f.read(), "AGENTAINER_RELEASE_VERSION=0.1.0-dev.20261104.1\n")

    def test_missing_k8s_manifest_fails_and_writes_nothing(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        rel = os.path.join("deploy", "kubernetes", "agentainer", "statefulset.yaml")
        with open(os.path.join(root, "versions.env")) as f:
            env_text = f.read()
        with tempfile.TemporaryDirectory() as d:
            env = os.path.join(d, "versions.env")
            with open(env, "w") as f:
                f.write(env_text)
            os.makedirs(os.path.join(d, os.path.dirname(rel)))
            shutil.copyfile(os.path.join(root, rel), os.path.join(d, rel))
            err = io.StringIO()
            with patch.object(bv, "fetch_json", return_value={"digest": "sha256:" + "c" * 64}), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(bv.main(["--file", env, "--only", "r_k8s_images"]), 1)
            self.assertIn("is missing; pins unchanged", err.getvalue())
            with open(env) as f:
                self.assertEqual(f.read(), env_text)
            with open(os.path.join(d, rel)) as f, open(os.path.join(root, rel)) as g:
                self.assertEqual(f.read(), g.read())

    def test_strip_v(self):
        self.assertEqual(bv.strip_v("v2.102.0"), "2.102.0")
        self.assertEqual(bv.strip_v("rust-v0.162.0"), "0.162.0")
        self.assertEqual(bv.strip_v("0.12.24"), "0.12.24")


class ValidationTests(unittest.TestCase):
    def test_checksum_must_be_hex(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_checksum_file("<html>not found</html>\n")

    def test_empty_digest_rejected(self):
        release = {"tag_name": "v1", "assets": [{"name": "a", "digest": "sha256:"}]}
        with self.assertRaises(bv.LookupFailed):
            bv.asset_sha256(release, "a", fetch_text=lambda url: "")

    def test_agy_url_must_be_google_storage_and_hex(self):
        good = {"version": "1.3.2", "url": "https://storage.googleapis.com/antigravity-public/x/1.3.2/a.tar.gz",
                "sha512": "f" * 128}
        self.assertEqual(bv.parse_agy(good)[0], "1.3.2")
        with self.assertRaises(bv.LookupFailed):
            bv.parse_agy(dict(good, url="https://example.com/a.tar.gz"))
        with self.assertRaises(bv.LookupFailed):
            bv.parse_agy(dict(good, sha512="ff"))

    def test_agy_url_cannot_leave_the_bucket(self):
        # curl collapses "." and ".." segments, so these would fetch from another bucket.
        good = {"version": "1.3.2", "url": "https://storage.googleapis.com/antigravity-public/x/1.3.2/a.tar.gz",
                "sha512": "f" * 128}
        base = "https://storage.googleapis.com/antigravity-public/"
        bad = [
            base + "../attacker-bucket/cli_linux_x64.tar.gz",
            base + "x/../../attacker-bucket/a.tar.gz",
            base + "./a.tar.gz",
            base + "x/./a.tar.gz",
            base + "x/..",
            base + "%2e%2e/attacker-bucket/a.tar.gz",
            base + "%2E%2E/attacker-bucket/a.tar.gz",
            base + "x%2f..%2fa.tar.gz",
            base + "x//a.tar.gz",
            base + "a.tar.gz?x=1",
            base + "a.tar.gz#frag",
            base,
            "https://storage.googleapis.com/antigravity-publicx/a.tar.gz",
            "https://user@storage.googleapis.com/antigravity-public/a.tar.gz",
            "https://storage.googleapis.com:8443/antigravity-public/a.tar.gz",
            "http://storage.googleapis.com/antigravity-public/a.tar.gz",
        ]
        for url in bad:
            with self.subTest(url=url):
                with self.assertRaises(bv.LookupFailed):
                    bv.parse_agy(dict(good, url=url))
                self.assertIsNotNone(bv.invalid("AGY_URL_AMD64", url))
        self.assertIsNone(bv.invalid("AGY_URL_AMD64", good["url"]))

    def test_node_pins_are_accepted(self):
        self.assertIsNone(bv.invalid("NODE_VERSION", "26.13.0"))
        self.assertIsNone(bv.invalid("NODE_SHA256_AMD64", "b" * 64))


class WriteTests(unittest.TestCase):
    def setUp(self):
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".env") as f:
            f.write("A=1\n")
            self.path = f.name

    def tearDown(self):
        os.unlink(self.path)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def test_failure_leaves_file_untouched(self):
        def boom():
            raise bv.LookupFailed("network down")

        self.assertEqual(bv.main(["--file", self.path], resolvers=[boom]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_failure_keeps_only_that_resolvers_pins(self):
        def ok():
            return {"GO_VERSION": "1.27.3"}

        def boom():
            raise bv.LookupFailed("signature check reported EXPKEYSIG")

        def broken():
            return {}["missing"]

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(bv.main(["--file", self.path], resolvers=[boom, ok, broken]), 1)
        self.assertEqual(self.read(), "A=1\nGO_VERSION=1.27.3\n")
        self.assertIn("boom: signature check reported EXPKEYSIG; its pins are unchanged", err.getvalue())
        self.assertIn("broken: unexpected upstream data", err.getvalue())

    def test_failures_file_lists_every_failed_resolver_and_the_run_exits_0(self):
        def ok():
            return {"GO_VERSION": "1.27.3"}

        def boom():
            raise bv.LookupFailed("network\ndown")

        def boom2():
            raise bv.LookupFailed("other")

        failures = self.path + ".failures"
        self.addCleanup(lambda: os.path.exists(failures) and os.unlink(failures))
        out = io.StringIO()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(out):
            self.assertEqual(bv.main(["--file", self.path, "--failures", failures], resolvers=[boom, ok, boom2]), 0)
        with open(failures) as f:
            self.assertEqual(f.read(), "boom: network down\nboom2: other\n")
        self.assertIn("boom2: other\n", out.getvalue())
        self.assertEqual(self.read(), "A=1\nGO_VERSION=1.27.3\n")

    def test_unexpected_error_is_a_clean_failure(self):
        def broken():
            return {}["missing"]

        self.assertEqual(bv.main(["--file", self.path], resolvers=[broken]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_unknown_only_name_is_rejected(self):
        self.assertEqual(bv.main(["--file", self.path, "--only", "r_nope"]), 2)
        self.assertEqual(self.read(), "A=1\n")

    def test_success_updates_file(self):
        self.assertEqual(bv.main(["--file", self.path], resolvers=[lambda: {"GO_VERSION": "1.27.3"}]), 0)
        self.assertEqual(self.read(), "A=1\nGO_VERSION=1.27.3\n")

    def test_value_that_could_run_code_is_refused(self):
        # Shell scripts source versions.env, so upstream text must not reach it raw.
        bad = [
            {"AGY_URL_AMD64": "https://storage.googleapis.com/antigravity-public/$(touch /tmp/x)/a.tgz"},
            {"GO_VERSION": "1.27.3;id"},
            {"GH_VERSION": "2.103.1`id`"},
            {"BASE_IMAGE": "docker.io/library/ubuntu:26.04@sha256:" + "a" * 63},
            {"APT_SNAPSHOT": "20261008"},
            {"GO_SHA256_AMD64": "A" * 64},
            {"AGY_SHA512_AMD64": "a" * 127},
            {"OPENCODE_INTEGRITY_AMD64": "sha512-abc def"},
            {"NEW_THING": "1"},
        ]
        for update in bad:
            with self.subTest(update=update):
                self.assertEqual(bv.main(["--file", self.path], resolvers=[lambda u=update: u]), 1)
                self.assertEqual(self.read(), "A=1\n")

    @unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
    def test_node_with_a_bad_signature_leaves_file_untouched(self):
        shasums = ("%s  node-v26.99.0-linux-x64.tar.xz\n%s  node-v26.99.0-linux-arm64.tar.xz\n"
                   % ("b" * 64, "a" * 64)).encode()
        err = io.StringIO()
        with patch.object(bv, "fetch_json", return_value=[{"version": "v26.99.0", "date": "2026-01-01"}]) as fj, \
                patch.object(bv, "fetch_bytes", side_effect=[shasums, b"not a signature"]) as fb, \
                contextlib.redirect_stderr(err):
            self.assertEqual(bv.main(["--file", self.path, "--only", "r_node"]), 1)
        fj.assert_called_once_with("https://nodejs.org/dist/index.json")
        self.assertEqual(fb.call_args_list, [call("https://nodejs.org/dist/v26.99.0/SHASUMS256.txt"),
                                             call("https://nodejs.org/dist/v26.99.0/SHASUMS256.txt.sig")])
        self.assertIn("signature", err.getvalue())
        self.assertEqual(self.read(), "A=1\n")

    def test_current_pins_pass_validation(self):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "..", "versions.env")) as f:
            for key, value in bv.values(bv.parse_env(f.read())).items():
                with self.subTest(key=key):
                    self.assertIsNone(bv.invalid(key, value))


AWSCLI_CHANGELOG = ("=========\nCHANGELOG\n=========\n\n2.39.3\n======\n\n* api-change:``s3``: x\n\n"
                    "2.39.2\n======\n\n* api-change:``ec2``: y\n\n2.9.10\n======\n\n* z\n")


class AwsCliParserTests(unittest.TestCase):
    def test_changelog_gives_the_first_heading(self):
        self.assertEqual(bv.parse_awscli_changelog(AWSCLI_CHANGELOG), "2.39.3")

    def test_changelog_without_a_version_heading_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_awscli_changelog("=========\nCHANGELOG\n=========\n\n2.39.3 is out\n")

    def test_changelog_from_another_major_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_awscli_changelog("1.44.0\n======\n\n* x\n")

    def test_changelog_whose_first_heading_is_not_the_newest_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_awscli_changelog("2.39.2\n======\n\n* x\n\n2.39.3\n======\n\n* y\n")

    def test_zip_url_is_the_documented_versioned_name(self):
        self.assertEqual(bv.awscli_zip_url("aarch64", "2.0.30"),
                         "https://awscli.amazonaws.com/awscli-exe-linux-aarch64-2.0.30.zip")

    def test_resolver_is_registered(self):
        self.assertIn(bv.r_awscli, bv.RESOLVERS)

    def test_pins_are_accepted(self):
        self.assertIsNone(bv.invalid("AWSCLI_VERSION", "2.39.3"))
        self.assertIsNone(bv.invalid("AWSCLI_SHA256_AMD64", "a" * 64))
        self.assertIsNone(bv.invalid("AWSCLI_SHA256_ARM64", "b" * 64))


@unittest.skipUnless(shutil.which("gpg"), "gpg is not installed")
class AwsCliResolverTests(unittest.TestCase):
    """r_awscli with fetches mocked and two keys made for the test: "aws" stands in for AWS's key."""

    ZIPS = {"x86_64": b"amd64 installer zip", "aarch64": b"arm64 installer zip"}

    @classmethod
    def setUpClass(cls):
        cls.home = tempfile.mkdtemp()
        cls.env = dict(os.environ, GNUPGHOME=cls.home)
        cls.fpr = {}
        for name in ("aws", "other"):
            uid = "Test %s <%s@example.com>" % (name, name)
            cls.gpg("--quick-gen-key", uid, "ed25519", "sign", "never")
            out = cls.gpg("--with-colons", "--fingerprint", uid).decode()
            cls.fpr[name] = [l.split(":")[9] for l in out.splitlines() if l.startswith("fpr")][0]
        cls.key_file = os.path.join(cls.home, "aws.asc")
        with open(cls.key_file, "wb") as f:
            f.write(cls.gpg("--armor", "--export", cls.fpr["aws"]))

    @classmethod
    def gpg(cls, *args, data=None):
        cmd = ["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", ""] + list(args)
        return subprocess.run(cmd, env=cls.env, check=True, capture_output=True, input=data).stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def sign(self, signer, data):
        return self.gpg("--local-user", self.fpr[signer], "--detach-sign", "--output", "-", data=data)

    def downloads(self, other_signer=None, missing=None, tampered=None):
        """fetch_bytes for both zips and signatures. other_signer: the triple whose zip the
        "other" key signs. tampered: the triple whose zip differs from the signed bytes."""
        files = {}
        for triple, data in self.ZIPS.items():
            if triple == missing:
                continue
            url = bv.awscli_zip_url(triple, "2.39.3")
            files[url] = data + b"!" if triple == tampered else data
            files[url + ".sig"] = self.sign("other" if triple == other_signer else "aws", data)

        def fetch_bytes(url):
            if url not in files:
                raise bv.LookupFailed("%s: HTTP Error 404: Not Found" % url)
            return files[url]
        return fetch_bytes

    def resolve(self, fetch_bytes, pins=None):
        # pins is the snapshot main takes from --file; r_awscli reads AWSCLI_VERSION from it.
        with patch.object(bv, "fetch", return_value=AWSCLI_CHANGELOG) as fetch, \
                patch.object(bv, "fetch_bytes", side_effect=fetch_bytes) as fb, \
                patch.object(bv.EXTRA_FILES, "pins", dict(pins or {})), \
                patch.object(bv, "AWSCLI_KEY", self.key_file), \
                patch.object(bv, "AWSCLI_KEY_FINGERPRINT", self.fpr["aws"]):
            try:
                return bv.r_awscli()
            finally:
                fetch.assert_called_once_with("https://raw.githubusercontent.com/aws/aws-cli/v2/CHANGELOG.rst")
                self.calls = [c.args[0] for c in fb.call_args_list]

    def test_good_signatures_give_the_sha256_of_each_verified_zip(self):
        out = self.resolve(self.downloads())
        self.assertEqual(out, {
            "AWSCLI_VERSION": "2.39.3",
            "AWSCLI_SHA256_AMD64": hashlib.sha256(self.ZIPS["x86_64"]).hexdigest(),
            "AWSCLI_SHA256_ARM64": hashlib.sha256(self.ZIPS["aarch64"]).hexdigest()})
        base = "https://awscli.amazonaws.com/awscli-exe-linux-"
        self.assertEqual(self.calls, [base + "x86_64-2.39.3.zip", base + "x86_64-2.39.3.zip.sig",
                                      base + "aarch64-2.39.3.zip", base + "aarch64-2.39.3.zip.sig"])

    def test_signature_by_another_key_is_refused_for_each_architecture(self):
        for triple in self.ZIPS:
            with self.subTest(triple=triple), self.assertRaises(bv.LookupFailed):
                self.resolve(self.downloads(other_signer=triple))

    def test_signature_over_other_bytes_is_refused_for_each_architecture(self):
        for triple in self.ZIPS:
            with self.subTest(triple=triple), self.assertRaises(bv.LookupFailed):
                self.resolve(self.downloads(tampered=triple))

    def test_missing_architecture_is_refused(self):
        for triple in self.ZIPS:
            with self.subTest(triple=triple), self.assertRaises(bv.LookupFailed):
                self.resolve(self.downloads(missing=triple))

    def test_pinned_version_downloads_nothing(self):
        self.assertEqual(self.resolve(self.downloads(), pins={"AWSCLI_VERSION": "2.39.3"}), {})
        self.assertEqual(self.calls, [])

    def test_newer_version_downloads_and_verifies_both_architectures(self):
        with patch.object(bv, "verify_signature", wraps=bv.verify_signature) as verify:
            out = self.resolve(self.downloads(), pins={"AWSCLI_VERSION": "2.39.2"})
        self.assertEqual(out["AWSCLI_VERSION"], "2.39.3")
        self.assertEqual(len(self.calls), 4)
        self.assertEqual([c.args[0] for c in verify.call_args_list], [self.ZIPS["x86_64"], self.ZIPS["aarch64"]])

    def test_pinned_version_through_main_leaves_the_file_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "AWSCLI_VERSION=2.39.3\nAWSCLI_SHA256_AMD64=%s\nAWSCLI_SHA256_ARM64=%s\n" % ("a" * 64, "b" * 64)
            with open(path, "w") as f:
                f.write(original)
            with patch.object(bv, "fetch", return_value=AWSCLI_CHANGELOG), \
                    patch.object(bv, "fetch_bytes") as fb, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(bv.main(["--file", path, "--only", "r_awscli"]), 0)
            fb.assert_not_called()
            with open(path) as f:
                self.assertEqual(f.read(), original)

    def test_bad_signature_leaves_the_pin_file_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            original = "AWSCLI_VERSION=2.39.2\nAWSCLI_SHA256_AMD64=%s\nAWSCLI_SHA256_ARM64=%s\n" % ("a" * 64, "b" * 64)
            with open(path, "w") as f:
                f.write(original)
            err = io.StringIO()
            with patch.object(bv, "fetch", return_value=AWSCLI_CHANGELOG), \
                    patch.object(bv, "fetch_bytes", side_effect=self.downloads(other_signer="aarch64")), \
                    patch.object(bv, "AWSCLI_KEY", self.key_file), \
                    patch.object(bv, "AWSCLI_KEY_FINGERPRINT", self.fpr["aws"]), \
                    contextlib.redirect_stderr(err):
                self.assertEqual(bv.main(["--file", path, "--only", "r_awscli"]), 1)
            self.assertIn("signature", err.getvalue())
            with open(path) as f:
                self.assertEqual(f.read(), original)


NOW = datetime.datetime(2026, 11, 1, 12, 0, tzinfo=datetime.timezone.utc)


def iso(days_before_now):
    return (NOW - datetime.timedelta(days=days_before_now)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class PickVersionTests(unittest.TestCase):
    def packument(self, versions, latest):
        return {"dist-tags": {"latest": latest},
                "versions": {v: dict(extra, version=v) for v, (_, extra) in versions.items()},
                "time": dict({"created": iso(400), "modified": iso(0)},
                             **{v: iso(age) for v, (age, _) in versions.items()})}

    def test_newest_version_at_least_seven_days_old(self):
        doc = self.packument({"1.0.0": (30, {}), "1.1.0": (8, {}), "1.2.0": (3, {}),
                              "1.3.0-beta.1": (10, {}), "1.1.5": (9, {"deprecated": "broken"}),
                              "2.0.0": (20, {})}, latest="1.2.0")
        # 2.0.0 is above dist-tags.latest, 1.2.0 is too young, 1.1.5 is deprecated, 1.3.0-beta.1 is a prerelease.
        self.assertEqual(bv.pick_version(doc, NOW), "1.1.0")

    def test_exactly_seven_days_qualifies(self):
        doc = self.packument({"1.0.0": (7, {})}, latest="1.0.0")
        self.assertEqual(bv.pick_version(doc, NOW), "1.0.0")

    def test_no_qualifying_version_fails(self):
        doc = self.packument({"1.0.0": (2, {}), "1.1.0-rc.1": (30, {})}, latest="1.0.0")
        with self.assertRaises(bv.LookupFailed):
            bv.pick_version(doc, NOW)

    def test_version_without_a_time_entry_is_skipped(self):
        doc = self.packument({"1.0.0": (30, {}), "1.1.0": (30, {})}, latest="1.1.0")
        del doc["time"]["1.1.0"]
        self.assertEqual(bv.pick_version(doc, NOW), "1.0.0")

    def test_prerelease_latest_bounds_the_pick_below_its_release(self):
        # npm accepts these prerelease forms; agentainer's own release_version.version_key rejects
        # the first two (dev.N without a date, and a numeric identifier with a leading zero).
        for latest in ("1.0.0-dev.5", "1.0.0-beta.01", "1.0.0-rc.1", "1.0.0-alpha+build.7"):
            with self.subTest(latest=latest):
                doc = self.packument({"0.9.0": (30, {}), "0.10.0": (20, {}), "1.0.0": (10, {}),
                                      latest: (15, {}), "1.0.0-dev.4": (25, {})}, latest=latest)
                # 1.0.0 is above a 1.0.0 prerelease, and 0.10.0 sorts above 0.9.0.
                self.assertEqual(bv.pick_version(doc, NOW), "0.10.0")

    def test_numeric_order_and_stable_latest_with_prereleases_in_versions(self):
        doc = self.packument({"1.9.0": (30, {}), "1.10.0": (20, {}), "2.0.0-dev.5": (15, {}),
                              "2.0.0-rc.1": (10, {}), "1.10.1-beta.02": (9, {})}, latest="1.10.0")
        self.assertEqual(bv.pick_version(doc, NOW), "1.10.0")

    def test_npm_version_key(self):
        key = bv.npm_version_key
        self.assertGreater(key("1.10.0"), key("1.9.0"))
        self.assertGreater(key("2.0.0"), key("2.0.0-dev.5"))
        self.assertGreater(key("2.0.0-rc.1"), key("1.99.99"))
        self.assertEqual(key("1.2.3+build.1"), key("1.2.3"))
        for bad in ("1.2", "v1.2.3", "1.2.3-", "x", ""):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                key(bad)


class NewInstallScriptsTests(unittest.TestCase):
    def test_reports_only_packages_newly_flagged(self):
        old = {"packages": {"": {}, "node_modules/a": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/c": {"version": "1.0.0"}}}
        new = {"packages": {"": {}, "node_modules/x/node_modules/a": {"version": "1.1.0", "hasInstallScript": True},
                            "node_modules/@s/b": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/c": {"version": "1.1.0"},
                            "node_modules/node-pty": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/frida": {"version": "1.0.0", "hasInstallScript": True}}}
        self.assertEqual(bv.new_install_scripts(old, new), ["@s/b"])

    def test_empty_old_lockfile_reports_every_flagged_package(self):
        new = {"packages": {"node_modules/a": {"version": "1.0.0", "hasInstallScript": True},
                            "node_modules/b": {"version": "1.0.0"}}}
        self.assertEqual(bv.new_install_scripts({}, new), ["a"])


def openssl(*args):
    return subprocess.run(["openssl"] + list(args), check=True, capture_output=True).stdout


@unittest.skipUnless(shutil.which("openssl"), "openssl is not installed")
class RegistrySignatureTests(unittest.TestCase):
    """verify_registry_signature against P-256 keys made for the test."""

    NAME, VERSION, INTEGRITY = "@s/pkg", "1.2.3", "sha512-" + "A" * 86 + "=="

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.keys, cls.pem = {}, {}
        for keyid in ("SHA256:good", "SHA256:old", "SHA256:other"):
            pem = os.path.join(cls.dir, keyid.split(":")[1] + ".pem")
            openssl("ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", pem)
            der = openssl("ec", "-in", pem, "-pubout", "-outform", "DER")
            cls.pem[keyid] = pem
            cls.keys[keyid] = {"keyid": keyid, "keytype": "ecdsa-sha2-nistp256", "scheme": "ecdsa-sha2-nistp256",
                               "expires": None, "key": base64.b64encode(der).decode()}
        cls.keys["SHA256:old"]["expires"] = "2025-01-29T00:00:00.000Z"
        # "other" signs but is not pinned.
        cls.pinned = {k: v for k, v in cls.keys.items() if k != "SHA256:other"}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def sign(self, keyid, message=None):
        message = message or "%s@%s:%s" % (self.NAME, self.VERSION, self.INTEGRITY)
        path = os.path.join(self.dir, "message")
        with open(path, "w") as f:
            f.write(message)
        sig = openssl("dgst", "-sha256", "-sign", self.pem[keyid], path)
        return {"keyid": keyid, "sig": base64.b64encode(sig).decode()}

    def verify(self, signatures, integrity=None, published=None):
        bv.verify_registry_signature(self.NAME, self.VERSION, integrity or self.INTEGRITY, signatures,
                                     self.pinned, published=published)

    def test_valid_signature_passes(self):
        self.verify([self.sign("SHA256:good")])

    def test_unknown_keyid_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:other")])

    def test_changed_integrity_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:good")], integrity="sha512-" + "B" * 86 + "==")

    def test_signature_over_other_data_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:good", message="other@1.2.3:" + self.INTEGRITY)])

    def test_garbage_signature_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([{"keyid": "SHA256:good", "sig": "bm90IGEgc2lnbmF0dXJl"}])

    def test_empty_list_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([])

    def test_any_verifying_signature_with_a_known_keyid_passes(self):
        bad = self.sign("SHA256:good", message="other@1.2.3:" + self.INTEGRITY)
        self.verify([self.sign("SHA256:other"), bad, self.sign("SHA256:good")])

    def test_expiring_key_passes_for_a_version_published_before_expiry(self):
        published = lambda: datetime.datetime(2024, 6, 1, tzinfo=datetime.timezone.utc)
        self.verify([self.sign("SHA256:old")], published=published)

    def test_expiring_key_fails_for_a_version_published_after_expiry(self):
        published = lambda: datetime.datetime(2025, 1, 29, tzinfo=datetime.timezone.utc)
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:old")], published=published)

    def test_expiring_key_fails_without_a_publish_time(self):
        with self.assertRaises(bv.LookupFailed):
            self.verify([self.sign("SHA256:old")])

    def test_missing_publish_time_moves_on_to_the_next_signature(self):
        def published():
            raise bv.LookupFailed("unexpected registry time None")

        self.verify([self.sign("SHA256:old"), self.sign("SHA256:good")], published=published)
        with self.assertRaises(bv.LookupFailed) as ctx:
            self.verify([self.sign("SHA256:old")], published=published)
        self.assertIn("@s/pkg@1.2.3", str(ctx.exception))
        self.assertIn("unexpected registry time", str(ctx.exception))

    def test_check_lockfile_verifies_every_entry(self):
        integrity = self.INTEGRITY
        lock = {"lockfileVersion": 3, "packages": {
            "": {"name": "wrapper", "dependencies": {"@s/pkg": "1.2.3"}},
            "node_modules/@s/pkg": {"version": "1.2.3", "integrity": integrity,
                                    "resolved": "https://registry.npmjs.org/@s/pkg/-/pkg-1.2.3.tgz"},
            "node_modules/@s/pkg/node_modules/inner": {"version": "1.0.0", "inBundle": True},
            "node_modules/alias": {"name": "@s/pkg", "version": "1.2.3", "integrity": integrity,
                                   "resolved": "https://registry.npmjs.org/@s/pkg/-/pkg-1.2.3.tgz"},
            "node_modules/old": {"version": "1.2.3", "integrity": integrity,
                                 "resolved": "https://registry.npmjs.org/old/-/old-1.2.3.tgz"}}}
        good = self.sign("SHA256:good")
        self.NAME = "old"
        old = self.sign("SHA256:old")
        self.NAME = "@s/pkg"
        docs = {"https://registry.npmjs.org/@s/pkg/1.2.3": {"dist": {"integrity": integrity, "signatures": [good]}},
                "https://registry.npmjs.org/old/1.2.3": {"dist": {"integrity": integrity, "signatures": [old]}},
                "https://registry.npmjs.org/old": {"time": {"1.2.3": "2024-06-01T00:00:00.000Z"}}}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return docs[url]

        bv.check_lockfile(lock, fetch_json=fetch, keys=self.pinned)
        self.assertEqual(sorted(set(fetched)), sorted(docs))
        docs["https://registry.npmjs.org/old"]["time"]["1.2.3"] = "2025-02-01T00:00:00.000Z"
        with self.assertRaises(bv.LookupFailed):
            bv.check_lockfile(lock, fetch_json=fetch, keys=self.pinned)


class CheckLockfileTests(unittest.TestCase):
    INTEGRITY = "sha512-" + "A" * 86 + "=="

    def lock(self, **entry):
        base = {"version": "1.0.0", "integrity": self.INTEGRITY,
                "resolved": "https://registry.npmjs.org/a/-/a-1.0.0.tgz"}
        base.update(entry)
        return {"packages": {"": {}, "node_modules/a": {k: v for k, v in base.items() if v is not None}}}

    def check(self, lock, dist):
        verify = patch.object(bv, "verify_registry_signature")
        with verify as verified:
            bv.check_lockfile(lock, fetch_json=lambda url: {"dist": dist}, keys={})
        return verified

    def test_registry_integrity_must_equal_the_lockfile(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(), {"integrity": "sha512-" + "B" * 86 + "==", "signatures": []})

    def test_matching_integrity_goes_to_the_signature_check(self):
        verified = self.check(self.lock(), {"integrity": self.INTEGRITY, "signatures": ["s"]})
        self.assertEqual(verified.call_args.args[:4], ("a", "1.0.0", self.INTEGRITY, ["s"]))

    def test_entry_without_integrity_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(integrity=None), {"integrity": self.INTEGRITY, "signatures": []})

    def test_entry_resolved_outside_the_registry_fails(self):
        with self.assertRaises(bv.LookupFailed):
            self.check(self.lock(resolved="https://example.com/a-1.0.0.tgz"),
                       {"integrity": self.INTEGRITY, "signatures": []})

    def test_link_entry_is_refused(self):
        lock = self.lock()
        lock["packages"]["node_modules/b"] = {"resolved": "../b", "link": True}
        with self.assertRaises(bv.LookupFailed) as ctx:
            self.check(lock, {"integrity": self.INTEGRITY, "signatures": []})
        self.assertIn("node_modules/b", str(ctx.exception))

    def test_bundled_entry_is_covered_by_its_parent(self):
        lock = self.lock()
        lock["packages"]["node_modules/a/node_modules/inner"] = {"version": "2.0.0", "inBundle": True}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return {"dist": {"integrity": self.INTEGRITY, "signatures": []}}

        with patch.object(bv, "verify_registry_signature") as verified:
            bv.check_lockfile(lock, fetch_json=fetch, keys={})
        self.assertEqual(fetched, ["https://registry.npmjs.org/a/1.0.0"])
        self.assertEqual(verified.call_count, 1)

    def test_entry_that_is_not_an_object_is_refused(self):
        lock = self.lock()
        lock["packages"]["node_modules/b"] = "1.0.0"
        with self.assertRaises(bv.LookupFailed):
            self.check(lock, {"integrity": self.INTEGRITY, "signatures": []})
        with self.assertRaises(bv.LookupFailed):
            self.check({"packages": []}, {})
        with self.assertRaises(bv.LookupFailed):
            self.check([], {})

    def test_registry_data_that_is_not_an_object_is_refused(self):
        for doc in ([], {"dist": []}, {"dist": {"integrity": self.INTEGRITY, "signatures": {}}}):
            with self.subTest(doc=doc):
                with patch.object(bv, "verify_registry_signature"), self.assertRaises(bv.LookupFailed):
                    bv.check_lockfile(self.lock(), fetch_json=lambda url, d=doc: d, keys={})

    def test_names_outside_npm_naming_rules_are_refused(self):
        for name in (".", "..", ".hidden", "_private", "@scope/..", "@../x", "a/b", "a" * 215):
            with self.subTest(name=name):
                with self.assertRaises(bv.LookupFailed):
                    self.check(self.lock(name=name), {"integrity": self.INTEGRITY, "signatures": []})
        # npm allows a scoped name to begin with a dot or an underscore.
        verified = self.check(self.lock(name="@scope/_x"), {"integrity": self.INTEGRITY, "signatures": []})
        self.assertEqual(verified.call_args.args[0], "@scope/_x")


CATALOG = "rootfs/usr/local/share/agentainer/extras"


class ExtrasTests(unittest.TestCase):
    """r_extras and main over a temporary repo copy with npm, the registry and check_lockfile mocked."""

    OLD_LOCK = {"lockfileVersion": 3, "packages": {"": {"dependencies": {"kandev": "1.0.0"}},
                                                   "node_modules/kandev": {"version": "1.0.0"}}}

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env = os.path.join(self.dir, "versions.env")
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.0.0\nOPENCHAMBER_VERSION=2.0.0\nREA_VERSION=3.0.0\n")
        for key, name, extra in bv.EXTRAS:
            pin = {"kandev": "1.0.0", "openchamber": "2.0.0", "rea": "3.0.0"}[extra]
            self.write("%s/%s/package.json" % (CATALOG, extra),
                       json.dumps({"private": True, "dependencies": {name: pin}}, indent=2) + "\n")
            self.write("%s/%s/package-lock.json" % (CATALOG, extra),
                       json.dumps(dict(self.OLD_LOCK, name=extra), indent=2) + "\n")
            self.write("%s/%s/extra.conf" % (CATALOG, extra), "description=x\n")
        self.latest = {"kandev": "1.1.0", "@openchamber/web": "2.1.0", "rea-agents": "3.1.0"}
        self.new_lock_extra = {}
        self.npm_calls = []
        self.registry_docs = {}
        self.lock_override = {}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def snapshot(self):
        out = {}
        for root, _, files in os.walk(self.dir):
            for name in files:
                path = os.path.join(root, name)
                with open(path, "rb") as f:
                    out[os.path.relpath(path, self.dir)] = f.read()
        return out

    def packument(self, url):
        if url in self.registry_docs:
            return self.registry_docs[url]
        name = url[len("https://registry.npmjs.org/"):]
        ver = self.latest[name]
        return {"dist-tags": {"latest": ver}, "versions": {ver: {"version": ver}}, "time": {ver: iso(10)}}

    def npm(self, argv, **kwargs):
        self.npm_calls.append((argv, kwargs))
        with open(os.path.join(kwargs["cwd"], "package.json")) as f:
            deps = json.load(f)["dependencies"]
        (name, ver), = deps.items()
        packages = {"": {"dependencies": deps}, "node_modules/" + name: {
            "version": ver, "integrity": "sha512-" + "A" * 86 + "==",
            "resolved": "https://registry.npmjs.org/%s/-/x-%s.tgz" % (name, ver)}}
        packages.update(self.new_lock_extra.get(name, {}))
        with open(os.path.join(kwargs["cwd"], "package-lock.json"), "w") as f:
            json.dump(self.lock_override.get(name, {"lockfileVersion": 3, "packages": packages}), f)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def run_main(self, argv=None, resolvers=None, check=None, real_check=False, github_actions=None):
        out, err = io.StringIO(), io.StringIO()
        environ = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
        if github_actions is not None:
            environ["GITHUB_ACTIONS"] = github_actions
        checker = (contextlib.nullcontext() if real_check
                   else patch.object(bv, "check_lockfile", side_effect=check))
        with patch.object(bv, "fetch_json", side_effect=self.packument), \
                patch.object(bv.subprocess, "run", side_effect=self.npm), \
                checker as checked, \
                patch.object(bv, "utcnow", return_value=NOW), \
                patch.dict(os.environ, environ, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bv.main(["--file", self.env] + (argv or []), resolvers=resolvers)
        self.checked = checked
        return rc, out.getvalue(), err.getvalue()

    def read(self, rel):
        with open(os.path.join(self.dir, rel)) as f:
            return f.read()

    def test_extras_resolver_is_registered_and_its_pins_validate(self):
        self.assertIn(bv.r_extras, bv.RESOLVERS)
        self.assertEqual([e[0] for e in bv.EXTRAS], ["KANDEV_VERSION", "OPENCHAMBER_VERSION", "REA_VERSION"])
        self.assertEqual(bv.EXTRA_MIN_AGE_DAYS, 7)
        for key, _, _ in bv.EXTRAS:
            self.assertIsNone(bv.invalid(key, "0.98.0"))

    def test_registry_keys_file_pins_both_npm_keys(self):
        keys = bv.load_registry_keys(bv.NPM_KEYS)
        self.assertEqual(sorted(keys), ["SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U",
                                        "SHA256:jl3bwswu80PjjokCgh0o2w5c2U4LhQAE57gj9cz1kzA"])
        self.assertIsNone(keys["SHA256:DhQ8wR5APBvFHLF/+Tc+AYvPOdTpcIDqOhxsBHRwC7U"]["expires"])
        self.assertEqual(keys["SHA256:jl3bwswu80PjjokCgh0o2w5c2U4LhQAE57gj9cz1kzA"]["expires"],
                         "2025-01-29T00:00:00.000Z")

    def test_success_writes_pins_wrappers_and_lockfiles(self):
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertIn("OPENCHAMBER_VERSION=2.1.0\n", env)
        self.assertIn("REA_VERSION=3.1.0\n", env)
        wrapper = json.loads(self.read(CATALOG + "/openchamber/package.json"))
        self.assertEqual(wrapper, {"private": True, "dependencies": {"@openchamber/web": "2.1.0"}})
        lock = json.loads(self.read(CATALOG + "/rea/package-lock.json"))
        self.assertEqual(lock["packages"]["node_modules/rea-agents"]["version"], "3.1.0")
        self.assertIn("extras kandev: lockfile regenerated", out)
        self.assertEqual(self.checked.call_count, 3)
        argv, kwargs = self.npm_calls[0]
        self.assertEqual(argv[:6], ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit",
                                    "--no-fund"])
        self.assertIn("--before=2026-10-25T12:00:00Z", argv)
        self.assertIn("--registry=https://registry.npmjs.org/", argv)
        self.assertTrue(any(a.startswith("--cache=") for a in argv))
        self.assertNotEqual(kwargs["cwd"], self.dir)
        self.assertEqual(env.splitlines()[0], "A=1")

    DOC = ("# Extras\n\n"
           "npm package `kandev`. License ([npm metadata for kandev 1.0.0](https://registry.npmjs.org/kandev/1.0.0)).\n"
           "README: https://unpkg.com/@openchamber/web@2.0.0/README.md and "
           "[`@openchamber/web` 2.0.0](https://unpkg.com/@openchamber/web@2.0.0/bin/lib/cli-args.js).\n"
           "REA ([npm metadata for rea-agents 3.0.0](https://registry.npmjs.org/rea-agents/3.0.0)).\n"
           "Unrelated: version 1.0.0, frida 3.0.0, kandev 1.0.0.1, xkandev 1.0.0.\n\n"
           "## Known findings\n\nChecked on one day.\n\n"
           "| Extra | Package |\n|---|---|\n| REA (`rea-agents` 3.0.0) | `minimatch` 1.0.0 |\n"
           "| Kandev (kandev 1.0.0) | none |\n\n"
           "Text after the table: rea-agents 3.0.0.\n\n## How the pins update\n\nkandev 1.0.0\n")

    def test_pin_bump_rewrites_extras_doc_outside_the_findings_table(self):
        self.write(bv.EXTRAS_DOC, self.DOC)
        rc, _, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        doc = self.read(bv.EXTRAS_DOC)
        for mention in ("npm metadata for kandev 1.1.0", "registry.npmjs.org/kandev/1.1.0",
                        "unpkg.com/@openchamber/web@2.1.0/README.md", "[`@openchamber/web` 2.1.0]",
                        "unpkg.com/@openchamber/web@2.1.0/bin/lib/cli-args.js",
                        "npm metadata for rea-agents 3.1.0", "registry.npmjs.org/rea-agents/3.1.0",
                        "Text after the table: rea-agents 3.1.0.", "## How the pins update\n\nkandev 1.1.0\n"):
            with self.subTest(mention=mention):
                self.assertIn(mention, doc)
        # Equal versions that do not follow the package name, or are part of a longer version or
        # name, stay as they are.
        self.assertIn("Unrelated: version 1.0.0, frida 3.0.0, kandev 1.0.0.1, xkandev 1.0.0.\n", doc)
        start = self.DOC.index("| Extra |")
        end = self.DOC.index("\n\nText after the table")
        self.assertEqual(doc[start:end], self.DOC[start:end])
        # The bump-pr action's content check accepts the rewrite.
        import check_bump_refs
        env = check_bump_refs.read_env(self.env)
        self.assertEqual(check_bump_refs.problems(bv.EXTRAS_DOC, self.DOC, doc, env), [])
        self.assertNotEqual(check_bump_refs.problems(bv.EXTRAS_DOC, self.DOC, doc,
                                                     dict(env, KANDEV_VERSION="1.2.0")), [])

    def test_unchanged_pins_leave_extras_doc_alone(self):
        self.write(bv.EXTRAS_DOC, self.DOC)
        self.latest = {"kandev": "1.0.0", "@openchamber/web": "2.0.0", "rea-agents": "3.0.0"}
        rc, _, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read(bv.EXTRAS_DOC), self.DOC)

    def test_catalog_test_passes_after_a_simulated_bump(self):
        """Bump every extra in a copy of the real catalog and docs, then run the catalog test there."""
        root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
        for rel in ("tests/host/test-extras-catalog.sh", "tests/lib.sh", bv.EXTRAS_DOC):
            os.makedirs(os.path.join(self.dir, os.path.dirname(rel)), exist_ok=True)
            shutil.copy2(os.path.join(root, rel), os.path.join(self.dir, rel))
        for rel in ("scripts", "rootfs/usr/local/lib/agentainer", CATALOG):
            shutil.rmtree(os.path.join(self.dir, rel), ignore_errors=True)
            shutil.copytree(os.path.join(root, rel), os.path.join(self.dir, rel),
                            ignore=shutil.ignore_patterns("__pycache__"))
        with open(os.path.join(root, "versions.env")) as f:
            pins = bv.values(bv.parse_env(f.read()))
        self.write("versions.env", "".join("%s=%s\n" % (key, pins[key]) for key, _, _ in bv.EXTRAS))
        self.latest = {}
        for key, name, extra in bv.EXTRAS:
            old = pins[key]
            new = "%s.%d.0" % (old.split(".")[0], int(old.split(".")[1]) + 1)
            self.latest[name] = new
            # The real lockfile with the package moved to the new version.
            with open(os.path.join(self.dir, CATALOG, extra, "package-lock.json")) as f:
                lock = json.load(f)
            lock["packages"][""]["dependencies"] = {name: new}
            lock["packages"]["node_modules/" + name]["version"] = new
            self.lock_override[name] = lock
        before = self.read(bv.EXTRAS_DOC)
        rc, _, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertNotEqual(self.read(bv.EXTRAS_DOC), before)
        result = subprocess.run(["sh", os.path.join(self.dir, "tests/host/test-extras-catalog.sh")],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for _, name, _ in bv.EXTRAS:
            self.assertRegex(result.stdout, r"(?m)^ok \d+ - docs/extras\.md names %s only at " % re.escape(name))
        self.assertNotIn("not ok", result.stdout)

    def test_failed_check_keeps_only_that_extras_pin_and_files(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: registry integrity differs from the lockfile")

        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        after = self.snapshot()
        for rel in ("package.json", "package-lock.json", "extra.conf"):
            path = os.path.join(CATALOG, "rea", rel)
            self.assertEqual(after[path], before[path])
        self.assertIn(b"REA_VERSION=3.0.0\n", after["versions.env"])
        self.assertIn(b"KANDEV_VERSION=1.1.0\n", after["versions.env"])
        self.assertNotEqual(after[os.path.join(CATALOG, "kandev", "package-lock.json")],
                            before[os.path.join(CATALOG, "kandev", "package-lock.json")])
        self.assertIn("bump_versions: extras rea: rea-agents@3.1.0: registry integrity differs from the lockfile; "
                      "pin unchanged", err)

    def test_new_install_script_keeps_the_pin(self):
        self.new_lock_extra["kandev"] = {"node_modules/evil": {"version": "1.0.0", "hasInstallScript": True}}
        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        after = self.snapshot()
        self.assertIn(b"KANDEV_VERSION=1.0.0\n", after["versions.env"])
        for rel in ("package.json", "package-lock.json"):
            path = os.path.join(CATALOG, "kandev", rel)
            self.assertEqual(after[path], before[path])
        self.assertIn("extras kandev:", err)
        self.assertIn("evil", err)

    def test_candidate_not_newer_keeps_the_pin_without_running_npm(self):
        self.latest = {"kandev": "1.0.0", "@openchamber/web": "1.9.0", "rea-agents": "3.0.0"}
        before = self.snapshot()
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.npm_calls, [])

    def test_prerelease_pin_is_replaced_by_its_release(self):
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.1.0-dev.5\nOPENCHAMBER_VERSION=2.0.0\nREA_VERSION=3.0.0\n")
        self.latest = {"kandev": "1.1.0", "@openchamber/web": "2.0.0", "rea-agents": "3.0.0"}
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("KANDEV_VERSION: 1.1.0-dev.5 -> 1.1.0", out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_downgrade_guard_orders_extras_pins_numerically(self):
        self.write("versions.env", "KANDEV_VERSION=1.10.0\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "1.9.0"}])
        self.assertNotEqual(rc, 0)
        self.assertIn("resolver would downgrade KANDEV_VERSION", err)
        self.assertEqual(self.read("versions.env"), "KANDEV_VERSION=1.10.0\n")
        self.write("versions.env", "KANDEV_VERSION=2.0.0-dev.5\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "1.99.0"}])
        self.assertNotEqual(rc, 0)
        self.assertIn("resolver would downgrade KANDEV_VERSION", err)
        self.write("versions.env", "KANDEV_VERSION=2.0.0-dev.5\n")
        rc, out, err = self.run_main(resolvers=[lambda: {"KANDEV_VERSION": "2.0.0"}])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read("versions.env"), "KANDEV_VERSION=2.0.0\n")

    def test_missing_catalog_or_pin_skips_that_extra(self):
        shutil.rmtree(os.path.join(self.dir, CATALOG, "openchamber"))
        self.write("versions.env", "A=1\nKANDEV_VERSION=1.0.0\nOPENCHAMBER_VERSION=2.0.0\n")
        rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("extras openchamber:", err)
        self.assertIn("extras rea:", err)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertNotIn("REA_VERSION", env)
        self.assertFalse(os.path.exists(os.path.join(self.dir, CATALOG, "openchamber")))
        self.assertEqual(len(self.npm_calls), 1)

    def test_verification_failure_is_recorded_and_other_pins_are_written(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                     github_actions="true")
        self.assertEqual(rc, 0, err)
        line = "extras rea: rea-agents@3.1.0: no registry signature verifies"
        with open(failures) as f:
            self.assertEqual(f.read(), line + "\n")
        self.assertIn("::warning::bump_versions: " + line + "\n", out)
        self.assertIn("\n" + line + "\n", "\n" + out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))
        self.assertIn("REA_VERSION=3.0.0\n", self.read("versions.env"))

    def test_failure_line_is_one_line_and_the_annotation_is_escaped(self):
        def check(lock, **kwargs):
            if "node_modules/kandev" in lock["packages"]:
                raise bv.LookupFailed("npm said\n100% wrong")

        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                     github_actions="true")
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "extras kandev: npm said 100% wrong\n")
        self.assertIn("::warning::bump_versions: extras kandev: npm said 100%25 wrong\n", out)

    def test_warning_annotation_only_on_github_actions(self):
        def check(lock, **kwargs):
            raise bv.LookupFailed("bad")

        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        self.assertNotIn("::warning::", out)
        self.assertIn("extras kandev: bad\n", out)

    def test_routine_skips_leave_the_failures_file_empty(self):
        shutil.rmtree(os.path.join(self.dir, CATALOG, "openchamber"))
        self.latest["kandev"] = "1.0.0"
        self.registry_docs["https://registry.npmjs.org/rea-agents"] = {
            "dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}, "time": {"3.1.0": iso(2)}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], github_actions="true")
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "")
        self.assertNotIn("extras", out)
        self.assertIn("extras openchamber:", err)
        self.assertIn("extras rea:", err)
        self.assertEqual(self.npm_calls, [])

    def test_failures_file_is_not_created_without_the_option(self):
        def check(lock, **kwargs):
            raise bv.LookupFailed("bad")

        rc, out, err = self.run_main(["--only", "r_extras"], check=check)
        self.assertEqual(rc, 0, err)
        self.assertEqual(sorted(p for p in os.listdir(self.dir)), ["rootfs", "versions.env"])

    def test_malformed_data_is_a_verification_failure_for_that_extra_only(self):
        # A lockfile that is a list, and a registry document for one version that is a list.
        self.lock_override["kandev"] = []
        self.registry_docs["https://registry.npmjs.org/rea-agents/3.1.0"] = []
        self.registry_docs["https://registry.npmjs.org/@openchamber/web/2.1.0"] = {
            "dist": {"integrity": "sha512-" + "B" * 86 + "==", "signatures": []}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], real_check=True)
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            lines = f.read().splitlines()
        self.assertEqual([line.split(":")[0] for line in lines],
                         ["extras kandev", "extras openchamber", "extras rea"])
        env = self.read("versions.env")
        for pin in ("KANDEV_VERSION=1.0.0", "OPENCHAMBER_VERSION=2.0.0", "REA_VERSION=3.0.0"):
            self.assertIn(pin + "\n", env)

    def test_unexpected_shape_inside_a_check_stays_with_that_extra(self):
        error = AttributeError("'list' object has no attribute 'get'")
        with patch.object(bv, "new_install_scripts", side_effect=[[], error, []]):
            rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertIn("extras openchamber: 'list' object has no attribute 'get'\n", out)
        env = self.read("versions.env")
        self.assertIn("KANDEV_VERSION=1.1.0\n", env)
        self.assertIn("OPENCHAMBER_VERSION=2.0.0\n", env)
        self.assertIn("REA_VERSION=3.1.0\n", env)

    def test_malformed_registry_times_are_failures(self):
        failures = os.path.join(self.dir, "failures.txt")
        for case, time_map in (("absent", None), ("empty", {}), ("not a string", {"3.1.0": 12345})):
            with self.subTest(case=case):
                doc = {"dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}}
                if time_map is not None:
                    doc["time"] = time_map
                self.registry_docs["https://registry.npmjs.org/rea-agents"] = doc
                rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
                self.assertEqual(rc, 0, err)
                with open(failures) as f:
                    lines = f.read().splitlines()
                self.assertEqual([line.split(":")[0] for line in lines], ["extras rea"])
                self.assertIn("REA_VERSION=3.0.0\n", self.read("versions.env"))

    def test_too_young_version_is_a_quiet_skip(self):
        self.registry_docs["https://registry.npmjs.org/rea-agents"] = {
            "dist-tags": {"latest": "3.1.0"}, "versions": {"3.1.0": {}}, "time": {"3.1.0": iso(2)}}
        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertNotIn("extras rea", f.read())
        self.assertIn("extras rea:", err)

    def test_failed_resolver_replaces_a_stale_failures_file(self):
        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        with open(failures, "w") as f:
            f.write("stale\n")
        rc, out, err = self.run_main(["--failures", failures], resolvers=[boom])
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "boom: network down\n")
        os.unlink(failures)
        rc, out, err = self.run_main(["--failures", failures, "--only", "r_nope"])
        self.assertEqual(rc, 2)
        with open(failures) as f:
            self.assertEqual(f.read(), "")

    def test_resolver_and_extras_failures_both_reach_the_file(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        rc, out, err = self.run_main(["--failures", failures], resolvers=[bv.r_extras, boom], check=check)
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "boom: network down\n"
                                       "extras rea: rea-agents@3.1.0: no registry signature verifies\n")
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))
        self.assertIn("REA_VERSION=3.0.0\n", self.read("versions.env"))

    def test_unwritable_failures_file_is_a_clean_error(self):
        failures = os.path.join(self.dir, "missing-dir", "failures.txt")
        before = self.snapshot()
        rc, out, err = self.run_main(["--failures", failures, "--only", "r_extras"])
        self.assertEqual(rc, 2)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.npm_calls, [])

    def failing_report_write(self, failures):
        """Patch write_atomic so every write to failures after the first (the truncation) raises."""
        real = bv.write_atomic
        calls = []

        def write(path, text):
            if path == failures:
                calls.append(text)
                if len(calls) > 1:
                    raise OSError(28, "No space left on device")
            real(path, text)

        return patch.object(bv, "write_atomic", side_effect=write)

    def test_failures_file_write_error_after_failures_fails_the_run(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("rea-agents@3.1.0: no registry signature verifies")

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check)
        self.assertEqual(rc, 2)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertIn("No space left on device", err)
        self.assertNotIn("Traceback", err)
        self.assertIn("extras rea: rea-agents@3.1.0: no registry signature verifies\n", out)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_failures_file_write_error_keeps_a_nonzero_exit_code(self):
        def check(lock, **kwargs):
            if "node_modules/rea-agents" in lock["packages"]:
                raise bv.LookupFailed("bad")

        def boom():
            raise bv.LookupFailed("network down")

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--failures", failures], resolvers=[bv.r_extras, boom], check=check)
        self.assertEqual(rc, 2)
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)

    def test_failures_file_write_error_does_not_mask_an_exception(self):
        original = RuntimeError("original error")

        def bump(args, resolvers):
            bv.EXTRA_FILES.failures.append("extras rea: bad")
            raise original

        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures), patch.object(bv, "bump", side_effect=bump):
            with self.assertRaises(RuntimeError) as caught:
                self.run_main(["--failures", failures])
        self.assertIs(caught.exception, original)

    def test_failures_file_write_error_without_failures_keeps_success(self):
        failures = os.path.join(self.dir, "failures.txt")
        with self.failing_report_write(failures):
            rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures])
        self.assertEqual(rc, 0, err)
        with open(failures) as f:
            self.assertEqual(f.read(), "")
        self.assertIn("bump_versions: cannot write --failures %s: " % failures, err)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))

    def test_broken_stdout_still_writes_the_failures_file(self):
        class BrokenPipe(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(32, "Broken pipe")

        def check(lock, **kwargs):
            if "node_modules/kandev" not in lock["packages"]:
                raise bv.LookupFailed("bad")

        failures = os.path.join(self.dir, "failures.txt")
        # bump prints progress to stdout too, so only the report runs against the broken stream.
        real_bump = bv.bump

        def bump(args, resolvers):
            rc = real_bump(args, resolvers)
            sys.stdout = BrokenPipe()
            return rc

        stdout = sys.stdout
        try:
            with patch.object(bv, "bump", side_effect=bump):
                rc, out, err = self.run_main(["--only", "r_extras", "--failures", failures], check=check,
                                             github_actions="true")
        finally:
            sys.stdout = stdout
        self.assertEqual(rc, 0, err)
        self.assertNotIn("Traceback", err)
        with open(failures) as f:
            self.assertEqual(f.read().splitlines(), ["extras openchamber: bad", "extras rea: bad"])

    def test_catalog_files_are_written_before_versions_env(self):
        written = []
        real = bv.write_atomic

        def record(path, text):
            written.append(os.path.relpath(path, self.dir))
            real(path, text)

        with patch.object(bv, "write_atomic", side_effect=record):
            rc, out, err = self.run_main(["--only", "r_extras"])
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(written), 7)
        self.assertEqual(written[-1], "versions.env")

    def test_failed_write_leaves_no_temp_file(self):
        target = os.path.join(self.dir, "versions.env")
        with patch.object(bv.os, "replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
            bv.write_atomic(target, "A=2\n")
        self.assertEqual(sorted(os.listdir(self.dir)), ["rootfs", "versions.env"])
        self.assertEqual(self.read("versions.env").splitlines()[0], "A=1")

    def test_written_file_keeps_its_mode(self):
        target = os.path.join(self.dir, "versions.env")
        os.chmod(target, 0o644)
        bv.write_atomic(target, "A=2\n")
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o644)

    def test_failure_in_another_resolver_still_writes_the_extras(self):
        def boom():
            raise bv.LookupFailed("network down")

        before = self.snapshot()
        rc, out, err = self.run_main(resolvers=[bv.r_extras, boom])
        self.assertEqual(rc, 1)
        after = self.snapshot()
        self.assertNotEqual(after, before)
        self.assertIn("KANDEV_VERSION=1.1.0\n", self.read("versions.env"))
        # Files computed by one run are not written again by the next one.
        rc, out, err = self.run_main(resolvers=[lambda: {}])
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.snapshot(), after)


class OpenCodeResolverTests(unittest.TestCase):
    INTEGRITY = {"linux-x64-baseline": "sha512-" + "A" * 86 + "==", "linux-arm64": "sha512-" + "B" * 86 + "=="}

    def fetch(self, url):
        if url == "https://registry.npmjs.org/@opencode/cli":
            return {"dist-tags": {"latest": "2.5.0"}, "versions": {"2.5.0": {}}, "time": {"2.5.0": OLD}}
        for target, integrity in self.INTEGRITY.items():
            if url == "https://registry.npmjs.org/@opencode/cli-%s/2.5.0" % target:
                return {"dist": {"integrity": integrity, "signatures": [{"keyid": "k", "sig": "s"}]}}
        raise AssertionError(url)

    def test_each_platform_package_needs_a_registry_signature(self):
        with patch.object(bv, "fetch_json", side_effect=self.fetch), \
                patch.object(bv, "load_registry_keys", return_value={"k": {}}), \
                patch.object(bv, "verify_registry_signature") as verify:
            out = bv.r_opencode()
        self.assertEqual(out["OPENCODE_INTEGRITY_AMD64"], self.INTEGRITY["linux-x64-baseline"])
        self.assertEqual(out["OPENCODE_INTEGRITY_ARM64"], self.INTEGRITY["linux-arm64"])
        self.assertEqual([c.args[:4] for c in verify.call_args_list],
                         [("@opencode/cli-linux-x64-baseline", "2.5.0", self.INTEGRITY["linux-x64-baseline"],
                           [{"keyid": "k", "sig": "s"}]),
                          ("@opencode/cli-linux-arm64", "2.5.0", self.INTEGRITY["linux-arm64"],
                           [{"keyid": "k", "sig": "s"}])])

    def test_a_signature_that_does_not_verify_keeps_the_pins(self):
        with patch.object(bv, "fetch_json", side_effect=self.fetch), \
                patch.object(bv, "load_registry_keys", return_value={}):
            with self.assertRaisesRegex(bv.LookupFailed, "unknown keyid"):
                bv.r_opencode()


class ReleaseAgeTests(unittest.TestCase):
    """The MIN_RELEASE_AGE_HOURS rule, with the run time fixed by patching utcnow."""
    NOW = datetime.datetime(2026, 11, 26, 12, 0, tzinfo=datetime.timezone.utc)

    def setUp(self):
        patcher = patch.object(bv, "utcnow", return_value=self.NOW)
        patcher.start()
        self.addCleanup(patcher.stop)
        del bv.YOUNG_RELEASES[:]
        del bv.AGE_FALLBACK[:]
        self.addCleanup(bv.YOUNG_RELEASES.clear)
        self.addCleanup(bv.AGE_FALLBACK.clear)

    def ago(self, hours):
        return (self.NOW - datetime.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def rel(self, tag, hours, **extra):
        return dict({"tag_name": tag, "published_at": self.ago(hours), "draft": False, "prerelease": False}, **extra)

    def test_the_minimum_is_72_hours(self):
        self.assertEqual(bv.MIN_RELEASE_AGE_HOURS, 72)

    def test_an_old_enough_latest_release_is_taken_without_the_list(self):
        latest = self.rel("v2.0.0", 73)
        with patch.object(bv, "gh_latest", return_value=latest), \
                patch.object(bv, "fetch_json", side_effect=AssertionError("must not list")):
            self.assertIs(bv.gh_release("o/r"), latest)
        self.assertEqual(bv.YOUNG_RELEASES, [])
        self.assertEqual(bv.AGE_FALLBACK, [])

    def test_a_release_exactly_72_hours_old_is_taken(self):
        latest = self.rel("v2.0.0", 72)
        with patch.object(bv, "gh_latest", return_value=latest):
            self.assertIs(bv.gh_release("o/r"), latest)

    def test_a_too_young_latest_release_falls_back_to_the_previous_one(self):
        releases = [self.rel("v2.1.0", 5), self.rel("v2.1.0-rc1", 100, prerelease=True),
                    self.rel("v2.0.1", 80), self.rel("v2.0.0", 500), self.rel("v3.0.0", 1, draft=True)]
        with patch.object(bv, "gh_latest", return_value=releases[0]), \
                patch.object(bv, "fetch_json", return_value=releases) as listed:
            self.assertEqual(bv.gh_release("o/r")["tag_name"], "v2.0.1")
        listed.assert_called_once_with("https://api.github.com/repos/o/r/releases?per_page=30")
        self.assertEqual(bv.YOUNG_RELEASES,
                         ["newer release o/r v2.1.0 skipped, published 5 hours ago (minimum 72 hours)"])
        self.assertEqual(bv.AGE_FALLBACK, ["o/r"])

    def test_no_release_old_enough_keeps_the_pin(self):
        releases = [self.rel("v2.1.0", 5), self.rel("v2.0.0", 30)]
        err = io.StringIO()
        with patch.object(bv, "gh_latest", return_value=releases[0]), \
                patch.object(bv, "fetch_json", return_value=releases), \
                patch.object(bv, "verify_asset", side_effect=AssertionError("must not verify")), \
                contextlib.redirect_stderr(err):
            self.assertIsNone(bv.gh_release("o/r"))
            self.assertEqual(bv.r_ruff(), {})
        self.assertIn("keeping the current pin", err.getvalue())

    def test_a_missing_publish_time_fails_the_resolver(self):
        with patch.object(bv, "gh_latest", return_value={"tag_name": "v1.0.0"}):
            with self.assertRaisesRegex(bv.LookupFailed, "no valid publish time"):
                bv.gh_release("o/r")

    def test_forgejo_and_gitea_releases_fall_back_the_same_way(self):
        latest = dict(self.rel("v0.8.0", 10), published_at="2026-11-26T03:00:00+01:00")
        older = [latest, self.rel("v0.7.0", 2000)]
        calls = []

        def fetch(url):
            calls.append(url)
            return latest if url.endswith("/latest") else older

        with patch.object(bv, "fetch_json", side_effect=fetch):
            self.assertEqual(bv.forge_release(bv.FJ_RELEASES, "forgejo-cli")["tag_name"], "v0.7.0")
        self.assertEqual(calls, [bv.FJ_RELEASES,
                                 "https://codeberg.org/api/v1/repos/forgejo-contrib/forgejo-cli/releases?limit=20"])
        # 03:00 at +01:00 is 02:00 UTC, ten hours before NOW.
        self.assertIn("forgejo-cli v0.8.0 skipped, published 10 hours ago", bv.YOUNG_RELEASES[0])

    def test_node_falls_back_by_release_day(self):
        doc = [{"version": "v26.14.0", "date": "2026-11-25"}, {"version": "v26.13.1", "date": "2026-11-22"},
               {"version": "v26.13.0", "date": "2026-11-01"}]
        # 2026-11-22 ends at 2026-11-23T00:00Z, 84 hours before NOW; 2026-11-25 ends 12 hours before.
        self.assertEqual(bv.parse_node_index(doc, 26, now=self.NOW), "26.13.1")
        self.assertIsNone(bv.parse_node_index(doc[:1], 26, now=self.NOW))
        with self.assertRaises(bv.LookupFailed):
            bv.parse_node_index([{"version": "v26.14.0"}], 26, now=self.NOW)

    def test_node_with_no_release_old_enough_keeps_the_pin(self):
        doc = [{"version": "v26.14.0", "date": "2026-11-25"}]
        with patch.object(bv, "fetch_json", return_value=doc), \
                patch.object(bv, "fetch_bytes", side_effect=AssertionError("must not download")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bv.r_node(), {})
        self.assertIn("node 26.14.0 skipped, published 12 hours ago", bv.YOUNG_RELEASES[0])

    def test_opencode_falls_back_to_the_newest_version_old_enough(self):
        packument = {"dist-tags": {"latest": "2.5.0"}, "versions": {"2.5.0": {}, "2.4.9": {}, "2.4.8": {}},
                     "time": {"2.5.0": self.ago(20), "2.4.9": self.ago(100), "2.4.8": self.ago(900)}}

        def fetch(url):
            if url == "https://registry.npmjs.org/@opencode/cli":
                return packument
            return {"dist": {"integrity": "sha512-" + "A" * 86 + "==", "signatures": []}}

        with patch.object(bv, "fetch_json", side_effect=fetch), \
                patch.object(bv, "load_registry_keys", return_value={}), \
                patch.object(bv, "verify_registry_signature"):
            self.assertEqual(bv.r_opencode()["OPENCODE_VERSION"], "2.4.9")
        self.assertEqual(bv.YOUNG_RELEASES,
                         ["newer release @opencode/cli 2.5.0 skipped, published 20 hours ago (minimum 72 hours)"])

    def test_a_too_young_rust_release_keeps_the_rust_pins(self):
        texts = {"https://static.rust-lang.org/rustup/release-stable.toml": "version = '1.29.3'\n",
                 "https://static.rust-lang.org/dist/channel-rust-stable.toml":
                     'manifest-version = "2"\ndate = "2026-11-25"\n[pkg.rustc]\nversion = "1.99.0 (abc 2026-11-24)"\n'}

        def fetch(url):
            if url in texts:
                return texts[url]
            if url.endswith("rustup-init.sha256"):
                return "a" * 64 + "  rustup-init\n"
            raise AssertionError(url)

        with patch.object(bv, "fetch", side_effect=fetch):
            out = bv.r_rust()
        self.assertEqual(sorted(out), ["RUSTUP_SHA256_AMD64", "RUSTUP_SHA256_ARM64", "RUSTUP_VERSION"])
        self.assertIn("rust 1.99.0 skipped", bv.YOUNG_RELEASES[0])

    def test_a_skipped_release_is_printed_and_does_not_fail_the_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            failures = os.path.join(directory, "failures.txt")
            with open(path, "w") as f:
                f.write("GH_VERSION=2.104.0\n")

            def resolver():
                bv.too_young("cli/cli", "v2.106.0", self.NOW - datetime.timedelta(hours=27), self.NOW)
                bv.AGE_FALLBACK.append("cli/cli")
                return {"GH_VERSION": "2.105.0"}

            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = bv.main(["--file", path, "--failures", failures], resolvers=[resolver])
            self.assertEqual(rc, 0)
            self.assertIn("release age: newer release cli/cli v2.106.0 skipped, published 27 hours ago",
                          out.getvalue())
            with open(failures) as f:
                self.assertEqual(f.read(), "")
            with open(path) as f:
                self.assertEqual(f.read(), "GH_VERSION=2.105.0\n")

    def test_a_fallback_older_than_the_pin_keeps_the_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            with open(path, "w") as f:
                f.write("GH_VERSION=2.106.0\n")

            def resolver():
                bv.AGE_FALLBACK.append("cli/cli")
                return {"GH_VERSION": "2.105.0"}

            err = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                self.assertEqual(bv.main(["--file", path], resolvers=[resolver]), 0)
            self.assertIn("keeping it", err.getvalue())
            with open(path) as f:
                self.assertEqual(f.read(), "GH_VERSION=2.106.0\n")

    def test_without_a_fallback_an_older_result_is_still_a_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "versions.env")
            with open(path, "w") as f:
                f.write("GH_VERSION=2.106.0\n")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(bv.main(["--file", path], resolvers=[lambda: {"GH_VERSION": "2.105.0"}]), 1)

    def test_containerssh_agent_and_buildkit_skip_young_releases(self):
        names = ["agent_0.11.%d_linux_amd64.tar.gz", "agent_0.11.%d_linux_arm64.tar.gz"]
        releases = []
        for patch_level, hours in ((3, 2), (2, 200)):
            assets = [{"name": n % patch_level, "digest": "sha256:" + l * 64} for n, l in zip(names, "ab")]
            assets.append({"name": "agent_0.11.%d_checksums.txt" % patch_level,
                           "browser_download_url": "https://example.com/%d" % patch_level})
            releases.append(self.rel("v0.11.%d" % patch_level, hours, assets=assets))
        text = "".join("%s  %s\n" % (l * 64, n % 2) for n, l in zip(names, "ab"))
        with patch.object(bv, "fetch_json", return_value=releases), \
                patch.object(bv, "fetch", return_value=text), \
                patch.object(bv, "verify_asset", return_value=False), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(bv.r_containerssh_agent()["CONTAINERSSH_AGENT_VERSION"], "0.11.2")
        self.assertIn("containerssh/agent v0.11.3 skipped", bv.YOUNG_RELEASES[0])
        del bv.YOUNG_RELEASES[:]
        buildkit = [self.rel("v0.30.0", 3), self.rel("v0.29.1", 300)]
        with patch.object(bv, "fetch_json", side_effect=[buildkit, {"digest": "sha256:" + "c" * 64}]):
            self.assertEqual(bv.r_buildkit(), {"BUILDKIT_IMAGE": "docker.io/moby/buildkit:v0.29.1@sha256:" + "c" * 64})
        self.assertIn("moby/buildkit v0.30.0 skipped", bv.YOUNG_RELEASES[0])



KELOS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
FORK_COMMIT = "c" * 40
TAG_OBJECT = "d" * 40
GOLANG_DIGEST = "sha256:" + "e" * 64
INDEX_DIGEST = "sha256:" + "f" * 64
KELOS_CONTAINERFILE_TEXT = (
    "# pins\n"
    "ARG AGENTAINER_IMAGE=ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261024.1@sha256:" + "1" * 64 + "\n"
    "ARG GOLANG_IMAGE=docker.io/library/golang:1.25.14@sha256:" + "2" * 64 + "\n"
    "ARG KELOS_FORK_COMMIT=" + "3" * 40 + "\n"
    "ARG KELOS_CAPTURE_VERSION=v0.62.0-proxy.3\n"
    "FROM --platform=$BUILDPLATFORM ${GOLANG_IMAGE} AS kelos-capture\n"
    "ARG KELOS_FORK_COMMIT\n")


def ref(tag, sha, kind="commit"):
    return {"ref": "refs/tags/" + tag, "object": {"sha": sha, "type": kind}}


class KelosParserTests(unittest.TestCase):
    def test_highest_rest_tag_by_version_then_n(self):
        refs = [ref("v0.65.0", "a" * 40), ref("v0.64.0-rest.9", "b" * 40), ref("v0.65.0-rest.1", "c" * 40),
                ref("v0.65.0-rest.2", "d" * 40, "tag"), ref("v0.65.0-rest.10", "e" * 40),
                ref("v0.65.0-rest.01", "f" * 40), ref("v0.65.0-proxy.3", "0" * 40), ref("v0.9.0-rest.1", "1" * 40)]
        self.assertEqual(bv.kelos_rest_tags(refs), [
            ("v0.65.0-rest.10", "e" * 40, "commit"), ("v0.65.0-rest.2", "d" * 40, "tag"),
            ("v0.65.0-rest.1", "c" * 40, "commit"), ("v0.64.0-rest.9", "b" * 40, "commit"),
            ("v0.9.0-rest.1", "1" * 40, "commit")])

    def test_version_beats_a_higher_n(self):
        refs = [ref("v0.65.0-rest.7", "a" * 40), ref("v0.66.0-rest.1", "b" * 40, "tag")]
        self.assertEqual(bv.kelos_rest_tags(refs)[0], ("v0.66.0-rest.1", "b" * 40, "tag"))

    def test_no_rest_tag_is_a_failure(self):
        with self.assertRaises(bv.LookupFailed):
            bv.kelos_rest_tags([ref("v0.65.0", "a" * 40), {"ref": "refs/heads/v0.65.0-rest.1"}])

    def test_annotated_tags_are_peeled_to_the_commit(self):
        responses = {"https://api.github.com/repos/o/r/git/tags/" + "1" * 40: {"object": {"sha": "2" * 40, "type": "tag"}},
                     "https://api.github.com/repos/o/r/git/tags/" + "2" * 40: {"object": {"sha": FORK_COMMIT, "type": "commit"}}}
        with patch.object(bv, "fetch_json", side_effect=lambda url: responses[url]):
            self.assertEqual(bv.peel_tag("o/r", "1" * 40, "tag"), FORK_COMMIT)

    def test_lightweight_tag_needs_no_request(self):
        with patch.object(bv, "fetch_json", side_effect=AssertionError("must not fetch")):
            self.assertEqual(bv.peel_tag("o/r", FORK_COMMIT, "commit"), FORK_COMMIT)

    def test_tag_of_a_tree_or_bad_sha_is_refused(self):
        with patch.object(bv, "fetch_json", return_value={"object": {"sha": "9" * 40, "type": "tree"}}):
            with self.assertRaises(bv.LookupFailed):
                bv.peel_tag("o/r", "1" * 40, "tag")
        with self.assertRaises(bv.LookupFailed):
            bv.peel_tag("o/r", "not-a-sha", "commit")

    def test_endless_tag_chain_is_refused(self):
        with patch.object(bv, "fetch_json", return_value={"object": {"sha": "1" * 40, "type": "tag"}}):
            with self.assertRaises(bv.LookupFailed):
                bv.peel_tag("o/r", "1" * 40, "tag")

    def test_go_mod_requirement(self):
        self.assertEqual(bv.parse_go_mod_go("module x\n\ngo 1.27.4\n"), (1, 27, 4))
        self.assertEqual(bv.parse_go_mod_go("module x\ngo 1.25\n"), (1, 25))
        self.assertEqual(bv.parse_go_mod_go("module x\ngo 1.25.0\ntoolchain go1.26.2\n"), (1, 26, 2))
        with self.assertRaises(bv.LookupFailed):
            bv.parse_go_mod_go("module x\n")

    def test_git_blob_sha_matches_git(self):
        # git hash-object of the bytes "hello\n".
        self.assertEqual(bv.git_blob_sha(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")

    def test_containerfile_args_are_read_and_rewritten_in_place(self):
        args = bv.read_containerfile_args(KELOS_CONTAINERFILE_TEXT, bv.KELOS_ARGS)
        self.assertEqual(args["KELOS_CAPTURE_VERSION"], "v0.62.0-proxy.3")
        out = bv.rewrite_containerfile_args(KELOS_CONTAINERFILE_TEXT, {"KELOS_CAPTURE_VERSION": "v0.65.0-rest.1"})
        self.assertEqual(out, KELOS_CONTAINERFILE_TEXT.replace("v0.62.0-proxy.3", "v0.65.0-rest.1"))
        # The ARG line without a value inside the stage stays as it is.
        out = bv.rewrite_containerfile_args(KELOS_CONTAINERFILE_TEXT, {"KELOS_FORK_COMMIT": FORK_COMMIT})
        self.assertIn("ARG KELOS_FORK_COMMIT=" + FORK_COMMIT + "\n", out)
        self.assertTrue(out.endswith("ARG KELOS_FORK_COMMIT\n"))

    def test_missing_or_repeated_arg_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            bv.read_containerfile_args("ARG X=1\n", ["KELOS_FORK_COMMIT"])
        with self.assertRaises(bv.LookupFailed):
            bv.rewrite_containerfile_args("ARG A=1\nARG A=2\n", {"A": "3"})

    def test_image_downgrades_are_refused(self):
        old = bv.read_containerfile_args(KELOS_CONTAINERFILE_TEXT, bv.KELOS_ARGS)
        bv.kelos_images_not_older(old, dict(old))
        for key, value in (("AGENTAINER_IMAGE", "ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261019.1@" + INDEX_DIGEST),
                           ("GOLANG_IMAGE", "docker.io/library/golang:1.25.9@" + GOLANG_DIGEST)):
            with self.subTest(key=key), self.assertRaises(bv.LookupFailed):
                bv.kelos_images_not_older(old, dict(old, **{key: value}))

    def test_capture_tag_order(self):
        self.assertFalse(bv.kelos_capture_older("v0.62.0-proxy.3", "v0.62.0-rest.1"))
        self.assertTrue(bv.kelos_capture_older("v0.62.0-proxy.3", "v0.61.0-rest.4"))
        self.assertTrue(bv.kelos_capture_older("v0.65.0-rest.2", "v0.65.0-rest.1"))
        self.assertFalse(bv.kelos_capture_older("v0.65.0-rest.2", "v0.65.0-rest.3"))

    def test_the_kelos_pins_in_the_repo_pass_validation(self):
        with open(os.path.join(KELOS_ROOT, "Containerfile.kelos")) as f:
            args = bv.read_containerfile_args(f.read(), bv.KELOS_ARGS)
        for key, value in args.items():
            with self.subTest(key=key):
                self.assertIsNone(bv.invalid(key, value))
        self.assertIsNotNone(bv.kelos_rest_key(args["KELOS_CAPTURE_VERSION"]))

    def test_source_md_names_the_release_the_copies_come_from(self):
        with open(os.path.join(KELOS_ROOT, "rootfs-kelos", "SOURCE.md")) as f:
            self.assertIn("tag %s," % bv.KELOS_COPIED_FROM, f.read())


class FakeResponse(io.BytesIO):
    def __init__(self, body, headers):
        super().__init__(body)
        self.headers = headers

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class GhcrDigestTests(unittest.TestCase):
    def digest(self, body, headers):
        requests = []

        def opener(req):
            requests.append(req)
            return FakeResponse(body, headers)
        with patch.object(bv, "fetch_json", return_value={"token": "anon"}) as fj, \
                patch.object(bv, "open_https", side_effect=opener):
            result = bv.ghcr_index_digest("chadmayfield/agentainer", "0.1.0-dev.20261104.1")
        fj.assert_called_once_with("https://ghcr.io/token?scope=repository:chadmayfield/agentainer:pull")
        self.assertEqual(requests[0].full_url,
                         "https://ghcr.io/v2/chadmayfield/agentainer/manifests/0.1.0-dev.20261104.1")
        self.assertEqual(requests[0].get_header("Authorization"), "Bearer anon")
        return result

    def test_digest_is_the_sha256_of_the_index(self):
        body = b'{"schemaVersion":2}'
        want = "sha256:" + hashlib.sha256(body).hexdigest()
        self.assertEqual(self.digest(body, {"Content-Type": "application/vnd.oci.image.index.v1+json",
                                            "Docker-Content-Digest": want}), want)

    def test_header_that_disagrees_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            self.digest(b"{}", {"Content-Type": "application/vnd.oci.image.index.v1+json",
                                "Docker-Content-Digest": INDEX_DIGEST})

    def test_single_platform_manifest_is_refused(self):
        with self.assertRaises(bv.LookupFailed):
            self.digest(b"{}", {"Content-Type": "application/vnd.oci.image.manifest.v1+json"})


class KelosResolverTests(unittest.TestCase):
    """r_kelos against a scratch tree and mocked GitHub, Go, Docker Hub and ghcr.io responses."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="cx-kelos-")
        self.addCleanup(shutil.rmtree, self.dir)
        with open(os.path.join(self.dir, "versions.env"), "w") as f:
            f.write("GO_VERSION=1.27.4\n")
        with open(os.path.join(self.dir, "Containerfile.kelos"), "w") as f:
            f.write(KELOS_CONTAINERFILE_TEXT)
        os.makedirs(os.path.join(self.dir, "rootfs-kelos"))
        self.copies = {}
        for local, upstream in bv.KELOS_COPIES:
            data = ("copy of %s\n" % upstream).encode()
            with open(os.path.join(self.dir, local), "wb") as f:
                f.write(data)
            self.copies[upstream] = bv.git_blob_sha(data)
        self.go_mod = "module github.com/kelos-dev/kelos\n\ngo 1.27.4\n"
        self.now = datetime.datetime(2026, 12, 10, tzinfo=datetime.timezone.utc)
        # Publish times: upstream releases and fork commits, days before now.
        self.upstream_age = {"v0.65.0": 30, "v0.64.0": 60}
        self.commit_age = {FORK_COMMIT: 10, "2" * 40: 20}
        self.codex_at_tag = "a" * 40
        self.codex_upstream = "a" * 40
        self.go = "1.27.4"

    def fetch(self, url):
        gh = "https://api.github.com/repos/"
        if url == gh + "chadmayfield/kelos/git/matching-refs/tags/v":
            return [ref("v0.62.0", "1" * 40), ref("v0.65.0-rest.1", TAG_OBJECT, "tag"), ref("v0.64.0-rest.3", "2" * 40)]
        if url == gh + "chadmayfield/kelos/git/tags/" + TAG_OBJECT:
            return {"object": {"sha": FORK_COMMIT, "type": "commit"}}
        for version, days in self.upstream_age.items():
            if url == gh + "kelos-dev/kelos/releases/tags/" + version:
                return {"published_at": (self.now - datetime.timedelta(days=days)).isoformat()}
        for commit, days in self.commit_age.items():
            if url == gh + "chadmayfield/kelos/commits/" + commit:
                return {"commit": {"committer": {"date": (self.now - datetime.timedelta(days=days)).isoformat()}}}
        for commit in self.commit_age:
            for upstream, sha in self.copies.items():
                if url == gh + "chadmayfield/kelos/contents/%s?ref=%s" % (upstream, commit):
                    return {"sha": sha}
            if url == gh + "chadmayfield/kelos/contents/codex/kelos_entrypoint.sh?ref=" + commit:
                return {"sha": self.codex_at_tag}
        if url == gh + "kelos-dev/kelos/contents/codex/kelos_entrypoint.sh?ref=v0.62.0":
            return {"sha": self.codex_upstream}
        if url.startswith(gh + "chadmayfield/kelos/contents/go.mod?ref="):
            return {"content": base64.b64encode(self.go_mod.encode()).decode()}
        if url == "https://go.dev/dl/?mode=json":
            return [{"version": "go" + self.go, "stable": True,
                     "files": [{"os": "linux", "arch": a, "kind": "archive", "sha256": "0" * 64}
                               for a in ("amd64", "arm64")]}]
        if url == "https://hub.docker.com/v2/repositories/library/golang/tags/" + self.go:
            return {"digest": GOLANG_DIGEST}
        if url == gh + "chadmayfield/agentainer/releases?per_page=100":
            return [{"tag_name": "v0.1.0-dev.20261104.1", "prerelease": True},
                    {"tag_name": "v0.1.0-dev.20261024.1", "prerelease": True}]
        raise AssertionError("unexpected fetch " + url)

    def run_main(self):
        out, err = io.StringIO(), io.StringIO()
        with patch.object(bv, "fetch_json", side_effect=self.fetch), \
                patch.object(bv, "utcnow", return_value=self.now), \
                patch.object(bv, "ghcr_index_digest", return_value=INDEX_DIGEST) as digest, \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bv.main(["--file", os.path.join(self.dir, "versions.env"), "--only", "r_kelos"])
        if rc == 0:
            digest.assert_called_once_with("chadmayfield/agentainer", "0.1.0-dev.20261104.1")
        return rc, out.getvalue(), err.getvalue()

    def read(self, rel):
        with open(os.path.join(self.dir, rel)) as f:
            return f.read()

    def test_pins_are_written_to_the_containerfile_only(self):
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        args = bv.read_containerfile_args(self.read("Containerfile.kelos"), bv.KELOS_ARGS)
        self.assertEqual(args, {
            "AGENTAINER_IMAGE": "ghcr.io/chadmayfield/agentainer:0.1.0-dev.20261104.1@" + INDEX_DIGEST,
            "GOLANG_IMAGE": "docker.io/library/golang:1.27.4@" + GOLANG_DIGEST,
            "KELOS_FORK_COMMIT": FORK_COMMIT,
            "KELOS_CAPTURE_VERSION": "v0.65.0-rest.1"})
        self.assertEqual(self.read("versions.env"), "GO_VERSION=1.27.4\n")
        self.assertIn("Containerfile.kelos KELOS_CAPTURE_VERSION: v0.62.0-proxy.3 -> v0.65.0-rest.1", out)
        self.assertIn("Containerfile.kelos AGENTAINER_IMAGE:", out)
        # A second run finds nothing to change.
        before = self.read("Containerfile.kelos")
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.read("Containerfile.kelos"), before)
        self.assertNotIn("Containerfile.kelos", out)

    def fork_args(self):
        args = bv.read_containerfile_args(self.read("Containerfile.kelos"), bv.KELOS_ARGS)
        return args["KELOS_FORK_COMMIT"], args["KELOS_CAPTURE_VERSION"]

    def test_a_young_fork_commit_falls_back_to_the_next_tag(self):
        self.commit_age[FORK_COMMIT] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fork_args(), ("2" * 40, "v0.64.0-rest.3"))
        self.assertIn("release age: newer release chadmayfield/kelos v0.65.0-rest.1 skipped, published 24 hours ago", out)

    def test_a_young_upstream_release_falls_back_to_the_next_tag(self):
        self.upstream_age["v0.65.0"] = 2
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fork_args(), ("2" * 40, "v0.64.0-rest.3"))
        self.assertIn("release age: newer release chadmayfield/kelos v0.65.0-rest.1 skipped", out)

    def test_a_fallback_below_the_pin_keeps_the_pin(self):
        with open(os.path.join(self.dir, "Containerfile.kelos"), "w") as f:
            f.write(KELOS_CONTAINERFILE_TEXT.replace("v0.62.0-proxy.3", "v0.64.0-rest.5"))
        self.commit_age[FORK_COMMIT] = 1
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fork_args(), ("3" * 40, "v0.64.0-rest.5"))
        self.assertIn("sorts below the v0.64.0-rest.5 pin; keeping it", err)
        # The image pins still move.
        self.assertIn("Containerfile.kelos AGENTAINER_IMAGE:", out)

    def test_no_tag_old_enough_keeps_the_fork_pins(self):
        self.commit_age = {FORK_COMMIT: 1, "2" * 40: 2}
        rc, out, err = self.run_main()
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.fork_args(), ("3" * 40, "v0.62.0-proxy.3"))
        self.assertIn("keeping the current pin", err)

    def test_a_failed_r_kelos_does_not_hold_back_other_pins(self):
        self.codex_at_tag = "b" * 40

        def other():
            return {"GO_VERSION": "1.27.5"}
        out, err = io.StringIO(), io.StringIO()
        with patch.object(bv, "fetch_json", side_effect=self.fetch), \
                patch.object(bv, "utcnow", return_value=self.now), \
                patch.object(bv, "ghcr_index_digest", return_value=INDEX_DIGEST), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = bv.main(["--file", os.path.join(self.dir, "versions.env")], resolvers=[bv.r_kelos, other])
        self.assertEqual(rc, 1, err.getvalue())
        self.assertIn("r_kelos:", err.getvalue())
        self.assertEqual(self.read("versions.env"), "GO_VERSION=1.27.5\n")
        self.assertEqual(self.read("Containerfile.kelos"), KELOS_CONTAINERFILE_TEXT)

    def assert_refused(self, needle):
        before = self.read("Containerfile.kelos")
        rc, out, err = self.run_main()
        self.assertEqual(rc, 1, out + err)
        self.assertIn(needle, err)
        self.assertEqual(self.read("Containerfile.kelos"), before)

    def test_a_changed_copied_file_stops_the_update(self):
        self.copies["claude-code/kelos_entrypoint.sh"] = "9" * 40
        self.assert_refused("claude-code/kelos_entrypoint.sh differs from rootfs-kelos/kelos_entrypoint_claude.sh")

    def test_a_changed_codex_entrypoint_stops_the_update(self):
        self.codex_at_tag = "b" * 40
        self.assert_refused("codex/kelos_entrypoint.sh changed since v0.62.0")

    def test_go_older_than_go_mod_stops_the_update(self):
        self.go_mod = "module x\n\ngo 1.28.0\n"
        self.assert_refused("needs Go 1.28.0")

    def test_a_downgrade_stops_the_update(self):
        with open(os.path.join(self.dir, "Containerfile.kelos"), "w") as f:
            f.write(KELOS_CONTAINERFILE_TEXT.replace("v0.62.0-proxy.3", "v0.65.0-rest.4"))
        self.assert_refused("downgrade KELOS_CAPTURE_VERSION")

    def test_a_malformed_digest_is_refused(self):
        real = self.fetch

        def fetch(url):
            if "hub.docker.com" in url:
                return {"digest": "sha256:short"}
            return real(url)
        self.fetch = fetch
        self.assert_refused("malformed digest")


if __name__ == "__main__":
    unittest.main()
