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
| 61 | LAUNCH-8 | Documented that successful updates leave replacements running, including previously stopped containers. |
| 62 | LAUNCH-9 | Trace quotes embedded single quotes; dry-run behavior and read-only inspections are documented. |
| 63 | RT-10 | Built a fresh temporary image from the current runtime source and validated its launcher lifecycle; the stale development image is unchanged. |
| 64 | RT-6 | Python helpers are isolated with entry 10; persisted-library detection includes python/lib. |
| 65 | RT-8 | Documented secret retention in Vim recovery files. Changing recovery defaults is deferred. |
| 66 | RT-9 | Version stamps publish through unique temporary files and atomic rename, with a concurrent-reader regression. |
| 67 | RT-ESCAPE-3 | Preserved the positive launcher posture and runtime-specific UID qualifications. |
| 68 | TEST-1 | The complete fresh-image container suite passed all 272 checks, including the updated passthrough default and Python startup isolation. |
| 69 | TEST-10 | Included the seeded POSIX profile in shellcheck and shfmt. A Python linter remains an optional policy decision. |
| 70 | TEST-11 | Reset conflict fixtures before independent checks and clarified doctor-overlay prerequisites. |
| 71 | TEST-12 | Added a manual read-only workflow for networked optional-tooling checks on both architectures. Its live GitHub execution is not verified. |
| 72 | TEST-7 | Shared helpers and direct MCP/lint runs refuse registry pulls for missing test images. |
| 73 | TEST-8 | Doctor/infrastructure fixtures use explicit failures that survive Python optimization. |
| 74 | TEST-9 | Added real Codex model-override and command-error coverage, strengthened reset content checks, corrected the instruction-settings test name, and made down refuse unrelated containers. |
| 75 | rt-host-6 | Documented stored env values, engine access, container recreation and leftover backup handling. |
| 76 | rt-k8s-2 | Stated that DNS and TCP 443 permit all destinations. Deployment-specific restrictions are deferred until their addresses and CNI behavior are verified. |
| 77 | rt-supply-5 | Documented automatic Go toolchains and advisory update locks. Changing Go's default selection policy is deferred. |

## Decisions left open

- Whether the generic egress example should require deployment-specific destination allowlists.
- Whether Go should default to the bundled compiler even for projects requiring a newer toolchain.

- Whether to disable Vim recovery files by default, trading recovery for reduced content retention.
- Whether to adopt a Python lint policy and which tool to use.

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

| Check | Result |
|---|---|
| Complete native arm64 container suite | 272 passed, zero failures, using a fresh temporary image. |
| Host Python unit suite | 305 tests passed, 31 platform-dependent skips. |
| Linux-specific unit modules | Passed on the image Python, including doctor, seeding, concurrency, reset, startup paths and atomic stamps. |
| Host launcher tests | 75 passed. |
| Real launcher lifecycle | 18 passed. |
| Build script tests | 12 passed. |
| Fetch tests | 65 passed. |
| Manifest tests | 49 passed. |
| Shellcheck and shfmt | Passed, including the POSIX profile. |
| Local actionlint 1.7.11 | Passed all workflow files. |
| Independent pinned Trivy secret scan | Passed on the exported fresh image, exit 0. |
| Missing-image checks | Exit 1 as expected, zero passing checks. The added Python-isolation test also fails without an image. |
| Python isolation runtime regression | Fails on the old image; passes on the fixed image while preserving intentional user Python startup. |

The first complete container run had one stale expectation for passthrough-on. After updating that expectation, the complete suite passed. The initial sandboxed unit run could not create local sockets; unit runs with loopback sockets allowed passed.

No Kubernetes deployment, GitHub policy change, release publication, full cross-architecture build, slow custom-UID build or BuildKit layer reproducibility run was performed. The optional network-install workflow has not been executed in GitHub Actions. These are separate from the local validations above.

Sources for the implementation contracts: [checkout ref selection](https://github.com/actions/checkout#usage), [Python isolation](https://docs.python.org/3/using/cmdline.html#cmdoption-I), [socket shutdown](https://docs.python.org/3/library/socket.html#socket.socket.shutdown), and the linked security and release documentation.
