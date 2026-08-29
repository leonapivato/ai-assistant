"""One browser per run is enforced and not merely arranged for (ADR-0216 §3).

§3 is normative: "One ``pytest`` run launches at most one browser process at a
time, whether it is serial or distributed: a distributed run launches no more
browsers than a serial one." The browser is a session-scoped fixture, so the
clause holds exactly when every case of the layer lands on one worker — which the
layer's ``xdist_group`` marker asks for, and which only ``loadgroup`` scheduling
honours.

``pyproject.toml``'s ``addopts`` selects that mode, and ``addopts`` is the weakest
source of an option: a ``--dist`` on a command line beats it, and so does one in
``PYTEST_ADDOPTS``. Under ``worksteal`` the layer scatters, each worker launches a
Chromium, **and the run is still green** — which is why the refusal in
``tests/conftest.py`` exists and why it is pinned here rather than left to be
inspected. Adversarial review has now twice reasoned about when that hook runs
relative to xdist's ``-n`` resolution, once wrongly; this module answers the
question by running it.

**Nested rather than in-process**, for ``tests/test_collection_guard.py``'s reason:
the subject is *when* a configuration hook fires against another plugin's, and
calling the hook directly would pin its wording and nothing else. Each run is
``--collect-only``, so the refused one never reaches a worker and the admitted one
spawns none.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

#: The repository root, from which the nested runs read this project's own
#: ``pyproject.toml`` and ``tests/conftest.py``. Both are the subject: the ini
#: supplies the mode, the conftest refuses the overrides.
_ROOT = Path(__file__).resolve().parents[3]

#: What a nested run collects. The smallest module in the corpus, because nothing
#: here is about what it holds — only about whether the run is allowed to start.
_TARGET = "tests/test_smoke.py"

#: pytest's exit status for a usage error, which is what a refused mode is.
_USAGE_ERROR = 4


def _collect(*args: str) -> subprocess.CompletedProcess[str]:
    """Try to collect one module in a pytest of its own.

    Args:
        *args: Extra pytest arguments, appended after the target so a ``--dist``
            among them lands where a developer's would: last, beating ``addopts``.

    Returns:
        The completed process, output captured.
    """
    return subprocess.run(  # noqa: S603  # fixed interpreter, fixed arguments
        [
            sys.executable,
            "-m",
            "pytest",
            _TARGET,
            "--collect-only",
            "-p",
            "no:cacheprovider",
            "-q",
            *args,
        ],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
        # A bare environment, so no `PYTEST_ADDOPTS` of the outer run reaches the
        # inner one and changes the mode under test (issue #1243's hazard, here as
        # a way for this test to lie rather than for an anchor to).
        env={"PATH": "/usr/bin:/bin", "HOME": str(_ROOT)},
    )


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["worksteal", "load", "loadfile", "each"])
def test_a_distributed_run_that_would_scatter_the_layer_is_refused(mode: str) -> None:
    """Every distribution mode but ``loadgroup`` is refused under ``-n``.

    ``load`` and ``worksteal`` ignore ``xdist_group`` outright; ``loadfile`` keeps a
    *module* together, which is a different promise from the layer's and one the
    layer already outgrew at two modules; ``each`` sends every test to every worker.
    None of them can hold §3's clause, so none of them is admitted.

    **And it is refused at configuration, before a worker exists**, which is the
    half that is easy to get wrong: xdist resolves ``-n auto`` into its worker
    specification in ``pytest_cmdline_main``, and that runs before the
    ``pytest_configure`` hooks. So the guard sees the resolved run.
    """
    refused = _collect("-n", "auto", "--dist", mode)

    assert refused.returncode == _USAGE_ERROR, refused.stdout + refused.stderr
    assert "ADR-0216 §3" in refused.stderr + refused.stdout


@pytest.mark.integration
def test_the_group_honouring_mode_and_a_serial_run_are_both_admitted() -> None:
    """The two shapes that hold the clause are left alone.

    Distributed under ``loadgroup``, which is what ``addopts`` selects and what the
    layer's group needs; and serial, where ``addopts``' mode is inert because there
    are no workers to distribute to. A guard that refused either would have made the
    ordinary run of this suite impossible, which is the failure worth pinning beside
    the refusal.
    """
    grouped = _collect("-n", "2", "--dist", "loadgroup")
    serial = _collect()

    assert grouped.returncode == 0, grouped.stdout + grouped.stderr
    assert serial.returncode == 0, serial.stdout + serial.stderr
