# Default configuration

Agentainer seeds these files into a new home and leaves existing files unchanged. They live in `rootfs/etc/agentainer/home/` in the repository and `/etc/agentainer/home/` in the image. The shared instructions come from `rootfs/etc/agentainer/AGENTS.md`. The startup step is [`20-seed.sh`](../rootfs/usr/local/lib/agentainer/entrypoint.d/20-seed.sh).

No default contains an account, token, private endpoint or signing key. The Git identity and signing examples are comments. Runtime environment variables can still supply Git identity and enable the GitHub credential helper ([logins](logins.md)).

## Contents

- [Agentainer colors](#agentainer-colors)
- [Shell and command-line tools](#shell-and-command-line-tools)
- [Tmux](#tmux)
- [Vim and EditorConfig](#vim-and-editorconfig)
- [Agent configurations](#agent-configurations)
- [Existing homes](#existing-homes)

## Agentainer colors

The Agentainer colorscheme is inspired by [Ayu Dark](https://github.com/ayu-theme/ayu-colors/blob/master/themes/dark.yaml). It uses a pure black background, a subtle charcoal tmux bar, and a slate-blue Vim status line. It is a local adaptation, not the upstream Ayu theme. OpenCode uses its own built-in Ayu theme.

| Role | Color |
|---|---|
| Background | `#000000` |
| Selection and tmux bar | `#202020` |
| Normal text and directories | `#bfbdb6` |
| Secondary text | `#747474` |
| Amber accents and links | `#e6b450` |
| Additions and executables | `#aad94c` |
| Removals and errors | `#f07178` |
| Blue accents | `#59c2ff` |
| Vim status line | `#253340` |

The shell exports `LS_COLORS` from `~/.config/agentainer/shell-theme.bash`. It gives `ls` and eza gray directories, amber symbolic links and green executables. Edit that file to customize the file colors. Agentainer does not change the host terminal's ANSI palette, which bat's `ansi` theme uses.

The offline tests in [`tests/55-defaults.sh`](../tests/55-defaults.sh) check actual RGB output from `ls`, eza and Git, eza's `LS_COLORS` override, redirected Git output, and Vim and tmux settings. They also check that startup preserves edited color configuration files. These checks do not replace a visual check in the user's terminal. Generate the optional screenshot gallery with the commands in [visual review](../tests/visual/README.md). The gallery captures multiple states per tool for human review; generation does not approve their appearance.

## Shell and command-line tools

| File in home | Default |
|---|---|
| `.bashrc` | Ubuntu shell defaults, append-only history, Git and fzf completion, `EDITOR=vim`, `VISUAL=vim`, and a `less` pager |
| `.config/agentainer/shell-theme.bash` | Black panes, amber username, blue hostname, gray path, and colored file listings |
| `.config/eza/theme.yml` | Ayu-inspired file types, permissions, sizes, owners, dates and Git indicators |
| `.config/fzf/config` | Black background with charcoal selection and Ayu accents |
| `.config/bat/config` | Built-in `ansi` theme, line numbers, changes and headers, automatic paging |
| `.gitconfig` | Vim editor, `main` initial branch, required identity, common aliases, Ayu diff/status/branch colors and `push.default=simple` |
| `.config/git/ignore` | OS metadata, Vim swap files and editor backups |

Bash loads Ubuntu's `/etc/skel/.bashrc` before applying Agentainer's defaults. It retains Ubuntu's `ll`, `la` and `l` aliases and adds `..`, `...` and `v`. History ignores duplicate adjacent commands and commands beginning with a space. History is appended when shells exit; running shells do not automatically import each other's history ([Bash history](https://www.gnu.org/software/bash/manual/html_node/Bash-History-Facilities.html)).

`EDITOR`, `VISUAL`, `PAGER`, `LESS` and `FZF_DEFAULT_OPTS_FILE` retain existing nonempty values. Git completion comes from `/usr/share/bash-completion/completions/git`, verified in the image; fzf integration uses its documented `--bash` option ([fzf](https://github.com/junegunn/fzf#setting-up-shell-integration)). Bash settings and prompt escapes follow the [Bash manual](https://www.gnu.org/software/bash/manual/). No shell alias bypasses agent approvals or performs a Git push or rebase.

The bat build does not include Ayu. Its `ansi` theme uses the terminal's ANSI palette rather than downloading a theme. The theme and options are verified with `bat --list-themes` and `bat --help` ([bat configuration](https://github.com/sharkdp/bat#configuration-file)). fzf supports the explicit RGB palette in its options file, verified with `fzf --help` and a filtered invocation. `less` preserves color escapes with `LESS=FRX`; Git uses `less -FRSX`, which also truncates long lines ([Git pager](https://git-scm.com/docs/git-config#Documentation/git-config.txt-corepager)). The palette follows [Ayu's published colors](https://github.com/ayu-theme/ayu-colors/blob/master/themes/dark.yaml).

eza reads `~/.config/eza/theme.yml`; `LS_COLORS` and `EZA_COLORS` take precedence over file-name colors. The theme also colors metadata in long listings such as `eza --long --group --header`. These options and the RGB output are tested against the installed binary ([eza themes and precedence](https://github.com/eza-community/eza-themes)). Git uses the same amber headings, gray context, green additions and red removals for diffs, with matching status, branch and log colors. `color.ui=auto` keeps redirected output free of color escapes, verified with `git status --short` ([Git color settings](https://git-scm.com/docs/git-config), [log color formatting](https://git-scm.com/docs/pretty-formats)).

## Tmux

`.tmux.conf` provides a charcoal bar with amber text. The image's `/etc/tmux.conf` supplies mouse support, truecolor and agent terminal settings. Windows and panes start at 1, and windows renumber when closed.

Press `Ctrl-b`, release it, then press the listed key:

| Key | Action |
|---|---|
| Pipe character, Shift-backslash on a US keyboard | Split left and right in the current directory |
| `-` | Split top and bottom in the current directory |
| `c` | Open a window in the current directory |
| `r` | Reload the personal tmux config |
| Uppercase `H`, `J`, `K`, `L` | Resize left, down, up or right; repeat within 750 ms |
| `[` | Enter copy mode; use `h/j/k/l`, `v` to select, `y` to copy, or `q` to leave |

Activity in other windows marks their status entries without an audible bell. Clipboard copying uses `set-clipboard=external` and OSC 52. The outside terminal must accept it; transfer to the host clipboard is not verified by the container tests ([tmux clipboard](https://github.com/tmux/tmux/wiki/Clipboard)). Commands and options follow the [tmux manual](https://github.com/tmux/tmux/blob/master/tmux.1).

## Vim and EditorConfig

`.vimrc` and `.vim/colors/agentainer.vim` provide black editing panes, Ayu-inspired syntax colors and a slate-blue status line distinct from tmux. Vim shows line numbers, the current line and trailing whitespace. Search is incremental and ignores case unless the pattern contains uppercase characters. Press Escape twice to clear search highlighting.

Indentation defaults to four spaces, with two for YAML, JSON, JavaScript, TypeScript, HTML and CSS. Vim's Makefile settings preserve tabs. Vim loads its bundled EditorConfig package so project rules take precedence. The bundled package's unnamed-buffer hooks cannot expand `<afile>`; the config uses named-file events and direct reloads instead. Non-bang `silent` suppresses informational runtime warnings while leaving errors enabled. These settings are checked against the installed runtime's `:help options`, `:help last-position-jump`, `:help netrw-:Lexplore` and `:help editorconfig`.

Undo, swap and backup files live in private directories under `~/.vim/`. These files can retain earlier contents of credentials or other sensitive files after the original changes or disappears. Avoid editing secrets in this shared home, or use Vim settings that disable the recovery files you do not want. Vim returns to the last cursor position except for commit messages, rebase instructions and diff mode. Press backslash then `e` to toggle a full-height browser on the right, using 25% of the window width.

An EditorConfig file applies to files in its directory and descendants, not to unrelated directories. A home `.editorconfig` would not control `/workspace`. The template `~/.config/agentainer/editorconfig` is available to copy into a project's `.editorconfig` when the project has none. Agentainer never writes it into your workspace automatically ([EditorConfig location and precedence](https://editorconfig.org/#file-location)).

## Agent configurations

| File in home | Default and source |
|---|---|
| `.claude/settings.json` | Shared `AGENTS.md` integration, stable updates, manual permissions, explanatory output, turn durations and terminal-bell notifications. Includes the published editor schema. [Settings and schema](https://code.claude.com/docs/en/settings), [output styles](https://code.claude.com/docs/en/output-styles), [duration setting](https://code.claude.com/docs/en/settings-reference#showturnduration), [notifications](https://code.claude.com/docs/en/terminal-config#get-a-terminal-bell-or-notification) |
| `.codex/config.toml` | File-backed login storage and explicit `approval_policy=on-request`. Retains the existing container sandbox setting, because bubblewrap cannot create its nested mount. [Config reference](https://learn.chatgpt.com/docs/config-file/config-reference) |
| `.gemini/antigravity-cli/settings.json` | Terminal colors, `toolPermission=request-review`, Vim as the external editor and completion notifications. [Antigravity settings](https://antigravity.google/docs/cli/reference#configuration-keys-settingsjson) |
| `.config/opencode/opencode.json` | Disabled updater and the published editor schema. [Config](https://opencode.ai/v2/docs/config) |
| `.config/opencode/cli.json` | Built-in `ayu` dark theme, notifications without sound, explicit prompting for permission requests, diff layout selected by available width, word wrapping and a diff file tree. The mini interface shows its status footer and turn summaries. Includes the published CLI schema. [CLI settings](https://opencode.ai/v2/docs/cli/config), [themes](https://opencode.ai/v2/docs/themes) |

Models, accounts and provider URLs are left for users to configure. Claude, Antigravity and OpenCode retain the approval settings listed above. Codex uses `on-request` with `danger-full-access`; that combination does not require confirmation for every command. The container, its mounts and its runtime credentials define what Codex can access ([approval semantics](https://learn.chatgpt.com/docs/agent-approvals-security)). The offline tests check configuration values and loading, not model-driven approval behavior. Interactive account access and actual agent tool approvals are not verified by those tests.

The offline defaults fixture uses a fresh named home volume and compares its seeded files with the image defaults before user edits. This checks files copied from the image into the volume as well as files added by the entrypoint. It runs `claude doctor` and checks its report for invalid settings, because the command can exit successfully while reporting a configuration error. It starts the actual OpenCode client in a terminal and checks that the configured Ayu cursor color is applied. Both checks include deliberately invalid settings: Claude must report the bad value, and OpenCode's fallback to its default theme must fail the Ayu check. The fixture also verifies that a second startup preserves edits to all four agents' configuration files.

In a manual container check, Antigravity login, terminal appearance, denied and approved file writes, and login/settings persistence worked. The task completed without an observed bell. The test session had `bell-action none`, matching the seeded tmux config. Whether Antigravity emitted a bell during that task is not verified.

Notification delivery depends on the host terminal and tmux settings. Claude uses a terminal bell so the container needs no desktop notification command. Antigravity's notification option includes a terminal chime; OpenCode's sound option is separate and disabled. Notification delivery from these defaults is not verified.

Customize models, providers, plugins and hooks in your own home files. Keep API keys in the runtime environment or the agent's login store. Claude and Antigravity use strict JSON, so put notes beside the configuration rather than adding comments. OpenCode supports JSONC, but Agentainer's MCP sync writes `opencode.json` and stops if `opencode.jsonc` exists; keep that filename when using sync. Codex's TOML supports comments. Custom status-line commands and hooks need their own scripts and are not included in these defaults.

## Existing homes

Image upgrades do not replace your `.bashrc`, `.gitconfig`, `.vimrc`, `.tmux.conf` or agent settings. Compare desired files with `/etc/agentainer/home/` and apply changes yourself. The shared `~/.agentainer/AGENTS.md` follows its separate version and ownership rules described in [configuration](configuration.md#agentsmd).

Changes to image seed files do not modify running containers.
