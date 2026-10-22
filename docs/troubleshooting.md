# Troubleshooting

## Offline diagnostics

From the host, check the running container with:

```sh
bin/agentainer doctor
bin/agentainer doctor agentainer-test --json
```

N defaults to `agentainer`. Inside the container, run `agentainer-doctor` or `agentainer-doctor --json`. The image must include that command; updating only the host launcher does not add it to an older image.

The command reports `ok`, `warn` or `fail` for:

- The image's `/etc/agentainer/versions.json` inventory format.
- Home-directory read, write and search access, plus group/other write permissions.
- The tools mode, active symlink target and tool-root write access.
- Syntax of the five seeded agent settings files listed in [default configuration](defaults.md#agent-configurations).
- Shared MCP input validation, ownership metadata, interrupted writes and the last successful input-hash stamp. An active sync produces a warning instead of reading partially updated state.
- Version-command execution for the four agents and the core tools listed in [`agentainer-doctor`](../rootfs/usr/local/bin/agentainer-doctor).

Settings checks respect `CLAUDE_CONFIG_DIR` ([Claude settings](https://code.claude.com/docs/en/settings#find-or-create-your-settings-files)), `CODEX_HOME` ([Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference)) and `XDG_CONFIG_HOME` for OpenCode. The OpenCode path override was checked with the bundled CLI's `opencode debug paths`. Missing settings files and OpenCode JSONC files produce warnings; invalid JSON/TOML or unreadable files fail. This checks home settings syntax, not the full precedence of project, profile and managed settings.

Version probes run from a temporary directory with a temporary home and a restricted environment that excludes runtime credentials and personal configuration overrides. Each probe has a five-second timeout; its stdout and stderr are discarded. The report does not print configuration values, provider URLs, tool output or exception details. It does not rewrite settings, install tools, repair MCP state or make model requests.

Exit status is `0` when no check failed, `1` when any check failed, and `2` for invalid arguments. Warnings do not fail the command. JSON output contains an overall `status` and a `checks` array; each check has `name`, `status` and `message` fields.

Login validity, agent-specific setting semantics, model access, MCP server connectivity and live approval behavior are not verified by these offline checks. MCP status records the last successful sync input, not whether every server is available. Follow the relevant agent's own diagnostics when syntax checks pass but the agent still rejects a setting.

## Common problems

**The container reports `starting` or `unhealthy`.**
Inspect `.State.Health` as described in [container health](running.md#container-health). A new container can remain `starting` while its entrypoint runs. Failures report `startup incomplete`, `home permissions` or `tools directory unavailable`, without printing environment values. Check the container's startup logs and home mount permissions, then run `agentainer doctor` for broader checks. A repaired container becomes `healthy` on its next successful probe. This probe does not test agent authentication or network access.

An older image without a health check may show `starting` on Podman 5.3.2 with an empty `.Config.Healthcheck` object and no probe log. That empty configuration is not a running startup check. Podman initializes `starting` when a non-null health-check object exists ([Podman source](https://github.com/containers/podman/blob/v5.3.2/libpod/container_internal.go#L1291-L1300)).

In local verification, a Podman 6.0.1 macOS client with a 5.3.2 VM server also omitted the command when creating a container from an image that defined one. The matching 5.3.2 CLI inside the VM inherited and ran it. With that client/server pair, an explicit `--health-cmd=/usr/local/bin/agentainer-healthcheck` on a raw `podman run` supplied the missing command. Use this only with an image that includes the probe. The launcher does not add that override ([Podman health command option](https://docs.podman.io/en/v5.3.2/markdown/podman-run.1.html#health-cmd-command)).

**`sudo: The "no new privileges" flag is set, which prevents sudo from running as root.`**
sudo is off by default. Recreate the container with `bin/agentainer up --sudo`, or leave out `--security-opt no-new-privileges=true` from a raw `docker run` or `podman run` ([docs/running.md](running.md#sudo)).

**`ping: socket: Operation not permitted`**
The container was started without `--sysctl "net.ipv4.ping_group_range=1000 1000"`. The launcher and the Kubernetes example set it; add it to raw `run` commands.

**The container name `agentainer` is already in use**
A container with that name exists. If it is running, `bin/agentainer attach` connects to it. If it is stopped, `bin/agentainer start` starts it, and `bin/agentainer down` removes it. The home volume stays either way.

**`agentainer: ... no option labels`** when running `agentainer update`
The container was not created by `agentainer up`, so `update` does not know its options. Run `bin/agentainer down` and `bin/agentainer up` once.

**Files in `/workspace` belong to UID 1000 on a Linux host.**
That is rootful Docker with a host UID other than 1000. Build an image with your UID, or use Podman or rootless Docker ([docs/running.md](running.md#file-ownership)).

**An agent shows an old setting after an upgrade.**
The entrypoint adds the image's files only where your home volume has none, so new default settings in the image do not replace yours. Compare your files with the image's copies in `/etc/agentainer/home/` ([docs/running.md](running.md#upgrading)). A few files are exceptions, and the entrypoint changes only the part it manages in each: `~/.agentainer/AGENTS.md` while you have not edited it ([AGENTS.md](configuration.md#agentsmd)), the MCP servers that `agentainer-mcp sync` added ([MCP servers](configuration.md#mcp-servers)), the gh credential helper in `~/.gitconfig` when `GH_TOKEN` or `GITHUB_TOKEN` is set, the git identity when `GIT_AUTHOR_NAME` or `GIT_AUTHOR_EMAIL` is set and `~/.gitconfig` has none, and `~/.config/opencode/service.json` when it does not exist yet.

**`claude doctor` warns that `~/.local/bin` is not in `PATH` and says to run `claude install`.**
The image installs Claude Code at `/usr/local/bin/claude`, and a new image brings a new version. The warnings look for Anthropic's per-user install in `~/.local`, which the image does not use. Ignore them: `claude install` prints "Updates are disabled by your administrator" and changes nothing.

**`agentainer-mcp` warns that an agent "already has a server named ... that agentainer did not add".**
That agent's own config has a server with the same name, which the sync leaves alone. Rename one of them in `~/.agentainer/mcp.json` or in the agent.

**The tmux session does not start over SSH in Kubernetes: "open terminal failed: terminal does not support clear".**
tmux needs `TERM`. The webhook in `deploy/kubernetes` sets it; check that ContainerSSH uses that webhook's `/config` answer ([docs/kubernetes.md](kubernetes.md#logging-in)).
