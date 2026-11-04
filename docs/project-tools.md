# Project-local tooling

Run these commands inside Agentainer, from the project root under `/workspace`. Follow an existing project's dependency files, lockfile and setup instructions. Each new-project example below assumes its own empty directory.

The image supplies Python, uv, Node.js and npm. The examples install development dependencies into the project. They do not change Agentainer's image pins or require sudo. Initial package resolution and uncached downloads need network access ([uv projects](https://docs.astral.sh/uv/guides/projects/), [npm install](https://docs.npmjs.com/cli/v9/commands/npm-install/)).

## Contents

- [Python tests and linting with uv](#python-tests-and-linting-with-uv)
- [JavaScript dependencies and package-manager versions](#javascript-dependencies-and-package-manager-versions)
- [Language servers](#language-servers)
- [Browser tests](#browser-tests)
- [Native builds](#native-builds)
- [Go formatting and security scans](#go-formatting-and-security-scans)
- [PDFs and images](#pdfs-and-images)
- [Document conversion with MarkItDown and pandoc](#document-conversion-with-markitdown-and-pandoc)
- [PostgreSQL scripts](#postgresql-scripts)
- [Kubernetes and Helm clients](#kubernetes-and-helm-clients)
- [AWS CLI](#aws-cli)
- [Persistence](#persistence)

## Python tests and linting with uv

For a new Python project, create its dependency declaration and add pytest and Ruff to the development group:

```sh
uv init --bare --vcs none
uv add --dev pytest ruff
mkdir -p tests
cat > tests/test_example.py <<'PY'
def test_addition():
    assert 2 + 2 == 4
PY
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

`uv add` updates `pyproject.toml` and resolves exact versions in `uv.lock`. The project environment is `.venv`. Keep `pyproject.toml` and `uv.lock` in version control; leave `.venv` out. See [dependency management](https://docs.astral.sh/uv/guides/projects/#managing-dependencies) and [Ruff's tutorial](https://docs.astral.sh/ruff/tutorial/).

For an existing uv project that declares pytest and Ruff, install its locked dependencies and run its checks:

```sh
uv sync --locked
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
```

`--locked` rejects a missing or stale lockfile instead of updating it. It does not force offline operation. Use `uv add` when deliberately changing dependencies, then review the declaration and lockfile together ([locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/)).

The example uses the image's Python. An existing project can require a different Python version; follow its runtime requirements. Ubuntu's Python rejects global and `--user` pip installs outside a virtual environment, so use the project's uv workflow or venv ([Python packaging and tool persistence](configuration.md#tools-that-agents-install)).

## JavaScript dependencies and package-manager versions

For a new npm project, record the npm version in use, add TypeScript as an exact development dependency, and create a test with Node's built-in test runner:

```sh
npm init --yes
npm pkg set "packageManager=npm@$(npm --version)" 'scripts.test=node --test'
npm install --save-dev --save-exact typescript
mkdir -p tests
cat > tests/example.test.mjs <<'JS'
import assert from 'node:assert/strict';
import test from 'node:test';

test('addition', () => {
  assert.equal(2 + 2, 4);
});
JS
npm exec -- tsc --version
npm test
```

Keep `package.json`, `package-lock.json` and the tests in version control; leave `node_modules` out. `--save-exact` records the selected dependency version without a range. `npm exec` runs the local TypeScript compiler in this example. See [npm install](https://docs.npmjs.com/cli/v9/commands/npm-install/), [npm pkg](https://docs.npmjs.com/cli/v9/commands/npm-pkg/) and [Node's test runner](https://github.com/nodejs/node/blob/v26.x/doc/api/test.md).

For an existing npm project with a committed lockfile and a test script:

```sh
npm ci
npm test
```

`npm ci` requires the lockfile to agree with `package.json`, replaces `node_modules` and leaves the dependency declarations and lockfile unchanged. Use `npm install` for deliberate dependency changes. Keep any project-specific install flags in the project's configuration so local and CI installs agree ([npm ci](https://docs.npmjs.com/cli/v9/commands/npm-ci/)).

The `packageManager` field records the project's expected package-manager version. Running plain `npm` uses the executable on `PATH`; the field alone does not switch it. Check `npm --version` against the project's requirement.

Node.js 26 does not include Corepack; Node.js shipped it only "up to (but not including) 25.0.0" ([Corepack README](https://github.com/nodejs/corepack#readme)). To use pnpm or Yarn, install it the way the project documents, or run `npm install -g corepack` and then `corepack enable` (same README). Follow an existing pnpm or Yarn project's setup rather than creating an npm lockfile beside its own lockfile.

## Language servers

See [optional language tooling](language-tooling.md) for gopls, rust-analyzer, Pyright and TypeScript 7's native server, with a project-local TypeScript 6 fallback. Installing a server does not configure an editor or agent to use it.

## Browser tests

See [optional browser testing](browser-testing.md) for project-local Playwright installation, persistent browser downloads, the Playwright MCP plugin and a headless execution check. The image has Chromium's OS libraries. Browsers are installed only when you choose that setup.

## Native builds

The image includes GCC, G++, Make, CMake, Ninja and pkg-config. For an existing CMake project that supports Ninja:

```sh
cmake -S . -B build -G Ninja
cmake --build build
```

`-S` selects the source directory and `-B` keeps generated files in a separate build directory. `-G Ninja` selects the Ninja generator. See the [CMake command reference](https://cmake.org/cmake/help/latest/manual/cmake.1.html) and [Ninja manual](https://ninja-build.org/manual.html).

Native addons build through `node-gyp`, which downloads the development files (headers) for the target Node.js version. `--devdir` sets the download directory, and the default is the OS cache directory. `--tarball` takes the headers from a local tarball ([node-gyp README](https://github.com/nodejs/node-gyp#readme)). That README does not say when the download happens or how to build offline with the image's Node.js; not verified.

The image installs Node.js from nodejs.org into `/opt/node` and has no `eslint`, `webpack`, `terser`, `node-gyp`, `gyp` or `corepack` command on `PATH`. A project runs its own copies through `npm install` and `npx`. npm builds native addons with the `node-gyp` bundled in npm itself (`/opt/node/lib/node_modules/npm/node_modules/node-gyp/`), so `npm install` needs no separate `node-gyp`.

Do not run `sudo npm install -g npm`. It replaces npm with a copy that lacks the image's builtin config, so root's global prefix falls back to `/opt/node`, whose `bin` directory is not on `PATH`.

Images up to `0.1.0-dev.20261024.1` installed Node.js from Ubuntu's `nodejs` and `npm` packages (`git show v0.1.0-dev.20261024.1:build/apt-packages.txt`). Projects that relied on commands from those packages must install them themselves.

pkg-config reads installed `.pc` metadata to supply compiler and linker flags. It does not install libraries. Project-specific headers and libraries remain optional dependencies; follow the project's setup instructions. See [Ubuntu's pkg-config manual](https://manpages.ubuntu.com/manpages/resolute/man1/pkg-config.1.html). The package list is [`build/apt-packages.txt`](../build/apt-packages.txt); the existing `APT_SNAPSHOT` pin in [`versions.env`](../versions.env) selects their versions.

## Go formatting and security scans

The image has no `goimports` command. golangci-lint 2.15.0 includes it as a formatter:

```sh
golangci-lint fmt -E goimports        # rewrite files
golangci-lint fmt -E goimports -d     # show a diff, change nothing
```

`-E` (`--enable`) turns on a formatter and `-d` (`--diff`) prints a diff instead of rewriting files (`golangci-lint fmt --help`). With `-d`, it exits with status 1 when a file needs changes. Git hooks, editor settings or Makefiles that call `goimports` must call this command instead. A project's `.golangci.yml` can enable the formatter permanently ([golangci-lint formatters](https://golangci-lint.run/docs/formatters/)).

The image also has gosec 2.30.0 and gitleaks 8.30.1:

```sh
gosec ./...          # scan the Go packages under the current directory
gitleaks git .       # scan the repository's history for secrets
gitleaks dir .       # scan the files in a directory
```

Both are upstream release binaries. The build checks their SHA-256 against the projects' published checksum files; their publisher signatures are not verified ([versions](versions.md#pinned-inputs)).

## PDFs and images

- `pdftotext file.pdf out.txt` extracts text; add `-layout` to keep the page layout. `pdftoppm -png -r 150 file.pdf page` renders each page to `page-1.png`, `page-2.png` and so on; `-f` and `-l` select the first and last page. Both come from poppler-utils 26.01.
- ImageMagick 7 (`magick`) converts, resizes and crops images, for example `magick in.png -resize 50% out.jpg`.
- ImageMagick reads PDF and PostScript through ghostscript, which the image does not install. `magick file.pdf out.png` fails with `gs: not found`. Render PDF pages with `pdftoppm` and process the PNG files with `magick`.

## Document conversion with MarkItDown and pandoc

These two tools are not in the image. Install them yourself when a project needs them. [Versions](versions.md#documented-installs) lists the pinned versions and when they were last checked.

[MarkItDown](https://github.com/microsoft/markitdown) 0.1.9 converts Office documents, PDFs and other formats to Markdown:

```sh
uv tool install "markitdown[docx,pptx,xlsx,xls,pdf,outlook]==0.1.9"
markitdown report.docx > report.md
```

The extras select the input formats (`[all]` installs every one). The install was about 240 MB. `uv tool` installs under the tools root, so MarkItDown survives a new container only with `AGENTAINER_TOOLS=persist`; otherwise install it again after the container is recreated ([tools that agents install](configuration.md#tools-that-agents-install)).

[pandoc](https://pandoc.org) 3.13 converts between markup formats. Install the upstream static binary into `~/.local/bin`, which is on the home volume and on `PATH` in login shells:

```sh
v=3.13
case "$(uname -m)" in
x86_64) a=amd64 s=38aa33b325a2bc96a4c39409631212db55702f564250bcdbead180b3bf646389 ;;
aarch64) a=arm64 s=21e1d4ba09bd0b334590d204580fd4f6629b21be4ab6a32b26cc98982e9e0c68 ;;
esac
cd "$(mktemp -d)"
curl -fsSLO "https://github.com/jgm/pandoc/releases/download/$v/pandoc-$v-linux-$a.tar.gz"
printf '%s  %s\n' "$s" "pandoc-$v-linux-$a.tar.gz" | sha256sum -c -
tar -xzf "pandoc-$v-linux-$a.tar.gz"
install -D -m 0755 "pandoc-$v/bin/pandoc" ~/.local/bin/pandoc
~/.local/bin/pandoc --version | head -n 1
```

The checksums are the SHA-256 digests GitHub publishes for the release assets (`gh api repos/jgm/pandoc/releases/tags/3.13 --jq '.assets[] | .name + " " + .digest'`). The binary unpacks to about 172 MB.

Both installs were run in the image on 2026-11-04: `markitdown 0.1.9` converted a `.docx` that `pandoc 3.13` had written.

## PostgreSQL scripts

Use `pgcli` for interactive work and `psql` for scripts. The image includes the client, not a PostgreSQL server. Configure the connection using your project's runtime environment or PostgreSQL service file. Supply credentials at runtime through a protected password file, never in a command-line connection URL. See [connection environment variables](https://www.postgresql.org/docs/current/libpq-envars.html), [service files](https://www.postgresql.org/docs/current/libpq-pgservice.html) and [password files](https://www.postgresql.org/docs/current/libpq-pgpass.html).

Run a project's SQL file after configuring its connection:

```sh
psql --no-psqlrc --no-password --set ON_ERROR_STOP=1 --file ./migration.sql
```

`--no-psqlrc` skips startup customizations. `--no-password` prevents an unattended script from waiting for a password prompt. `ON_ERROR_STOP=1` stops on SQL errors and returns exit code 3; connection failures return 2. Check the exit code in automation. Stopping does not undo earlier committed statements. Follow the project's transaction strategy. See the [psql reference](https://www.postgresql.org/docs/current/app-psql.html).

## Kubernetes and Helm clients

The image includes `kubectl` and Helm release binaries, pinned in [`versions.env`](../versions.env) ([versions](versions.md)). See [kubectl binary installation](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/) and [Helm binary installation](https://helm.sh/docs/intro/install/#from-the-binary-releases).

Inspect client versions without contacting a cluster:

```sh
kubectl version --client=true --output=json
helm version --short
```

Local rendering also works without a cluster:

```sh
kubectl kustomize ./deploy/kubernetes
helm template example-release ./path/to/chart
```

`kubectl kustomize` reads the local kustomization, and `helm template` renders the local chart. Remote bases, chart dependencies or template options can introduce downloads or cluster access; follow the project's instructions. Agentainer's tests use local fixtures with networking disabled and no kubeconfig. See [kubectl kustomize](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_kustomize/) and [Helm template](https://helm.sh/docs/helm/helm_template/).

Cluster credentials are not included. Supply a kubeconfig at runtime only when you intend to allow cluster access, and check that kubectl is within one minor version of the API server ([kubectl version skew](https://kubernetes.io/releases/version-skew-policy/#kubectl)). The AWS CLI is the only bundled cloud CLI ([AWS CLI](#aws-cli)). Other cloud CLIs and cloud authentication helpers are not bundled. Helm 4 is the current stable major selected by the upstream release API; projects requiring Helm 3 must use a compatible custom setup ([Helm releases](https://github.com/helm/helm/releases)).

## AWS CLI

The image includes AWS CLI v2, installed from AWS's signed installer zip with its own `aws/install` script into `/usr/local/aws-cli`, with `aws` and `aws_completer` in `/usr/local/bin` ([AWS CLI install guide](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)). The version is pinned in [`versions.env`](../versions.env) ([AWS CLI signing key](versions.md#aws-cli-signing-key)).

```sh
aws --version
```

The image carries no AWS configuration or credentials. Supply them at runtime only when you intend to allow AWS access.

## Persistence

`.venv` and `node_modules` live with the project under the workspace mount. User-wide tool installations are separate ([tools that agents install](configuration.md#tools-that-agents-install)). See [customization](customization.md#project-dependencies-and-installed-tools) for recreation and runtime-change guidance. A persistent home does not preserve dependencies installed only in a container's writable layer.
