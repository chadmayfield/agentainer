# Optional agent plugins

Run these commands inside Agentainer as the regular container user. Choose the plugins you want for each agent. The image does not install these optional plugins during its build or startup. Its existing built-in agent settings are described in [default configuration](defaults.md).

Keep the same persistent home when recreating the container to retain home-based plugin settings and files. Try plugins with a [separate test home](customization.md#image-upgrades-and-separate-test-homes) first. External dependencies and account connections may need separate setup; a persistent home does not preserve software installed elsewhere in the container.

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

Native command syntax was checked against the bundled CLIs' help. Recommended package names, sources and setup steps come from the linked upstream guides and skill files. Remote installation, plugin loading and account-dependent behavior in Agentainer are not verified. These instructions do not install or enable anything until you run the installation commands or apply the plugin configuration.
