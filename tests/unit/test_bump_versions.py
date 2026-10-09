import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
import bump_versions as bv  # noqa: E402


class EnvFileTests(unittest.TestCase):
    def test_round_trip_keeps_comments_and_order(self):
        text = "# header\nA=1\n\n# note\nB=2\n"
        lines = bv.parse_env(text)
        out = bv.render_env(lines, {"B": "3", "C": "4"})
        self.assertEqual(out, "# header\nA=1\n\n# note\nB=3\nC=4\n")

    def test_values_reads_keys(self):
        self.assertEqual(bv.values(bv.parse_env("A=1\n#x\nB=two\n")), {"A": "1", "B": "two"})


class ParserTests(unittest.TestCase):
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
        release = {"tag_name": "v1.8.2", "assets": [
            {"name": "curlie_1.8.2_linux_arm64.tar.gz", "digest": None},
            {"name": "curlie_1.8.2_checksums.txt", "digest": None,
             "browser_download_url": "https://example.com/curlie_1.8.2_checksums.txt"}]}
        a, b = "a" * 64, "b" * 64
        text = "%s  curlie_1.8.2_linux_amd64.tar.gz\n%s  curlie_1.8.2_linux_arm64.tar.gz\n" % (a, b)
        got = bv.asset_sha256(release, "curlie_1.8.2_linux_arm64.tar.gz", fetch_text=lambda url: text)
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

    def test_npm_stable_channel(self):
        doc = {"dist-tags": {"stable": "2.1.287", "latest": "2.1.296"},
               "versions": {"2.1.287": {"dist": {"integrity": "sha512-abc="}}}}
        self.assertEqual(bv.parse_npm_channel(doc, "stable"), ("2.1.287", "sha512-abc="))

    def test_npm_channel_missing_raises(self):
        with self.assertRaises(bv.LookupFailed):
            bv.parse_npm_channel({"dist-tags": {"latest": "1"}, "versions": {}}, "stable")

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

    def test_failure_after_a_success_leaves_file_untouched(self):
        def ok():
            return {"A": "2"}

        def boom():
            raise bv.LookupFailed("network down")

        self.assertEqual(bv.main(["--file", self.path], resolvers=[ok, boom]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_unexpected_error_is_a_clean_failure(self):
        def broken():
            return {}["missing"]

        self.assertEqual(bv.main(["--file", self.path], resolvers=[broken]), 1)
        self.assertEqual(self.read(), "A=1\n")

    def test_unknown_only_name_is_rejected(self):
        self.assertEqual(bv.main(["--file", self.path, "--only", "r_nope"]), 2)
        self.assertEqual(self.read(), "A=1\n")

    def test_success_updates_file(self):
        self.assertEqual(bv.main(["--file", self.path], resolvers=[lambda: {"A": "2", "B": "3"}]), 0)
        self.assertEqual(self.read(), "A=2\nB=3\n")


if __name__ == "__main__":
    unittest.main()
