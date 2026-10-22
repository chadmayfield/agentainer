# Maintenance review

This table tracks the 77 entries reviewed at commit `b87d7b5`. Duplicate entries share a fix. A deferred entry needs a maintainer decision or further evidence.

| Entry | Finding | Disposition |
|---|---|---|
| 1 | rt-host-1 | Documented verified host-loopback reachability. An online network configuration that blocks host access is deferred until tested on supported runtimes. |
| 2 | rt-host-2 | Documented host execution through writable project configuration and programs. |
| 3 | rt-supply-1 | Release authorization checks out main. Tag rulesets and protected environments remain repository-setting decisions. |
| 4 | DC-1 | Added an absolute request deadline for headers and body, with trickle regressions. |
| 5 | DC-2 | Corrected release examples and required explicit prerelease selection before installation. The documented stable-only latest default remains unchanged. |
| 6 | DC-3 | Same code fix and settings decision as entry 3. |
| 7 | DOC-1 | Quick start selects the published prerelease. Raw and Kubernetes instructions explain the missing latest tag. |
| 8 | LAUNCH-1 | Reject option-like names and extra positional arguments before invoking the engine. |
| 9 | RT-1 | Reject incomplete, reversed or duplicated managed markers without modifying user TOML. |
| 10 | RT-ESCAPE-1 | Image-owned Python commands and the startup version helper use isolated Python. |

| 11 | rt-host-3 | Arbitrary tmux pane passthrough is disabled; opt-in and terminal risks are documented. |
| 12 | BUILD-1 | Resolver redirects require HTTPS and drop authorization across origins. |
| 13 | BUILD-2 | Claude manifest citation refers to the version pin rather than a stale literal. |
| 14 | BUILD-4 | Downgrades are refused before writing any pins. Major-line restrictions remain a policy decision. |
| 15 | BUILD-5 | Deferred. No incompatible base/snapshot pair has been reproduced. |
| 16 | DC-4 | Documented default queue cancellation and reruns. Local actionlint 1.7.11 rejects queue: max; pinned 1.7.12 support is not verified. |
| 17 | DOC-2 | Corrected with entry 5. |
| 18 | DOC-3 | Documented signing access through forwarded SSH agents. |
| 19 | DOC-4 | Clarified that server-side TLS requires additional implementation. |
| 20 | DOC-5 | Added the explicit Codex API-key login step to the env example. |

| 21 | DOC-7 | Documented host paths versus volume names and relative directory syntax. |
| 22 | LAUNCH-2 | Warn for group/other write access as well as read access. |
| 23 | LAUNCH-4 | Warn when mounts expose host home, its parents, or host root; retain the documented current-directory default. |
| 24 | LAUNCH-5 | Validate names and the 64-byte hostname limit before creation. |
| 25 | LAUNCH-7 | Resolve dot and dot-dot home sources on the client. |
| 26 | RT-2 | Skip seeding with a warning when its lock cannot open; warn on optional ledger/stamp failures. |
| 27 | RT-3 | Preserve dangling service configuration symlinks. |
| 28 | RT-4 | Atomically restrict config permissions when syncing literal environment or header values. |
| 29 | RT-5 | Clarified raw-image sudo behavior. A different sudo architecture is deferred. |
| 30 | RT-7 | Documented sync coordination limits. Lost writes by live agents are not verified. |

| 31 | RT-ESCAPE-2 | Shared-home shell and sudo trust is documented with entry 1. |
| 32 | TEST-2 | Positional argument regressions cover the fix from entry 8. |
| 33 | TEST-3 | Status derives its effective mode from the active root; tests assert the root. |
| 34 | TEST-4 | Readiness uses a versioned capability file, with current/legacy protocol tests. |
| 35 | TEST-5 | Sudo restrictions run in the local container suite; the group assertion describes groups only. |
| 36 | TEST-6 | Added a container runner for modules skipped on macOS and listed it in contributor commands. |
| 37 | rt-host-4 | Documented literal env-file syntax and bare-name imports. |
| 38 | rt-host-5 | MCP example uses the verified published package version 2.0.0 and explains code execution. |
| 39 | rt-k8s-1 | Key-file decoding tolerates non-UTF-8 comments. |
| 40 | rt-supply-2 | Documented pre-review execution and the absence of an age delay. Release-age and publisher-verification policy is deferred. |

