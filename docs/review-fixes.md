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

## Decisions left open

- Whether to configure release-tag restrictions and protected publication environments in GitHub.
- Whether to replace the stable-only latest defaults before the first stable release.
- Which online networking configuration should block host-service access on each supported runtime. This configuration is not verified.

## Validation

Regression tests cover launcher argument rejection, malformed MCP markers, isolated Python, release authorization source selection, and slow webhook headers and bodies. Tests against the original source reproduce their failures. Shell lint and existing launcher tests run for this batch.

Sources for the implementation contracts: [checkout ref selection](https://github.com/actions/checkout#usage), [Python isolation](https://docs.python.org/3/using/cmdline.html#cmdoption-I), [socket shutdown](https://docs.python.org/3/library/socket.html#socket.socket.shutdown), and the linked security and release documentation.
