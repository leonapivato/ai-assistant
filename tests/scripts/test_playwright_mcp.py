"""Tests for ``scripts/playwright-mcp.sh`` — the launcher `.mcp.json` names (issue #1403).

This script is the one indirection that makes a committed ``.mcp.json`` portable,
and every part of it is a workaround for a failure that arrived at *someone
else's* machine: `npx` missing from an editor-spawned environment (#1380), a
`node` absent from `PATH` under an `npx` named absolutely, a snapshot written
into the clone that costs a lane its review, and a branded-Chrome default that
fails at the first tool call rather than at startup. Nothing in the gate runs
it, so until now nothing noticed when one of those regressed — the gap was
raised as `major` by three separate adversarial rounds on PR #1402 and waived
each time on the fence.

Six resolution paths are pinned: `PLAYWRIGHT_MCP_NPX`, an `npx` on `PATH`, the
nvm fallback when there is none, the version ordering that picks `v24.19.0` over
`v9.99.99`, the resolved `node`'s directory going onto `PATH` before the exec,
and the no-usable-`npx` diagnostic — which is also issue #1408, because under
`set -u` an unset `HOME` used to abort the script with bash's own
``HOME: unbound variable`` before that guidance could print.

The ordering case carries a mutation check beside it: the fixture is re-run
against a deliberately broken `version_key`, and must select the *wrong* version.
A comparison test that passes under both implementations pins nothing, and this
one would — `v24.19.0` beats `v9.99.99` on a numeric key and loses on a string.

Driven as a subprocess with a fake `npx` and a fake nvm tree, under a fully
replaced environment (the `env -i` of the reproductions), so no developer's real
Node installation is reachable and none of it is required to be present.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

_SCRIPT = Path(__file__).parents[2] / "scripts" / "playwright-mcp.sh"
_BASH = shutil.which("bash") or "/bin/bash"

# The pinned server version, read from the script rather than restated, so a
# reviewed bump does not fail these tests — what is pinned is that the pin is
# what actually reaches `npx`, which is the property #1380 bought.
_VERSION_PIN = re.search(r'(?m)^version="([^"]+)"$', _SCRIPT.read_text())
assert _VERSION_PIN is not None, "scripts/playwright-mcp.sh no longer pins a version"
_VERSION = _VERSION_PIN.group(1)

# A minimal PATH: the script needs `dirname`, `cd` and `pwd`, and must NOT be
# able to see a developer's real `npx`.
_SYSTEM_PATH = "/usr/bin:/bin"

# The launcher's documented `--output-dir` fallback, and a target to override it
# with. Both are compared against a rendered command line; nothing here creates
# or writes to either, because no `npx` that could is ever real in these tests.
_TMP = "/tmp"  # noqa: S108  # compared as a string, never created
_OVERRIDE_DIR = "/var/tmp/playwright-mcp-override"  # noqa: S108  # ditto


def _fake_npx(path: Path, tag: str) -> Path:
    """Write an executable stub that reports how it was invoked.

    It prints its own tag, the `PATH` it inherited, whether a `node` is findable
    on that `PATH`, and one line per argument — everything the script's four
    documented behaviours are decided by.

    Args:
        path: Where to write it.
        tag: The identity it reports, so a test can say *which* npx ran.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f'echo "npx={tag}"\n'
        'echo "PATH=$PATH"\n'
        'echo "node=$(command -v node || echo none)"\n'
        'for a in "$@"; do echo "arg=$a"; done\n'
    )
    path.chmod(0o755)
    return path


def _fake_node(path: Path) -> Path:
    """Write an executable `node` stub beside a fake `npx`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def _nvm_tree(root: Path, *versions: str) -> Path:
    """Build ``root/versions/node/<v>/bin/{npx,node}`` for each version given.

    Args:
        root: The ``NVM_DIR`` to build under.
        *versions: Directory names, e.g. ``v24.19.0``.

    Returns:
        ``root``.
    """
    for version in versions:
        bin_dir = root / "versions" / "node" / version / "bin"
        _fake_npx(bin_dir / "npx", version)
        _fake_node(bin_dir / "node")
    return root


def _env(**overrides: str) -> dict[str, str]:
    """The environment for a run: a system `PATH` and nothing else by default.

    Nothing is inherited — not `HOME`, not `NVM_DIR`, not `TMPDIR` — because the
    environment an editor's MCP launcher provides is very nearly this one, and
    that is the environment every failure here was reported from.

    Args:
        **overrides: Variables to add.

    Returns:
        The environment mapping.
    """
    return {"PATH": _SYSTEM_PATH, **overrides}


def _launch(
    cwd: Path,
    env: Mapping[str, str],
    *args: str,
    script: Path = _SCRIPT,
) -> subprocess.CompletedProcess[str]:
    """Run the launcher and capture everything it and its `npx` printed."""
    return subprocess.run(  # noqa: S603  # resolved bash, in-repo script
        [_BASH, str(script), *args],
        cwd=str(cwd),
        env=dict(env),
        capture_output=True,
        text=True,
        check=False,
    )


def _fields(result: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """The stub's non-argument report lines, as a mapping."""
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in result.stdout.splitlines()
        if not line.startswith("arg=") and "=" in line
    }


