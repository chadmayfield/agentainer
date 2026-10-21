# Visual color review

Generate terminal screenshots and an offline HTML gallery for human review. This is an optional test command. It does not build or publish an Agentainer image, modify a personal home, or call an agent API.

## Install the test dependencies

Use an existing Node.js installation compatible with the `engines` requirement in the locked Playwright package, Python 3, and Docker or Podman. The image must already be available locally. Capture uses `--pull=never` and `--network none`.

From the repository root:

```sh
cd tests/visual
npm ci --ignore-scripts
```

The exact test dependency versions and published integrity hashes are in `package.json` and `package-lock.json`. They were verified with `npm view PACKAGE version dist.integrity --json` against the npm registry. Nothing is added to the Agentainer runtime image. npm setup needs network access; terminal capture and rendering do not.

Dependabot checks these npm dependencies weekly and groups updates into one pull request against `develop`, with a seven-day cooldown. Review the lockfile changes and run the visual tests before merging ([Dependabot configuration](../../.github/dependabot.yml), [configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)).

## Generate the review

From `tests/visual/`, using an existing Chrome installation:

```sh
python3 capture.py --image localhost/agentainer:dev
BROWSER_CHANNEL=chrome npm run screenshots
```

To review changes to home defaults before rebuilding, use an existing compatible image and overlay this checkout's defaults read-only:

```sh
python3 capture.py --image localhost/agentainer:dev --source-defaults
BROWSER_CHANNEL=chrome npm run screenshots
```

`--source-defaults` changes only the mounted home seed files and shared instructions. It does not test changes to the Containerfile or entrypoint. The gallery labels the defaults as either `image` or `checkout overlay`. An overlay preview does not verify a newly built image.

Use `--runtime docker` for Docker Engine, or set `RUNTIME=docker`. `IMAGE` can supply the image reference instead of `--image`. These invocation options are documented by `python3 capture.py --help`; container flags were verified with `podman run --help` and the [Docker run reference](https://docs.docker.com/reference/cli/docker/container/run/).

`BROWSER_CHANNEL=chrome` selects installed Google Chrome. With an existing Playwright Chromium installation, omit that variable. The command does not install browsers automatically. Follow [Playwright's browser documentation](https://playwright.dev/docs/browsers) to install a browser if needed. Do not install one on someone else's machine without their approval.

Open `artifacts/visual/index.html` relative to the repository root. It embeds every screenshot and opens directly from disk without JavaScript, a web server, external fonts or a CDN. The page follows the client's light or dark preference; the terminal screenshots retain their captured colors. A Markdown companion, `artifacts/visual/index.md`, links to individual PNGs in `artifacts/visual/screenshots/`. Commit the Markdown and its PNGs together, preserving their relative paths, for GitHub rendering ([GitHub relative image paths](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#relative-links)). Generating them does not commit or publish them. The HTML, raw terminal recordings in `captures.json`, temporary output and `tests/visual/node_modules/` remain gitignored. Generated HTML and screenshots include font-rendered pixels, not redistributed font files.

Check both command exit codes. A failed capture or render does not replace the previous complete capture or gallery. An old gallery can remain after a failed run.

## Coverage

| Tool | States |
|---|---|
| Shell and ls | Prompt, normal files, directory, symbolic link, executable |
| eza | Long listing with metadata and Git indicators; nested tree; working and broken symbolic links |
| Git | Mixed staged, modified, deleted and untracked status; working-tree diff; staged diff; real unresolved merge conflict |
| bat | Python and YAML syntax with its configured ANSI theme |
| fzf | Empty query; matching query; multiple selections; no matches |
| Vim | Python; YAML; search matches and trailing whitespace; visual selection; right-hand browser at 120 and 80 columns |
| tmux | Single pane; multiple windows and split panes; copy-mode selection; background-window activity; split panes at 80 columns |

There are 25 screenshots. Each case captures actual tool output through a Linux pseudo-terminal, including full-screen applications before they exit. The browser replays that output in [xterm.js](https://xtermjs.org/docs/api/terminal/classes/terminal/) and uses [Playwright element screenshots](https://playwright.dev/docs/screenshots#element-screenshot). The test checks expected text on the rendered screen, colored text, loaded fonts, browser errors, and that all embedded images load. It checks explicit selection background colors and that the zero-result fzf screen contains no candidate names. Missing scenarios or incomplete recordings fail the run. The Markdown checks verify relative image paths and escape captured text. It does not compare screenshots against approved baselines.

The fixture uses generic files and identity inside the disposable container. It creates temporary Git history there, never in the host repository. All containers are named `cx-visual-*`; capture runs one container at a time and removes it when finished or on timeout. No personal home, credentials, container socket or real project is mounted. The optional source overlay mounts only the two documented seed paths.

The renderer fixes most terminals at 120 columns by 32 rows, with the two narrow views at 80 columns by 24 rows. Each screenshot is labeled with its dimensions. It uses the locked JetBrains Mono font at 14px, and supplies an Ayu-inspired reference ANSI palette. Truecolor escapes come from the captured programs. bat's ANSI colors depend on this reference palette and may differ in a user's terminal. Sample file dates, Git dates and the tmux clock are fixed. Browser and operating-system rendering can still differ ([Playwright rendering limits](https://playwright.dev/docs/test-snapshots)). The renderer records its browser version in the gallery. Local execution used Podman on arm64 with installed Chrome and the checkout overlay. Docker Engine and amd64 execution are not verified.

Agent client interfaces, real authentication, shell completion menus and live clipboard transfer are not verified by this gallery. A human should inspect text contrast, selection visibility, gutters and status lines in the gallery, then confirm the result in their own terminal. Generation is not visual approval.

## Release use

Keep this command optional until it has been reviewed. For a release, run it against the already built candidate image without `--source-defaults` and review the resulting gallery. A separate Agentainer build is unnecessary. No release or pull-request workflow is enabled by this change.

The same command can later run manually in CI or on configuration pull requests and upload `artifacts/visual/`, including both gallery formats and the PNGs. Browser dependencies belong in the test environment. Release-only execution would miss useful feedback while colors are being changed.
