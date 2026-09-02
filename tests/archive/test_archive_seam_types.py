"""The seam split is a ``mypy`` property, not a convention (ADR-0225 §10, §13 item 2).

§13 item 2 asks for these as **type-level** tests rather than runtime ones, and the
distinction is the whole point: nothing at runtime stops a holder calling a method
that exists on the object it was passed — one concrete satisfies both Protocols. What
§10 buys is that the *declared type* does not carry the member, so the call does not
type-check, and the only way to assert that is to run the type checker.

So this module runs ``mypy`` over one snippet carrying every case at once and reads
what it reports. One run rather than four, because the cost is the run and not the
snippet.

**No case asserts that the concrete archive is rejected at either parameter**, and
§10 says why: a value declared ``TranscriptArchive`` does not satisfy
``TranscriptArchiveWriter`` — it has no ``append`` — so handing the engine's seam to
the write site fails; what still type-checks is handing the **concrete**, which
satisfies both. That is the composition root's discipline and
``tests/app/test_composition.py`` asserts it directly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

pytestmark = pytest.mark.integration

_ROOT: Final = Path(__file__).resolve().parents[2]

#: Every case, in one file, each on its own named function so a report line can be
#: attributed. The imports are real; only the bodies are the subject.
_SNIPPET: Final = '''
from datetime import timedelta

from ai_assistant.core.protocols import (
    ConversationStore,
    MemoryStore,
    TranscriptArchive,
    TranscriptArchiveWriter,
)
from ai_assistant.orchestration.conversations import ConversationLifecycle


async def read_on_the_writer_seam(writer: TranscriptArchiveWriter) -> object:
    """§4: the one component that writes an entry cannot read one back."""
    return await writer.search("anything")


async def enumerate_on_the_writer_seam(writer: TranscriptArchiveWriter) -> object:
    """The same, over the read that is the archive's export."""
    return await writer.entries()


async def append_on_the_archive_seam(archive: TranscriptArchive) -> None:
    """§1 reserves writing to capture, so the engine's seam carries no append."""
    await archive.append(None)


def a_composition_omitting_the_writer_seam(
    conversations: ConversationStore, memory: MemoryStore, retention: timedelta | None
) -> ConversationLifecycle:
    """§10: "a composition that omits it does not type-check"."""
    return ConversationLifecycle(
        conversations=conversations, memory=memory, retention=retention, archive_enabled=True
    )
'''

#: What the run must report, one per case above. Matched as substrings of the whole
#: report rather than by line, so a snippet edit that moves a case does not silently
#: stop asserting it.
_EXPECTED: Final = (
    '"TranscriptArchiveWriter" has no attribute "search"',
    '"TranscriptArchiveWriter" has no attribute "entries"',
    '"TranscriptArchive" has no attribute "append"',
    'Missing named argument "archive" for "ConversationLifecycle"',
)


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> str:
    """``mypy``'s own output over the snippet, run once for the whole module.

    **A subprocess rather than** ``mypy.api.run``, for two reasons that both bit.
    The checker then shares nothing with the pytest process that drives it — no
    module table, no import cache, no accumulated state from whatever ran before it
    under ``-n auto``. And its output width is ours to fix: ``mypy`` wraps its
    messages to the terminal, and under xdist the width is not the one an
    interactive run has, so a message that reads as one line here arrives folded
    there. The whitespace normalisation below is the belt to that brace.

    ``--follow-imports=silent`` keeps the run to the snippet itself: what is under
    assertion is what the *declared types* carry, and re-checking the package would
    only make the case slower and its failure harder to read. The cache lives in a
    temporary directory so a run leaves the project's own untouched.
    """
    directory = tmp_path_factory.mktemp("archive-seams")
    snippet = directory / "seams.py"
    snippet.write_text(_SNIPPET, encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 — this interpreter, a fixed argument list
        [
            sys.executable,
            "-m",
            "mypy",
            "--follow-imports=silent",
            "--no-error-summary",
            "--no-color-output",
            f"--cache-dir={directory / 'cache'}",
            str(snippet),
        ],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ | {"COLUMNS": "1000"},
        cwd=_ROOT,
    )
    assert not completed.stderr, completed.stderr
    return completed.stdout


@pytest.mark.parametrize("expected", _EXPECTED, ids=["search", "entries", "append", "composition"])
def test_the_type_checker_reports_the_seam_violation(report: str, expected: str) -> None:
    """Each of §13 item 2's four type-level cases, as ``mypy`` reports it.

    Matched over the report with its whitespace collapsed, because ``mypy`` folds a
    long message to the terminal width and the width is not a property of what is
    being asserted.
    """
    assert expected in " ".join(report.split())


def test_the_snippet_reports_nothing_else(report: str) -> None:
    """The control: every reported error is one of the four this module is about.

    Without it the cases above would keep passing after a change that made the whole
    snippet fail for an unrelated reason — an import that stopped resolving, say —
    and the seam split would stop being asserted while the module stayed green.
    """
    reported = [line for line in report.splitlines() if ": error:" in line]

    assert len(reported) == len(_EXPECTED), report
