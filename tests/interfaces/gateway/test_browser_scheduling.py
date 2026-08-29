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
calling the hook directly would pin its wording and nothing else. The runs about
the refusal are ``--collect-only``, so the refused ones never reach a worker and
the admitted one spawns none.

**Three questions, and it takes all three to hold the clause.** That every mode
but ``loadgroup`` is refused; that a shared group really is answered by one
worker, so one session-scoped resource is built once; and that every case of the
layer really declares that group. The middle one is asked of a generated corpus in
the layer's shape rather than of the layer itself — a nested run of the real
modules would hold a second Chromium inside a run that may already hold one, which
is the memory §3 exists to bound.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

#: The repository root, from which the nested runs read this project's own
#: ``pyproject.toml`` and ``tests/conftest.py``. Both are the subject: the ini
#: supplies the mode, the conftest refuses the overrides.
_ROOT = Path(__file__).resolve().parents[3]

#: What a nested run collects. The smallest module in the corpus, because nothing
#: here is about what it holds — only about whether the run is allowed to start.
_TARGET = "tests/test_smoke.py"

#: pytest's exit status for a usage error, which is what a refused mode is.
_USAGE_ERROR = 4

#: The group every case of the layer declares. It is what makes ``loadgroup`` put
#: them all on one worker, and therefore behind one browser.
_GROUP = "gateway_browser"

#: The fixture that launches the browser, and therefore the only honest definition
#: of "the layer": a case that requests it can build one, and a case that does not
#: cannot. Auditing the ``browser`` marker by selecting on the ``browser`` marker
#: would be blind to the one module that matters — the one that declares neither.
_BROWSER_FIXTURE = "gateway_browser"

#: A corpus in the layer's own shape: two modules under one module-level
#: ``xdist_group``, and one session-scoped resource that records which process
#: built it.
#:
#: It stands in for the layer rather than being it, deliberately. Driving the real
#: modules distributed from inside this suite would put a second Chromium in a
#: process tree that may already hold one, which is the memory ADR-0216 §3 exists
#: to bound. What this establishes is the mechanism the real modules rest on — two
#: modules sharing a group are answered by one worker, so a session-scoped resource
#: is built once — and the case below establishes the other half, that the layer
#: declares that group on every case it has.
_GROUPED_MODULE = '''\
"""One half of a two-module group."""

import pytest

pytestmark = [pytest.mark.xdist_group("{group}")]


def test_first(costly: str) -> None:
    assert costly == "built"


def test_second(costly: str) -> None:
    assert costly == "built"
'''

#: The corpus's conftest. Every case takes ``costly``, so the file it appends to
#: holds one line per process that built it -- which is the count under test.
_GROUPED_CONFTEST = '''\
"""A session-scoped resource that says which process built it."""

import os

import pytest


@pytest.fixture(scope="session")
def costly() -> str:
    with open(os.environ["GROUP_RECORD"], "a") as record:
        record.write(f"{os.getpid()}\\n")
    return "built"
'''


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


def _group_of(item: pytest.Item) -> str | None:
    """The ``xdist_group`` name an item declares, or ``None``."""
    marker = item.get_closest_marker("xdist_group")
    if marker is None:
        return None
    if marker.args:
        return str(marker.args[0])
    return str(marker.kwargs.get("name", "default"))


def _built_by(record: Path) -> Sequence[str]:
    """The distinct processes that built the corpus's session-scoped resource."""
    return sorted({line for line in record.read_text().splitlines() if line.strip()})


@pytest.mark.integration
def test_two_modules_sharing_a_group_are_answered_by_one_worker(tmp_path: Path) -> None:
    """The mechanism the layer's ``xdist_group`` rests on, run rather than assumed.

    Four cases across two modules, one group, two workers, one session-scoped
    resource — and the resource is built once, by one process. That is what makes
    "The browser is started once and shared by every case in the layer" (ADR-0216
    §3) true of a distributed run and not only of a serial one.

    In the layer's shape rather than in the layer itself, for the reason
    :data:`_GROUPED_MODULE` gives: a nested run of the real modules would hold a
    second browser inside a run that may already hold one.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "conftest.py").write_text(_GROUPED_CONFTEST)
    (corpus / "test_one.py").write_text(_GROUPED_MODULE.format(group=_GROUP))
    (corpus / "test_two.py").write_text(_GROUPED_MODULE.format(group=_GROUP))
    record = tmp_path / "built-by"
    record.touch()

    run = subprocess.run(  # noqa: S603  # fixed interpreter, generated corpus
        [
            sys.executable,
            "-m",
            "pytest",
            str(corpus),
            "-n",
            "2",
            "--dist",
            "loadgroup",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=corpus,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "HOME": str(corpus), "GROUP_RECORD": str(record)},
    )

    assert run.returncode == 0, run.stdout + run.stderr
    assert "4 passed" in run.stdout
    assert len(_built_by(record)) == 1, run.stdout


def test_every_case_that_takes_the_browser_carries_both_of_the_layers_markers(
    request: pytest.FixtureRequest,
) -> None:
    """No case that takes the browser may sit outside the group that shares it.

    The case above establishes that a shared group is answered by one worker; this
    is the other half — that the layer actually declares it, on every case, and one
    group rather than two. A module added to the layer without the marker, or under
    a second group name, scatters exactly as ``worksteal`` would, and ADR-0216 §3
    stops holding while every test stays green.

    **The layer is identified by what a case asks for, not by the marker being
    audited.** Adversarial review, round 4, ``major``: filtering on
    ``pytest.mark.browser`` made this blind to precisely the module that would break
    the clause — one that requests the browser and declares neither marker was not in
    the set, so it could take a second worker's session fixture and a second Chromium
    with this green. Asking which cases request ``gateway_browser`` cannot miss one:
    a case that does not request it launches nothing.

    The ``browser`` marker is asserted here for the same reason and in the same
    place, because §3 obliges it of every module of the layer ("Each such module also
    carries a second marker … naming it as a browser drive") and nothing else checks
    that a drive declares itself.

    Read off **this run's own collection**, so a module is covered the day it is
    written rather than the day someone remembers to list it here. A run narrowed
    away from the layer collects no such case and this says nothing about one, which
    is worth saying beside the fact that both of ADR-0136 §1's anchors run the whole
    suite.
    """
    layer = [
        item
        for item in request.session.items
        if _BROWSER_FIXTURE in getattr(item, "fixturenames", ())
    ]

    assert [item.nodeid for item in layer if _group_of(item) != _GROUP] == []
    assert [item.nodeid for item in layer if item.get_closest_marker("browser") is None] == []
