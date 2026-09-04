"""``PROTOCOL_VERSION`` moved to 28 and its log names the decision (ADR-0230 §12).

§14 item 19 asks that "``PROTOCOL_VERSION`` reads 28 with ``wire/envelope.py``'s log
naming this ADR". The rest of that item — a ``PlanExport`` round-tripping at
``schema_version`` 5, a document labelled 4 not validating, and both conforming
``PlanStore`` implementations exporting the new version — is asserted where those
values live (``tests/core/test_planning_types.py``, ``tests/planning/``).

**Both halves matter and neither substitutes for the other.** ADR-0124 §9 makes
compliance with the bump rule a **review obligation** and decides no mechanical check
(#891 carries the one that does not exist), so what a test can hold is that the number
moved *and* that the move is accounted for in the log a reviewer reads. A number that
moved with no entry behind it is the state this file exists to refuse.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.wire import envelope

#: The version ADR-0230 §12 moves to, and the one it moves from.
_MOVED_TO: Final = 28
_MOVED_FROM: Final = 27


def test_the_protocol_version_moved_to_the_figure_the_decision_names() -> None:
    """§12: "``PROTOCOL_VERSION`` moves 27 → 28", asserted as a move and not as a state.

    **An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0230**, which is the failure ``CONTRIBUTING.md`` -> "No
    state claims in living documents" is about, and which ADR-0186 §13 already ruled
    on for the neighbouring clause: a clause fixing what *this* decision does to the
    number "is not a bar on any later one". ADR-0233 §15 moved it again, to 29, under
    the same limb of ADR-0124 §9 and for a different type.

    So what is asserted is the half that stays true for as long as ADR-0230 stands:
    the number is **at or past** the figure §12 names, because a later ADR can move it
    on and none can un-move ADR-0230's move. The absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``, where a lane moving it is made to
    name the limb it is under; the other half — that the move is *accounted for* in
    the log a reviewer reads — is the case below.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_reason() -> None:
    """§12: "``wire/envelope.py``'s log gains an entry naming this ADR and this reason".

    The log is the comment block above the constant, so it is read out of the module's
    source. What is asserted is that the entry names the version, the decision, and
    **both** of the two changes §12's conjunction rests on — a peer whose ``ReadKind``
    predates ``LOCAL_FILE``, or whose ``ReadAsk`` predates ``entry``, fails to decode a
    ``TurnOutcome`` whose plan carries either.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{_MOVED_FROM} since")[-1].split("PROTOCOL_VERSION: Final")[0]

    assert f"**{_MOVED_TO} since ADR-0230 §12**" in entry
    assert "LOCAL_FILE" in entry
    assert "entry" in entry
    assert 'extra="forbid"' in entry


def test_the_entry_records_that_the_promoted_method_set_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0230 adds one Protocol — ``Fetcher`` — and no method to the promoted
    ``AssistantEngine`` surface, so the method-set limb is not what obliges this bump.
    ``tests/core/test_engine_surface_closure.py`` pins the figure itself beside the
    constant; what this asserts is that the log *says so*, which is the half a reviewer
    reads when asking why the number moved.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{_MOVED_TO} since")[-1].split("PROTOCOL_VERSION: Final")[0]

    assert "forty-nine" in entry
    assert "thirty-one" in entry
