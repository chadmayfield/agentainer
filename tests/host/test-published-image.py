#!/usr/bin/env python3
"""Read-only checks of a released index, platform signatures and attached attestations.

CLI flags: https://docs.sigstore.dev/quickstart/quickstart-ci/
Attestation descriptors: https://docs.docker.com/build/metadata/attestations/attestation-storage/
Inspect flags: https://docs.docker.com/reference/cli/docker/buildx/imagetools/inspect/
"""
import json
import re
import subprocess
import sys


def run(argv):
    return subprocess.check_output(argv, text=True)


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", value):
        raise ValueError("invalid registry digest")
    return value


def verify(image, tag, identity, issuer):
    descriptor = json.loads(run(["docker", "buildx", "imagetools", "inspect", image + ":" + tag,
                                 "--format", "{{json .Manifest}}"] ))
    ref = image + "@" + digest(descriptor["digest"])
    index = json.loads(run(["docker", "buildx", "imagetools", "inspect", "--raw", ref]))

    def signature(target):
        run(["cosign", "verify", target, "--certificate-identity", identity,
             "--certificate-oidc-issuer", issuer])

    signature(ref)
    for arch in ("amd64", "arm64"):
        manifests = [m for m in index["manifests"] if m.get("platform", {}).get("os") == "linux"
                     and m.get("platform", {}).get("architecture") == arch]
        if len(manifests) != 1:
            raise ValueError("expected one runnable manifest for " + arch)
        child = digest(manifests[0]["digest"])
        signature(image + "@" + child)
        attached = [m for m in index["manifests"] if
                    m.get("annotations", {}).get("vnd.docker.reference.type") == "attestation-manifest"
                    and m.get("annotations", {}).get("vnd.docker.reference.digest") == child]
        predicates = set()
        for attestation in attached:
            doc = json.loads(run(["docker", "buildx", "imagetools", "inspect", "--raw",
                                  image + "@" + digest(attestation["digest"])]))
            predicates.update(layer.get("annotations", {}).get("in-toto.io/predicate-type", "")
                              for layer in doc.get("layers", [])
                              if layer.get("mediaType") == "application/vnd.in-toto+json")
        if "https://spdx.dev/Document" not in predicates:
            raise ValueError("missing SBOM attestation for " + arch)
        if not any(p.startswith("https://slsa.dev/provenance/") for p in predicates):
            raise ValueError("missing provenance attestation for " + arch)
    return ref


def main():
    if len(sys.argv) != 5:
        raise SystemExit("usage: test-published-image.py IMAGE TAG CERTIFICATE_IDENTITY OIDC_ISSUER")
    ref = verify(*sys.argv[1:])
    # Pin the pull and smoke test to the verified index, not a mutable public tag.
    subprocess.run(["docker", "pull", ref], check=True)
    subprocess.run(["docker", "run", "--rm", "--name", "cx-release-smoke", "--network", "none", ref,
                    "sh", "-ec", "id; claude --version; codex --version; agy --version; opencode --version"], check=True)
    print("Published index, both platform signatures, SBOM/provenance descriptors and native startup verified")


if __name__ == "__main__":
    main()
