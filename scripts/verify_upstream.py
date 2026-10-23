#!/usr/bin/env python3
"""Verify supported publishers before accepting their release checksums."""
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile

ISSUER = "https://token.actions.githubusercontent.com"
# Identities match the verified certificates and official release workflows.
# https://cli.github.com/manual/gh_attestation_verify
ATTESTATIONS = {
    "cli/cli": ("deployment.yml", "refs/heads/trunk"),
    "astral-sh/uv": ("release.yml", "refs/heads/main"),
    "astral-sh/ruff": ("release.yml", "refs/heads/main"),
    "golangci/golangci-lint": ("release.yml", None),
}
# These workflows sign the checksum file, binding each selected binary's hash.
# https://github.com/mikefarah/yq/blob/master/.github/workflows/release.yml
# https://github.com/aquasecurity/trivy/blob/main/.github/workflows/reusable-release.yaml
CHECKSUM_BUNDLES = {
    "mikefarah/yq": ("checksums-bsd", ".bundle", "release.yml"),
    "aquasecurity/trivy": ("trivy_{version}_checksums.txt", ".sigstore.json", "reusable-release.yaml"),
}


class VerificationFailed(Exception):
    pass


def asset_url(release, name):
    matches = [a for a in release.get("assets", []) if a["name"] == name]
    if len(matches) != 1:
        raise VerificationFailed("missing or ambiguous publisher verification asset: " + name)
    return matches[0]["browser_download_url"]


def verify_asset(repo, release, name, expected, fetch_bytes):
    """True for verified publishers, False when no verification policy is defined."""
    if repo not in ATTESTATIONS and repo not in CHECKSUM_BUNDLES and repo != "openai/codex":
        return False
    tag = release["tag_name"]
    with tempfile.TemporaryDirectory(prefix="agentainer-publisher-") as directory:
        root = Path(directory)
        artifact = root / "artifact"
        if repo in CHECKSUM_BUNDLES:
            sums, suffix, workflow = CHECKSUM_BUNDLES[repo]
            sums = sums.format(version=tag.removeprefix("v"))
            data = fetch_bytes(asset_url(release, sums))
            hashes = set()
            for line in data.decode("utf-8").splitlines():
                gnu = re.fullmatch(r"([0-9a-f]{64})\s+\*?" + re.escape(name), line)
                bsd = re.fullmatch(r"SHA256 \(" + re.escape(name) + r"\) = ([0-9a-f]{64})", line)
                if gnu or bsd:
                    hashes.add((gnu or bsd)[1])
            if hashes != {expected}:
                raise VerificationFailed("signed checksum does not match the selected pin: " + name)
            artifact.write_bytes(data)
            bundle = root / "bundle"
            bundle.write_bytes(fetch_bytes(asset_url(release, sums + suffix)))
        else:
            data = fetch_bytes(asset_url(release, name))
            if hashlib.sha256(data).hexdigest() != expected:
                raise VerificationFailed("publisher verification download changed: " + name)
            artifact.write_bytes(data)

        if repo in ATTESTATIONS:
            workflow, ref = ATTESTATIONS[repo]
            ref = ref or "refs/tags/" + tag
            identity = "https://github.com/%s/.github/workflows/%s@%s" % (repo, workflow, ref)
            command = ["gh", "attestation", "verify", str(artifact), "--repo", repo,
                       "--cert-identity", identity, "--cert-oidc-issuer", ISSUER,
                       "--source-ref", ref]
        else:
            if repo == "openai/codex":
                # https://github.com/openai/codex/blob/main/.github/actions/linux-code-sign/action.yml
                workflow = "rust-release.yml"
                bundle = root / "bundle"
                bundle.write_bytes(fetch_bytes(asset_url(release, name + ".sigstore")))
            identity = "https://github.com/%s/.github/workflows/%s@refs/tags/%s" % (repo, workflow, tag)
            command = ["cosign", "verify-blob", "--bundle", str(bundle),
                       "--certificate-identity", identity, "--certificate-oidc-issuer", ISSUER,
                       str(artifact)]
        try:
            subprocess.run(command, check=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as error:
            raise VerificationFailed("%s publisher verification failed: %s" % (repo, error)) from error
    return True
