# Agentainer color review

Agentainer uses GitHub Dark colors on a #010409 background. Review contrast, selections, error colors, gutters and status lines.

- Image: localhost/agentainer:gdt-int
- Defaults: image
- Renderer: 156.0.8078.80
- Terminal: 120 × 32 and narrow 80 × 24, JetBrains Mono 14px.

Captured from actual tools with generic files. Browser rendering uses a fixed font and the GitHub Dark reference ANSI palette from tests/unit/palette.py. Your terminal's font rendering and ANSI colors may differ, especially for bat. Sample dates and the tmux time and date are fixed.

## Shell and ls

Blue user, gray hostname, bold white path, blue directories, cyan links and green executables.

Terminal: 120 columns by 32 rows.

![Shell and ls terminal screenshot](screenshots/shell.png)

## ls file types

Every ls file type the agent user can create, plus /dev/null. Special permissions use red, orange and blue backgrounds. The block-device row is illustrated.

Terminal: 120 columns by 32 rows.

![ls file types terminal screenshot](screenshots/ls-colors.png)

## eza

File types, permissions, owners, sizes, dates and Git indicators.

Terminal: 120 columns by 32 rows.

![eza terminal screenshot](screenshots/eza.png)

## eza tree

Nested files, directories, executables and symbolic links.

Terminal: 120 columns by 32 rows.

![eza tree terminal screenshot](screenshots/eza-tree.png)

## eza broken symbolic link

A working link beside an orphaned link and its missing target.

Terminal: 120 columns by 32 rows.

![eza broken symbolic link terminal screenshot](screenshots/eza-broken.png)

## Git status

Staged changes, working-tree changes, deletions and untracked files.

Terminal: 120 columns by 32 rows.

![Git status terminal screenshot](screenshots/git-status.png)

## Git diff

Bold blue file headers, purple hunk headings, light context, green additions and red removals.

Terminal: 120 columns by 32 rows.

![Git diff terminal screenshot](screenshots/git-diff.png)

## Git staged diff

The diff of staged changes, separate from working-tree edits.

Terminal: 120 columns by 32 rows.

![Git staged diff terminal screenshot](screenshots/git-staged.png)

## Git merge conflict

A real unresolved merge with current and incoming conflict markers.

Terminal: 120 columns by 32 rows.

![Git merge conflict terminal screenshot](screenshots/git-conflict.png)

## bat

The built-in ANSI theme, shown with the reference terminal palette.

Terminal: 120 columns by 32 rows.

![bat terminal screenshot](screenshots/bat.png)

## bat YAML

Comments, mappings, strings, booleans and numbers in the ANSI theme.

Terminal: 120 columns by 32 rows.

![bat YAML terminal screenshot](screenshots/bat-yaml.png)

## fzf before filtering

All candidates with an empty search prompt and the current row selected.

Terminal: 120 columns by 32 rows.

![fzf before filtering terminal screenshot](screenshots/fzf-idle.png)

## fzf

Near-black background, dark gray current row, blue prompt and blue matching highlights.

Terminal: 120 columns by 32 rows.

![fzf terminal screenshot](screenshots/fzf.png)

## fzf multiple selections

Both matching files selected, showing selected and current rows.

Terminal: 120 columns by 32 rows.

![fzf multiple selections terminal screenshot](screenshots/fzf-selected.png)

## fzf without matches

An unmatched query with a zero-result count and no candidate rows.

Terminal: 120 columns by 32 rows.

![fzf without matches terminal screenshot](screenshots/fzf-empty.png)

## Vim

Syntax colors, gray line numbers, current line and the dark blue status line.

Terminal: 120 columns by 32 rows.

![Vim terminal screenshot](screenshots/vim.png)

## Vim YAML

YAML syntax with two-space indentation and the current-line gutter.

Terminal: 120 columns by 32 rows.

![Vim YAML terminal screenshot](screenshots/vim-yaml.png)

## Vim file browser

The right-hand file browser alongside the Python buffer.

Terminal: 120 columns by 32 rows.

![Vim file browser terminal screenshot](screenshots/vim-browser.png)

## Vim search and whitespace

Highlighted path matches, trailing-space dots and the current-line gutter.

Terminal: 120 columns by 32 rows.

![Vim search and whitespace terminal screenshot](screenshots/vim-search.png)

## Vim visual selection

Character selection alongside the cursor line and visible trailing whitespace.

Terminal: 120 columns by 32 rows.

![Vim visual selection terminal screenshot](screenshots/vim-selection.png)

## Vim browser at 80 columns

The right-hand browser and editing buffer at 80 columns by 24 rows.

Terminal: 80 columns by 24 rows.

![Vim browser at 80 columns terminal screenshot](screenshots/vim-browser-narrow.png)

## tmux single pane

One window and one pane with the dark status bar, blue session name, time, date and agentainer blocks.

Terminal: 120 columns by 32 rows.

![tmux single pane terminal screenshot](screenshots/tmux-single.png)

## tmux

Split panes and multiple windows. The current window is light blue on blue. Time and date fixed for review.

Terminal: 120 columns by 32 rows.

![tmux terminal screenshot](screenshots/tmux.png)

## tmux copy-mode selection

Selected terminal text in the configured copy-mode colors.

Terminal: 120 columns by 32 rows.

![tmux copy-mode selection terminal screenshot](screenshots/tmux-copy.png)

## tmux window activity

The background logs window has a verified activity flag and a pale blue status entry.

Terminal: 120 columns by 32 rows.

![tmux window activity terminal screenshot](screenshots/tmux-activity.png)

## tmux split panes at 80 columns

Split panes, window names, time and date at 80 columns by 24 rows.

Terminal: 80 columns by 24 rows.

![tmux split panes at 80 columns terminal screenshot](screenshots/tmux-narrow.png)

Screenshots are review artifacts.
