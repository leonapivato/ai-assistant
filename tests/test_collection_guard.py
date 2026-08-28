"""The guard in ``collection_guard``, against the drop it exists to stop (issue #1757).

Both halves are established here, in nested pytest runs over one generated
corpus: **that** pytest drops an abstract binding in silence, and that the guard
turns the same corpus into a failure naming the class. The first half is what
makes the second worth having, and it is asserted rather than assumed because it
is a property of pytest rather than of this repository -- the day it changes
upstream, this is the test that says so.

Nested rather than in-process: the guard is a collection hook, and the thing
being pinned is what a *collection* does. Driving it through pytest's own
collection is the only evidence that the hook is reached at all; calling the
refusal function directly would pin its wording and nothing else. The generated
corpus reproduces PR #1751's shape exactly -- one contract suite, one binding
that implements its abstract fixture and one that does not.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent

#: One conformance suite and two bindings, of which the second is PR #1751's
#: case: an abstract fixture the binding never implements. It is written out
#: rather than defined here because a class of this shape at module scope in a
#: collected file is exactly what the guard refuses -- this module would not
#: collect.
_CORPUS = '''\
"""A contract suite with two bindings, one of them incomplete."""

from abc import ABC, abstractmethod

import pytest


class WidgetContract(ABC):
    @pytest.fixture
    @abstractmethod
    def widget(self) -> int:
        """The subject."""

    def test_the_obligation(self, widget: int) -> None:
        assert widget == 1


class TestBoundWidget(WidgetContract):
    @pytest.fixture
    def widget(self) -> int:
        return 1


class TestUnboundWidget(WidgetContract):
    """Implements nothing, so it stays abstract."""
'''

#: An abstract class under a collected name that carries no test at all, in both
#: spellings: with pytest's explicit ``__test__ = False`` opt-out and without it.
#: Neither takes anything down with it, so neither is this guard's business.
_LOSES_NOTHING = '''\
"""Abstract helpers that carry no test."""

from abc import ABC, abstractmethod

import pytest


class TestSharedBase(ABC):
    __test__ = False

    @pytest.fixture
    @abstractmethod
    def widget(self) -> int:
        """The subject."""


class TestOtherBase(ABC):
    @pytest.fixture
    @abstractmethod
    def gadget(self) -> int:
        """Another subject."""


def test_something_else() -> None:
    assert True
'''

#: The incomplete binding again, this time carrying the opt-out. It loses exactly
#: the same inherited obligations, so the flag changes nothing about it.
_OPTED_OUT_BINDING = _CORPUS.replace(
    '''class TestUnboundWidget(WidgetContract):
    """Implements nothing, so it stays abstract."""''',
    '''class TestUnboundWidget(WidgetContract):
    """Implements nothing, so it stays abstract."""

    __test__ = False''',
)


def _run_nested(corpus: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Collect and run ``corpus`` in a pytest of its own.

    Args:
        corpus: The directory to run over. Its own rootdir, so this repository's
            ``pyproject.toml`` settings are not in play and the run is decided by
            the corpus and the arguments alone.
        *args: Extra pytest arguments.

    Returns:
        The completed process, output captured.
    """
    return subprocess.run(  # noqa: S603  # fixed interpreter, generated corpus
        [sys.executable, "-m", "pytest", str(corpus), "-p", "no:cacheprovider", "-q", *args],
        capture_output=True,
        text=True,
        check=False,
        env={"PYTHONPATH": str(_TESTS), "PATH": "/usr/bin:/bin", "HOME": str(corpus)},
    )


def _write_corpus(tmp_path: Path) -> Path:
    """Write the two-binding corpus into a directory of its own."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "test_widget_bindings.py").write_text(_CORPUS)
    return corpus


def test_pytest_drops_an_abstract_binding_without_a_word(tmp_path: Path) -> None:
    """The mechanism, unguarded: a green run that stopped asserting half of what it held.

    ``PyCollector.istestclass`` answers ``False`` for an abstract class, so no
    item is made from ``TestUnboundWidget`` and nothing anywhere says so. This is
    the whole of issue #1757 in four lines of output: one test collected where
    two were written, and exit 0.
    """
    result = _run_nested(_write_corpus(tmp_path))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "TestUnboundWidget" not in result.stdout + result.stderr


def test_the_guard_fails_that_collection_and_names_the_binding(tmp_path: Path) -> None:
    """The same corpus, with the guard loaded: an error naming the class and the fixture.

    The class name and the unimplemented fixture are both asserted because both
    are what a lane needs. #1757's own case was found by comparing collection
    counts between two runs, which says something is gone and not what -- the
    point of failing here is that the answer arrives with the failure.
    """
    result = _run_nested(_write_corpus(tmp_path), "-p", "collection_guard")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "TestUnboundWidget" in output
    assert "never implemented: widget" in output
    assert "issue #1757" in output


def test_the_guard_leaves_a_complete_binding_alone(tmp_path: Path) -> None:
    """It refuses abstractness, not inheritance: the bound binding still runs.

    Asserted against the corpus with its incomplete binding removed, so the pass
    is the guard's silence rather than a collection that failed before reaching
    the good class.
    """
    corpus = _write_corpus(tmp_path)
    source = corpus / "test_widget_bindings.py"
    source.write_text(source.read_text().split("class TestUnboundWidget")[0])

    result = _run_nested(corpus, "-p", "collection_guard")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout


def test_an_abstract_class_that_carries_no_test_is_not_refused(tmp_path: Path) -> None:
    """The guard's subject is the loss, so a class with nothing to lose is left alone.

    Both spellings are in this corpus: an abstract helper carrying pytest's
    explicit ``__test__ = False`` opt-out, and one carrying nothing. Neither
    inherits a test function, so neither stops contributing anything by being
    abstract, and refusing either would break the ordinary way to write a base
    under a name pytest collects.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "test_helpers.py").write_text(_LOSES_NOTHING)

    result = _run_nested(corpus, "-p", "collection_guard")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
    assert "TestSharedBase" not in result.stdout + result.stderr
    assert "TestOtherBase" not in result.stdout + result.stderr


def test_an_opted_out_binding_that_loses_obligations_is_still_refused(tmp_path: Path) -> None:
    """``__test__ = False`` does not buy a binding out of this: it removes the same tests.

    pytest reads the flag in ``Class.collect``, one step past the abstractness
    check, and returns no items for the class either way. So an incomplete
    binding carrying it loses exactly the inherited obligations an incomplete
    binding without it loses -- and the suite stays green, because
    `tests/core/test_protocol_triad.py` needs only *a* binding per Protocol, not
    every one. The flag cannot change the answer where there is something to
    lose, which is why the guard does not ask about it.
    """
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "test_widget_bindings.py").write_text(_OPTED_OUT_BINDING)

    result = _run_nested(corpus, "-p", "collection_guard")
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "TestUnboundWidget" in output
    assert "would stop running: test_the_obligation" in output
