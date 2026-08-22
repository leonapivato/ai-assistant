#!/usr/bin/env bash
# Launch the Playwright MCP server this repository's `.mcp.json` declares.
#
# `.mcp.json` is committed, so its `command` has to work in every clone. A path
# into one developer's Node installation does not: `npx` lives wherever that
# machine's Node manager put it, and under nvm that is a versioned directory
# whose name changes on every upgrade. This script is the one indirection that
# makes the committed config portable — it finds `npx`, then execs the pinned
# server package.
#
# Two things it does that a bare `npx` in `.mcp.json` does not:
#
#   1. It looks past PATH. An MCP server is spawned by the editor's own
#      launcher, not from an interactive shell, so a Node installed by nvm — a
#      shell function sourced by ~/.bashrc — is frequently absent from that
#      environment. `ENOENT: npx` is what that looks like, and it is the failure
#      issue #1380 records.
#   2. It puts the resolved `node` on PATH before exec'ing. This is not
#      belt-and-braces: nvm's `npx` is a JavaScript file whose shebang is
#      `#!/usr/bin/env node`, so naming it by absolute path is NOT sufficient —
#      in an environment without `node` on PATH it fails with
#      `env: 'node': No such file or directory`, having never run a line.
#
# Everything else stays in `.mcp.json`, where a reader expects it. In particular
# the version is pinned HERE rather than floating, so two clones do not silently
# drive two different browsers' worth of behaviour.
#
# Escape hatch: set PLAYWRIGHT_MCP_NPX to an `npx` of your own. Prefer it to
# editing `.mcp.json`, which is tracked — a modified working tree makes
# `just review-codex` and `just ship` refuse, so a local edit there costs every
# lane in that clone its review.
#
# Usage: scripts/playwright-mcp.sh [extra @playwright/mcp arguments]
set -euo pipefail

# Pinned deliberately (issue #1380): the version the browser arm was smoke-tested
# against. Bump it in one place, for every clone, as a reviewed change.
version="0.0.79"

npx="${PLAYWRIGHT_MCP_NPX:-}"

if [[ -z "$npx" ]] && ! npx="$(command -v npx)"; then
    # No `npx` on PATH. Look where nvm keeps them and take the newest — `sort -V`
    # over paths that differ only in their version component, so v24.19.0 sorts
    # above v9.99.99 the way a version does and a plain sort would not.
    nvm_dir="${NVM_DIR:-$HOME/.nvm}"
    shopt -s nullglob
    candidates=("$nvm_dir"/versions/node/*/bin/npx)
    shopt -u nullglob
    npx=""
    if ((${#candidates[@]} > 0)); then
        mapfile -t candidates < <(printf '%s\n' "${candidates[@]}" | sort -V)
        npx="${candidates[-1]}"
    fi
fi

if [[ -z "$npx" || ! -x "$npx" ]]; then
    cat >&2 <<'MSG'
playwright-mcp: no usable `npx` found.

Install Node (any current LTS) — for example:
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    nvm install --lts

Then run the browsers' one-time install, which needs the owner's sudo once for
the system libraries:
    npx playwright install chromium webkit
    sudo npx playwright install-deps chromium webkit

Or point PLAYWRIGHT_MCP_NPX at an `npx` this script should use.
MSG
    exit 1
fi

# The shebang above needs `node` findable, and the only `node` guaranteed to
# match this `npx` is its own sibling.
node_bin="$(cd -- "$(dirname -- "$npx")" && pwd)"
PATH="$node_bin:$PATH"
export PATH

exec "$npx" -y "@playwright/mcp@${version}" "$@"
