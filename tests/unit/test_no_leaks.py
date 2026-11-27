"""Scan every tracked text file for personal or infrastructure data (AGENTS.md, "Public and generic").

The checks look for email addresses, private and shared IPv4 addresses, IPv6 unique local
and link-local addresses, home directory paths and private network host names. Each
exception below is explicit and says why it is allowed. Binary files are skipped.
"""
import ipaddress
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = "tests/unit/test_no_leaks.py"

# RFC 2606 and RFC 6761 reserve these names for examples, tests and documentation.
EXAMPLE_DOMAINS = re.compile(r"(?:^|\.)(?:example\.(?:com|net|org)|example|test|invalid|localhost)$")
ALLOWED_EMAIL_DOMAINS = {
    # GitHub's noreply addresses carry no personal address (GitHub docs, "Setting your commit email address").
    "users.noreply.github.com",
    # SSH algorithm names such as sk-ssh-ed25519@openssh.com use the name@domain form (RFC 4251, section 6).
    "openssh.com",
}
ALLOWED_EMAILS = {
    # The Co-Authored-By address Claude Code documents for its commits (AGENTS.md, "Git").
    "noreply@anthropic.com",
    # The user ID of the AWS CLI release signing key, as the AWS CLI install guide prints it (docs/versions.md).
    "aws-cli@amazon.com",
}

# Files that list private ranges on purpose, with the exact values each may contain.
EGRESS_RANGES = {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16",
                 "fc00::/7", "fe80::/10"}
ALLOWED_ADDRESSES = {
    # The egress policy excludes these ranges from its port 443 rule.
    "deploy/kubernetes/agentainer/networkpolicy.yaml": EGRESS_RANGES,
    # The Kubernetes guide documents that policy, and names the cloud metadata address it blocks.
    "docs/kubernetes.md": EGRESS_RANGES | {"169.254.169.254"},
    # The manifest test checks that the rendered policy has exactly these exclusions.
    "tests/host/test-manifests.sh": EGRESS_RANGES,
}
# Home directories of the users the images create: agent (Containerfile), filebrowser (the
# FileBrowser sidecar's config) and kelos (Containerfile.kelos).
ALLOWED_HOMES = {"agent", "filebrowser", "kelos"}
# Podman's documented name for the host, as seen from a container (docs/security.md).
ALLOWED_HOSTS = {"host.containers.internal"}

EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9._%+-]+)@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})(?![A-Za-z0-9-])")
IPV4 = re.compile(r"(?<![0-9.])((?:[0-9]{1,3}\.){3}[0-9]{1,3})(/[0-9]{1,2})?(?![0-9]|\.[0-9])")
IPV6 = re.compile(r"(?i)(?<![0-9a-z:])((?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f]):[0-9a-f:]*)(/[0-9]{1,3})?")
HOME = re.compile(r"(?<![A-Za-z0-9._~/-])(?:/Users/|/home/|[A-Za-z]:\\Users\\)([A-Za-z0-9._-]+)")
HOST = re.compile(r"(?i)(?<![A-Za-z0-9.-])((?:[a-z0-9-]+\.)+(?:lan|internal|intranet|corp|localdomain|home\.arpa|ts\.net))"
                  r"(?![A-Za-z0-9-])")
PRIVATE_V4 = [ipaddress.ip_network(n) for n in
              ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "169.254.0.0/16")]
PRIVATE_V6 = [ipaddress.ip_network(n) for n in ("fc00::/7", "fe80::/10")]


def email_problems(line):
    for m in EMAIL.finditer(line):
        local, domain = m.group(1), m.group(2).lower()
        # user@host in a URL is credentials or a user name, not an email address.
        start = line.rfind(" ", 0, m.start()) + 1
        if "://" in line[start:m.start()]:
            continue
        address = "%s@%s" % (local, domain)
        if EXAMPLE_DOMAINS.search(domain) or domain in ALLOWED_EMAIL_DOMAINS or address in ALLOWED_EMAILS:
            continue
        if any(domain.endswith("." + d) for d in ALLOWED_EMAIL_DOMAINS):
            continue
        yield "email address " + address


def address_problems(line, allowed):
    for m in IPV4.finditer(line):
        try:
            addr = ipaddress.ip_address(m.group(1))
        except ValueError:
            continue
        value = m.group(1) + (m.group(2) or "")
        if any(addr in net for net in PRIVATE_V4) and value not in allowed:
            yield "private IPv4 address " + value
    for m in IPV6.finditer(line):
        text = m.group(1).rstrip(":") if not m.group(1).endswith("::") else m.group(1)
        try:
            addr = ipaddress.ip_address(text)
        except ValueError:
            continue
        value = m.group(1) + (m.group(2) or "")
        if any(addr in net for net in PRIVATE_V6) and value not in allowed:
            yield "private IPv6 address " + value


