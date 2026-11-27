#!/usr/bin/env python3
"""Resolve the latest upstream pins and rewrite versions.env.

Every value comes from the upstream source named in its resolver. A resolver that
fails keeps every pin it owns, and the other resolvers still run and write theirs.
The extras resolver does the same for each extra and its catalog files. --failures
FILE lists every failed resolver and extra, one per line; without --failures, a
failed resolver makes the exit status 1 after the other pins are written. A refused
value or a downgrade still stops the run and leaves the file unchanged. No resolver
pins a release younger than MIN_RELEASE_AGE_HOURS; skipped releases are printed with
the pin changes and never fail the run. Uses the Python
standard library, the publisher verification CLIs documented in docs/versions.md,
npm to generate extras lockfiles, and openssl to verify npm registry signatures.
"""
import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import sys
import urllib.error
import urllib.parse
import urllib.request
from verify_upstream import VerificationFailed, verify_asset

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/usr/local/lib/agentainer"))
from release_version import version_key

ARCHES = {"AMD64": "amd64", "ARM64": "arm64"}
# Manifest paths come from DOWNLOAD_BASE_URL and MANIFEST_URL in the official installer:
# https://antigravity.google/cli/install.sh
AGY_MANIFEST = "https://antigravity-cli-auto-updater-974169037036.us-central1.run.app/manifests/linux_{arch}.json"
AGY_KEYS = ("version", "url", "sha512")
AGY_HOST = "storage.googleapis.com"
AGY_BUCKET = "antigravity-public"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX128 = re.compile(r"^[0-9a-f]{128}$")


class LookupFailed(Exception):
    pass


# ---- versions.env handling -------------------------------------------------

# Shell scripts source versions.env and the build passes its values into RUN steps as
# root, so every value written must match a strict pattern for its key. Anything else, including an unknown key, is refused.
IMAGE_REF = r"[a-z0-9.-]+(:[0-9]+)?/[a-z0-9._/-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}"
VALUE_PATTERNS = [
    (r"(BASE_IMAGE|[A-Z0-9_]+_IMAGE)", IMAGE_REF),
    (r"APT_SNAPSHOT", r"[0-9]{8}T[0-9]{6}Z"),
    (r"SOURCE_DATE_EPOCH", r"[0-9]{1,12}"),
    (r"UNSLOP_COMMIT", r"[0-9a-f]{40}"),
    (r"[A-Z0-9_]+_VERSION", r"v?[0-9]+(\.[0-9]+)*([-+][0-9A-Za-z.-]+)?"),
    (r"[A-Z0-9_]+_SHA256(_[A-Z0-9]+)?", r"[0-9a-f]{64}"),
    (r"[A-Z0-9_]+_SHA512(_[A-Z0-9]+)?", r"[0-9a-f]{128}"),
    (r"[A-Z0-9_]+_INTEGRITY(_[A-Z0-9]+)?", r"sha512-[A-Za-z0-9+/]+={0,2}"),
    (r"AGY_URL_[A-Z0-9]+", r"https://storage\.googleapis\.com/antigravity-public/[A-Za-z0-9._/-]+"),
]


def agy_url_problem(url):
    """None when url names an object in the agy bucket, otherwise the reason.

    curl merges "/../" and "/./" in a URL path (see --path-as-is in curl(1)), and a
    server may decode percent escapes before it resolves the path, so a URL that
    starts with the bucket path can still reach another bucket. Only plain,
    non-empty segments with no escapes, query or fragment are accepted.
    """
    if any(c in url for c in "%?#\\"):
        return "agy url has a percent escape, query, fragment or backslash: %s" % url
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.netloc != AGY_HOST:
        return "agy url is not https://%s: %s" % (AGY_HOST, url)
    segments = parts.path.split("/")
    if segments[:2] != ["", AGY_BUCKET] or len(segments) < 3:
        return "agy url is not in the %s bucket: %s" % (AGY_BUCKET, url)
    if any(seg in ("", ".", "..") for seg in segments[2:]):
        return "agy url has an empty, . or .. segment: %s" % url
    return None


def invalid(key, value):
    """None when value is safe to write for key, otherwise the reason."""
    for key_re, value_re in VALUE_PATTERNS:
        if re.fullmatch(key_re, key):
            if not re.fullmatch(value_re, value):
                return "%s=%r does not match %s" % (key, value, value_re)
            if key.startswith("AGY_URL_"):
                return agy_url_problem(value)
            return None
    return "%s is not a known pin" % key