def _argv(result: subprocess.CompletedProcess[str]) -> list[str]:
    """The arguments the stub `npx` was exec'd with, in order."""
    return [
        line.removeprefix("arg=") for line in result.stdout.splitlines() if line.startswith("arg=")
    ]


def _option(argv: list[str], name: str) -> str | None:
    """The value following ``name`` in ``argv``, or ``None`` when absent."""
    return argv[argv.index(name) + 1] if name in argv else None


# --------------------------------------------------------------------------- #
# Path 1 — finding an npx at all                                              #
# --------------------------------------------------------------------------- #


def test_an_npx_on_path_is_the_one_exec_d(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")

    result = _launch(tmp_path, _env(PATH=f"{bin_dir}:{_SYSTEM_PATH}"))

    assert result.returncode == 0, result.stderr
    assert _fields(result)["npx"] == "on-path"


def test_the_pinned_server_version_is_what_reaches_npx(tmp_path: Path) -> None:
    # The pin is the whole of issue #1380's fix: the browser arm was smoke-tested
    # against one version, and a floating `@latest` is what it was traded for.
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")

    argv = _argv(_launch(tmp_path, _env(PATH=f"{bin_dir}:{_SYSTEM_PATH}")))

    assert argv[0] == "-y"
    assert argv[1] == f"@playwright/mcp@{_VERSION}"


def test_an_npx_outside_path_is_found_under_nvm(tmp_path: Path) -> None:
    # The failure #1380 records: an MCP server is spawned by the editor's own
    # launcher, so an nvm Node — a shell function sourced by ~/.bashrc — is
    # simply not on the PATH this script inherits.
    nvm = _nvm_tree(tmp_path / "nvm", "v24.19.0")

    result = _launch(tmp_path, _env(NVM_DIR=str(nvm)))

    assert result.returncode == 0, result.stderr
    assert _fields(result)["npx"] == "v24.19.0"


def test_the_nvm_directory_is_found_under_home_when_nvm_dir_is_unset(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _nvm_tree(home / ".nvm", "v24.19.0")

    result = _launch(tmp_path, _env(HOME=str(home)))

    assert result.returncode == 0, result.stderr
    assert _fields(result)["npx"] == "v24.19.0"


def test_nvm_dir_wins_over_home(tmp_path: Path) -> None:
    home = tmp_path / "home"
    _nvm_tree(home / ".nvm", "v24.19.0")
    _nvm_tree(tmp_path / "elsewhere", "v22.1.0")

    result = _launch(tmp_path, _env(HOME=str(home), NVM_DIR=str(tmp_path / "elsewhere")))

    assert _fields(result)["npx"] == "v22.1.0"


def test_a_non_executable_candidate_is_not_selected(tmp_path: Path) -> None:
    nvm = _nvm_tree(tmp_path / "nvm", "v24.19.0")
    (nvm / "versions" / "node" / "v24.19.0" / "bin" / "npx").chmod(0o644)

    result = _launch(tmp_path, _env(NVM_DIR=str(nvm)))

    assert result.returncode == 1
    assert "no usable `npx` found" in result.stderr


# --------------------------------------------------------------------------- #
# Path 2 — version ordering, with the mutation check that makes it a test      #
# --------------------------------------------------------------------------- #


def test_the_newest_nvm_version_wins_numerically_not_lexically(tmp_path: Path) -> None:
    # v24.19.0 > v9.99.99 as versions, and `<` as strings. The concrete failure
    # the round-3 review of PR #1402 named.
    nvm = _nvm_tree(tmp_path / "nvm", "v9.99.99", "v24.19.0")

    result = _launch(tmp_path, _env(NVM_DIR=str(nvm)))

    assert result.returncode == 0, result.stderr
    assert _fields(result)["npx"] == "v24.19.0"


def test_that_ordering_case_would_catch_a_string_comparison(tmp_path: Path) -> None:
    # The mutation check. `version_key` exists only so that this comparison is
    # numeric; with its zero-padding removed the key is the raw component, "9"
    # sorts above "24", and the fixture above must select the wrong one. If it
    # does not, that test is passing for a reason other than the ordering.
    broken = tmp_path / "broken.sh"
    source = _SCRIPT.read_text()
    mutated = source.replace("printf '%05d' \"${part:-0}\"", "printf '%s' \"${part:-0}\"")
    assert mutated != source, "version_key no longer pads; update the mutation"
    broken.write_text(mutated)
    nvm = _nvm_tree(tmp_path / "nvm", "v9.99.99", "v24.19.0")

    result = _launch(tmp_path, _env(NVM_DIR=str(nvm)), script=broken)

    assert _fields(result)["npx"] == "v9.99.99"


def test_a_pre_release_tail_orders_without_erroring(tmp_path: Path) -> None:
    # `printf %05d` on "0-rc" is an error, not a comparison, so the tail is
    # dropped. v24.0.0-rc.1 still has to beat v23.9.9.
    nvm = _nvm_tree(tmp_path / "nvm", "v23.9.9", "v24.0.0-rc.1")

    result = _launch(tmp_path, _env(NVM_DIR=str(nvm)))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert _fields(result)["npx"] == "v24.0.0-rc.1"


# --------------------------------------------------------------------------- #
# Path 3 — the resolved node goes on PATH before the exec                      #
# --------------------------------------------------------------------------- #


def test_the_resolved_nodes_directory_is_prepended_to_path(tmp_path: Path) -> None:
    # Not belt-and-braces: nvm's `npx` is a JavaScript file whose shebang is
    # `#!/usr/bin/env node`, so naming it by absolute path is not sufficient.
    # This is the regression that reproduces #1380 exactly.
    nvm = _nvm_tree(tmp_path / "nvm", "v24.19.0")
    bin_dir = nvm / "versions" / "node" / "v24.19.0" / "bin"

    fields = _fields(_launch(tmp_path, _env(NVM_DIR=str(nvm))))

    assert fields["PATH"].split(":")[0] == str(bin_dir)
    assert fields["node"] == str(bin_dir / "node")


# --------------------------------------------------------------------------- #
# Path 4 — PLAYWRIGHT_MCP_NPX                                                  #
# --------------------------------------------------------------------------- #


def test_playwright_mcp_npx_wins_over_an_npx_on_path(tmp_path: Path) -> None:
    on_path = tmp_path / "bin"
    _fake_npx(on_path / "npx", "on-path")
    chosen = _fake_npx(tmp_path / "chosen" / "npx", "chosen")

    fields = _fields(
        _launch(tmp_path, _env(PATH=f"{on_path}:{_SYSTEM_PATH}", PLAYWRIGHT_MCP_NPX=str(chosen)))
    )

    assert fields["npx"] == "chosen"


def test_a_playwright_mcp_npx_that_is_not_executable_refuses(tmp_path: Path) -> None:
    dud = tmp_path / "not-executable"
    dud.write_text("#!/bin/sh\n")

    result = _launch(tmp_path, _env(PLAYWRIGHT_MCP_NPX=str(dud)))

    assert result.returncode == 1
    assert "no usable `npx` found" in result.stderr


# --------------------------------------------------------------------------- #
# The defaults the launcher exists to supply                                   #
# --------------------------------------------------------------------------- #


def test_the_output_directory_is_outside_the_clone(tmp_path: Path) -> None:
    # The server's own default is `.playwright-mcp/` under the working directory,
    # i.e. inside the clone — and an untracked directory is a dirty tree, which
    # `just review-codex` and `just ship` both refuse. Driving the page would
    # cost the lane its review.
    clone = tmp_path / "clone"
    clone.mkdir()
    scratch = tmp_path / "scratch"
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")

    argv = _argv(_launch(clone, _env(PATH=f"{bin_dir}:{_SYSTEM_PATH}", TMPDIR=str(scratch))))

    output_dir = _option(argv, "--output-dir")
    assert output_dir == str(scratch / "playwright-mcp")
    assert not Path(output_dir).is_relative_to(clone)


def test_the_output_directory_falls_back_to_tmp_and_is_overridable(tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    clone.mkdir()
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")
    path = f"{bin_dir}:{_SYSTEM_PATH}"

    default = _argv(_launch(clone, _env(PATH=path)))
    chosen = _argv(_launch(clone, _env(PATH=path, PLAYWRIGHT_MCP_OUTPUT_DIR=_OVERRIDE_DIR)))

    assert _option(default, "--output-dir") == f"{_TMP}/playwright-mcp"
    assert _option(chosen, "--output-dir") == _OVERRIDE_DIR


def test_a_browser_this_repository_installs_is_asked_for_and_is_overridable(tmp_path: Path) -> None:
    # The server's own default is branded Chrome, which a Linux dev box generally
    # does not have — and it fails at the FIRST TOOL CALL, not at startup.
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")
    path = f"{bin_dir}:{_SYSTEM_PATH}"

    default = _argv(_launch(tmp_path, _env(PATH=path)))
    chosen = _argv(_launch(tmp_path, _env(PATH=path, PLAYWRIGHT_MCP_BROWSER="webkit")))

    assert _option(default, "--browser") == "chromium"
    assert _option(chosen, "--browser") == "webkit"


def test_the_callers_own_flags_come_after_the_defaults(tmp_path: Path) -> None:
    # A later occurrence wins, so a caller's `--browser` overrides rather than
    # colliding with a default they did not ask for.
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")

    argv = _argv(_launch(tmp_path, _env(PATH=f"{bin_dir}:{_SYSTEM_PATH}"), "--browser", "webkit"))

    assert argv.index("--browser") < argv.index("--browser", argv.index("--browser") + 1)
    assert argv[-2:] == ["--browser", "webkit"]


def test_a_subcommand_is_not_given_the_servers_options(tmp_path: Path) -> None:
    # The server's subcommands take none of the server's options: prepending them
    # fails outright with `error: unknown option '--browser'`, which would break
    # the very command this script's own guidance tells a lane to run.
    bin_dir = tmp_path / "bin"
    _fake_npx(bin_dir / "npx", "on-path")

    argv = _argv(
        _launch(
            tmp_path,
            _env(PATH=f"{bin_dir}:{_SYSTEM_PATH}"),
            "install-browser",
            "chrome-for-testing",
        )
    )

    assert argv == ["-y", f"@playwright/mcp@{_VERSION}", "install-browser", "chrome-for-testing"]


# --------------------------------------------------------------------------- #
# The diagnostic — and issue #1408, which made it unreachable                  #
# --------------------------------------------------------------------------- #


def test_an_empty_environment_reaches_the_guidance_rather_than_aborting(tmp_path: Path) -> None:
    # Issue #1408. `nvm_dir="${NVM_DIR:-$HOME/.nvm}"` under `set -u` aborted with
    # bash's own `HOME: unbound variable` — so the one message naming the install
    # commands and PLAYWRIGHT_MCP_NPX was unreachable in exactly the environment
    # that needed it: the near-empty one an editor's launcher provides.
    result = _launch(tmp_path, _env())

    assert result.returncode == 1
    assert "HOME: unbound variable" not in result.stderr
    assert "playwright-mcp: no usable `npx` found." in result.stderr
    assert "PLAYWRIGHT_MCP_NPX" in result.stderr
    assert "install-browser chrome-for-testing" in result.stderr


def test_a_set_but_empty_home_or_nvm_dir_reaches_the_guidance_too(tmp_path: Path) -> None:
    # `${VAR:-default}` treats set-but-empty as absent, so these take the same
    # branch as unset — which is worth pinning separately because a launcher that
    # exports an empty HOME is not the same environment as one that exports none,
    # and only one of the two was ever reproduced.
    #
    # (What is NOT asserted, because a test cannot observe it without writing to
    # `/`: with neither variable usable the glob is skipped rather than aimed at
    # `/.nvm`. Its observable consequence — this diagnostic, this exit status —
    # is what is pinned here and in the test above.)
    for env in (_env(HOME=""), _env(NVM_DIR=""), _env(HOME="", NVM_DIR="")):
        result = _launch(tmp_path, env)

        assert result.returncode == 1, env
        assert "HOME: unbound variable" not in result.stderr
        assert "playwright-mcp: no usable `npx` found." in result.stderr