| 41 | rt-supply-3 | Candidate and pushed-digest secret scans use an independent pinned scanner; removed implicit secret-rule overrides. |
| 42 | rt-supply-4 | Documented consumer verification with the existing verifier and subsequent digest-pinned launch. |
| 43 | BUILD-10 | Both build-ignore files exclude runtime env and host-key paths. |
| 44 | BUILD-11 | Documented the intentional initial agent-owned shell seed exception. |
| 45 | BUILD-3 | Bootstrap CA bundle uses a temporary stage bind mount instead of a final image COPY. |
| 46 | BUILD-6 | Published GNU/BSD/per-asset SHA-256 files are checked against GitHub digests when available. Additional signature mechanisms remain deferred. |
| 47 | BUILD-7 | Cited the official Antigravity installer beside its manifest endpoint. |
| 48 | BUILD-8 | Made the timestamp guarantee conditional on builder support. |
| 49 | BUILD-9 | Same documented sudo policy and deferred architecture decision as entry 29. |
| 50 | DC-5 | Disabled checkout credential persistence in build jobs. The bump resolve job already disables it; push jobs retain it intentionally. |

| 51 | DC-6 | Corrected the attest action comment to the verified exact version. |
| 52 | DC-7 | Deferred. Branch review and administrator policies require a maintainer decision; no repository settings changed. |
| 53 | DC-8 | Added startup/readiness probes with legacy-image fallback. Liveness responsiveness and recovery remain a separate decision. |
| 54 | DOC-10 | Listed optional networked, health, release and visual checks in contributor instructions. |
| 55 | DOC-6 | Corrected reset/status descriptions and included Python executable entries in status. |
| 56 | DOC-8 | Marked current-source additions as absent from the published prerelease. No release was published. |
| 57 | DOC-9 | Independent scanning is implemented and documented with entry 41. |
| 58 | LAUNCH-10 | Warn for an explicitly supplied missing or nonregular env file. |
| 59 | LAUNCH-3 | Runnable prerelease selection and latest limits are covered with entry 7. |
| 60 | LAUNCH-6 | Suppressed cd output when resolving workspace paths under dash. |

## Decisions left open

- Which branch review, administrator enforcement and Actions approval settings to require.
- What agent responsiveness a Kubernetes liveness probe should measure, and whether restart can recover it.

- Whether to impose a release-age delay, how long it should be, and which publisher signatures should be required.

- Whether to change the documented passwordless-sudo architecture.
- Whether to require isolated config roots for simultaneously running agents. A lost-update incident is not verified.

- Whether to restrict major-version updates in addition to refusing downgrades.
- Whether to change snapshot selection after reproducing a base/snapshot mismatch.
- Whether to upgrade actionlint and enable a larger release queue after verifying the pinned version.

- Whether to configure release-tag restrictions and protected publication environments in GitHub.
- Whether to replace the stable-only latest defaults before the first stable release.
- Which online networking configuration should block host-service access on each supported runtime. This configuration is not verified.

## Validation

Regression tests cover launcher argument rejection, malformed MCP markers, isolated Python, release authorization source selection, and slow webhook headers and bodies. Tests against the original source reproduce their failures. Shell lint and existing launcher tests run for this batch.

Sources for the implementation contracts: [checkout ref selection](https://github.com/actions/checkout#usage), [Python isolation](https://docs.python.org/3/using/cmdline.html#cmdoption-I), [socket shutdown](https://docs.python.org/3/library/socket.html#socket.socket.shutdown), and the linked security and release documentation.
