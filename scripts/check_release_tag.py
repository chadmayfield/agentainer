#!/usr/bin/env python3
"""Require a signed annotated tag on a first-parent release merge in main.

Git verification: https://git-scm.com/docs/git-verify-tag
Public signing keys: https://docs.github.com/en/rest/users/gpg-keys
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/usr/local/lib/agentainer"))
from release_version import from_merge, version_key


def git(*args):
    return subprocess.check_output(["git", *args], text=True).strip()


def check(tag, sha, owner, fingerprint, public_key=None, signer=None):
    if not tag.startswith("v"):
        raise ValueError("release tag must start with v")
    value = tag[1:]
    version_key(value)
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("invalid release commit")
    if not re.fullmatch(r"[A-Z0-9-]+", owner, re.I):
        raise ValueError("invalid repository owner")
    if not re.fullmatch(r"(?:[0-9A-F]{40}|[0-9A-F]{64})", fingerprint):
        raise ValueError("RELEASE_SIGNING_FINGERPRINT must be a full uppercase fingerprint")
    ref = "refs/tags/" + tag
    if git("cat-file", "-t", ref) != "tag":
        raise ValueError("release requires an annotated GPG-signed tag")
    header = git("cat-file", "-p", ref).split("\n\n", 1)[0].splitlines()
    if not all(line in header for line in ("object " + sha, "type commit", "tag " + tag)):
        raise ValueError("tag name or target does not match the release event")
    if sha not in git("log", "--first-parent", "--format=%H", "origin/main").splitlines():
        raise ValueError("release commit is not on main's first-parent history")
    if len(git("log", "-1", "--format=%P", sha).split()) != 2:
        raise ValueError("release target must be a two-parent merge commit")
    if from_merge(git("log", "-1", "--format=%s", sha), owner) != value:
        raise ValueError("tag version does not match the release merge")
    if public_key is None:
        signer = signer or owner
        if not re.fullmatch(r"[A-Za-z0-9-]+", signer):
            raise ValueError("invalid GitHub signing account")
        keys = json.loads(subprocess.check_output(
            ["gh", "api", "--method", "GET", "users/" + signer + "/gpg_keys"], text=True))
        matches = [key["raw_key"] for key in keys if key.get("key_id") == fingerprint[-16:]]
        if len(matches) != 1:
            raise ValueError("trusted release key is not registered on the configured GitHub signing account")
        public_key = matches[0]
    with tempfile.TemporaryDirectory(prefix="cx-tag-keyring-") as home:
        env = dict(os.environ, GNUPGHOME=home)
        subprocess.run(["gpg", "--batch", "--import"], input=public_key, text=True,
                       env=env, check=True, capture_output=True)
        result = subprocess.run(["git", "-c", "gpg.format=openpgp", "-c", "gpg.program=gpg",
                                 "verify-tag", "--raw", ref], env=env, capture_output=True, text=True)
        statuses = [line.split()[1:] for line in result.stderr.splitlines() if line.startswith("[GNUPG:] ")]
        signers = [line[-1] for line in statuses if line[0] == "VALIDSIG"]
        bad = {"BADSIG", "ERRSIG", "EXPKEYSIG", "REVKEYSIG", "EXPSIG"}
        if result.returncode or signers != [fingerprint] or any(line[0] in bad for line in statuses):
            raise ValueError("tag is not a valid signature by the trusted release key")
    return value


def require_unpublished(repository, tag):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("invalid release repository")
    result = subprocess.run(["gh", "api", "--method", "GET", "--include",
                             "repos/" + repository + "/releases/tags/" + tag],
                            capture_output=True, text=True)
    if result.returncode == 0:
        raise ValueError("GitHub release already exists; publish a new version")
    if not re.match(r"HTTP/\S+ 404\b", result.stdout):
        raise ValueError("could not confirm that the release version is unpublished")


def main():
    try:
        value = check(os.environ["GITHUB_REF_NAME"], os.environ["SHA"], os.environ["OWNER"],
                      os.environ.get("RELEASE_SIGNING_FINGERPRINT", ""),
                      signer=os.environ.get("RELEASE_SIGNER"))
        require_unpublished(os.environ["REPOSITORY"], "v" + value)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print("release-tag: %s" % error, file=sys.stderr)
        return 1
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
