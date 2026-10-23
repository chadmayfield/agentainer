# Agent session monitoring

The image includes [abtop](https://github.com/graykode/abtop) as a manually launched terminal monitor. The build installs upstream Linux amd64 and arm64 binaries after checking the published SHA-256. Its version and checksums live in [`versions.env`](../versions.env), and the scheduled updater resolves both architectures from [upstream releases](https://github.com/graykode/abtop/releases).

Run inside the container, in a separate terminal or tmux window:

```sh
abtop
```

Upstream documents session, token, process and port monitoring for Claude Code, Codex and OpenCode. Antigravity is not listed. OpenCode monitoring requires `sqlite3`, which the image already includes. Detection and token accuracy for Agentainer's pinned agents remain not verified. Running inside a container limits process visibility to that container's PID namespace; this is not a host-wide dashboard. See [supported agents](https://github.com/graykode/abtop#supported-agents).

## Model calls and controls

The normal TUI and `abtop --once` generate session titles through `claude --print`, using initial prompt and assistant-response excerpts. Those calls can consume Claude quota. A supported switch to disable this in the TUI has not been verified. Installing abtop does not start the monitor. Agentainer does not run `abtop --setup`, install its rate-limit hook or replace an existing status line. See the release's [summary implementation](https://github.com/graykode/abtop/blob/v0.5.5/src/app.rs#L462) and [CLI implementation](https://github.com/graykode/abtop/blob/v0.5.5/src/lib.rs#L138).

For a one-shot snapshot that skips model-generated summaries:

```sh
abtop --json
```

The JSON mode uses `tick_no_summaries`, as shown in the [CLI source](https://github.com/graykode/abtop/blob/v0.5.5/src/lib.rs#L138). Its output can contain transcript-derived text and project paths. Keep it out of public logs. This mode avoids the summary calls; it does not establish complete agent discovery or accurate quota reporting.

The TUI can terminate processes. `x` targets the selected session, and `X` targets orphan ports. Press `q` to quit and `t` to cycle themes. Theme selection persists in `~/.config/abtop/config.toml` on the home volume. See [upstream key bindings](https://github.com/graykode/abtop#key-bindings) and [configuration](https://github.com/graykode/abtop#configuration).

## Verification

The offline container test checks the installed version, parses live and demo JSON snapshots, and checks that those runs do not create Claude settings. It does not invoke authenticated agents or measure token accuracy, rate-limit collection, interactive controls or cross-agent discovery. Those remain not verified.
