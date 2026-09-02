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
# **This is the coding harness's browser, not the assistant's tool.** Nothing
# under `src/ai_assistant` launches this server, imports it, or hands it anything;
# an agent's own editor does, to look at a page served on loopback by a gateway
# bound over a fake engine. ADR-0147 §4's "no MCP server is connected to ... until
# a ratified ADR authorises it" is a rule about *this system* connecting one as a
# tool integration, for the reason it states — "a program this repository did not
# write becomes a recipient of user data", handed a tool name and an
# `ActionRequest.parameters` mapping. There is no such call here, no
# `ToolDefinition` is built from anything this server describes, and no memory,
# belief, context facet or credential is within its reach. It sits where
# `just review-codex` sits: developer tooling, which is why ADR-0017 §1 as
# ADR-0124 §1 replaces it — an enumeration of the components of `ai_assistant`
# that may transmit — is not reached either.
#
# Four things it does that a bare `npx` in `.mcp.json` does not:
#
#   1. It looks past PATH for `npx`. An MCP server is spawned by the editor's own
#      launcher, not from an interactive shell, so a Node installed by nvm — a
#      shell function sourced by ~/.bashrc — is frequently absent from that
#      environment. `ENOENT: npx` is what that looks like, and it is the failure
#      issue #1380 records.
#   2. It puts the resolved `node` on PATH before exec'ing. This is not
#      belt-and-braces: nvm's `npx` is a JavaScript file whose shebang is
#      `#!/usr/bin/env node`, so naming it by absolute path is NOT sufficient —
#      in an environment without `node` on PATH it fails with
#      `env: 'node': No such file or directory`, having never run a line.
#   3. It writes the server's output files OUTSIDE the repository. The default is
#      `.playwright-mcp/` under the working directory, i.e. inside the clone: a
#      console log and a snapshot land there on the first navigation, and an
#      untracked directory is a dirty tree, which `just review-codex` and
#      `just ship` both refuse. Driving the page would cost the lane its review.
#   4. It asks for a browser this repository actually installs. The server's own
#      default is branded Chrome (`/opt/google/chrome/chrome`), which a Linux dev
#      box generally does not have, and the failure arrives at the first tool
#      call rather than at startup.
#
# **Install the browsers through THIS script**, so the builds match the pinned
# server rather than whatever a stray `npx playwright` resolved — the two are
# versioned separately and a mismatch reads as "Browser is not installed" while
# `~/.cache/ms-playwright` visibly holds one:
#
#     scripts/playwright-mcp.sh install-browser chrome-for-testing
#     scripts/playwright-mcp.sh install-browser webkit
#
# The system libraries under those browsers need the owner's sudo once:
# `sudo npx playwright install-deps chromium webkit`.
#
# Every default below is overridable, and none of them by editing a tracked file:
# `.mcp.json` and this script are both committed, and a modified working tree
# costs every lane in that clone its review. Pass a flag after the ones here — a
# later `--browser` or `--output-dir` wins — or set PLAYWRIGHT_MCP_NPX,
# PLAYWRIGHT_MCP_BROWSER or PLAYWRIGHT_MCP_OUTPUT_DIR.
#
# Usage: scripts/playwright-mcp.sh [extra @playwright/mcp arguments]
set -euo pipefail

# Pinned deliberately (issue #1380): the version the browser arm was smoke-tested
# against. Bump it in one place, for every clone, as a reviewed change.
version="0.0.79"

npx="${PLAYWRIGHT_MCP_NPX:-}"

# A sortable key for one nvm directory name, so that v24.19.0 ranks above
# v9.99.99 the way a version does and a plain string comparison does not. Written
# out rather than delegated to `sort -V`, and compared with `>` rather than
# collected by `mapfile`, because both of those are absent from what macOS ships:
# BSD `sort` has no `-V`, and the system Bash is 3.2, which has neither `mapfile`
# nor a negative array index. A developer with nvm-installed Node is exactly who
# reaches this branch, so a Bash-4-only fallback would fail precisely the case it
# exists for.
version_key() {
    local name="${1#v}" part key=""
    local IFS=.
    for part in $name; do
        # A pre-release tail (`24.0.0-rc.1`) is dropped rather than parsed: it
        # only has to order consistently, and `printf %05d` on a non-number is an
        # error, not a comparison.
        part="${part%%[!0-9]*}"
        key="$key$(printf '%05d' "${part:-0}")"
    done
    printf '%s' "$key"
}