def parse_env(text):
    """Return a list of (key or None, raw line)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        out.append((m.group(1) if m else None, line))
    return out


def values(lines):
    return {k: raw.split("=", 1)[1] for k, raw in lines if k}


def render_env(lines, updates):
    seen = set()
    out = []
    for key, raw in lines:
        if key and key in updates:
            out.append("%s=%s" % (key, updates[key]))
            seen.add(key)
        else:
            out.append(raw)
    for key in updates:
        if key not in seen and key not in values(lines):
            out.append("%s=%s" % (key, updates[key]))
    return "\n".join(out) + "\n"


# ---- HTTP -----------------------------------------------------------------

class HTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep downloads on HTTPS and credentials on the origin that received them.

    https://docs.python.org/3/library/urllib.request.html#urllib.request.HTTPRedirectHandler
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https":
            raise urllib.error.HTTPError(newurl, code, "redirect requires HTTPS", headers, fp)
        result = super().redirect_request(req, fp, code, msg, headers, newurl)
        origin = urllib.parse.urlsplit(req.full_url)
        if result is not None and (origin.hostname, origin.port or 443) != (target.hostname, target.port or 443):
            result.remove_header("Authorization")
        return result


def open_https(request):
    if urllib.parse.urlsplit(request.full_url).scheme != "https":
        raise LookupFailed("download requires HTTPS")
    return urllib.request.build_opener(HTTPSRedirectHandler()).open(request, timeout=60)

def fetch(url, accept=None):
    headers = {"User-Agent": "agentainer-bump"}
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith("https://api.github.com/"):
        headers["Authorization"] = "Bearer " + token
    try:
        with open_https(urllib.request.Request(url, headers=headers)) as r:
            return r.read().decode()
    except Exception as e:  # noqa: BLE001 - report any network error the same way
        raise LookupFailed("%s: %s" % (url, e))


def fetch_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agentainer-bump"})
        with open_https(req) as r:
            return r.read()
    except Exception as e:  # noqa: BLE001 - report any network error the same way
        raise LookupFailed("%s: %s" % (url, e))


def fetch_json(url):
    try:
        return json.loads(fetch(url, "application/json"))
    except ValueError as e:
        raise LookupFailed("%s: bad JSON: %s" % (url, e))


# ---- parsers (pure, unit tested) -------------------------------------------

def strip_v(tag):
    return re.sub(r"^(rust-)?v", "", tag)


def parse_go(data):
    for rel in data:
        if not rel.get("stable"):
            continue
        out = {"GO_VERSION": rel["version"][2:]}
        for up, arch in ARCHES.items():
            match = [f for f in rel["files"] if f["os"] == "linux" and f["arch"] == arch and f["kind"] == "archive"]
            if not match:
                raise LookupFailed("go: no linux/%s archive" % arch)
            out["GO_SHA256_" + up] = match[0]["sha256"]
        return out
    raise LookupFailed("go: no stable release")


def parse_rust_channel(text):
    m = re.search(r'\[pkg\.rustc\]\s*\nversion = "([0-9.]+) ', text)
    if not m:
        raise LookupFailed("rust: no pkg.rustc version")
    return m.group(1)


def parse_rustup_release(text):
    m = re.search(r"^version = '([0-9.]+)'", text, re.M)
    if not m:
        raise LookupFailed("rustup: no version")
    return m.group(1)


def asset_sha256(release, name, fetch_text=None):
    """Require published SHA-256 files to agree with GitHub's asset digest.

    Projects use GNU checksum lists, BSD SHA256 lists, or per-asset .sha256 files.
    GitHub's server-computed digest is a fallback only when no such file exists.
    """
    tag = release.get("tag_name")
    assets = release.get("assets", [])
    match = [asset for asset in assets if asset["name"] == name]
    if len(match) != 1:
        raise LookupFailed("%s: asset %s missing or ambiguous" % (tag, name))
    digest = match[0].get("digest") or ""
    value = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    if digest and (not digest.startswith("sha256:") or not HEX64.fullmatch(value)):
        raise LookupFailed("%s: malformed asset digest" % tag)
    files = [asset for asset in assets if asset["name"] == name + ".sha256"]
    if not files:
        files = [asset for asset in assets if asset["name"].endswith(("checksums.txt", "SHA256SUMS"))
                 or asset["name"] in ("sha256.sum", "checksums-bsd", "checksums.sha256")]
    published = set()
    for asset in files:
        text = (fetch_text or fetch)(asset["browser_download_url"])
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == name and HEX64.fullmatch(parts[0]):
                published.add(parts[0])
            bsd = re.fullmatch(r"SHA256\s+\(" + re.escape(name) + r"\) = ([0-9a-f]{64})", line)
            if bsd:
                published.add(bsd.group(1))
    if files:
        if len(published) != 1 or (digest and value not in published):
            raise LookupFailed("%s: missing or conflicting published sha256 for %s" % (tag, name))
        return published.pop()
    if digest:
        return value
    raise LookupFailed("%s: no sha256 for asset %s" % (tag, name))


def parse_checksum_file(text):
    parts = text.split()
    if not parts or not HEX64.match(parts[0]):
        raise LookupFailed("checksum file does not start with a sha256: %r" % text[:60])
    return parts[0]


def parse_agy(manifest):
    try:
        version, url, sha = (manifest[k] for k in AGY_KEYS)
    except KeyError as e:
        raise LookupFailed("agy manifest: missing %s" % e)
    problem = agy_url_problem(url)
    if problem:
        raise LookupFailed("agy manifest: %s" % problem)
    if not HEX128.match(sha):
        raise LookupFailed("agy manifest: malformed sha512")
    return version, url, sha


# ---- resolvers (network) ---------------------------------------------------

def gh_latest(repo):
    return fetch_json("https://api.github.com/repos/%s/releases/latest" % repo)


# ---- release age ------------------------------------------------------------
# No resolver pins a release published less than MIN_RELEASE_AGE_HOURS before the run.
# When the newest release is younger, the resolver pins the newest release that is old
# enough; when none is, the pin stays. Each skipped release goes to YOUNG_RELEASES, which
# bump prints with the pin changes, so it reaches the pull request text without failing
# the run. Resolvers whose source gives no publish time say so in a comment and are not
# held back (docs/versions.md, "Minimum release age"). The extras keep their own, longer
# EXTRA_MIN_AGE_DAYS.
MIN_RELEASE_AGE_HOURS = 72
YOUNG_RELEASES = []
# A resolver that picked an older release because of its age records it here. bump then
# keeps the current pin when that older release sorts below it, instead of stopping the run
# as a downgrade.
AGE_FALLBACK = []


def release_cutoff(now):
    return now - datetime.timedelta(hours=MIN_RELEASE_AGE_HOURS)


def parse_time(value, what):
    """An ISO 8601 time with a UTC offset (GitHub, Gitea and Forgejo published_at) in UTC."""
    when = None
    if isinstance(value, str):
        try:
            when = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            when = None
    if when is None or when.tzinfo is None:
        raise LookupFailed("%s: no valid publish time %r" % (what, value))
    return when.astimezone(datetime.timezone.utc)


def too_young(what, version, published, now, note=""):
    """True when published is less than MIN_RELEASE_AGE_HOURS before now; records the skip."""
    if published <= release_cutoff(now):
        return False
    hours = int((now - published).total_seconds() // 3600)
    YOUNG_RELEASES.append("newer release %s %s skipped, published %d hours ago%s (minimum %d hours)"
                          % (what, version, hours, note, MIN_RELEASE_AGE_HOURS))
    return True


def gh_release(repo):
    """The GitHub release to pin for repo, or None when no stable release is old enough.

    That is the latest release, or, when it is too young, the stable release with the
    newest published_at that is at least MIN_RELEASE_AGE_HOURS old.
    """
    now = utcnow()
    latest = gh_latest(repo)
    if not too_young(repo, latest.get("tag_name"), parse_time(latest.get("published_at"), repo), now):
        return latest
    AGE_FALLBACK.append(repo)
    older = []
    for rel in fetch_json("https://api.github.com/repos/%s/releases?per_page=30" % repo):
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        published = parse_time(rel.get("published_at"), repo)
        if published <= release_cutoff(now):
            older.append((published, rel))
    return max(older, key=lambda pair: pair[0])[1] if older else None


def forge_release(latest_url, what):
    """The release to pin from a Gitea or Forgejo releases/latest URL, as gh_release does for GitHub.

    The list endpoint takes a limit parameter (Gitea API, "List a repo's releases").
    """
    now = utcnow()
    latest = fetch_json(latest_url)
    if not too_young(what, latest.get("tag_name"), parse_time(latest.get("published_at"), what), now):
        return latest
    AGE_FALLBACK.append(what)
    older = []
    for rel in fetch_json(latest_url.rsplit("/latest", 1)[0] + "?limit=20"):
        if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
            continue
        published = parse_time(rel.get("published_at"), what)
        if published <= release_cutoff(now):
            older.append((published, rel))
    return max(older, key=lambda pair: pair[0])[1] if older else None


def keep_pin(what):
    print("%s: no release is %d hours old yet; keeping the current pin" % (what, MIN_RELEASE_AGE_HOURS),
          file=sys.stderr)
    return {}


def r_base():
    # Unchanged by the release age rule: the tag moves with each Ubuntu image rebuild, and
    # the apt snapshot is always the previous day.
    tag = fetch_json("https://hub.docker.com/v2/repositories/library/ubuntu/tags/26.04")
    snap = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).strftime("%Y%m%dT000000Z")
    return {"BASE_IMAGE": "docker.io/library/ubuntu:26.04@" + tag["digest"], "APT_SNAPSHOT": snap}


def r_go():
    # go.dev/dl/?mode=json gives no release time, so the release age rule does not apply.
    return parse_go(fetch_json("https://go.dev/dl/?mode=json"))


def rust_manifest_url(version):
    return "https://static.rust-lang.org/dist/channel-rust-%s.toml" % version


def parse_rust_date(text):
    """The end of the day in the channel manifest's date line, the latest time it can mean."""
    m = re.search(r'^date = "([0-9]{4}-[0-9]{2}-[0-9]{2})"$', text, re.M)
    if not m:
        raise LookupFailed("rust: no date in the channel manifest")
    day = datetime.datetime.strptime(m.group(1), "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    return day + datetime.timedelta(days=1)


def r_rust():
    # rustup's release-stable.toml gives no release time, so the age rule covers only Rust.
    # The channel manifest gives only a day. No list of earlier releases is fetched, so a
    # Rust release that is too young keeps the current Rust pins.
    rustup = parse_rustup_release(fetch("https://static.rust-lang.org/rustup/release-stable.toml"))
    channel = fetch("https://static.rust-lang.org/dist/channel-rust-stable.toml")
    rust = parse_rust_channel(channel)
    out = {"RUSTUP_VERSION": rustup}
    if not too_young("rust", rust, parse_rust_date(channel), utcnow(), note=" (the manifest gives only the day)"):
        out["RUST_VERSION"] = rust
        # rustup checks every component against this versioned manifest; the build checks the manifest.
        out["RUST_MANIFEST_SHA256"] = parse_checksum_file(fetch(rust_manifest_url(rust) + ".sha256"))
    for up, triple in (("AMD64", "x86_64-unknown-linux-gnu"), ("ARM64", "aarch64-unknown-linux-gnu")):
        url = "https://static.rust-lang.org/rustup/archive/%s/%s/rustup-init.sha256" % (rustup, triple)
        out["RUSTUP_SHA256_" + up] = parse_checksum_file(fetch(url))
    return out


def github_tool(prefix, repo, names, rel=None, checksums=None):
    """names maps AMD64/ARM64 to a function of the bare version returning the asset name.

    rel is the release to pin; the default is gh_release, which applies the release age rule.
    """
    if rel is None:
        rel = gh_release(repo)
        if rel is None:
            return keep_pin(repo)
    ver = strip_v(rel["tag_name"])
    if checksums:
        # Only the named checksum list may supply the hashes; an asset digest alone is not enough.
        listed = checksums(ver)
        if not any(a["name"] == listed for a in rel.get("assets", [])):
            raise LookupFailed("%s: release %s has no %s" % (repo, rel["tag_name"], listed))
        rel = dict(rel, assets=[a for a in rel["assets"] if a["name"] == listed or a["name"] in
                                [fn(ver) for fn in names.values()]])
    out = {prefix + "_VERSION": ver}
    for up, fn in names.items():
        name = fn(ver)
        checksum = asset_sha256(rel, name)
        try:
            supported = verify_asset(repo, rel, name, checksum, fetch_bytes)
        except VerificationFailed as error:
            raise LookupFailed(str(error)) from error
        if not supported:
            print("%s: publisher signature verification not verified; retaining checksum checks" % repo,
                  file=sys.stderr)
        out["%s_SHA256_%s" % (prefix, up)] = checksum
    return out


def r_yq():
    return github_tool("YQ", "mikefarah/yq", {"AMD64": lambda v: "yq_linux_amd64", "ARM64": lambda v: "yq_linux_arm64"})


def r_gh():
    return github_tool("GH", "cli/cli", {
        "AMD64": lambda v: "gh_%s_linux_amd64.tar.gz" % v, "ARM64": lambda v: "gh_%s_linux_arm64.tar.gz" % v})


def r_uv():
    return github_tool("UV", "astral-sh/uv", {
        "AMD64": lambda v: "uv-x86_64-unknown-linux-gnu.tar.gz", "ARM64": lambda v: "uv-aarch64-unknown-linux-gnu.tar.gz"})


def r_ruff():
    # Official release binaries and per-asset checksums: https://github.com/astral-sh/ruff/releases
    return github_tool("RUFF", "astral-sh/ruff", {
        "AMD64": lambda v: "ruff-x86_64-unknown-linux-gnu.tar.gz",
        "ARM64": lambda v: "ruff-aarch64-unknown-linux-gnu.tar.gz"})


def r_gosec():
    # Release archives and gosec_<version>_checksums.txt: https://github.com/securego/gosec/releases
    return github_tool("GOSEC", "securego/gosec", {
        "AMD64": lambda v: "gosec_%s_linux_amd64.tar.gz" % v,
        "ARM64": lambda v: "gosec_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "gosec_%s_checksums.txt" % v)


def r_gitleaks():
    # Release archives name the amd64 build linux_x64: https://github.com/gitleaks/gitleaks/releases
    return github_tool("GITLEAKS", "gitleaks/gitleaks", {
        "AMD64": lambda v: "gitleaks_%s_linux_x64.tar.gz" % v,
        "ARM64": lambda v: "gitleaks_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "gitleaks_%s_checksums.txt" % v)


# ContainerSSH server image tag series -> the ContainerSSH guest agent minor series verified
# with it. The mapping limits proposals to the agent minor series verified against that server
# series. The "v0.6" tag's digest can move between patch releases. A new server series needs a
# reviewed entry.
CONTAINERSSH_AGENT_SERIES = {"v0.6": "0.11"}

# The server image reference and agent version that passed SFTP, ssh -L and ssh -D in a cluster
# on 2026-11-04 (docs/versions.md). test_pinned_containerssh_pair_is_the_cluster_verified_pair
# fails when versions.env pins another pair, so a bump pull request fails CI until someone
# re-verifies and updates this constant and docs/versions.md. The test runs in the build workflow
# on the pull request, not in the bump job, so the pull request still opens.
VERIFIED_CONTAINERSSH_PAIR = {
    "server_image": "docker.io/containerssh/containerssh:v0.6"
                    "@sha256:f6b195c221739b0f1a43c567bc9df0a0f3b3bd92ccc25ef451e6d4122820c13b",
    "agent_version": "0.11.0",
}


def r_containerssh_agent():
    tags = [tag for key, _, tag, _ in K8S_IMAGES if key == "CONTAINERSSH_IMAGE"]
    series = CONTAINERSSH_AGENT_SERIES.get(tags[0]) if tags else None
    if series is None:
        print("containerssh/agent: no agent series is mapped for the ContainerSSH tag %s; keeping the current pin"
              % (tags[0] if tags else "(none)"), file=sys.stderr)
        return {}
    wanted = re.compile(r"v?%s\.([0-9]+)" % re.escape(series))
    found = []
    young = False
    now = utcnow()
    for rel in fetch_json("https://api.github.com/repos/containerssh/agent/releases?per_page=50"):
        m = wanted.fullmatch(rel.get("tag_name", ""))
        if m and not rel.get("prerelease") and not rel.get("draft"):
            if too_young("containerssh/agent", rel["tag_name"],
                         parse_time(rel.get("published_at"), "containerssh/agent"), now):
                young = True
                continue
            found.append((int(m.group(1)), rel))
    if young:
        AGE_FALLBACK.append("containerssh/agent")
    if not found:
        if young:
            return keep_pin("containerssh/agent")
        raise LookupFailed("containerssh/agent: no stable %s.x release found" % series)
    return github_tool("CONTAINERSSH_AGENT", "containerssh/agent", {
        "AMD64": lambda v: "agent_%s_linux_amd64.tar.gz" % v,
        "ARM64": lambda v: "agent_%s_linux_arm64.tar.gz" % v},
        rel=max(found, key=lambda f: f[0])[1], checksums=lambda v: "agent_%s_checksums.txt" % v)


def r_trivy():
    out = github_tool("TRIVY", "aquasecurity/trivy", {
        "AMD64": lambda v: "trivy_%s_Linux-64bit.tar.gz" % v,
        "ARM64": lambda v: "trivy_%s_Linux-ARM64.tar.gz" % v})
    if not out:
        return out
    tag = out["TRIVY_VERSION"]
    out["TRIVY_SCANNER_IMAGE"] = hub_ref("aquasec/trivy", tag, fetch_json(
        "https://hub.docker.com/v2/repositories/aquasec/trivy/tags/" + tag))
    return out


def r_abtop():
    # Official release binaries and per-asset checksums: https://github.com/graykode/abtop/releases
    return github_tool("ABTOP", "graykode/abtop", {
        "AMD64": lambda v: "abtop-x86_64-unknown-linux-gnu.tar.xz",
        "ARM64": lambda v: "abtop-aarch64-unknown-linux-gnu.tar.xz"})


def r_unslop():
    # The pstack directory includes the skill and its license. Source files have no
    # published checksums, so compute both from the same immutable upstream commit.
    # https://github.com/cursor/plugins/tree/main/pstack
    # The age rule uses the commit's committer date, which the committer sets. The commits
    # API's until parameter returns only commits from before that time.
    url = 'https://api.github.com/repos/cursor/plugins/commits?path=pstack&per_page=1'
    commits = fetch_json(url)
    if not commits or not isinstance(commits[0], dict):
        raise LookupFailed('unslop: no upstream commit')
    now = utcnow()
    when = parse_time(((commits[0].get('commit') or {}).get('committer') or {}).get('date'), 'unslop')
    if too_young('unslop commit', str(commits[0].get('sha', ''))[:12], when, now):
        AGE_FALLBACK.append('unslop')
        commits = fetch_json(url + '&until=' + release_cutoff(now).strftime('%Y-%m-%dT%H:%M:%SZ'))
        if not commits:
            return keep_pin('unslop')
        if not isinstance(commits[0], dict):
            raise LookupFailed('unslop: no upstream commit')
    commit = commits[0].get('sha', '')
    if not isinstance(commit, str) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise LookupFailed('unslop: expected a full lowercase commit SHA')
    base = 'https://raw.githubusercontent.com/cursor/plugins/' + commit + '/pstack/'
    return {'UNSLOP_COMMIT': commit,
            'UNSLOP_SHA256': hashlib.sha256(fetch_bytes(base + 'skills/unslop/SKILL.md')).hexdigest(),
            'UNSLOP_LICENSE_SHA256': hashlib.sha256(fetch_bytes(base + 'LICENSE')).hexdigest()}


def r_golangci():
    return github_tool("GOLANGCI_LINT", "golangci/golangci-lint", {
        "AMD64": lambda v: "golangci-lint-%s-linux-amd64.tar.gz" % v,
        "ARM64": lambda v: "golangci-lint-%s-linux-arm64.tar.gz" % v})


def r_kubectl():
    # https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/
    # stable.txt and dl.k8s.io give no release time, so the release age rule does not apply.
    tag = fetch("https://dl.k8s.io/release/stable.txt").strip()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise LookupFailed("kubectl: stable release must be a version tag")
    out = {"KUBECTL_VERSION": tag[1:]}
    for up, arch in ARCHES.items():
        out["KUBECTL_SHA256_" + up] = parse_checksum_file(fetch(
            "https://dl.k8s.io/release/%s/bin/linux/%s/kubectl.sha256" % (tag, arch)))
    return out


def r_helm():
    # https://helm.sh/docs/intro/install/#from-the-binary-releases
    release = gh_release("helm/helm")
    if release is None:
        return keep_pin("helm/helm")
    tag = release["tag_name"]
    if release.get("prerelease") or release.get("draft") or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise LookupFailed("helm: latest release must be a stable version tag")
    out = {"HELM_VERSION": tag[1:]}
    for up, arch in ARCHES.items():
        name = "helm-%s-linux-%s.tar.gz" % (tag, arch)
        parts = fetch("https://get.helm.sh/" + name + ".sha256sum").split()
        if len(parts) != 2 or parts[1].lstrip("*") != name or not HEX64.fullmatch(parts[0]):
            raise LookupFailed("helm: invalid or mismatched checksum for " + name)
        out["HELM_SHA256_" + up] = parts[0]
    return out


def codex_asset(triple):
    # The complete package (bin/codex, codex-code-mode-host, rg, bwrap, codex-package.json).
    # The interactive CLI refuses to start from the bare binary ("this CLI has no complete
    # local package"); OpenAI's own installer uses this asset (chatgpt.com/codex/install.sh).
    return "codex-package-%s-unknown-linux-musl.tar.gz" % triple


def r_codex():
    return github_tool("CODEX", "openai/codex", {
        "AMD64": lambda v: codex_asset("x86_64"),
        "ARM64": lambda v: codex_asset("aarch64")})


TEA_RELEASES = "https://gitea.com/api/v1/repos/gitea/tea/releases/latest"


def r_tea():
    rel = forge_release(TEA_RELEASES, "gitea/tea")
    if rel is None:
        return keep_pin("gitea/tea")
    ver = strip_v(rel["tag_name"])
    out = {"TEA_VERSION": ver}
    for up, arch in ARCHES.items():
        name = "tea-%s-linux-%s.xz.sha256" % (ver, arch)
        assets = [a for a in rel.get("assets", []) if a["name"] == name]
        if not assets:
            raise LookupFailed("tea: %s not found" % name)
        out["TEA_SHA256_" + up] = parse_checksum_file(fetch(assets[0]["browser_download_url"]))
    return out


# forgejo-cli (fj) releases on Codeberg, a Forgejo instance:
# https://codeberg.org/forgejo-contrib/forgejo-cli/releases
FJ_RELEASES = "https://codeberg.org/api/v1/repos/forgejo-contrib/forgejo-cli/releases/latest"
FJ_TRIPLES = (("AMD64", "x86_64"), ("ARM64", "aarch64"))


def r_fj():
    # forgejo-cli publishes no checksums and the Forgejo release API returns no asset digest,
    # so the pins are SHA-256 values computed here from the downloaded archives.
    rel = forge_release(FJ_RELEASES, "forgejo-cli")
    if rel is None:
        return keep_pin("forgejo-cli")
    ver = strip_v(rel["tag_name"])
    out = {"FJ_VERSION": ver}
    for up, triple in FJ_TRIPLES:
        name = "forgejo-cli-%s-linux.tar.gz" % triple
        assets = [a for a in rel.get("assets", []) if a["name"] == name]
        if len(assets) != 1:
            raise LookupFailed("fj: %s missing or ambiguous in %s" % (name, rel["tag_name"]))
        out["FJ_SHA256_" + up] = hashlib.sha256(fetch_bytes(assets[0]["browser_download_url"])).hexdigest()
    return out


def r_crane():
    # Release archives and checksums.txt: https://github.com/google/go-containerregistry/releases
    return github_tool("CRANE", "google/go-containerregistry", {
        "AMD64": lambda v: "go-containerregistry_Linux_x86_64.tar.gz",
        "ARM64": lambda v: "go-containerregistry_Linux_arm64.tar.gz"},
        checksums=lambda v: "checksums.txt")


def r_kyverno():
    # The CLI archives keep the v in their names: https://github.com/kyverno/kyverno/releases
    return github_tool("KYVERNO", "kyverno/kyverno", {
        "AMD64": lambda v: "kyverno-cli_v%s_linux_x86_64.tar.gz" % v,
        "ARM64": lambda v: "kyverno-cli_v%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "checksums.txt")


def r_actionlint():
    # Release archives and actionlint_<version>_checksums.txt: https://github.com/rhysd/actionlint/releases
    return github_tool("ACTIONLINT", "rhysd/actionlint", {
        "AMD64": lambda v: "actionlint_%s_linux_amd64.tar.gz" % v,
        "ARM64": lambda v: "actionlint_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "actionlint_%s_checksums.txt" % v)


def r_zizmor():
    # No checksum list; github_tool falls back to GitHub's asset digest.
    # https://github.com/zizmorcore/zizmor/releases
    return github_tool("ZIZMOR", "zizmorcore/zizmor", {
        "AMD64": lambda v: "zizmor-x86_64-unknown-linux-gnu.tar.gz",
        "ARM64": lambda v: "zizmor-aarch64-unknown-linux-gnu.tar.gz"})


def r_hadolint():
    # Bare binaries and checksums.sha256: https://github.com/hadolint/hadolint/releases
    return github_tool("HADOLINT", "hadolint/hadolint", {
        "AMD64": lambda v: "hadolint-linux-x86_64",
        "ARM64": lambda v: "hadolint-linux-arm64"},
        checksums=lambda v: "checksums.sha256")


def r_ast_grep():
    # Zip archives without a checksum list; GitHub's asset digest is the fallback.
    # https://github.com/ast-grep/ast-grep/releases
    return github_tool("AST_GREP", "ast-grep/ast-grep", {
        "AMD64": lambda v: "app-x86_64-unknown-linux-gnu.zip",
        "ARM64": lambda v: "app-aarch64-unknown-linux-gnu.zip"})


def r_difftastic():
    # No checksum list; GitHub's asset digest is the fallback. https://github.com/Wilfred/difftastic/releases
    return github_tool("DIFFTASTIC", "Wilfred/difftastic", {
        "AMD64": lambda v: "difft-%s-x86_64-unknown-linux-gnu.tar.gz" % v,
        "ARM64": lambda v: "difft-%s-aarch64-unknown-linux-gnu.tar.gz" % v})


def r_delta():
    # No checksum list; GitHub's asset digest is the fallback. https://github.com/dandavison/delta/releases
    return github_tool("DELTA", "dandavison/delta", {
        "AMD64": lambda v: "delta-%s-x86_64-unknown-linux-gnu.tar.gz" % v,
        "ARM64": lambda v: "delta-%s-aarch64-unknown-linux-gnu.tar.gz" % v})


def r_scc():
    # Release archives and checksums.txt: https://github.com/boyter/scc/releases
    return github_tool("SCC", "boyter/scc", {
        "AMD64": lambda v: "scc_Linux_x86_64.tar.gz",
        "ARM64": lambda v: "scc_Linux_arm64.tar.gz"},
        checksums=lambda v: "checksums.txt")


def r_hyperfine():
    # No checksum list; GitHub's asset digest is the fallback. https://github.com/sharkdp/hyperfine/releases
    return github_tool("HYPERFINE", "sharkdp/hyperfine", {
        "AMD64": lambda v: "hyperfine-v%s-x86_64-unknown-linux-gnu.tar.gz" % v,
        "ARM64": lambda v: "hyperfine-v%s-aarch64-unknown-linux-gnu.tar.gz" % v})


def r_lazygit():
    # Release archives and checksums.txt: https://github.com/jesseduffield/lazygit/releases
    return github_tool("LAZYGIT", "jesseduffield/lazygit", {
        "AMD64": lambda v: "lazygit_%s_linux_x86_64.tar.gz" % v,
        "ARM64": lambda v: "lazygit_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "checksums.txt")


def r_glow():
    # Release archives and checksums.txt: https://github.com/charmbracelet/glow/releases
    return github_tool("GLOW", "charmbracelet/glow", {
        "AMD64": lambda v: "glow_%s_Linux_x86_64.tar.gz" % v,
        "ARM64": lambda v: "glow_%s_Linux_arm64.tar.gz" % v},
        checksums=lambda v: "checksums.txt")


def r_syft():
    # Release archives and syft_<version>_checksums.txt: https://github.com/anchore/syft/releases
    return github_tool("SYFT", "anchore/syft", {
        "AMD64": lambda v: "syft_%s_linux_amd64.tar.gz" % v,
        "ARM64": lambda v: "syft_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "syft_%s_checksums.txt" % v)


def r_grype():
    # Release archives and grype_<version>_checksums.txt: https://github.com/anchore/grype/releases
    return github_tool("GRYPE", "anchore/grype", {
        "AMD64": lambda v: "grype_%s_linux_amd64.tar.gz" % v,
        "ARM64": lambda v: "grype_%s_linux_arm64.tar.gz" % v},
        checksums=lambda v: "grype_%s_checksums.txt" % v)


# Claude Code's native release host, the one https://claude.ai/install.sh downloads from.
# Each release's manifest.json lists a SHA-256 per platform and is signed with this key
# (code.claude.com/docs/en/setup, "Binary integrity and code signing").
CLAUDE_RELEASES = "https://downloads.claude.ai/claude-code-releases"
CLAUDE_KEY_URL = "https://downloads.claude.ai/keys/claude-code.asc"
CLAUDE_KEY_FINGERPRINT = "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE"
CLAUDE_PLATFORMS = (("AMD64", "linux-x64"), ("ARM64", "linux-arm64"))
# Node's active release keys, listed after the README marker <!-- Active releasers keys --> in nodejs/release-keys at
# commit 481637f813e912c4aa3622d7964ab426c97b8e8d. NODE_KEYRING holds exactly these keys.
NODE_KEY_FINGERPRINTS = (
    "5BE8A3F6C8A5C01D106C0AD820B1A390B168D356",
    "DD792F5973C6DE52C432CBDAC77ABFA00DDBF2B7",
    "CC68F5A3106FF448322E48ED27F5E38D5B0A215F",
    "890C08DB8579162FEE0DF9DB8BEAB4DFCF555EF4",
    "C82FA3AE1CBEDC6BE46B9360C43CEC45C17AB93C",
    "108F52B48DB57BB0CC439B2997B01419BD92F80A",
    "655F3B5C1FB3FA8D1A0CA6BDE4A7D232B936D2FD",
    "A363A499291CBBC940DD62E41F10027AF002F8B0",
)
NODE_KEYRING = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys", "nodejs-release-keys.asc")


def parse_claude_manifest(doc, ver):
    """The pins for one Claude Code release from its manifest.json."""
    if doc.get("version") != ver:
        raise LookupFailed("claude: manifest is for %r, not %s" % (doc.get("version"), ver))
    out = {"CLAUDE_CODE_VERSION": ver}
    for up, platform in CLAUDE_PLATFORMS:
        checksum = ((doc.get("platforms") or {}).get(platform) or {}).get("checksum", "")
        if not HEX64.match(checksum):
            raise LookupFailed("claude %s: no valid checksum for %s" % (ver, platform))
        out["CLAUDE_CODE_SHA256_" + up] = checksum
    return out


def verify_signature(data, sig, key, fingerprints):
    """Raise LookupFailed unless sig is a valid signature of data by a key in the set fingerprints.

    fingerprints is one fingerprint or a tuple of them. The key file must hold exactly that set
    of primary keys, and gpg's status output must name one of them as the signer. gpg --verify
    alone accepts a signature by any key in the keyring.
    """
    wanted = frozenset([fingerprints] if isinstance(fingerprints, str) else fingerprints)
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, GNUPGHOME=home)
        paths = {}
        for name, content in (("key", key), ("data", data), ("sig", sig)):
            paths[name] = os.path.join(home, name)
            with open(paths[name], "wb") as f:
                f.write(content)
        gpg = ["gpg", "--batch", "--no-tty"]
        try:
            subprocess.run(gpg + ["--import", paths["key"]], env=env, check=True, capture_output=True)
            listing = subprocess.run(gpg + ["--with-colons", "--fingerprint"], env=env, check=True,
                                     capture_output=True, text=True).stdout
            lines = listing.splitlines()
            # The fpr line right after each pub line is that primary key's fingerprint.
            primaries = [lines[i + 1].split(":")[9] for i, line in enumerate(lines)
                         if line.startswith("pub:") and i + 1 < len(lines) and lines[i + 1].startswith("fpr:")]
            if len(primaries) != len(wanted) or set(primaries) != wanted:
                raise LookupFailed("signing key file holds %s, expected only %s"
                                   % (sorted(primaries), sorted(wanted)))
            # --trusted-key accepts these keys for the check without a trust database entry.
            trusted = [arg for fpr in sorted(wanted) for arg in ("--trusted-key", fpr[-16:])]
            status = subprocess.run(gpg + ["--status-fd", "1"] + trusted + ["--verify", paths["sig"], paths["data"]],
                                    env=env, check=True, capture_output=True, text=True).stdout
        except (OSError, subprocess.CalledProcessError) as e:
            raise LookupFailed("signature check failed: %s" % e)
    # GnuPG doc/DETAILS: GOODSIG means a good signature by a key that is neither expired nor
    # revoked; the last VALIDSIG field is the signing key's primary key fingerprint.
    words = [line.split() for line in status.splitlines() if line.startswith("[GNUPG:] ")]
    good = any(w[1] == "GOODSIG" for w in words if len(w) > 1)
    signers = [w[-1] for w in words if len(w) > 2 and w[1] == "VALIDSIG"]
    if not good or len(signers) != 1 or signers[0] not in wanted:
        bad = sorted({w[1] for w in words if len(w) > 1 and w[1] in ("EXPKEYSIG", "REVKEYSIG")})
        if bad:
            raise LookupFailed("signature check reported %s; the pinned signing key needs a hand update"
                               % " and ".join(bad))
        raise LookupFailed("signature is not a good signature by one of %s" % sorted(wanted))


def r_claude():
    # The "stable" channel Anthropic documents for Claude Code (code.claude.com/docs/en/setup).
    # The release host gives no time a version reached that channel. manifest.json has a
    # buildDate, but a release is published after it is built, so buildDate cannot show that
    # a release is old enough. The release age rule does not apply.
    ver = fetch(CLAUDE_RELEASES + "/stable").strip()
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", ver):
        raise LookupFailed("claude: unexpected stable version %r" % ver[:40])
    base = "%s/%s/" % (CLAUDE_RELEASES, ver)
    manifest = fetch_bytes(base + "manifest.json")
    verify_signature(manifest, fetch_bytes(base + "manifest.json.sig"), fetch_bytes(CLAUDE_KEY_URL),
                     CLAUDE_KEY_FINGERPRINT)
    return parse_claude_manifest(json.loads(manifest), ver)


NODE_DIST = "https://nodejs.org/dist"
NODE_MAJOR = 26


def node_release_end(entry):
    """The end of the day in an index.json entry's date, the latest time it can mean."""
    try:
        day = datetime.datetime.strptime(str(entry.get("date")), "%Y-%m-%d")
    except ValueError:
        raise LookupFailed("node: no valid date for %s in index.json" % entry.get("version"))
    return day.replace(tzinfo=datetime.timezone.utc) + datetime.timedelta(days=1)


def parse_node_index(doc, major, now=None):
    """Newest release of one Node.js major from nodejs.org/dist/index.json, without the v.

    With now, only releases whose day ended at least MIN_RELEASE_AGE_HOURS before now count,
    and the result is None when there is none.
    """
    if not isinstance(doc, list):
        raise LookupFailed("node: unexpected index.json shape")
    pattern = re.compile(r"v(%d\.[0-9]+\.[0-9]+)" % major)
    found = [(m.group(1), e) for m, e in ((pattern.fullmatch(str(e.get("version", ""))), e)
                                          for e in doc if isinstance(e, dict)) if m]
    if not found:
        raise LookupFailed("node: no release of major %d in index.json" % major)
    if now is not None:
        found = [(v, e) for v, e in found if node_release_end(e) <= release_cutoff(now)]
        if not found:
            return None
    return max((v for v, _ in found), key=version_key)


def parse_node_shasums(text, ver):
    """Both linux tarball hashes for one version from SHASUMS256.txt."""
    names = {"NODE_SHA256_AMD64": "node-v%s-linux-x64.tar.xz" % ver,
             "NODE_SHA256_ARM64": "node-v%s-linux-arm64.tar.xz" % ver}
    hashes = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2:
            hashes[parts[1]] = parts[0]
    out = {"NODE_VERSION": ver}
    for key, name in names.items():
        digest = hashes.get(name, "")
        if not HEX64.match(digest):
            raise LookupFailed("node: no valid sha256 for %s in SHASUMS256.txt" % name)
        out[key] = digest
    return out


def r_node():
    # nodejs.org signs SHASUMS256.txt with the release keys pinned in scripts/keys.
    # index.json gives each release's day, which counts as the end of that day.
    doc = fetch_json(NODE_DIST + "/index.json")
    now = utcnow()
    newest = parse_node_index(doc, NODE_MAJOR)
    ver = parse_node_index(doc, NODE_MAJOR, now=now)
    if ver != newest:
        entry = next(e for e in doc if isinstance(e, dict) and e.get("version") == "v" + newest)
        too_young("node", newest, node_release_end(entry), now, note=" (index.json gives only the day)")
        AGE_FALLBACK.append("node")
    if ver is None:
        return keep_pin("node")
    base = "%s/v%s/SHASUMS256.txt" % (NODE_DIST, ver)
    shasums = fetch_bytes(base)
    sig = fetch_bytes(base + ".sig")
    with open(NODE_KEYRING, "rb") as f:
        key = f.read()
    verify_signature(shasums, sig, key, NODE_KEY_FINGERPRINTS)
    return parse_node_shasums(shasums.decode(), ver)


# AWS CLI v2 installer zips, one per version and architecture, each with a detached PGP
# signature at <zip>.sig. AWS links the v2 changelog as the list of versions
# (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-version.html).
# AWS publishes its signing key only as text in the install guide
# (https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html), so
# AWSCLI_KEY is a copy of that block and AWSCLI_KEY_FINGERPRINT is the fingerprint the guide
# lists for it. AWS publishes no checksums; the pins are SHA-256 values of the verified zips.
AWSCLI_CHANGELOG = "https://raw.githubusercontent.com/aws/aws-cli/v2/CHANGELOG.rst"
AWSCLI_DOWNLOADS = "https://awscli.amazonaws.com"
AWSCLI_KEY_FINGERPRINT = "FB5DB77FD5C118B80511ADA8A6310ACC4672475C"
AWSCLI_KEY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys", "aws-cli-public-key.asc")
AWSCLI_TRIPLES = (("AMD64", "x86_64"), ("ARM64", "aarch64"))


def parse_awscli_changelog(text):
    """The newest version in the AWS CLI v2 CHANGELOG.rst, whose first heading is the newest release."""
    found = re.findall(r"^([0-9]+\.[0-9]+\.[0-9]+)\n=+$", text, re.M)
    if not found:
        raise LookupFailed("awscli: no version heading in CHANGELOG.rst")
    if not found[0].startswith("2."):
        raise LookupFailed("awscli: newest changelog version %s is not v2" % found[0])
    if found[0] != max(found, key=version_key):
        raise LookupFailed("awscli: first changelog heading %s is not the newest version" % found[0])
    return found[0]


def awscli_zip_url(triple, ver):
    return "%s/awscli-exe-linux-%s-%s.zip" % (AWSCLI_DOWNLOADS, triple, ver)


def r_awscli():
    # The changelog headings give no release time, so the release age rule does not apply.
    ver = parse_awscli_changelog(fetch(AWSCLI_CHANGELOG))
    # The zips are about 75 MB each. When the version is already pinned, its checksums are
    # already pinned too, so nothing is downloaded and the pins stay as they are. main
    # snapshots the pins from --file into EXTRA_FILES.pins before the resolvers run.
    if EXTRA_FILES.pins.get("AWSCLI_VERSION") == ver:
        return {}
    with open(AWSCLI_KEY, "rb") as f:
        key = f.read()
    out = {"AWSCLI_VERSION": ver}
    for up, triple in AWSCLI_TRIPLES:
        url = awscli_zip_url(triple, ver)
        data = fetch_bytes(url)
        verify_signature(data, fetch_bytes(url + ".sig"), key, AWSCLI_KEY_FINGERPRINT)
        out["AWSCLI_SHA256_" + up] = hashlib.sha256(data).hexdigest()
    return out


def r_agy():
    # The manifest has only version, url and sha512, no release time, so the release age
    # rule does not apply.
    out = {}
    versions = set()
    for up, arch in ARCHES.items():
        ver, url, sha = parse_agy(fetch_json(AGY_MANIFEST.format(arch=arch)))
        versions.add(ver)
        out["AGY_URL_" + up] = url
        out["AGY_SHA512_" + up] = sha
    if len(versions) != 1:
        raise LookupFailed("agy: architectures disagree on version %s" % sorted(versions))
    out["AGY_VERSION"] = versions.pop()
    return out


def r_opencode():
    # The release age rule uses the registry's time for each version of @opencode/cli.
    packument = fetch_json(NPM_REGISTRY + "@opencode/cli")
    now = utcnow()
    latest = packument["dist-tags"]["latest"]
    try:
        ver = pick_version(packument, now, datetime.timedelta(hours=MIN_RELEASE_AGE_HOURS))
    except NothingNewer:
        ver = None
    if ver != latest:
        too_young("@opencode/cli", latest, parse_registry_time(packument["time"].get(latest)), now)
        AGE_FALLBACK.append("@opencode/cli")
    if ver is None:
        return keep_pin("@opencode/cli")
    out = {"OPENCODE_VERSION": ver}
    keys = load_registry_keys(NPM_KEYS)
    for up, target in (("AMD64", "linux-x64-baseline"), ("ARM64", "linux-arm64")):
        name = "@opencode/cli-%s" % target
        dist = fetch_json(NPM_REGISTRY + name + "/" + ver)["dist"]
        integrity = dist["integrity"]

        # The per-version document has no publish time; the packument's time map does.
        def published(name=name):
            times = fetch_json(NPM_REGISTRY + name).get("time")
            return parse_registry_time(times.get(ver) if isinstance(times, dict) else None)

        # The same registry signature check as the extras lockfile entries.
        verify_registry_signature(name, ver, integrity, dist.get("signatures") or [], keys, published=published)
        out["OPENCODE_INTEGRITY_" + up] = integrity
    return out


# ---- extras ----------------------------------------------------------------

NPM_REGISTRY = "https://registry.npmjs.org/"
EXTRAS_DIR = "rootfs/usr/local/share/agentainer/extras"
# (versions.env key, npm package, catalog directory under EXTRAS_DIR)
EXTRAS = (("KANDEV_VERSION", "kandev", "kandev"),
          ("OPENCHAMBER_VERSION", "@openchamber/web", "openchamber"),
          ("REA_VERSION", "rea-agents", "rea"))
EXTRA_MIN_AGE_DAYS = 7
# Packages whose install scripts may appear in a lockfile. Extras install with
# npm ci --ignore-scripts, so no install script runs. node-pty 1.2.0-beta.15 ships
# prebuilds/linux-x64 and prebuilds/linux-arm64
# (https://unpkg.com/node-pty@1.2.0-beta.15/?meta), and its install script
# scripts/prebuild.js only checks that prebuilds/<platform>-<arch> exists
# (https://unpkg.com/node-pty@1.2.0-beta.15/scripts/prebuild.js). rea keeps
# optional dependencies, so frida installs without running its install script
# (npm ci --ignore-scripts).
INSTALL_SCRIPT_ALLOWLIST = frozenset(("node-pty", "frida"))
# Both keys from https://registry.npmjs.org/-/npm/v1/keys, copied verbatim on 2026-11-01.
NPM_KEYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keys", "npm-registry-keys.json")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STABLE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
NPM_NAME = re.compile(r"(?:@([A-Za-z0-9._~-]+)/)?([A-Za-z0-9._~-]+)")
NPM_VERSION = re.compile(r"[0-9A-Za-z.+-]+")
# An npm version as node-semver parses it: MAJOR.MINOR.PATCH, an optional -prerelease and an
# optional +build (https://docs.npmjs.com/about-semantic-versioning, https://semver.org/#spec-item-9).
NPM_SEMVER = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?")
REGISTRY_TIME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})(\.[0-9]+)?Z")


def npm_name_ok(name):
    """True when name follows npm's package name rules.

    https://docs.npmjs.com/cli/v11/configuring-npm/package-json#name: at most 214
    characters including the scope, URL-safe, and an unscoped name must not begin
    with a dot or an underscore (a scoped one may). "." and ".." are refused in
    either part because the name becomes part of a registry URL path.
    """
    m = NPM_NAME.fullmatch(name) if isinstance(name, str) else None
    if not m or len(name) > 214:
        return False
    scope, pkg = m.groups()
    if scope is None:
        return not pkg.startswith((".", "_"))
    return scope not in (".", "..") and pkg not in (".", "..")


class NothingNewer(LookupFailed):
    """The registry has no version that may replace the pin yet. Not a failed check."""


class ExtraFiles:
    """Catalog files r_extras computed in one run of main.

    main calls reset before the resolvers run and writes files only after every
    resolver and check passed. Paths in files are relative to base. failures holds
    one "extras <name>: <reason>" line per extra whose checks failed.
    """

    def __init__(self):
        self.reset(None, {})

    def reset(self, base, pins):
        self.base = base
        self.pins = dict(pins)
        self.files = {}
        self.regenerated = []
        self.failures = []


EXTRA_FILES = ExtraFiles()
# One "<resolver>: <reason>" line per resolver that failed in this run of main.
RESOLVER_FAILURES = []


def utcnow():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_registry_time(value):
    """A registry timestamp such as 2025-01-29T00:00:00.000Z as an aware UTC datetime."""
    m = REGISTRY_TIME.fullmatch(value) if isinstance(value, str) else None
    if not m:
        raise LookupFailed("unexpected registry time %r" % (value,))
    when = datetime.datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S").replace(tzinfo=datetime.timezone.utc)
    return when + datetime.timedelta(seconds=float("0" + (m.group(2) or "")))


def npm_version_key(value):
    """Sort key for an npm version: (major, minor, patch, 0 for a prerelease or 1 for a release).

    A prerelease sorts below the release with the same major, minor and patch, as in
    https://semver.org/#spec-item-11. Prerelease identifiers and build metadata are not compared,
    because the extras resolver only picks releases. Raises ValueError for any other string.
    """
    m = NPM_SEMVER.fullmatch(value) if isinstance(value, str) else None
    if not m:
        raise ValueError("invalid npm version %r" % (value,))
    return tuple(int(n) for n in m.group(1, 2, 3)) + (int(m.group(4) is None),)


def pick_version(packument, now, min_age=None):
    """Newest stable, non-deprecated version up to dist-tags.latest published at least min_age before now.

    min_age defaults to EXTRA_MIN_AGE_DAYS.
    """
    if min_age is None:
        min_age = datetime.timedelta(days=EXTRA_MIN_AGE_DAYS)
    if not isinstance(packument, dict) or not isinstance(packument.get("versions"), dict):
        raise LookupFailed("packument is not an object with versions")
    latest = npm_version_key(packument["dist-tags"]["latest"])
    times = packument.get("time")
    if not isinstance(times, dict) or not times:
        raise LookupFailed("packument has no time object")
    cutoff = now - min_age
    found = []
    candidates = timed = 0
    for ver, meta in packument["versions"].items():
        if not STABLE_VERSION.fullmatch(ver) or (isinstance(meta, dict) and meta.get("deprecated")):
            continue
        if npm_version_key(ver) > latest:
            continue
        candidates += 1
        try:
            published = parse_registry_time(times.get(ver))
        except LookupFailed:
            continue
        timed += 1
        if published <= cutoff:
            found.append(ver)
    if candidates and not timed:
        raise LookupFailed("packument time has no valid entry for any stable version")
    if not found:
        raise NothingNewer("no stable version published at least %d hours ago" % (min_age.total_seconds() // 3600))
    return max(found, key=npm_version_key)


def lock_entry_name(path, entry):
    """Package name of a lockfile packages entry. Aliased packages record their real name in "name"."""
    return entry.get("name") or path.rsplit("node_modules/", 1)[-1]


def new_install_scripts(old_lock, new_lock):
    """Names of packages with hasInstallScript in new_lock and in no entry of old_lock, minus the allowlist."""
    def flagged(lock):
        return {lock_entry_name(path, entry) for path, entry in (lock.get("packages") or {}).items()
                if path and isinstance(entry, dict) and entry.get("hasInstallScript")}
    return sorted(flagged(new_lock) - flagged(old_lock) - INSTALL_SCRIPT_ALLOWLIST)


def load_registry_keys(path):
    """The keys of an npm /-/npm/v1/keys document, by keyid."""
    with open(path) as f:
        doc = json.load(f)
    keys = {}
    for key in doc["keys"]:
        if key.get("keytype") != "ecdsa-sha2-nistp256" or key.get("scheme") != "ecdsa-sha2-nistp256":
            raise LookupFailed("%s: unsupported key type for %s" % (path, key.get("keyid")))
        keys[key["keyid"]] = key
    return keys


def verify_registry_signature(name, version, integrity, signatures, keys, published=None):
    """Raise LookupFailed unless one of signatures verifies against a key in keys.

    The registry signs "<name>@<version>:<integrity>" with ECDSA P-256 over SHA-256
    (https://docs.npmjs.com/about-registry-signatures). sig is a base64 DER signature
    and key is a base64 DER SubjectPublicKeyInfo. A key with "expires" counts only
    for a version published before that time, as npm does (npm/pacote lib/registry.js).
    published is a function returning the version's publish time; it is called only
    for such a key.
    """
    message = ("%s@%s:%s" % (name, version, integrity)).encode()
    reasons = []
    with tempfile.TemporaryDirectory() as tmp:
        paths = {n: os.path.join(tmp, n) for n in ("data", "key", "sig")}
        with open(paths["data"], "wb") as f:
            f.write(message)
        for signature in signatures or []:
            keyid = signature.get("keyid") if isinstance(signature, dict) else None
            key = keys.get(keyid)
            if key is None:
                reasons.append("unknown keyid %r" % (keyid,))
                continue
            if key.get("expires"):
                try:
                    when = published() if published else None
                except LookupFailed as e:
                    reasons.append("no publish time for key %s: %s" % (keyid, e))
                    continue
                if when is None or not when < parse_registry_time(key["expires"]):
                    reasons.append("key %s expired %s, before this version was published" % (keyid, key["expires"]))
                    continue
            try:
                der_key = base64.b64decode(key["key"], validate=True)
                der_sig = base64.b64decode(signature["sig"], validate=True)
            except (KeyError, TypeError, binascii.Error):
                reasons.append("malformed signature or key for %s" % keyid)
                continue
            for n, content in (("key", der_key), ("sig", der_sig)):
                with open(paths[n], "wb") as f:
                    f.write(content)
            try:
                result = subprocess.run(["openssl", "dgst", "-sha256", "-verify", paths["key"], "-keyform", "DER",
                                         "-signature", paths["sig"], paths["data"]],
                                        capture_output=True, text=True)
            except OSError as e:
                raise LookupFailed("openssl: %s" % e)
            if result.returncode == 0 and "Verified OK" in result.stdout:
                return
            reasons.append("signature by %s does not verify" % keyid)
    raise LookupFailed("%s@%s: no registry signature verifies (%s)"
                       % (name, version, "; ".join(reasons) or "no signatures"))


def check_lockfile(lock, fetch_json=fetch_json, keys=None):
    """Raise LookupFailed unless every downloaded package in lock matches a signed registry entry.

    Each entry must come from the public registry with an integrity equal to the
    registry's dist.integrity for that version, and that integrity must carry a
    registry signature. Bundled entries ship inside their parent's tarball, so the
    parent's integrity covers them. A link entry points outside the registry and is refused.
    """
    keys = load_registry_keys(NPM_KEYS) if keys is None else keys
    packages = lock.get("packages") if isinstance(lock, dict) else None
    if not isinstance(packages, dict):
        raise LookupFailed("lockfile has no packages object")
    packuments = {}
    for path, entry in sorted(packages.items()):
        if not isinstance(entry, dict):
            raise LookupFailed("%s: lockfile entry is not an object" % path)
        if not path:
            continue
        if entry.get("link"):
            raise LookupFailed("%s: lockfile entry is a link" % path)
        if entry.get("inBundle"):
            continue
        name, version, integrity = lock_entry_name(path, entry), entry.get("version"), entry.get("integrity")
        if not npm_name_ok(name) or not isinstance(version, str) or not NPM_VERSION.fullmatch(version):
            raise LookupFailed("%s: unexpected name or version" % path)
        if not integrity or not isinstance(integrity, str):
            raise LookupFailed("%s: lockfile entry has no integrity" % path)
        if not str(entry.get("resolved", "")).startswith(NPM_REGISTRY):
            raise LookupFailed("%s: resolved outside %s" % (path, NPM_REGISTRY))
        doc = fetch_json(NPM_REGISTRY + name + "/" + version)
        dist = doc.get("dist") if isinstance(doc, dict) else None
        if not isinstance(dist, dict) or not isinstance(dist.get("signatures", []), list):
            raise LookupFailed("%s@%s: registry document has no dist object" % (name, version))
        if dist.get("integrity") != integrity:
            raise LookupFailed("%s@%s: registry integrity differs from the lockfile" % (name, version))

        # The per-version document has no publish time; the full packument's time map does.
        def published(name=name, version=version):
            if name not in packuments:
                packuments[name] = fetch_json(NPM_REGISTRY + name)
            doc = packuments[name]
            times = doc.get("time") if isinstance(doc, dict) else None
            return parse_registry_time(times.get(version) if isinstance(times, dict) else None)

        verify_registry_signature(name, version, integrity, dist.get("signatures") or [], keys, published=published)


def npm_lockfile(package_json, now):
    """package-lock.json text that npm generates for package_json, without running package code.

    --before applies the same release-age rule to every dependency in the tree
    (https://docs.npmjs.com/cli/v11/using-npm/config#before). The empty userconfig
    keeps a local ~/.npmrc from changing the registry or other settings.
    """
    before = (now - datetime.timedelta(days=EXTRA_MIN_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as tmp:
        work = os.path.join(tmp, "work")
        os.mkdir(work)
        with open(os.path.join(work, "package.json"), "w") as f:
            f.write(package_json)
        userconfig = os.path.join(tmp, "npmrc")
        open(userconfig, "w").close()
        argv = ["npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache=" + os.path.join(tmp, "cache"), "--userconfig=" + userconfig,
                "--registry=" + NPM_REGISTRY, "--before=" + before]
        try:
            subprocess.run(argv, cwd=work, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            tail = " ".join((e.stderr or "").strip().splitlines()[-3:])
            raise LookupFailed("npm install exited %d: %s" % (e.returncode, tail))
        except OSError as e:
            raise LookupFailed("npm: %s" % e)
        with open(os.path.join(work, "package-lock.json")) as f:
            return f.read()


def extra_update(base, pin, name, extra, now):
    """(version, {relative path: text}) for one extra, or None when its pin stays."""
    rel = EXTRAS_DIR + "/" + extra
    directory = os.path.join(base, rel)
    if pin is None or not os.path.isdir(directory):
        what = "no pin in versions.env" if pin is None else "no catalog directory %s" % rel
        print("bump_versions: extras %s: %s; skipped" % (extra, what), file=sys.stderr)
        return None
    ver = pick_version(fetch_json(NPM_REGISTRY + name), now)
    if npm_version_key(ver) <= npm_version_key(pin):
        if npm_version_key(ver) < npm_version_key(pin):
            print("bump_versions: extras %s: registry offers %s, older than %s; pin unchanged" % (extra, ver, pin),
                  file=sys.stderr)
        return None
    with open(os.path.join(directory, "package.json")) as f:
        wrapper = json.load(f)
    if not isinstance(wrapper, dict) or not isinstance(wrapper.get("dependencies"), dict) \
            or list(wrapper["dependencies"]) != [name]:
        raise LookupFailed("%s/package.json must depend on exactly %s" % (rel, name))
    wrapper["dependencies"] = {name: ver}
    package_json = json.dumps(wrapper, indent=2) + "\n"
    with open(os.path.join(directory, "package-lock.json")) as f:
        old_lock = json.load(f)
    lock_text = npm_lockfile(package_json, now)
    new_lock = json.loads(lock_text)
    for label, lock in (("committed", old_lock), ("generated", new_lock)):
        if not isinstance(lock, dict) or not isinstance(lock.get("packages"), dict):
            raise LookupFailed("%s lockfile has no packages object" % label)
    if (new_lock["packages"].get("node_modules/" + name) or {}).get("version") != ver:
        raise LookupFailed("generated lockfile does not hold %s@%s" % (name, ver))
    added = new_install_scripts(old_lock, new_lock)
    if added:
        raise LookupFailed("new install scripts in %s" % ", ".join(added))
    check_lockfile(new_lock)
    return ver, {rel + "/package.json": package_json, rel + "/package-lock.json": lock_text}


def r_extras():
    """Pins for the extras whose newer version passed every check.

    Their files go to EXTRA_FILES.files. A failed check for one extra, including
    malformed upstream data or a missing npm or openssl, keeps that extra's pin
    and goes to EXTRA_FILES.failures; the other extras continue.
    """
    base = EXTRA_FILES.base or REPO_ROOT
    now = utcnow()
    out = {}
    for key, name, extra in EXTRAS:
        try:
            result = extra_update(base, EXTRA_FILES.pins.get(key), name, extra, now)
        except NothingNewer as e:
            print("bump_versions: extras %s: %s; pin unchanged" % (extra, e), file=sys.stderr)
            continue
        except (LookupFailed, OSError, AttributeError, KeyError, IndexError, TypeError, ValueError) as e:
            print("bump_versions: extras %s: %s; pin unchanged" % (extra, e), file=sys.stderr)
            # One line per failure, so the --failures file has one entry per line.
            EXTRA_FILES.failures.append("extras %s: %s" % (extra, " ".join(str(e).split())))
            continue
        if result:
            out[key], files = result
            EXTRA_FILES.files.update(files)
            EXTRA_FILES.regenerated.append(extra)
    return out


K8S_IMAGES = (("CONTAINERSSH_IMAGE", "containerssh/containerssh", "v0.6",
                "deploy/kubernetes/containerssh/deployment.yaml"),
               ("WEBHOOK_PYTHON_IMAGE", "library/python", "3.14-slim",
                "deploy/kubernetes/auth-webhook/deployment.yaml"),
               # 2.0-stable-slim follows 2.0.x patch releases and never crosses a major version.
               ("FILEBROWSER_IMAGE", "gtstef/filebrowser", "2.0-stable-slim",
                "deploy/kubernetes/agentainer/statefulset.yaml"))


def hub_ref(repo, tag, data):
    digest = data.get("digest") or ""
    if not re.match(r"^sha256:[0-9a-f]{64}$", digest):
        raise LookupFailed("docker hub %s:%s: malformed digest %r" % (repo, tag, digest))
    return "docker.io/%s:%s@%s" % (repo, tag, digest)


def rewrite_image_ref(text, ref):
    """Replace any digest-pinned reference to the same image with ref."""
    image = ref.split("@")[0].rsplit(":", 1)[0]
    return re.sub(re.escape(image) + r":[^\s@]+@sha256:[0-9a-f]{64}", ref, text)


def r_k8s_images():
    # Unchanged by the release age rule: each tag follows a series and moves with every
    # rebuild, and Docker Hub keeps no earlier digests to fall back to.
    return {key: hub_ref(repo, tag, fetch_json("https://hub.docker.com/v2/repositories/%s/tags/%s" % (repo, tag)))
            for key, repo, tag, _ in K8S_IMAGES}


def buildkit_tag(releases):
    """Newest stable BuildKit release. The repo also tags Dockerfile frontend releases."""
    for r in releases:
        if not r.get("prerelease") and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", r.get("tag_name", "")):
            return r["tag_name"]
    raise LookupFailed("moby/buildkit: no stable release found")


def r_buildkit():
    # The BuildKit image buildx uses to build the published image (build.yml, publish job).
    now = utcnow()
    releases = []
    young = False
    for r in fetch_json("https://api.github.com/repos/moby/buildkit/releases?per_page=20"):
        if not r.get("prerelease") and re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", r.get("tag_name", "")) \
                and too_young("moby/buildkit", r["tag_name"], parse_time(r.get("published_at"), "moby/buildkit"), now):
            young = True
            continue
        releases.append(r)
    if young:
        AGE_FALLBACK.append("moby/buildkit")
    try:
        tag = buildkit_tag(releases)
    except LookupFailed:
        if young:
            return keep_pin("moby/buildkit")
        raise
    return {"BUILDKIT_IMAGE": hub_ref("moby/buildkit", tag,
                                      fetch_json("https://hub.docker.com/v2/repositories/moby/buildkit/tags/%s" % tag))}


AGENTAINER_REPO = "chadmayfield/agentainer"
AGENTAINER_IMAGE = "ghcr.io/" + AGENTAINER_REPO
# Files that use AGENTAINER_RELEASE_VERSION as their default or example tag, each with the
# text that comes right before the tag. bump() rewrites them when the pin changes, and
# tests/unit/test_bump_versions.py checks that every entry holds the current pin.
RELEASE_REFS = (("bin/agentainer", AGENTAINER_IMAGE + ":"),
                ("deploy/kubernetes/agentainer/statefulset.yaml", AGENTAINER_IMAGE + ":"),
                ("deploy/kubernetes/agentainer/kustomization.yaml", "newTag: "),
                ("README.md", AGENTAINER_IMAGE + ":"),
                ("docs/running.md", AGENTAINER_IMAGE + ":"),
                ("docs/versions.md", AGENTAINER_IMAGE + ":"),
                ("docs/versions.md", "version="))


def agentainer_release(releases):
    """Newest published release by version order, without its leading v.

    Prereleases count, because they are the only published images before the first
    stable release. Drafts and tags that are not release versions are skipped.
    """
    found = []
    for r in releases:
        tag = r.get("tag_name") or ""
        if r.get("draft") or not tag.startswith("v"):
            continue
        try:
            version_key(tag[1:])
        except ValueError:
            continue
        found.append(tag[1:])
    if not found:
        raise LookupFailed("%s: no published release found" % AGENTAINER_REPO)
    return max(found, key=version_key)


def r_agentainer_release():
    # The list endpoint includes prereleases. /releases/latest leaves them out and returns
    # 404 while every release is a prerelease.
    releases = fetch_json("https://api.github.com/repos/%s/releases?per_page=100" % AGENTAINER_REPO)
    return {"AGENTAINER_RELEASE_VERSION": agentainer_release(releases)}


def rewrite_release_ref(text, prefix, old, new):
    """Replace prefix+old with prefix+new where old is the whole version, not the start of a longer one."""
    pattern = re.escape(prefix + old) + r"(?![0-9A-Za-z-]|\.[0-9A-Za-z])"
    return re.sub(pattern, lambda _: prefix + new, text)


RESOLVERS = [r_base, r_go, r_rust, r_yq, r_gh, r_uv, r_ruff, r_trivy, r_gosec, r_gitleaks, r_containerssh_agent,
             r_abtop, r_unslop, r_golangci, r_kubectl, r_helm, r_awscli, r_tea, r_fj, r_crane, r_kyverno,
             r_actionlint, r_zizmor, r_hadolint, r_ast_grep, r_difftastic, r_delta, r_scc, r_hyperfine,
             r_lazygit, r_glow, r_syft, r_grype, r_claude, r_node, r_codex, r_agy,
             r_opencode, r_k8s_images, r_buildkit, r_agentainer_release, r_extras]


def write_atomic(path, text):
    """Replace path with text through a unique temp file in the same directory.

    The new file keeps the old file's permission bits; a new file gets 0666 minus the umask.
    """
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix="." + os.path.basename(path) + ".")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def main(argv=None, resolvers=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", default="versions.env")
    ap.add_argument("--only", nargs="*", help="resolver names such as r_go r_agy")
    ap.add_argument("--failures", help="file to list failed resolvers and extras checks in, one per line (empty when none)")
    args = ap.parse_args(argv)
    EXTRA_FILES.reset(None, {})
    del RESOLVER_FAILURES[:]
    del YOUNG_RELEASES[:]
    if args.failures:
        # A later workflow step reads this file, so it exists even when the run fails.
        try:
            write_atomic(args.failures, "")
        except OSError as e:
            print("bump_versions: cannot write --failures %s: %s" % (args.failures, e), file=sys.stderr)
            return 2
    try:
        rc = bump(args, resolvers)
    except BaseException:
        # report_failures never raises, so the original exception propagates unchanged.
        report_failures(args.failures)
        raise
    if not report_failures(args.failures) and rc == 0:
        # Failures that never reached the file would let the workflow job pass.
        return 2
    return rc


def report_failures(path):
    """Write the failed resolvers and extras checks to path and print them, on every exit from main.

    Failed checks keep their pins while the other pins still go out. The lines
    go to path, which a later workflow step fails on when it is not empty, then
    to stdout (and a GitHub Actions warning). Never raises. Returns False when
    failures exist but path could not be written, True otherwise.
    """
    failures = RESOLVER_FAILURES + list(EXTRA_FILES.failures)
    ok = True
    if path:
        try:
            write_atomic(path, "".join(line + "\n" for line in failures))
        except OSError as e:
            # main truncated path at the start, so it is empty rather than stale.
            ok = not failures
            try:
                print("bump_versions: cannot write --failures %s: %s" % (path, e), file=sys.stderr)
            except OSError:
                pass
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        for line in failures:
            if annotate:
                # Workflow command data escapes % as %25 (actions/toolkit packages/core/src/command.ts, escapeData).
                print("::warning::bump_versions: %s" % line.replace("%", "%25"))
            print(line)
    except OSError:
        # A closed stdout (BrokenPipeError) must not hide the exit code or exception from bump.
        pass
    return ok


def older_than_pin(result, old, npm_keys):
    """The first _VERSION key in result whose value sorts below its current pin, or None."""
    for key, value in result.items():
        if key.endswith("_VERSION") and key in old and old[key] != value:
            order = npm_version_key if key in npm_keys else version_key
            try:
                if order(strip_v(value)) < order(strip_v(old[key])):
                    return key
            except ValueError:
                continue
    return None


def bump(args, resolvers):
    known = {r.__name__ for r in RESOLVERS}
    unknown = sorted(set(args.only or []) - known)
    if unknown:
        print("bump_versions: unknown resolver(s) %s; known: %s" % (", ".join(unknown), ", ".join(sorted(known))),
              file=sys.stderr)
        return 2
    chosen = resolvers or [r for r in RESOLVERS if not args.only or r.__name__ in args.only]
    with open(args.file) as f:
        lines = parse_env(f.read())
    # Every path main reads or writes besides args.file is relative to the directory that holds it.
    base = os.path.dirname(os.path.abspath(args.file))
    EXTRA_FILES.reset(base, values(lines))
    updates = {}
    old = values(lines)
    npm_keys = {key for key, _, _ in EXTRAS}
    # A failed resolver keeps its pins; one failed publisher check, such as an expired
    # signing key, must not hold back every other tool.
    for r in chosen:
        name = getattr(r, "__name__", repr(r))
        del AGE_FALLBACK[:]
        try:
            result = r()
            below = AGE_FALLBACK and older_than_pin(result, old, npm_keys)
            if below:
                # The release old enough to pin is older than the current pin, which an
                # earlier run took before it was old enough. Keep the current pin.
                print("bump_versions: %s: the newest release old enough sorts below the %s pin; keeping it"
                      % (name, below), file=sys.stderr)
                result = {}
            updates.update(result)
        except LookupFailed as e:
            reason = str(e)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            # Upstream returned something with an unexpected shape.
            reason = "unexpected upstream data: %r" % (e,)
        else:
            continue
        line = "%s: %s" % (name, " ".join(reason.split()))
        print("bump_versions: %s; its pins are unchanged" % line, file=sys.stderr)
        RESOLVER_FAILURES.append(line)
    # Releases skipped for their age go to stdout with the pin changes, which the scheduled
    # workflow puts in the pull request text. They never fail the run.
    for line in YOUNG_RELEASES:
        print("release age: %s" % line)
    bad = [why for why in (invalid(k, v) for k, v in sorted(updates.items())) if why]
    if bad:
        for why in bad:
            print("bump_versions: refusing to write %s" % why, file=sys.stderr)
        return 1
    for key, value in updates.items():
        if key.endswith("_VERSION") and key in old and old[key] != value:
            order = npm_version_key if key in npm_keys else version_key
            try:
                if order(strip_v(value)) < order(strip_v(old[key])):
                    raise ValueError("resolver would downgrade %s" % key)
            except ValueError as error:
                print("bump_versions: %s; pins unchanged" % error, file=sys.stderr)
                return 1
    for k in sorted(updates):
        if old.get(k) != updates[k]:
            print("%s: %s -> %s" % (k, old.get(k, "(new)"), updates[k]))
    for extra in EXTRA_FILES.regenerated:
        print("extras %s: lockfile regenerated" % extra)
    # versions.env goes last, so an interrupted run never pins a version whose catalog files are missing.
    for rel, text in sorted(EXTRA_FILES.files.items()):
        write_atomic(os.path.join(base, rel), text)
    # The Kubernetes example must use the same image references as versions.env.
    for key, _, _, rel in K8S_IMAGES:
        path = os.path.join(base, rel)
        if key in updates and os.path.exists(path):
            with open(path) as f:
                text = f.read()
            write_atomic(path, rewrite_image_ref(text, updates[key]))
    # The launcher, the Kubernetes example and the docs default to the pinned release.
    release_old = old.get("AGENTAINER_RELEASE_VERSION")
    release_new = updates.get("AGENTAINER_RELEASE_VERSION")
    if release_old and release_new and release_old != release_new:
        for rel in sorted({rel for rel, _ in RELEASE_REFS}):
            path = os.path.join(base, rel)
            if not os.path.exists(path):
                continue
            with open(path) as f:
                text = f.read()
            for prefix in (p for r, p in RELEASE_REFS if r == rel):
                text = rewrite_release_ref(text, prefix, release_old, release_new)
            write_atomic(path, text)
    write_atomic(args.file, render_env(lines, updates))
    # With --failures, the workflow fails the run on that file after the pull request opens.
    return 1 if RESOLVER_FAILURES and not args.failures else 0


if __name__ == "__main__":
    sys.exit(main())