def home_problems(line):
    for m in HOME.finditer(line):
        if m.group(1) not in ALLOWED_HOMES:
            yield "home directory " + m.group(0)


def host_problems(line):
    for m in HOST.finditer(line):
        if m.group(1).lower() not in ALLOWED_HOSTS:
            yield "private host name " + m.group(1)


def problems(rel, text):
    allowed = ALLOWED_ADDRESSES.get(rel, set())
    for n, line in enumerate(text.splitlines(), 1):
        for checks in (email_problems(line), address_problems(line, allowed), home_problems(line),
                       host_problems(line)):
            for problem in checks:
                yield "%s:%d: %s" % (rel, n, problem)


def tracked_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=False)
    if out.returncode != 0:
        return None
    return [p for p in out.stdout.decode().split("\0") if p]


class NoLeakTests(unittest.TestCase):
    def test_tracked_files_hold_no_personal_or_infrastructure_data(self):
        files = tracked_files()
        if files is None:
            self.skipTest("not a git checkout")
        found = []
        scanned = 0
        for rel in files:
            if rel == THIS_FILE:
                continue
            path = ROOT / rel
            if path.is_symlink() or not path.is_file():
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1
            found.extend(problems(rel, text))
        # A marker that the scan reached the repository's files.
        self.assertGreater(scanned, 100)
        self.assertEqual(found, [], "remove these or add an explained exception in %s" % THIS_FILE)

    def test_allowed_addresses_are_still_in_their_files(self):
        # An exception for a file that no longer lists the value would hide a later leak there.
        for rel, values in ALLOWED_ADDRESSES.items():
            text = (ROOT / rel).read_text()
            for value in values:
                with self.subTest(rel=rel, value=value):
                    self.assertIn(value, text)

    def test_each_check_finds_its_target(self):
        cases = {
            "mail me at someone@gmail.com": "email address someone@gmail.com",
            "Author: A <a.person@corp-mail.co.uk>": "email address a.person@corp-mail.co.uk",
            "server: 192.168.1.20": "private IPv4 address 192.168.1.20",
            "endpoint 10.2.3.4:443": "private IPv4 address 10.2.3.4",
            "# tailnet 100.101.12.7": "private IPv4 address 100.101.12.7",
            "metadata 169.254.169.254": "private IPv4 address 169.254.169.254",
            "subnet 172.20.0.0/16": "private IPv4 address 172.20.0.0/16",
            "addr fd12:3456:789a::1": "private IPv6 address fd12:3456:789a::1",
            "via fe80::1": "private IPv6 address fe80::1",
            "cd /Users/someone/code": "home directory /Users/someone",
            "path /home/someone/.ssh": "home directory /home/someone",
            "registry: registry.home.lan": "private host name registry.home.lan",
            "ssh build.corp": "private host name build.corp",
            "box.tail1234.ts.net": "private host name box.tail1234.ts.net",
        }
        for line, problem in cases.items():
            with self.subTest(line=line):
                self.assertEqual(list(problems("x.md", line)), ["x.md:1: " + problem])

    def test_allowed_forms_pass(self):
        for line in ("you@example.com", "t@test.example", "1+bot[bot]@users.noreply.github.com",
                     "Co-Authored-By: Claude <noreply@anthropic.com>", "sk-ssh-ed25519@openssh.com",
                     "https://user:pass@github.com/o/r.git", "ghost@1.0.0.abc123", "npm i pkg@1.2.3",
                     "203.0.113.7", "8.8.8.8", "1.27.4.1", "/home/agent/.bashrc", "/home/filebrowser",
                     "rootfs/etc/agentainer/home/.claude", "host.containers.internal", "Path.home()",
                     "self.home", "version 10.0.1"):
            with self.subTest(line=line):
                self.assertEqual(list(problems("x.md", line)), [])

    def test_exceptions_apply_only_to_their_file(self):
        self.assertEqual(list(problems("deploy/kubernetes/agentainer/networkpolicy.yaml", "- 10.0.0.0/8")), [])
        self.assertEqual(list(problems("docs/other.md", "- 10.0.0.0/8")),
                         ["docs/other.md:1: private IPv4 address 10.0.0.0/8"])
        self.assertEqual(list(problems("deploy/kubernetes/agentainer/networkpolicy.yaml", "- 10.1.2.3")),
                         ["deploy/kubernetes/agentainer/networkpolicy.yaml:1: private IPv4 address 10.1.2.3"])


if __name__ == "__main__":
    unittest.main()
