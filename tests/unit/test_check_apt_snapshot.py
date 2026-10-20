import importlib.util
import os
import unittest

HERE = os.path.dirname(__file__)
spec = importlib.util.spec_from_file_location(
    "check_apt_snapshot", os.path.join(HERE, "..", "..", "build", "check-apt-snapshot.py"))
cas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cas)

SNAP = "https://snapshot.ubuntu.com/ubuntu/20261008T000000Z"


class UnpinnedTests(unittest.TestCase):
    def test_phased_version_from_snapshot_is_pinned(self):
        policy = (
            "openssh-client:\n"
            "  Installed: 1:10.2p1-2ubuntu3.7\n"
            "  Candidate: 1:10.2p1-2ubuntu3.7\n"
            "  Version table:\n"
            " *** 1:10.2p1-2ubuntu3.7 500 (phased 15%)\n"
            "        500 " + SNAP + " resolute-updates/main arm64 Packages\n"
            "        100 /var/lib/dpkg/status\n"
            "     1:10.2p1-2ubuntu3.6 500\n"
            "        500 " + SNAP + " resolute-security/main arm64 Packages\n")
        self.assertEqual(cas.unpinned(policy), [])

    def test_version_only_in_dpkg_status_is_unpinned(self):
        policy = (
            "libfoo:\n"
            "  Installed: 2.0\n"
            "  Candidate: 1.0\n"
            "  Version table:\n"
            " *** 2.0 100\n"
            "        100 /var/lib/dpkg/status\n"
            "     1.0 500\n"
            "        500 " + SNAP + " resolute/main arm64 Packages\n")
        self.assertEqual(cas.unpinned(policy), ["libfoo 2.0"])

    def test_negative_pin_priority_is_parsed(self):
        policy = (
            "libbaz:\n"
            "  Installed: 1.0\n"
            "  Candidate: 1.0\n"
            "  Version table:\n"
            " *** 1.0 -1\n"
            "       -1 " + SNAP + " resolute/main arm64 Packages\n"
            "        100 /var/lib/dpkg/status\n")
        self.assertEqual(cas.unpinned(policy), [])

    def test_live_archive_version_is_unpinned(self):
        policy = (
            "libbar:\n"
            "  Installed: 3.1\n"
            "  Candidate: 3.1\n"
            "  Version table:\n"
            " *** 3.1 500\n"
            "        500 http://archive.ubuntu.com/ubuntu resolute-updates/main arm64 Packages\n"
            "        100 /var/lib/dpkg/status\n")
        self.assertEqual(cas.unpinned(policy), ["libbar 3.1"])


if __name__ == "__main__":
    unittest.main()
