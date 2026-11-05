# Optional browser testing

Install Playwright in the project that needs it. Agentainer supplies Node.js, npm and the OS libraries and fonts that Playwright lists for Chromium on Ubuntu 26.04 (`nativeDeps.ts` in Playwright v1.64.1, without `xvfb`). The browsers themselves are not in the image. They download into your home as the `agent` user, with no sudo. Playwright supports Ubuntu 26.04 on amd64 and arm64 ([system requirements](https://playwright.dev/docs/intro#system-requirements)). Follow an existing project's package-manager instructions and lockfile instead of creating a second setup.

## Contents

- [Install the project dependency and browser](#install-the-project-dependency-and-browser)
- [Verify execution](#verify-execution)
- [Other browsers and older images](#other-browsers-and-older-images)
- [The Playwright MCP plugin](#the-playwright-mcp-plugin)
- [Shared memory and network access](#shared-memory-and-network-access)
- [Updates, recreation and cleanup](#updates-recreation-and-cleanup)
- [Verify the Agentainer instructions](#verify-the-agentainer-instructions)

## Install the project dependency and browser

Inside the container, enter the project directory under `/workspace`. For a new, empty npm project:

```sh
npm init --yes
npm install --save-dev --save-exact @playwright/test
export PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright"
./node_modules/.bin/playwright install --only-shell chromium
```

Keep `package.json` and `package-lock.json` in version control. For an existing locked npm project, use `npm ci` instead of the first two commands. Run the browser download as the normal `agent` user. See [Playwright installation](https://playwright.dev/docs/intro) and [npm dependency locking](project-tools.md#javascript-dependencies-and-package-manager-versions). Browser binaries must match the project's Playwright version ([Playwright browser requirements](https://playwright.dev/docs/browsers)).

`--only-shell chromium` downloads Chromium's headless shell. It supports headless tests without a browser channel selection. Headed tests, code generation with a visible browser, or a configuration using `channel: 'chromium'` need the full browser instead: run `./node_modules/.bin/playwright install chromium`. The image has no X server (`xvfb` is left out), so a headed browser needs a display from somewhere else ([browser installation choices](https://playwright.dev/docs/browsers#chromium-headless-shell)).

Use the same `PLAYWRIGHT_BROWSERS_PATH` when installing and running tests. Export it in each shell that runs Playwright, or add the export to your own container `~/.bashrc`. `~/.cache/ms-playwright` is on the home volume in either tools mode; `AGENTAINER_TOOLS=persist` is not required. It stores executables, not browser login sessions ([browser storage](https://playwright.dev/docs/browsers#managing-browser-binaries)).

## Verify execution

Create `browser-smoke.spec.cjs` in the project:

```js
const { test, expect } = require('@playwright/test');

test('Chromium renders, handles input and captures a screenshot', async ({ page }, testInfo) => {
  await page.route('**/*', route => route.abort());
  await page.setContent('<h1>Browser ready</h1><button onclick="this.textContent=\'Clicked\'">Try it</button>');
  await expect(page.getByRole('heading')).toHaveText('Browser ready');
  await page.getByRole('button', { name: 'Try it' }).click();
  await expect(page.getByRole('button')).toHaveText('Clicked');
  await page.screenshot({ path: testInfo.outputPath('browser-smoke.png') });
});
```

Run it with the project-local command:

```sh
./node_modules/.bin/playwright test browser-smoke.spec.cjs --workers=1 --reporter=line
```

The test renders a page, clicks a button, checks its new text and writes `browser-smoke.png` under `test-results/`. It aborts page network requests and needs no external website. A browser launch failure or failed assertion returns a nonzero exit code. See [test assertions](https://playwright.dev/docs/test-assertions), [request interception](https://playwright.dev/docs/network#handle-requests) and [screenshots](https://playwright.dev/docs/screenshots).

On 2026-11-04 this test passed in the [Kubernetes example](kubernetes.md) pod under the Restricted Pod Security Standard, with the optional egress policy on, using `@playwright/test` 1.64.1 and `playwright install --only-shell chromium`. It wrote a valid PNG.

For an existing project, follow its Playwright configuration and test command. A development server inside the container can listen on `0.0.0.0`; use the launcher's [port publishing](running.md#development-server-ports) to open it in a host browser.

## Other browsers and older images

The image carries Chromium's libraries only. Firefox and WebKit need their own downloads and OS dependencies, and images older than this change have no browser libraries at all. Both cases need root for `install-deps`. The launcher blocks sudo by default, so create a container with `--sudo` for that step, or use a [custom image](customization.md#customize-the-image-itself) that already has the libraries ([Linux dependencies](https://playwright.dev/docs/browsers#install-system-dependencies)).

Select an available image as described in [running Agentainer](running.md), then run this from the repository root for a separate browser-testing home:

```sh
AGENTAINER_HOME_VOLUME=agentainer-browser-home \
  bin/agentainer up --sudo --name agentainer-browser "$HOME/code"
bin/agentainer shell agentainer-browser
```

`$HOME/code` must exist on the host. Inside the container, install the libraries before the browser, for example for Firefox:

```sh
sudo ./node_modules/.bin/playwright install-deps firefox
./node_modules/.bin/playwright install firefox
```

The home volume keeps browser downloads. OS libraries installed with sudo live in the container's writable layer. Repeat their installation when replacing the container, or include them in your custom image. The launcher keeps `--sudo` during updates ([launcher options](running.md#the-launcher)).

## The Playwright MCP plugin

Claude Code's Playwright plugin starts `npx @playwright/mcp@latest` with no arguments ([its `.mcp.json`](https://github.com/anthropics/claude-plugins-official/blob/main/external_plugins/playwright/.mcp.json)). The image's Claude Code has the built-in `anthropic-plugin-directory` marketplace (`claude plugin marketplace list`), so this works with no marketplace step:

```sh
claude plugin install playwright@anthropic-plugin-directory --scope user
```

`playwright@claude-plugins-official` installs the same plugin after you add that marketplace as described in [plugins.md](plugins.md#claude-code).

The server's default browser is the `chrome` channel, which the image does not have. The image sets `PLAYWRIGHT_MCP_BROWSER=chromium`, which `@playwright/mcp` reads as its `--browser` option, so the server uses Playwright's own Chromium build. With no `DISPLAY` set, the server runs the browser headless.

Before the first use, download the browser that the server's Playwright version expects:

```sh
npx @playwright/mcp install-browser chromium
```

- The plugin follows `@latest`, so the browser build it needs changes when a new server release comes out. Rerun the command after an update, and when a tool call reports a missing browser.
- The command downloads a full Chromium build plus a headless shell and ffmpeg into `~/.cache/ms-playwright`, separate from your projects' browsers. With `@playwright/mcp` 0.0.84 on arm64 that was 692 MB (`chromium-1252` 407 MB, `chromium_headless_shell-1252` 281 MB, `ffmpeg-1013` 3.9 MB). Each new build adds another set to your home. `du -sh ~/.cache/ms-playwright/*` shows what is there.
- Pinning the plugin to a fixed `@playwright/mcp` version is your choice. The image does not do it.

Verified with `@playwright/mcp` 0.0.84: `tests/host/test-playwright-setup.py` lists the server's 25 tools, opens a page on `127.0.0.1` and takes a screenshot. The same check passed in the Kubernetes example pod on 2026-11-04 ("mcp-ok tools=25").

## Shared memory and network access

Chromium uses `/dev/shm`. Playwright's Docker guide recommends `--ipc=host` and says "Without it, Chromium can run out of memory and crash" ([Playwright Docker docs](https://playwright.dev/docs/docker)). The launcher keeps the engine's default size, which is 64 MB under Podman (`df -h /dev/shm` shows 63M). The smoke test and the MCP check pass with that size. For pages that need more, run the container without the launcher and add `--shm-size=1g` ([without the launcher](running.md#without-the-launcher), `man podman-run`). The Kubernetes example mounts a 1 GiB memory-backed volume at `/dev/shm`, which counts against the agent container's memory limit ([shared memory](kubernetes.md#shared-memory)).

Under the Kubernetes example's optional egress policy, the pod reaches public addresses on TCP 443 only. Plain HTTP on port 80 is blocked, so test against `https://` URLs or a server inside the pod. The npm registry and the Playwright download CDN use 443, and `npx -y @playwright/mcp@0.0.84 install-browser chromium` worked under that policy on 2026-11-04 ([network policy](kubernetes.md#network-policy)).

## Updates, recreation and cleanup

After updating the project's Playwright version, repeat the browser install command. Playwright versions select matching browser revisions. After replacing the container, restore the project's dependencies with `npm ci` if needed and export the same browser path. Browser files remain on the persistent home, and the new container's image supplies the libraries. Reinstall browser files and project dependencies when changing architecture. See [Playwright browser versions](https://playwright.dev/docs/browsers) and [project environment portability](customization.md#project-dependencies-and-installed-tools).

Playwright removes unused browser revisions as clients are updated. `./node_modules/.bin/playwright install --list` shows installed browsers; `./node_modules/.bin/playwright uninstall` removes browsers for that Playwright installation. Avoid `uninstall --all` when other projects or the MCP plugin share the browser directory ([browser management](https://playwright.dev/docs/browsers#stale-browser-removal)).

Keep `node_modules/`, `test-results/` and any generated `playwright-report/` out of the project's Git history. Browser authentication state, traces and screenshots can contain application data; store and publish only the outputs you intend to share ([authentication state](https://playwright.dev/docs/auth)).

## Verify the Agentainer instructions

From this repository root, run the optional networked setup check against an existing local image:

```sh
python3 tests/host/test-playwright-setup.py --image localhost/agentainer:dev
```

Use `--runtime docker` for Docker Engine. The check does the following:

- Runs the containers with `--security-opt no-new-privileges`, so sudo cannot gain root.
- Installs the Playwright version locked for [visual tests](../tests/visual/package.json) and Chromium's headless shell as the `agent` user.
- Runs the smoke test, and checks that a deliberately wrong assertion fails.
- Recreates the container with the same home and workspace volumes, checks the browser file hashes and runs the test again.
- Installs the MCP server's browser with `npx @playwright/mcp@0.0.84 install-browser chromium`, checks that the project's browser files keep their hashes, then starts the server, lists its tools, opens a local page and takes a screenshot.
- Creates one container at a time, uses only `cx-*` names and removes its containers and volumes. It does not build an image or mount a personal home.

Setup needs network access to npm and the Playwright downloads. The smoke test itself blocks page network requests.

The manual workflow [`.github/workflows/optional-tooling.yml`](../.github/workflows/optional-tooling.yml) (`workflow_dispatch`) builds the image and runs this check and the [language tooling check](language-tooling.md#updates-and-verification) with Docker on amd64 and arm64 runners. Not verified: the workflow has no runs yet (`gh run list --workflow optional-tooling.yml` returns none). See [CONTRIBUTING.md](../CONTRIBUTING.md#ci).
