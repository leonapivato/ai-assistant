"""Tier 1 of ADR-0088 §6, run over the real ``docs/adr/**``.

**This is where the check can fail a change.** ADR-0088's Context records that
the gate's five steps are "structurally incapable of failing on the only defect
a `docs/adr/**` change can have", because none of them opens a file under
``docs/adr/``. §6 answers that by requiring a check "capable of failing", and
leaves its placement open.

It is here, in ``pytest``, for the reason ``tests/core/test_protocol_triad.py``
gives for living here: ``uv run pytest`` is already the gate and already CI, so
a repository-level rule put in it inherits both and fails as an ordinary test
naming exactly what is wrong. The gate stays five steps and one of them now
reads the ADRs — which is §6's requirement met without a sixth step that
``CLAUDE.md`` and ``CONTRIBUTING.md`` would then be wrong about.

Tier 2 is deliberately **not** asserted here. §3 is explicit that an append-only
corpus correctly cites what the tree does not contain, so the Tier 2 list is
permanently non-empty and pinning it would turn every legitimate ADR into a test
failure. ``just citations`` prints it, and CI publishes it to the job summary.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).parents[2]
_SCRIPT = _ROOT / "scripts" / "check_citations.py"

#: The one Tier 1 finding `main` carries today, and it is a finding about
#: **ADR-0088 rather than about ADR-0067**. ADR-0067 writes "31 further ADRs,
#: ADR-0036 through ADR-0066, no ADR-0035 having been issued" — a correct
#: sentence about a number that was never issued, in §1(a)'s canonical form and
#: outside any fence. §6's Tier 1 rests on "ADRs are append-only so a file is
#: never deleted", which covers a *deleted* target and silently assumes every
#: cited number was issued; ADR-0088 states twice that the corpus passes today
#: ("0035 is absent, and nothing cites it"), and both statements are false.
#:
#: It is pinned rather than excused inside the checker, which stays a faithful
#: reading of §6 and reports it. Pinning keeps the gate green on a defect this
#: lane may not fix — `docs/adr/**` is another lane's — while leaving the check
#: live: a *new* dangling ADR citation changes this set and fails. Correcting
#: the corpus, or amending §6, also fails it, which is the point — whoever does
#: that deletes this pin. Tracked in the issue named below.
_KNOWN_TIER_1 = (("docs/adr/0067-retire-the-changelog.md", "ADR-0035"),)

#: The issue carrying the ADR-0088 §6 / ADR-0067 question above.
_TRACKING_ISSUE = "#603"


@cache
def _report(*args: str) -> dict[str, object]:
    """Run the checker over this repository and return its report.

    Cached: the checker parses every module under the three code roots, so the
    two offline tests below share one ~6s run rather than paying for it twice.
    """
    argv = [sys.executable, str(_SCRIPT), "--root", str(_ROOT), "--format", "json", *args]
    result = subprocess.run(  # noqa: S603  # fixed argv, no shell
        argv, capture_output=True, text=True, check=False
    )
    assert result.returncode in (0, 1), result.stderr
    report = json.loads(result.stdout)
    assert isinstance(report, dict)
    return report


def _tier_1(report: dict[str, object], kind: str) -> list[tuple[str, str]]:
    findings = report["findings"]
    assert isinstance(findings, list)
    return [
        (str(f["path"]), str(f["citation"]))
        for f in findings
        if f["tier"] == 1 and f["kind"] == kind
    ]


def test_no_adr_cites_a_decision_that_does_not_exist() -> None:
    """Tier 1: an ADR file is never deleted, so a citation naming a missing one is a defect."""
    report = _report("--no-tracker")

    found = sorted(_tier_1(report, "decision"))

    assert found == sorted(_KNOWN_TIER_1), (
        "A decision citation names an ADR file that does not exist (ADR-0088 §6, Tier 1). "
        f"If you corrected the corpus or amended §6, delete the pin above and {_TRACKING_ISSUE}."
    )


def test_the_corpus_is_actually_being_read() -> None:
    """A check that selected nothing would pass this module silently.

    ADR-0088 §6's whole hazard is a tool that looks authoritative while doing
    less than it claims, so the denominator is asserted rather than assumed.
    """
    counts = _report("--no-tracker")["counts"]

    assert isinstance(counts, dict)
    assert counts["decision"] > 1000
    assert counts["tracker"] > 100
    assert counts["module-path"] > 100
    assert counts["dotted-symbol"] > 100


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("gh") is None, reason="the tracker is unevaluable without `gh`")
def test_no_adr_cites_an_issue_number_that_does_not_exist() -> None:
    """Tier 1: "an issue number once assigned stays assigned" (ADR-0088 §6).

    Issue *state* is not checked and this test asserts nothing about it (§2(c)).
    Marked ``integration`` because it reads GitHub; when ``gh`` cannot answer,
    the checker passes the citations silently and this test skips, which is §6's
    asymmetry rule rather than a hole in it.
    """
    report = _report()

    if not report["tracker_checked"]:
        pytest.skip("`gh` is present but could not read the tracker")
    assert _tier_1(report, "tracker") == []