if [[ -z "$npx" ]] && ! npx="$(command -v npx)"; then
    # No `npx` on PATH. Look where nvm keeps them, and take the newest.
    #
    # HOME is read as `${HOME:-}` and not `$HOME` (issue #1408). An MCP server is
    # spawned by the editor's own launcher, and that environment can be very
    # nearly empty — the same reason this branch exists at all. Under `set -u` a
    # bare `$HOME` there does not fall through to the guidance below: bash aborts
    # the script on the spot with `HOME: unbound variable`, so the one message
    # naming the install commands and PLAYWRIGHT_MCP_NPX was unreachable in
    # exactly the environment that needed it.
    #
    # With neither NVM_DIR nor HOME set there is no directory to search, so the
    # search is skipped rather than aimed at `/.nvm` — a real path, and one no
    # caller asked for.
    nvm_dir="${NVM_DIR:-}"
    if [[ -z "$nvm_dir" && -n "${HOME:-}" ]]; then
        nvm_dir="$HOME/.nvm"
    fi
    npx=""
    best_key=""
    if [[ -n "$nvm_dir" ]]; then
        shopt -s nullglob
        for candidate in "$nvm_dir"/versions/node/*/bin/npx; do
            [[ -x "$candidate" ]] || continue
            candidate_dir="${candidate%/bin/npx}"
            candidate_key="$(version_key "${candidate_dir##*/}")"
            if [[ -z "$npx" || "$candidate_key" > "$best_key" ]]; then
                npx="$candidate"
                best_key="$candidate_key"
            fi
        done
        shopt -u nullglob
    fi
fi

if [[ -z "$npx" || ! -x "$npx" ]]; then
    cat >&2 <<'MSG'
playwright-mcp: no usable `npx` found.

Install Node (any current LTS) — for example:
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
    nvm install --lts

Then install the browsers THROUGH THIS SCRIPT, so their builds match the pinned
server rather than whatever a stray `npx playwright` resolves:
    scripts/playwright-mcp.sh install-browser chrome-for-testing
    scripts/playwright-mcp.sh install-browser webkit

The system libraries under them need the owner's sudo once:
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

# A first argument that is not a flag is a SUBCOMMAND — `install-browser` is the
# one this script's own guidance names — and the server's subcommands take none
# of the server's options: prepending them there fails outright with
# `error: unknown option '--browser'`. So the defaults are added to a server run
# and to nothing else, which is also the only run they mean anything for.
if (($# > 0)) && [[ $1 != -* ]]; then
    exec "$npx" -y "@playwright/mcp@${version}" "$@"
fi

# Anything the caller passes comes AFTER these, so a `--browser` or
# `--output-dir` of their own wins on the last occurrence rather than colliding
# with a default they did not ask for.
#
# `--output-dir` is out of the repository because the server's own default is
# `.playwright-mcp/` under the working directory: one navigation leaves a console
# log and a snapshot inside the clone, and that untracked directory is a dirty
# tree that `just review-codex` and `just ship` both refuse.
#
# `--browser` is named because the server's own default is branded Chrome, which
# a Linux dev box generally does not have — and it fails at the first tool call,
# not at startup, so the server connects and then cannot do anything.
browser="${PLAYWRIGHT_MCP_BROWSER:-chromium}"
output_dir="${PLAYWRIGHT_MCP_OUTPUT_DIR:-${TMPDIR:-/tmp}/playwright-mcp}"

exec "$npx" -y "@playwright/mcp@${version}" \
    --browser "$browser" --output-dir "$output_dir" "$@"
