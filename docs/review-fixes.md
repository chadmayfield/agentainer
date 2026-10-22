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

## Decisions left open

- Whether to restrict major-version updates in addition to refusing downgrades.
- Whether to change snapshot selection after reproducing a base/snapshot mismatch.
- Whether to upgrade actionlint and enable a larger release queue after verifying the pinned version.

- Whether to configure release-tag restrictions and protected publication environments in GitHub.
- Whether to replace the stable-only latest defaults before the first stable release.
- Which online networking configuration should block host-service access on each supported runtime. This configuration is not verified.

## Validation

Regression tests cover launcher argument rejection, malformed MCP markers, isolated Python, release authorization source selection, and slow webhook headers and bodies. Tests against the original source reproduce their failures. Shell lint and existing launcher tests run for this batch.

Sources for the implementation contracts: [checkout ref selection](https://github.com/actions/checkout#usage), [Python isolation](https://docs.python.org/3/using/cmdline.html#cmdoption-I), [socket shutdown](https://docs.python.org/3/library/socket.html#socket.socket.shutdown), and the linked security and release documentation.
