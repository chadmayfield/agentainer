# Optional agent tools and plugins

Run these commands inside Agentainer as the regular container user. Choose the plugins you want for each agent. The image does not install these optional plugins during its build or startup. Its existing built-in agent settings are described in [default configuration](defaults.md).

Keep the same persistent home when recreating the container to retain home-based plugin settings and files. Try plugins with a [separate test home](customization.md#image-upgrades-and-separate-test-homes) first. External dependencies and account connections may need separate setup; a persistent home does not preserve software installed elsewhere in the container.

## Contents

- [Recommended starting points](#recommended-starting-points)
- [Token and context tools](#token-and-context-tools)
- [Claude Code](#claude-code)
- [Codex](#codex)
- [OpenCode](#opencode)
- [Antigravity](#antigravity)
- [Verification limits](#verification-limits)

## Recommended starting points

For Codex, OpenCode and Antigravity, [Addy Osmani's agent-skills](https://github.com/addyosmani/agent-skills) provides these reusable workflows:

| Skill | Use |
|---|---|
| [code-simplification](https://github.com/addyosmani/agent-skills/tree/main/skills/code-simplification) | Reduce complexity while preserving behavior |
| [code-review-and-quality](https://github.com/addyosmani/agent-skills/tree/main/skills/code-review-and-quality) | Review correctness, readability, architecture, security and performance |
| [frontend-ui-engineering](https://github.com/addyosmani/agent-skills/tree/main/skills/frontend-ui-engineering) | Build responsive, accessible interfaces |
| [security-and-hardening](https://github.com/addyosmani/agent-skills/tree/main/skills/security-and-hardening) | Review trust boundaries, authentication, untrusted input and secrets |

Start with simplification and review. Add frontend and security workflows for the work you do. Google uses the review skill in its [Antigravity code-review tutorial](https://codelabs.developers.google.com/agy-cli-sdk-code-review?hl=en). These are community-maintained skills, not agent-vendor defaults.

[Superpowers](https://github.com/obra/superpowers) is an optional workflow package for all four agents. It adds planning, test-driven development, debugging and verification skills. It also directs agents to invoke skills at the start of work, so expect broader workflow changes than a single cleanup skill. Choose it separately from the focused skills above. Follow your project's instructions and approval requirements when a workflow proposes commits or other actions.

For more visual design guidance, [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill#installation) provides palettes, typography and design-system tools. Its installation guide supports Codex, OpenCode and Antigravity. Keep its scripts and data with the skill; copying only its instructions is insufficient.

## Token and context tools

These tools solve different problems. Start with one in a separate test home, measure the result, and keep the original command output available when checking a failure. Automatic hooks change what agents execute or see; installing a package does not prove that those hooks work with Agentainer's pinned agents.

| Tool | Purpose | Suggested use |
|---|---|---|
| [RTK](#rtk) | Filter command output before the model reads it | First trial for output-heavy builds and tests; enable each agent integration separately |
| [context-mode](#context-mode) | Execute analysis through MCP tools and search indexed content | Optional trial for large logs, research and long sessions |
| [Superpowers](#recommended-starting-points) | Planning, test-driven development, debugging and verification workflows | Choose for its development process; it is not a token compressor |
| [Context7](#context7) | Retrieve library documentation and examples | Optional documentation lookup through its CLI or hosted MCP server |

Do not enable all four across every agent as one setup step. RTK and context-mode can both intercept tools, while Superpowers changes the workflow. Check them independently before combining them. No token or billing savings from these tools have been measured in Agentainer.

### RTK

RTK filters shell-command output. Its [upstream guide](https://github.com/rtk-ai/rtk#how-savings-work) distinguishes reduced shell output from total input tokens or billing savings; its token counts are estimates. The current [editions](https://github.com/rtk-ai/rtk#what-you-install) include an Apache-2.0 `rtk-oss` build and a full build with additional licensed components. Start with the OSS edition for command filtering. Both editions install a binary named `rtk`; the API proxy is a separate component.

Use upstream release binaries, not the unrelated package with the same name on crates.io. The [installer source](https://github.com/rtk-ai/rtk/blob/master/install.sh) supports `RTK_EDITION=oss` and an exact `RTK_VERSION`, checks the published SHA-256, and installs under `~/.local/bin` by default. Replace `vX.Y.Z` with an actual reviewed [release tag](https://github.com/rtk-ai/rtk/releases) before running these commands inside the container:

```sh
installer=$(mktemp)
curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/refs/heads/master/install.sh -o "$installer"
less "$installer"
RTK_EDITION=oss RTK_VERSION=vX.Y.Z RTK_INSTALL_DIR="$HOME/.local/bin" sh "$installer"
rm -f "$installer"
export PATH="$PATH:$HOME/.local/bin"
rtk --version
rtk init --help
```

Review the downloaded installer before executing it. Installing the binary does not configure every agent. The upstream [agent table](https://github.com/rtk-ai/rtk#supported-ai-tools) documents these separate setup commands; choose only the integration you want:

| Agent | Upstream setup command |
|---|---|
| Claude Code | `rtk init -g` |
| Codex | `rtk init -g --codex` |
| OpenCode | `rtk init -g --opencode` |
| Antigravity CLI | `rtk init -g --agent antigravity` |

RTK's [agent table](https://github.com/rtk-ai/rtk#supported-ai-tools) describes Codex command rewriting through `updatedInput`, while context-mode's [Codex guide](https://github.com/mksglu/context-mode) describes deny-only `PreToolUse` routing. Those upstream descriptions disagree. Actual rewriting behavior with the pinned Codex is not verified.

Those integration commands have not been run against Agentainer's pinned agents. In particular, do not infer OpenCode V2 plugin compatibility from an upstream minimum version for older OpenCode. Inspect changes to existing hooks, settings and instructions before using the integration. Keep Agentainer's shared instructions and project `AGENTS.md` files. After restarting the chosen agent, check actual command interception and compare the result with the original output; `rtk gain` reports RTK's savings estimates. See the [installation guide](https://www.rtk-ai.app/docs/getting-started/installation/) for removal.

### context-mode

[context-mode](https://github.com/mksglu/context-mode) provides MCP execution and indexing tools, plus client-specific routing hooks. It stores session and indexed content locally. Its current [license](https://github.com/mksglu/context-mode/blob/main/LICENSE) is Elastic License 2.0. Review its configuration and retention behavior before indexing sensitive files.

For an MCP-only trial, select a reviewed exact package version from [published npm metadata](https://registry.npmjs.org/context-mode). Replace `VERSION` below; do not run the placeholder literally:

```sh
npm install --global 'context-mode@VERSION'
context-mode doctor
```

Merge this server into the existing `mcpServers` object in `~/.agentainer/mcp.json`, preserving its other entries:

```json
{
  "mcpServers": {
    "context-mode": {"command": "context-mode"}
  }
}
```

Stop agents that write their config files, then run `agentainer-mcp sync` as described in [MCP synchronization](configuration.md#mcp-servers). MCP-only registration exposes tools; it does not install routing hooks or establish session-continuity behavior. Use the [upstream installation guide](https://github.com/mksglu/context-mode) for the chosen client's full plugin setup, restart requirements and diagnostics. Do not copy its example instructions over an existing project or shared `AGENTS.md`.

Codex's upstream setup includes hook feature flags and hook trust, and the Antigravity CLI setup differs from the Antigravity desktop IDE. These integrations, their permission behavior and their interaction with RTK are not verified in Agentainer. Confirm the tools are callable and the chosen hooks actually fire before relying on them. The existing OpenCode discovery limitations below still apply. Uninstalling the npm package alone does not describe how to remove client-specific plugin configuration; use the matching upstream removal instructions.

### Context7

[Context7](https://github.com/upstash/context7) retrieves library documentation and code examples. It is a documentation service, not a general command-output compressor. Its hosted MCP server avoids installing a local MCP server package. Queries go to the hosted service, so use public library names, versions and focused documentation questions rather than secrets.

For the upstream setup flow, select an exact reviewed `ctx7` version from [published npm metadata](https://registry.npmjs.org/ctx7) and replace `VERSION`:

```sh
npx 'ctx7@VERSION' setup
```

The [setup guide](https://github.com/upstash/context7#installation) documents the Node.js requirement, OAuth flow and choice between CLI skills and MCP. To use Agentainer's shared MCP configuration instead, merge the following entry into its existing `mcpServers` object and provide `CONTEXT7_API_KEY` through the runtime env file:

```json
{
  "mcpServers": {
    "context7": {
      "url": "https://mcp.context7.com/mcp",
      "headers": {"Authorization": "Bearer ${CONTEXT7_API_KEY}"}
    }
  }
}
```

This endpoint and bearer-header format come from the [upstream client guide](https://github.com/upstash/context7/blob/master/docs/resources/all-clients.mdx). Follow [MCP synchronization](configuration.md#mcp-servers) before running `agentainer-mcp sync`. Antigravity does not receive headers containing environment references through that sync; configure authentication for it using its native client instructions. OpenCode discovery remains not verified. Do not assume that a shared entry establishes authentication in every agent.

After restarting the client, verify that `resolve-library-id` and `query-docs` are available and complete a public-library lookup. Request documentation for the project's actual version and check the original source when accuracy matters. Authenticated use, coverage of particular libraries and cost effects have not been verified here. Remove generated setup with the matching `ctx7` CLI's `remove` command, or remove the manually managed server entry and re-sync. See the upstream [CLI guide](https://context7.com/docs/clients/cli) for the selected version's options.

## Claude Code

These plugins are available through Anthropic's official marketplace. Superpowers is maintained by its own project:

| Plugin | Purpose |
|---|---|
| [code-simplifier](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/code-simplifier) | Simplify code while preserving its behavior |
| [frontend-design](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/frontend-design) | Help implement web interfaces |
| [security-guidance](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/security-guidance) | Add security checks through hooks and reviews; can make additional model calls |
| [Superpowers](https://github.com/obra/superpowers#claude-code) | Planning, test-driven development, debugging and verification workflows |

Check registered marketplaces:

```sh
claude plugin marketplace list
```

If `claude-plugins-official` is missing, add it:

```sh
claude plugin marketplace add anthropics/claude-plugins-official
```

Choose either installation independently. User scope applies to your home across projects:

```sh
claude plugin install code-simplifier@claude-plugins-official --scope user
```

```sh
claude plugin install frontend-design@claude-plugins-official --scope user
```

Choose Superpowers if you want its broader development workflow. The [project's Claude installation guide](https://github.com/obra/superpowers#claude-code) lists the official marketplace installation:

```sh
claude plugin install superpowers@claude-plugins-official --scope user
```

Install security guidance separately if you want its hooks and reviews:

```sh
claude plugin install security-guidance@claude-plugins-official --scope user
```

List installed plugins, then start a new Claude session to load them:

```sh
claude plugin list
```

For example, disable or uninstall code-simplifier with:

```sh
claude plugin disable code-simplifier@claude-plugins-official --scope user
claude plugin uninstall code-simplifier@claude-plugins-official --scope user
```

See [Claude's installation and scope documentation](https://code.claude.com/docs/en/discover-plugins). Avoid project scope when the choice should apply only to you.

The bundled Claude installer rewrote the seeded permission mode from `manual` to `default` during the installation check. It retained the other seeded display and shared-instruction settings. Inspect your settings after installation; plugin management can normalize existing settings as well as add plugin entries. Actual tool-approval behavior was not tested.

## Codex

Browse configured marketplaces and their available plugins:

```sh
codex plugin marketplace list
codex plugin list --available --json
```

Select a plugin from that output. Replace `PLUGIN` and `MARKETPLACE` below with its actual names; they are placeholders:

```sh
codex plugin add 'PLUGIN@MARKETPLACE'
codex plugin list
```

Remove that installation with:

```sh
codex plugin remove 'PLUGIN@MARKETPLACE'
```

To install the full Addy Osmani skills pack, follow its [Codex installation guide](https://github.com/addyosmani/agent-skills#quick-start):

```sh
codex plugin marketplace add addyosmani/agent-skills
codex plugin add agent-skills@agent-skills
```

This installs the pack, including workflows beyond the four starting skills. The project's [Codex setup guide](https://github.com/addyosmani/agent-skills/blob/main/docs/codex-setup.md) explains skill invocation and discovery. Do not paste its meta-skill into your shared instructions; Codex discovers the installed skills on demand.

For Superpowers, open `/plugins` in Codex, search for `Superpowers`, and select its installation option ([project guide](https://github.com/obra/superpowers#codex-cli)). For dedicated security scans, the official [Codex Security guide](https://learn.chatgpt.com/docs/security/plugin) documents the same browser flow for `Codex Security`. Start a new session after installation.

Agentainer does not enable these recommendations automatically. See the [official Codex CLI plugin reference](https://learn.chatgpt.com/docs/cli/reference#codex-plugin) for supported sources and marketplace management.

## OpenCode

Runtime discovery is not verified with the pinned OpenCode. In a disposable-container check, `plugin add` wrote the expected `plugins` entry and `plugin remove` removed it, but `plugin list` and the native plugin API returned empty lists. The skill API also returned an empty list after copying the four recommended skills and their shared references. An installation success message alone does not prove that OpenCode loaded them.

List installed package plugins:

```sh
opencode plugin list
```

Choose a package after reviewing its publisher, source and required configuration. Replace `PACKAGE@VERSION` with the package's actual name and an exact published version:

```sh
opencode plugin add 'PACKAGE@VERSION'
opencode plugin list
```

The installer adds a global package plugin. Remove it using the same configured package specifier:

```sh
opencode plugin remove 'PACKAGE@VERSION'
```

OpenCode also supports local plugin files and directories. Its configuration key is `plugins`, plural. See the [OpenCode plugin documentation](https://opencode.ai/v2/docs/plugins) for package sources, configuration and reload behavior.

Keep Agentainer's existing `~/.config/opencode/opencode.json` when editing configuration. Adding `opencode.jsonc` prevents Agentainer's MCP sync from updating OpenCode; see [MCP synchronization](configuration.md#mcp-servers).

For the focused starting skills, follow the [agent-skills OpenCode setup guide](https://github.com/addyosmani/agent-skills/blob/main/docs/opencode-setup.md). Select the desired skill directories and retain their shared references. The guide notes that individual skill installs can omit required pack-level references. Do not replace your project's `AGENTS.md` with the upstream repository's instructions.

Superpowers documents an [OpenCode V2 installation](https://github.com/obra/superpowers/blob/main/docs/README.opencode.md). Merge this entry into the existing `plugins` array in your home configuration, preserving other settings:

```json
{
  "plugins": ["superpowers@git+https://github.com/obra/superpowers.git"]
}
```

The JSON above shows the setting to merge, not a replacement configuration file. Restart OpenCode after configuring it. This Git source follows upstream changes; select a reviewed immutable revision for a fixed installation, using the source forms in the [OpenCode plugin documentation](https://opencode.ai/v2/docs/plugins).

## Antigravity

In an interactive `agy` session, use `/plugin` to browse the official marketplace. From a container shell, list installed plugins:

```sh
agy plugin list
```

Replace `PLUGIN` with the name you selected:

```sh
agy plugin install 'PLUGIN@antigravity-plugins-official'
agy plugin list
```

Disable or uninstall it with:

```sh
agy plugin disable PLUGIN
agy plugin uninstall PLUGIN
```

The [agent-skills Antigravity guide](https://github.com/addyosmani/agent-skills/blob/main/docs/antigravity-setup.md) documents installation of its full pack:

```sh
agy plugin install https://github.com/addyosmani/agent-skills.git
```

That guide records limitations with legacy short command wrappers in some Antigravity releases. Use the installed namespaced skills directly and check discovery in your session. Whether our pinned CLI has that wrapper limitation is not verified.

For Superpowers, its [Antigravity installation guide](https://github.com/obra/superpowers#antigravity) documents:

```sh
agy plugin install https://github.com/obra/superpowers
```

Choose each pack independently. See [Antigravity's plugin documentation](https://antigravity.google/docs/plugins) for discovery, installation and account requirements. Compatibility of other Claude plugins with Antigravity is not verified.

## Verification limits

The following checks ran on 2026-10-21 with the agent versions pinned in [versions.env](../versions.env), using disposable homes in the existing local arm64 image. No personal home or credentials were mounted, and no model requests were sent.

| Agent or package | Observed result |
|---|---|
| Claude Code | All four recommended plugins installed from the official marketplace, appeared enabled in `claude plugin list --json`, and disappeared after uninstalling them. The installer normalized the permission-mode spelling as described above. |
| Codex | Superpowers and agent-skills installed from local checkouts of their upstream repositories, appeared enabled in `codex plugin list --json`, and disappeared after removal. The unauthenticated default catalog returned no available entries, so the curated Superpowers and Codex Security browser installations remain not verified. |
| Antigravity | Both packs installed from local upstream checkouts. `agy plugin list --json` listed the four recommended agent-skills workflows and Superpowers' skills; both packs disappeared after uninstalling them. |
| OpenCode | Superpowers' pinned Git package entry was added and removed successfully. Runtime plugin and skill discovery remain not verified, as described above. |
| UI UX Pro Max | The `ui-ux-pro-max-cli` installer created per-project assets for Codex, OpenCode and Antigravity. Its local `ui-ux-pro-max/scripts/search.py` design-system generator succeeded for all three layouts. Agent-driven use remains not verified. |

The pack checks used Superpowers revision [`b739a8a`](https://github.com/obra/superpowers/tree/b739a8af570e10a95898f2bdf6cec97467fa6c12) and agent-skills revision [`aeac41d`](https://github.com/addyosmani/agent-skills/tree/aeac41d4d005999432bb7312f7ff06383a91d59d). The UI UX Pro Max check used the npm CLI release `2.15.0`. That installer also included auxiliary design skills; inspect its generated files before adding them to a project.

Native command syntax was checked against the bundled CLIs' help. Recommended package names, sources and setup steps come from the linked upstream guides and skill files. Actual coding workflows, account connections, model costs, hook execution and approval delivery remain not verified. Installation checks do not establish plugin effectiveness or constitute a full security audit. These instructions do not install or enable anything until you run the installation commands or apply the plugin configuration.

The RTK, context-mode and Context7 examples were checked against upstream documentation on 2026-10-22. Their installers, authentication, agent hooks and savings were not tested in Agentainer. These examples are not additions to the image or its startup defaults.
