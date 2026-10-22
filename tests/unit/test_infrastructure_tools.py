"""Resolve infrastructure pins without accepting malformed release metadata."""
import importlib.util
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("cx_infra_bump", ROOT / "scripts/bump_versions.py")
bump = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump)


class InfrastructureResolverTests(unittest.TestCase):
    def test_kubectl_uses_stable_release_and_both_official_checksums(self):
        responses = {
            "https://dl.k8s.io/release/stable.txt": "v1.37.1\n",
            "https://dl.k8s.io/release/v1.37.1/bin/linux/amd64/kubectl.sha256": "a" * 64,
            "https://dl.k8s.io/release/v1.37.1/bin/linux/arm64/kubectl.sha256": "b" * 64,
        }
        with mock.patch.object(bump, "fetch", side_effect=responses.__getitem__) as fetch:
            self.assertEqual(bump.r_kubectl(), {"KUBECTL_VERSION": "1.37.1",
                             "KUBECTL_SHA256_AMD64": "a" * 64, "KUBECTL_SHA256_ARM64": "b" * 64})
        self.assertEqual({call.args[0] for call in fetch.call_args_list}, set(responses))

    def test_kubectl_refuses_bad_versions_and_checksums(self):
        for value in ("v1.37.1;id", "v1.38.0-rc.1", "<html>unavailable</html>"):
            with self.subTest(value=value), mock.patch.object(bump, "fetch", return_value=value):
                with self.assertRaises(bump.LookupFailed):
                    bump.r_kubectl()
        with mock.patch.object(bump, "fetch", side_effect=["v1.37.1", "bad checksum"]):
            with self.assertRaises(bump.LookupFailed):
                bump.r_kubectl()

    def helm(self, checksum=None, release=None):
        def fetch(url):
            arch = "arm64" if "arm64" in url else "amd64"
            value = "b" * 64 if arch == "arm64" else "a" * 64
            return checksum if checksum is not None else value + "  helm-v4.3.1-linux-" + arch + ".tar.gz\n"
        with mock.patch.object(bump, "gh_latest", return_value=release or {"tag_name": "v4.3.1"}) as latest, \
                mock.patch.object(bump, "fetch", side_effect=fetch) as fetched:
            result = bump.r_helm()
            latest.assert_called_once_with("helm/helm")
            self.assertEqual({call.args[0] for call in fetched.call_args_list}, {
                "https://get.helm.sh/helm-v4.3.1-linux-amd64.tar.gz.sha256sum",
                "https://get.helm.sh/helm-v4.3.1-linux-arm64.tar.gz.sha256sum"})
            return result

    def test_helm_uses_named_published_checksums_for_both_architectures(self):
        self.assertEqual(self.helm(), {"HELM_VERSION": "4.3.1", "HELM_SHA256_AMD64": "a" * 64,
                                      "HELM_SHA256_ARM64": "b" * 64})

    def test_helm_rejects_missing_mismatched_or_malformed_checksums(self):
        for text in ("", "a" * 64 + "  wrong-archive.tar.gz", "a" * 64,
                     "not-a-hash  helm-v4.3.1-linux-amd64.tar.gz"):
            with self.subTest(text=text), self.assertRaises(bump.LookupFailed):
                self.helm(checksum=text)

    def test_helm_rejects_prereleases_and_unsafe_tags(self):
        for release in ({"tag_name": "v4.4.0-rc.1"}, {"tag_name": "v4.3.1/../evil"},
                        {"tag_name": "v4.3.1", "prerelease": True},
                        {"tag_name": "v4.3.1", "draft": True}):
            with self.subTest(release=release), self.assertRaises(bump.LookupFailed):
                self.helm(release=release)

    def test_resolvers_are_included_in_scheduled_updates(self):
        names = {resolver.__name__ for resolver in bump.RESOLVERS}
        self.assertTrue({"r_kubectl", "r_helm"} <= names)

    def test_doctor_has_offline_client_version_probes(self):
        import importlib.machinery
        loader = importlib.machinery.SourceFileLoader("cx_infra_doctor", str(ROOT / "rootfs/usr/local/bin/agentainer-doctor"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        doctor = importlib.util.module_from_spec(spec)
        loader.exec_module(doctor)
        probes = dict(doctor.PROBES)
        self.assertEqual(probes.get("kubectl"), ["version", "--client=true", "--output=json"])
        self.assertEqual(probes.get("helm"), ["version", "--short"])


@unittest.skipUnless(shutil.which("bash") and shutil.which("sha256sum"), "installer requires bash and sha256sum")
class InfrastructureInstallerTests(unittest.TestCase):
    def install(self, tool, arch, corrupt=False):
        with tempfile.TemporaryDirectory(prefix="cx-infra-install-") as directory:
            base = Path(directory)
            bindir = base / "bin"
            bindir.mkdir()
            output = base / "installed"
            output.mkdir()
            payload = base / "payload"
            binary = b"#!/bin/sh\nprintf 'fixture\\n'\n"
            if tool == "helm":
                with tarfile.open(payload, "w:gz") as archive:
                    member = tarfile.TarInfo("linux-" + arch + "/helm")
                    member.size = len(binary)
                    archive.addfile(member, io.BytesIO(binary))
            else:
                payload.write_bytes(binary)
            digest = hashlib.sha256(payload.read_bytes()).hexdigest()
            curl = bindir / "curl"
            curl.write_text('#!/bin/sh\nout=\nwhile [ "$#" -gt 0 ]; do\n'
                            '  case "$1" in -o) out=$2; shift ;; esac\n'
                            '  url=$1\n  shift\ndone\n'
                            'printf "%s\\n" "$url" >"$CX_URL"\ncp "$CX_PAYLOAD" "$out"\n')
            curl.chmod(0o755)
            script = base / "install.sh"
            script.write_text((ROOT / "build/install-tool.sh").read_text()
                              .replace("F=/usr/local/lib/agentainer-build/fetch.sh", "F=" + str(ROOT / "build/fetch.sh"))
                              .replace("/usr/local/bin/" + tool, str(output / tool)))
            env = dict(os.environ, TARGETARCH=arch, PATH=str(bindir) + ":" + os.environ["PATH"],
                       TMPDIR=str(base), CX_PAYLOAD=str(payload), CX_URL=str(base / "url"))
            prefix = tool.upper()
            env[prefix + "_VERSION"] = "1.2.3"
            # The other architecture must never supply the selected download's pin.
            for candidate in ("AMD64", "ARM64"):
                env[prefix + "_SHA256_" + candidate] = (
                    digest if candidate == arch.upper() and not corrupt else "0" * 64)
            result = subprocess.run(["bash", str(script), tool], env=env,
                                    capture_output=True, text=True, timeout=10)
            if corrupt:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("checksum mismatch", result.stderr)
                self.assertFalse((output / tool).exists(), "unverified bytes were installed")
            else:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((output / tool).read_bytes(), binary)
                self.assertEqual((output / tool).stat().st_mode & 0o777, 0o755)
            expected = ("https://dl.k8s.io/release/v1.2.3/bin/linux/" + arch + "/kubectl"
                        if tool == "kubectl" else "https://get.helm.sh/helm-v1.2.3-linux-" + arch + ".tar.gz")
            self.assertEqual((base / "url").read_text().strip(), expected)

    def test_installs_verified_bytes_for_each_architecture(self):
        for tool in ("kubectl", "helm"):
            for arch in ("amd64", "arm64"):
                with self.subTest(tool=tool, arch=arch):
                    self.install(tool, arch)

    def test_bad_checksums_cannot_install_either_tool(self):
        for tool in ("kubectl", "helm"):
            for arch in ("amd64", "arm64"):
                with self.subTest(tool=tool, arch=arch):
                    self.install(tool, arch, corrupt=True)
