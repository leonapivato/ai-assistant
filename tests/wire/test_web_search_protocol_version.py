"""``PROTOCOL_VERSION`` moved for ``WEB_SEARCH`` and its log names why (ADR-0231 §16).

§16 asks that "``PROTOCOL_VERSION`` moves" and that "``wire/envelope.py``'s log gains
an entry naming this ADR and this reason". The rest of §16's persistence clauses — a
``PlanExport`` at ``schema_version`` 6, a document of the earlier shape not validating,
and both conforming ``PlanStore`` implementations exporting the new version — are
asserted where those values live (``tests/core/test_planning_types.py``,
``tests/planning/``).

**Both halves matter and neither substitutes for the other**, which is
``test_fetch_protocol_version.py``'s reasoning one decision on: ADR-0124 §9 makes
compliance with the bump rule a **review obligation** and decides no mechanical check
(#891 carries the one that does not exist), so what a test can hold is that the number
moved *and* that the move is accounted for in the log a reviewer reads.

**And here the accounting is the half worth having, because this move's ground is not
the previous one's.** ADR-0230 §12's entry rests on a conjunction whose widest limb is
a defaulted field the projection emits and ``extra="forbid"`` refuses; ADR-0231 §1
gives ``WEB_SEARCH`` **no field at all**, so that limb is unavailable and the closed
enumeration is the whole of the break. An entry that borrowed the previous reasoning
would be a correctly-moved number with a false account under it, which is exactly what
a reviewer reading the log would be misled by.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0231 §16 moves to, and the one it moves from.
#:
#: **§16's own figures are one behind the tree and this is the correction**, recorded
#: here rather than in the ADR because ADR-0070 §1 does not permit rewriting ratified
#: decision text. §16 reads "``PROTOCOL_VERSION`` moves 28 → 29", written while 28 was
#: the standing value; ADR-0233 §15 moved it to 29 for ``ConfirmationEgress.coverage``
#: before this lane ran, so the move §16 obliges is made from wherever the number then
#: stood. What §16 decides is that this decision moves it once, and that is what is
#: asserted.
_MOVED_TO: Final = 30
_MOVED_FROM: Final = 29


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§16: the move, asserted as a move and not as a state.

    **An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0231**, which is the failure ``CONTRIBUTING.md`` -> "No
    state claims in living documents" is about, and which ADR-0186 §13 already ruled on
    for the neighbouring clause: a clause fixing what *this* decision does to the number
    "is not a bar on any later one".

    So what is asserted is the half that stays true for as long as ADR-0231 stands: the
    number is **at or past** the figure this decision reached, because a later ADR can
    move it on and none can un-move this move. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``, where a lane moving it is made to
    name the limb it is under; the other half — that the move is *accounted for* in the
    log a reviewer reads — is the case below.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_reason() -> None:
    """§16: "``wire/envelope.py``'s log gains an entry naming this ADR and this reason".

    The log is the comment block above the constant, so it is read out of the module's
    source. What is asserted is that the entry names the version, the decision, and the
    member whose arrival is the break — a peer whose ``ReadKind`` predates
    ``WEB_SEARCH`` cannot decode a ``TurnOutcome`` whose plan names that kind.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0231 §16**" in entry
    assert "WEB_SEARCH" in entry
    assert "ReadKind" in entry
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_disclaims_the_limb_this_move_does_not_rest_on() -> None:
    """The half a reviewer would otherwise have to re-derive from three entries.

    ADR-0231 §16's closing clause is explicit that "no lane reads this section as
    authority for bumping on a defaulted addition alone", and this move could not rest
    on one in any case: §1 rules that "``ReadAsk`` gains **no field** for this kind".
    So the entry has to say that the ``extra="forbid"`` limb the 27, 28 and 29 entries
    turn on is *not reached* here, rather than repeating it as though it were — an
    entry that copied its neighbour would account for the number with a mechanism this
    change does not have.
    """
    entry = _entry_for(_MOVED_TO)

    assert "no field" in entry, "the entry says why the defaulted-member limb is absent"
    assert 'extra="forbid"' in entry, "and names the limb it is disclaiming"
    assert "not reached here" in entry


def test_the_entry_records_that_the_promoted_method_set_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0231 §17's Lane 4 adds no Protocol and no method to the promoted
    ``AssistantEngine`` surface, so the method-set limb is not what obliges this bump.
    ``tests/core/test_engine_surface_closure.py`` pins the figure itself beside the
    constant; what this asserts is that the log *says so*, which is the half a reviewer
    reads when asking why the number moved.
    """
    entry = _entry_for(_MOVED_TO)

    assert "forty-nine" in entry
    assert "thirty-one" in entry


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    The log is a run of ``#:`` comments above the constant, each entry opening with
    ``**<n> since ADR-…**``, so an entry is the span from its own opener to the next
    one — or to the constant, for the last. Sliced rather than parsed because the
    comment block is prose a reviewer reads and has no structure worth asserting.

    **The prefixes and the wrapping are stripped**, so what the cases above match is
    the entry's *prose* rather than the column it happened to be reflowed to. A
    phrase asserted across a line break is a test that fails on ``ruff format``
    rewrapping a paragraph, which would report a rewrapped comment as a missing
    account of the version.

    Args:
        version: The version whose entry to return.

    Returns:
        That entry's prose, one line, with the comment prefixes removed.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)
