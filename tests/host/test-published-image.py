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


def verify(image, tag, identity, issuer, repository, commit, source_ref):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("invalid expected source commit")
    if tag.startswith("sha256:"):
        ref = image + "@" + digest(tag)
    else:
        descriptor = json.loads(run(["docker", "buildx", "imagetools", "inspect", image + ":" + tag,
                                     "--format", "{{json .Manifest}}"] ))
        ref = image + "@" + digest(descriptor["digest"])
    index = json.loads(run(["docker", "buildx", "imagetools", "inspect", "--raw", ref]))

    def signature(target):
        run(["cosign", "verify", target, "--certificate-identity", identity,
             "--certificate-oidc-issuer", issuer])

    signature(ref)
    run(["gh", "attestation", "verify", "oci://" + ref, "--repo", repository,
         "--cert-identity", identity, "--cert-oidc-issuer", issuer,
         "--source-digest", commit, "--source-ref", source_ref, "--deny-self-hosted-runners"])
    provenance = json.loads(run(["docker", "buildx", "imagetools", "inspect", ref,
                                 "--format", "{{json .Provenance}}"] ))
    if not isinstance(provenance, dict):
        raise ValueError("missing provenance payload")
    for arch in ("amd64", "arm64"):
        manifests = [m for m in index["manifests"] if m.get("platform", {}).get("os") == "linux"
                     and m.get("platform", {}).get("architecture") == arch]
        if len(manifests) != 1:
            raise ValueError("expected one runnable manifest for " + arch)
        platforms = [value for platform, value in provenance.items()
                     if platform == "linux/" + arch or (arch == "arm64" and platform == "linux/arm64/v8")]
        if len(platforms) != 1:
            raise ValueError("missing or ambiguous provenance payload for " + arch)
        predicate = platforms[0].get("SLSA", {})
        vcs = predicate.get("metadata", {}).get("https://mobyproject.org/buildkit@v1#metadata", {}).get("vcs", {})
        sources = {"https://github.com/" + repository, "https://github.com/" + repository + ".git"}
        if (predicate.get("buildType") != "https://mobyproject.org/buildkit@v1"
                or vcs.get("source") not in sources or vcs.get("revision") != commit):
            raise ValueError("provenance source repository or commit differs for " + arch)
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
    if len(sys.argv) != 8:
        raise SystemExit("usage: test-published-image.py IMAGE TAG_OR_DIGEST CERTIFICATE_IDENTITY OIDC_ISSUER REPOSITORY COMMIT REF")
    ref = verify(*sys.argv[1:])
    # Pin the pull and smoke test to the verified index, not a mutable public tag.
    subprocess.run(["docker", "pull", ref], check=True)
    subprocess.run(["docker", "run", "--rm", "--name", "cx-release-smoke", "--network", "none", ref,
                    "sh", "-ec", "id; claude --version; codex --version; agy --version; opencode --version"], check=True)
    print("Published index, both platform signatures, GitHub and BuildKit provenance, SBOM descriptors and native startup verified")


if __name__ == "__main__":
    main()
