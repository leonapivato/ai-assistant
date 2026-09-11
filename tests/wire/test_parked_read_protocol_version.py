"""``PROTOCOL_VERSION`` moved for ADR-0244, and its log names all three grounds (§17).

§17 rules that "``PROTOCOL_VERSION`` moves 34 → 35, once, for this whole decision, and
``wire/envelope.py``'s log gains one entry naming this ADR and this reason". The rest of
§17's clauses — that ``PlanExport.schema_version`` does not move, and that
``SearchDisposition`` and its nine neighbours do not either — are asserted where those
values live.

**Both halves matter and neither substitutes for the other**, which is
``test_web_search_protocol_version.py``'s reasoning two decisions on: ADR-0124 §9 makes
compliance with the bump rule a **review obligation** and decides no mechanical check
(#891 carries the one that does not exist), so what a test can hold is that the number
moved *and* that the move is accounted for in the log a reviewer reads.

**And here the accounting is the half worth having, because this move rests on three
independent grounds where every entry above it rests on one or two.** §17 states all
three so that none is read as unversioned, and any one of them obliges the bump alone:
a required member on an ``extra="forbid"`` type, two defaulted members a projection
emits, and a method on the promoted surface. An entry naming fewer would be a correctly
moved number with an incomplete account under it.

**The first of the three is the one that bites in *both* directions**, which no entry
above this one does: ``Confirmation.read`` is required with no default, so a version 34
peer fails ``extra_forbidden`` on a version 35 hub's confirmation and a version 35 peer
fails ``missing`` on a version 34 hub's — where every ``TurnOutcome`` widening in the log
fails in one direction and decodes to a default in the other.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0244 §17 moves to, and the one it moves from.
#:
#: **§17 fixes the pair explicitly**, and is the first section in this log's history to
#: do so — "It moves ``PROTOCOL_VERSION`` from 34 to 35, stated up front rather than
#: found by the implementing lane". That is safe here where it was not for ADR-0240
#: because ADR-0244's batch schedules no other wire-moving lane ahead of it, and the
#: figures are recorded here as well, where they can be checked.
_MOVED_TO: Final = 35
_MOVED_FROM: Final = 34


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§17: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look like
    a violation of ADR-0244 — the failure ``CONTRIBUTING.md`` → "No state claims in
    living documents" is about. So what is asserted is the half that stays true for as
    long as ADR-0244 stands: the number is **at or past** the figure this decision
    reached, because a later ADR can move it on and none can un-move this move. The
    absolute figure has exactly one home, ``tests/core/test_engine_surface_closure.py``,
    where a lane moving it is made to name the limb it is under.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_all_three_grounds() -> None:
    """§17: the entry names the ADR and each of the three limbs it is under."""
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0244 §17**" in entry
    assert "Confirmation" in entry, "the type the required-member ground is about"
    assert "read" in entry, "and the member it names"
    assert "required" in entry
    assert 'extra="forbid"' in entry, "and the limb it bites through"
    assert "read_confirmation" in entry, "the first of the two TurnOutcome members"
    assert "read_answer" in entry, "and the second"
    assert "cancel_read" in entry, "the promoted-method ground"
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_says_which_stored_versions_did_not_move() -> None:
    """§17's "the versions that do not move", stated rather than left silent.

    ``PlanExport.schema_version`` is the one a reader would expect to move, because this
    decision persists an ``ActionPlan``; §17 says why it does not — "the plan a park
    persists is the plan the planner already returned, stored as a value and not
    re-shaped" — and the entry has to carry that, because a reviewer asking "why did the
    plan's version not move when a plan became durable?" reads the log and not the ADR.
    """
    entry = _entry_for(_MOVED_TO)

    assert "PlanExport.schema_version" in entry
    assert "ParkedRead" in entry, "and that the record itself never crosses the wire"


def test_the_entry_records_that_the_browser_enumeration_did_not_move() -> None:
    """ADR-0177 §1's thirty-one, unmoved a fourth time.

    ADR-0244 §13 admits the browser for this kind, which is what makes this worth
    asserting rather than assuming: the *decision* reaches the browser and the **lane**
    does not, so the entry has to say that this change adds no gateway route rather than
    that the browser is out of scope.
    """
    entry = _entry_for(_MOVED_TO)

    assert "thirty-one" in entry
    assert "fifty-eight" in entry, "and the method set's own figure beside it"


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    The log is a run of ``#:`` comments above the constant, each entry opening with
    ``**<n> since ADR-…**``, so an entry is the span from its own opener to the next one
    — or to the constant, for the last. Sliced rather than parsed because the comment
    block is prose a reviewer reads and has no structure worth asserting.

    **The prefixes and the wrapping are stripped**, so what the cases above match is the
    entry's *prose* rather than the column it happened to be reflowed to: a phrase
    asserted across a line break is a test that fails on ``ruff format`` rewrapping a
    paragraph, which would report a rewrapped comment as a missing account of the
    version.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose, one line, with the comment prefixes removed.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)
