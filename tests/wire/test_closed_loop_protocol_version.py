"""``PROTOCOL_VERSION`` moved for ``closed_loop`` and its log names why (ADR-0238 §13).

§13 asks that "``PROTOCOL_VERSION`` moves" and that "``wire/envelope.py``'s log gains
an entry naming this ADR and this reason" — the ``EgressBinding`` member that crosses
the wire inside a ``PermissionDecision``. ``tests/wire/test_web_search_protocol_version.py``
and ``tests/wire/test_structured_read_protocol_version.py`` are this file's two
precedents and it is written to their shape.
"""

from __future__ import annotations

import inspect
from typing import Final

from ai_assistant.core.types import CarriedProvenance, ConversationExport, EgressBinding
from ai_assistant.wire import envelope

#: The version ADR-0238's lane moves to, and the one it moves from.
#:
#: **§13's numeral was stale before this lane ran, and the figure is recorded here
#: rather than taken from the decision text.** §13 reads "``PROTOCOL_VERSION`` moves
#: 31 → 32", written while the tree stood at 31; ADR-0240's lane moved it to 32 in
#: between. ADR-0240 §11 anticipated exactly this and said why it deliberately fixed
#: no numeral of its own: "ADR-0238 has already scheduled ``PROTOCOL_VERSION`` 31 → 32
#: for a lane that may land before or after this one, and a numeral in a ratified ADR
#: that the tree has moved past is the failure ADR-0226 §4's own successors had to
#: correct". So the **substance** of §13 is the move and its ground — one more than
#: the tree of the implementing lane's own day — and the figure is read off the tree
#: and pinned here, where it can be checked.
_MOVED_TO: Final = 33
_MOVED_FROM: Final = 32


def test_the_protocol_version_moved_past_the_figure_this_decision_reached() -> None:
    """§13: the move, asserted as a move and not as a state.

    An equality here would make a later, unrelated and correctly reasoned bump look
    like a violation of ADR-0238 — the failure ``CONTRIBUTING.md`` → "No state claims
    in living documents" is about. So what is asserted is the half that stays true for
    as long as ADR-0238 stands: the number is **at or past** the figure this decision
    reached, because a later ADR can move it on and none can un-move this move. The
    absolute figure has exactly one home,
    ``tests/core/test_engine_surface_closure.py``, where a lane moving it is made to
    name the limb it is under.
    """
    assert envelope.PROTOCOL_VERSION >= _MOVED_TO


def test_the_log_carries_an_entry_naming_this_decision_and_its_ground() -> None:
    """§13: the entry names the ADR, the type, the member and the route it crosses by.

    The log is the comment block above the constant, so it is read out of the module's
    source. The ground is ADR-0124 §9's second limb read through ADR-0178 §6's rule:
    ``recent_decisions`` and ``export_decisions`` return
    ``tuple[PermissionDecision, ...]`` across the wire, a ``PermissionDecision``
    carries an ``EgressBinding``, and that binding's shape changed.
    """
    entry = _entry_for(_MOVED_TO)

    assert f"**{_MOVED_TO} since ADR-0238 §13**" in entry
    assert "closed_loop" in entry
    assert "EgressBinding" in entry
    assert "recent_decisions" in entry, "the route the type crosses by"
    assert "export_decisions" in entry
    assert f"**{_MOVED_FROM} since" in inspect.getsource(envelope), (
        "the log is appended to and never rewritten: the entry this move follows stands"
    )


def test_the_entry_says_the_numeral_in_the_decision_text_was_read_rather_than_assumed() -> None:
    """The half a reviewer reads when the constant does not match the ADR.

    A lane that had simply obeyed §13's "31 → 32" would have moved the number
    **backwards**, and a reader comparing the two later would have no way to tell that
    from a mistake. So the entry states the discrepancy and its resolution in terms,
    which is what ADR-0240 §11's own entry does one version down.
    """
    entry = _entry_for(_MOVED_TO)

    assert "31" in entry, "the figure the decision text names"
    assert "32" in entry, "the figure the tree stood at"
    assert "ADR-0240 §11" in entry, "the decision that anticipated it"


def test_the_entry_records_what_did_not_move() -> None:
    """ADR-0124 §9's **first** limb, stated as not reached rather than left silent.

    ADR-0238 adds a Protocol and three members to another, and neither is a ground for
    this bump: ``DestinationTrustStore`` is a hub-side store on neither promoted
    surface, and ``ConversationStore``'s three new members are in-process reads and
    writes no peer emits. ``test_engine_surface_closure`` pins the figure itself beside
    the constant; what this asserts is that the log *says so*.
    """
    entry = _entry_for(_MOVED_TO)

    assert "fifty-four" in entry
    assert "thirty-one" in entry
    assert "DestinationTrustStore" in entry
    assert "search_draw" in entry, "and why the widened Protocol is not a ground"


def test_neither_the_carrier_nor_the_export_changed_shape_in_a_way_this_move_covers() -> None:
    """§13's two statements the entry rests on, checked against the types themselves.

    ``CarriedProvenance`` gains the field too — the seam writes the binding's value
    from the carrier's — but it crosses no wire, so it is not a second ground. And
    ``ConversationExport`` changes neither shape nor version, which is why §8's counter
    and flag cost no export-version move: they are the store's own row state and appear
    on no presented model.
    """
    assert "closed_loop" in EgressBinding.model_fields
    assert "closed_loop" in CarriedProvenance.model_fields
    assert ConversationExport.model_fields["schema_version"].default == 2


def _entry_for(version: int) -> str:
    """The version log's entry for one version, read out of the module's source.

    ``tests/wire/test_structured_read_protocol_version.py``'s helper, and for its
    reason: the prefixes and the wrapping are stripped, so what the cases above match
    is the entry's *prose* rather than the column it happened to be reflowed to. A
    phrase asserted across a line break is a test that fails on ``ruff format``
    rewrapping a paragraph, which would report a rewrapped comment as a missing account
    of the version.
    """
    source = inspect.getsource(envelope)
    entry = source.split(f"#: **{version} since")[-1].split("PROTOCOL_VERSION: Final")[0]
    stripped = (line.removeprefix("#:").strip() for line in entry.splitlines())
    return f"**{version} since " + " ".join(part for part in stripped if part)
