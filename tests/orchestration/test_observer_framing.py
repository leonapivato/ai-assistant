"""Framing: what the call proposes, and every check code makes of it (ADR-0346 §5, §7, §9).

Driven on values: a view of a finding's parts, a reply, and what :func:`framed` keeps. Each
memory is checked on its own, and one that fails a check is not written while the others
stand (§5:4). Code sets origins and ``when`` from the parts (ADR-0329 §9:5), keeps an
approved wording exactly (§5:3), names a person only as a part gives them (§5:5), lets a
round's message back only a record of the saying (§7:6-§7:9), and keeps labels within the
root's bounds (ADR-0345 §7:3).
"""

from __future__ import annotations

from datetime import timedelta

from observer_support import AT, LABELS, Minter, address, episode, framed, framing, read_as

from ai_assistant.core.types import (
    OWNER_PERSON_ID,
    ConfirmationPart,
    EvidenceItemPart,
    InputPart,
    MemoryMark,
    MemoryStanding,
    ObservationFinding,
    QuestionPart,
    ReadingCertainty,
    RoundMessagePart,
    SupportOrigin,
)
from ai_assistant.orchestration.observer.framing import (
    Framing,
    FramingView,
)
from ai_assistant.orchestration.observer.framing import (
    framed as framed_by_code,
)
from ai_assistant.orchestration.observer.reading import ReadPart
from ai_assistant.orchestration.observer.replies import FramingReplyShape

_SWIM = "can't do Friday evening, that's my swim"
_RUN = "out for my Tuesday morning run, back by 8"
_SAID = "Saltmarsh takes bookings for up to six."


def _part(  # noqa: PLR0913 — one keyword per fact of a part a case varies
    handle: str,
    text: str,
    *,
    episode_name: str = "one",
    origin: SupportOrigin = SupportOrigin.USER_MESSAGE,
    part: object | None = None,
    minutes: int = 0,
) -> ReadPart:
    occurred = AT - timedelta(minutes=minutes)
    return ReadPart(
        handle=handle,
        part=part or InputPart(episode=address(episode_name)),  # type: ignore[arg-type]  # a part
        episode=address(episode_name),
        occurred_at=occurred,
        text=text,
        origin=origin,
        when=occurred,
    )


_P1 = _part("P1", _SWIM)
_P2 = _part("P2", _RUN, episode_name="earlier", minutes=60)
_P3 = _part(
    "P3",
    _SAID,
    origin=SupportOrigin.ASSISTANT_MESSAGE,
    part=RoundMessagePart(episode=address("one"), round="r1"),
)
_YES = _part(
    "P4",
    "The user prefers window seats.",
    origin=SupportOrigin.CONFIRMATION,
    part=ConfirmationPart(
        episode=address("one"),
        asking_activation="asking",
        question=QuestionPart(round="r-ask", part=1),
    ),
)


def _view(*parts: ReadPart) -> FramingView:
    finding = ObservationFinding(
        id="f1",
        episode=address("one"),
        claim="The user swims on Fridays and runs on Tuesdays.",
        rests_on=tuple(one.part for one in parts),
    )
    return FramingView(finding=finding, leaving=episode("one"), parts=tuple(parts))


def _framed(view: FramingView, reply: str, *, person: bool = False) -> Framing:
    read = read_as(reply, FramingReplyShape)
    assert read is not None
    return framed_by_code(read, view, now=AT, mint=Minter(), labels=LABELS, person=person)


def test_claims_that_could_each_be_true_are_kept_as_memories_of_their_own() -> None:
    """ADR-0346 §5:3: one claim per memory, each backed by the part stating it."""
    view = _view(_P1, _P2)

    result = _framed(
        view,
        framing(
            framed("The user swims on Friday evenings.", "P1"),
            framed("The user runs on Tuesday mornings.", "P1", "P2"),
        ),
    )

    swim, run = (one.memory for one in result.memories)
    assert swim.content == "The user swims on Friday evenings."
    (support,) = swim.supports
    assert support.points_at == _P1.part
    assert (support.origin, support.when) == (SupportOrigin.USER_MESSAGE, _P1.when)
    assert support.holder is None, "the writer sets the holder (ADR-0345 §2:2)"
    assert run.supports[0].points_at == _P1.part
    assert result.failed == 0


def test_a_memory_failing_a_check_is_not_written_and_the_others_stand() -> None:
    """ADR-0346 §5:4: a part the finding does not rest on fails that memory alone."""
    result = _framed(
        _view(_P1),
        framing(framed("The user swims on Friday evenings.", "P1"), framed("Made up.", "P9")),
    )

    (kept,) = result.memories
    assert kept.memory.content == "The user swims on Friday evenings."
    assert result.failed == 1
    assert [note["refused"] is None for note in result.notes] == [True, False]


def test_a_memory_resting_on_no_part_of_the_leaving_episode_fails() -> None:
    """ADR-0346 §3:1: a ``for`` support on the exchange under review, at least."""
    result = _framed(_view(_P1, _P2), framing(framed("The user runs on Tuesdays.", "P2")))

    assert result.memories == ()
    assert result.failed == 1


def test_a_memory_no_support_backs_as_worded_fails() -> None:
    result = _framed(_view(_P1), framing(framed("The user swims.", "P1", backs=False)))

    assert (result.memories, result.failed) == ((), 1)


def test_an_approved_wording_is_kept_exactly_and_never_reworded() -> None:
    """ADR-0346 §5:3, ADR-0329 §5:5: a reworded memory fails, and code frames the yes."""
    view = _view(_P1, _YES)

    reworded = _framed(view, framing(framed("User likes windows", "P4")))
    exact = _framed(view, framing(framed("anything at all", "P4")))

    (kept,) = reworded.memories
    assert kept.memory.content == _YES.text, "framed by code, in exactly the words approved"
    (support,) = kept.memory.supports
    assert (support.origin, support.how_sure) == (SupportOrigin.CONFIRMATION, ReadingCertainty.SURE)
    assert kept.memory.standing is MemoryStanding.CONFIRMED
    (approved,) = exact.memories
    assert approved.memory.content == _YES.text, "the approved wording is the memory's wording"


def test_an_approved_wording_framing_left_out_is_framed_by_code() -> None:
    """ADR-0346 §5:3: every approved wording the finding rests on is a memory of its own."""
    result = _framed(_view(_P1, _YES), framing(framed("The user swims on Fridays.", "P1")))

    contents = [one.memory.content for one in result.memories]
    assert contents == ["The user swims on Fridays.", _YES.text]


def test_a_name_is_carried_only_as_a_part_gives_it() -> None:
    """ADR-0346 §5:5, ADR-0345 §9:3-§9:4: the owner by the owner's identifier."""
    ana = _part("P1", "my sister Ana teaches piano")
    view = _view(ana)

    given = _framed(
        view,
        framing(framed("Ana teaches piano.", "P1", subjects=["Ana"], involved=["the user"])),
    )
    ungiven = _framed(view, framing(framed("Ana teaches piano.", "P1", subjects=["Anabel"])))
    both = _framed(
        view, framing(framed("Ana teaches piano.", "P1", subjects=["Ana"], involved=["Ana"]))
    )
    unset = _framed(view, framing(framed("Ana teaches piano.", "P1", subjects=None)))

    (kept,) = given.memories
    assert kept.memory.subjects == ("Ana",)
    assert kept.memory.involved == (OWNER_PERSON_ID,)
    assert ungiven.memories == ()
    (once,) = both.memories
    assert (once.memory.subjects, once.memory.involved) == (("Ana",), ())
    assert unset.memories == (), "subjects and involved are never left unset"


def test_a_round_message_backs_only_a_record_of_the_saying() -> None:
    """ADR-0346 §7:8, ADR-0345 §2:4, §8:3: marked ``assistant_statement`` and ``occasion``."""
    view = _view(_P1, _P3)

    bare = _framed(view, framing(framed(_SAID, "P3")))
    record = _framed(
        view,
        framing(
            framed(
                "On Oct 18 the assistant said Saltmarsh takes bookings for up to six.",
                "P3",
                marks=["assistant_statement", "occasion"],
            )
        ),
    )
    marked_alone = _framed(
        _view(_P1), framing(framed("The user swims.", "P1", marks=["assistant_statement"]))
    )

    assert bare.memories == ()
    (kept,) = record.memories
    assert set(kept.memory.marks) == {MemoryMark.ASSISTANT_STATEMENT, MemoryMark.OCCASION}
    assert marked_alone.memories == (), "assistant_statement cites a round's message"


def test_what_a_round_message_claims_is_kept_on_a_persons_backing_in_the_exchange() -> None:
    """ADR-0346 §7:6, ADR-0348 §2:3: the person's agreement backs it, the message cited beside.

    Code cannot tell an agreement from a request to keep, so it reads only that a
    person's part in the exchange backs the memory: which parts back it is the call's.
    """
    keep = _part("P1", "yes, that's right, six is our usual number")
    view = _view(keep, _P3)
    with_keep = framing(
        {
            "wording": _SAID,
            "supports": [
                {"part": "P1", "direction": "for", "backs_as_worded": True, "how_sure": "sure"},
                {"part": "P3", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
            ],
            "subjects": [],
            "involved": [],
            "marks": ["assistant_statement"],
        }
    )
    without_keep = framing(
        {
            "wording": _SAID,
            "supports": [
                {"part": "P1", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
                {"part": "P3", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
            ],
            "subjects": [],
            "involved": [],
        }
    )

    (kept,) = _framed(view, with_keep).memories
    assert kept.memory.supports[0].points_at == keep.part, "the person's backing is cited"
    assert _framed(view, without_keep).memories == ()


def test_an_occasion_carries_no_validity_end() -> None:
    """ADR-0345 §8:4."""
    end = (AT + timedelta(days=3)).isoformat()

    result = _framed(
        _view(_P1), framing(framed("The user swam.", "P1", marks=["occasion"], valid_until=end))
    )

    assert result.memories == ()


def test_a_validity_end_is_the_about_when_of_the_support_the_create_cites() -> None:
    """ADR-0345 §6:1: a future end, named by a backing support's about-when."""
    end = AT + timedelta(days=3)
    flying = _part("P1", "I'm flying to Lisbon on the 21st")
    other = _part("P2", "flight's booked", episode_name="earlier", minutes=60)
    named = framing(
        {
            "wording": "The user is flying to Lisbon on Oct 21.",
            "supports": [
                {"part": "P2", "direction": "for", "backs_as_worded": True, "how_sure": "sure"},
                {
                    "part": "P1",
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "sure",
                    "about_when": end.isoformat(),
                },
            ],
            "subjects": ["the user"],
            "involved": [],
            "valid_until": end.isoformat(),
        }
    )
    unnamed = framing(framed("The user is flying to Lisbon.", "P1", valid_until=end.isoformat()))
    past = framing(framed("The user flew.", "P1", valid_until=(AT - timedelta(days=1)).isoformat()))

    (kept,) = _framed(_view(flying, other), named).memories
    assert kept.memory.validity.valid_until == end
    assert kept.memory.operations[0].cites == flying.part
    assert _framed(_view(flying), unnamed).memories == ()
    assert _framed(_view(flying), past).memories == ()


def test_an_end_already_past_when_framed_is_kept_as_history() -> None:
    """ADR-0345 §6:1-§6:2: an end its support names is kept though it has passed.

    The episode said the stay ends on a day that has passed by the time it leaves the
    window. The memory keeps that end, and is not live; it is never refused for it.
    """
    end = AT - timedelta(days=1)
    staying = _part("P1", "I'm staying in Lisbon until the 23rd")
    reply = framing(
        {
            "wording": "The user is staying in Lisbon until Oct 23.",
            "supports": [
                {
                    "part": "P1",
                    "direction": "for",
                    "backs_as_worded": True,
                    "how_sure": "sure",
                    "about_when": end.isoformat(),
                }
            ],
            "subjects": ["the user"],
            "involved": [],
            "valid_until": end.isoformat(),
        }
    )

    (kept,) = _framed(_view(staying), reply).memories

    assert kept.memory.validity.valid_until == end
    assert kept.memory.operations[0].cites == staying.part


def test_a_reply_neither_framing_nor_saying_why_not_does_not_parse() -> None:
    """ADR-0346 §5:6: nothing is kept only with a reason; anything else is retried."""
    assert read_as("{}", FramingReplyShape) is None
    assert read_as('{"error": "could not frame"}', FramingReplyShape) is None
    assert read_as('{"memories": [], "nothing": "  "}', FramingReplyShape) is None
    reason = read_as('{"memories": [], "nothing": "One choice is no habit."}', FramingReplyShape)
    assert reason is not None
    assert reason.nothing == "One choice is no habit."


def test_labels_are_kept_within_the_bounds_and_suggested_by_the_episode() -> None:
    """ADR-0345 §7:1, §7:3, ADR-0346 §9:1: a label past a bound is left out."""
    long = "x" * (LABELS.max_chars + 1)

    result = _framed(
        _view(_P1),
        framing(
            framed(
                "The user swims on Friday evenings.",
                "P1",
                labels=["planning the week", long, "exercise", "evenings", "more"],
            )
        ),
    )

    (kept,) = result.memories
    labels = kept.memory.labels
    assert [one.text for one in labels] == ["planning the week", "exercise", "evenings"]
    assert {(one.added_by.value, one.episode) for one in labels} == {("observer", address("one"))}


def test_an_unknown_mark_fails_the_memory() -> None:
    result = _framed(_view(_P1), framing(framed("The user swims.", "P1", marks=["habit"])))

    assert result.memories == ()


def test_nothing_kept_says_why() -> None:
    """ADR-0346 §5:6: where the parts do not bear the claim out."""
    result = _framed(_view(_P1), framing(nothing="One choice is no habit."))

    assert (result.memories, result.failed, result.nothing) == ((), 0, "One choice is no habit.")


def test_style_and_pin_are_read_only_where_the_call_was_given_a_person() -> None:
    """ADR-0338 §9:4-§9:5: read only under the person model, and only where ``true``."""
    reply = framing(framed("The user prefers short replies.", "P1", style=True, pin="yes"))

    (with_person,) = _framed(_view(_P1), reply, person=True).memories
    (without,) = _framed(_view(_P1), reply).memories

    assert (with_person.style, with_person.pin) == (True, False)
    assert (without.style, without.pin) == (False, False)


def test_two_claims_of_one_exchange_each_pass_on_their_own_part() -> None:
    """The compound-claim case's split, as code checks it (prompt_cases/observer_framing).

    Each message of the exchange under review backs the claim it states, so each memory
    passes on its own evidence alone.
    """
    swim = _part("P1", _SWIM, part=InputPart(episode=address("one"), message=0))
    run = _part(
        "P2", "and tuesday mornings I run", part=InputPart(episode=address("one"), message=1)
    )

    result = _framed(
        _view(swim, run),
        framing(
            framed("The user swims on Friday evenings.", "P1"),
            framed("The user runs on Tuesday mornings.", "P2"),
        ),
    )

    assert [one.memory.content for one in result.memories] == [
        "The user swims on Friday evenings.",
        "The user runs on Tuesday mornings.",
    ]
    assert result.failed == 0


def test_a_list_in_one_part_passes_as_a_memory_per_item() -> None:
    """#3399's split, as code checks it (prompt_cases/observer_framing/list-in-one-clause).

    One message lists two allergies; each memory is backed as worded by that one part.
    """
    said = _part("P1", "please remember I'm allergic to sesame and kiwi")

    result = _framed(
        _view(said),
        framing(
            framed("The user is allergic to sesame.", "P1"),
            framed("The user is allergic to kiwi.", "P1"),
        ),
    )

    assert [one.memory.content for one in result.memories] == [
        "The user is allergic to sesame.",
        "The user is allergic to kiwi.",
    ]
    assert all(one.memory.supports[0].backs_as_worded for one in result.memories)


def test_a_kept_report_passes_on_the_evidence_never_on_the_relay() -> None:
    """#3400, ADR-0346 §7:6, ADR-0348 §2:2: the source's part backs it, the relay never.

    ADR-0345 §5's worked example, step 3, as ADR-0348 leaves it: the report rests on the
    source's evidence item, which holds it, and cites the person's request and the message
    that relayed it, neither backing it. A framing that also lets the request back it
    passes the checks, since code cannot tell a request from an agreement.
    """
    keep = _part("P1", "Remember that.")
    relay = _part(
        "P2",
        "Harrow Point on Monday: high of 14, low of 6, dry.",
        episode_name="earlier",
        minutes=2,
        origin=SupportOrigin.ASSISTANT_MESSAGE_OVER_OUTSIDE,
        part=RoundMessagePart(episode=address("earlier"), round="r1"),
    )
    evidence = _part(
        "P3",
        "Monday at Harrow Point: high 14, low 6.",
        episode_name="earlier",
        minutes=2,
        origin=SupportOrigin.EVIDENCE,
        part=EvidenceItemPart(episode=address("earlier"), digest=0, item=0),
    )
    view = _view(keep, relay, evidence)

    def report(*backing: str) -> str:
        return framing(
            {
                "wording": "A forecast said Harrow Point's Monday high is 14 and its low 6.",
                "supports": [
                    {
                        "part": one,
                        "direction": "for",
                        "backs_as_worded": one in backing,
                        "how_sure": "sure",
                    }
                    for one in ("P1", "P2", "P3")
                ],
                "subjects": [],
                "involved": [],
            }
        )

    (kept,) = _framed(view, report("P3")).memories
    assert {one.points_at for one in kept.memory.supports if one.backs_as_worded} == {evidence.part}
    assert {one.points_at for one in kept.memory.supports} == {
        keep.part,
        relay.part,
        evidence.part,
    }, "the request and the relay are cited"
    assert _framed(view, report("P1", "P3")).memories != ()
    assert _framed(view, report("P2")).memories == (), "a relay backs no memory but a saying"
    assert _framed(view, report()).memories == (), "a request alone backs nothing"


def test_a_request_to_keep_the_assistants_words_keeps_a_record_of_the_saying() -> None:
    """ADR-0348 §2:3: kept from a round's message alone, it is a record of the saying.

    Held by the assistant's statement, which backs it, and citing the person's request,
    which backs nothing; without the person's backing, the message's claim is not kept as
    the person's.
    """
    keep = _part("P1", "Remember that.")
    view = _view(keep, _P3)
    record = framing(
        {
            "wording": f"On Oct 20 the assistant said: {_SAID}",
            "supports": [
                {"part": "P1", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
                {"part": "P3", "direction": "for", "backs_as_worded": True, "how_sure": "sure"},
            ],
            "subjects": [],
            "involved": [],
            "marks": ["assistant_statement", "occasion"],
        }
    )
    claim = framing(
        {
            "wording": _SAID,
            "supports": [
                {"part": "P1", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
                {"part": "P3", "direction": "for", "backs_as_worded": False, "how_sure": "sure"},
            ],
            "subjects": [],
            "involved": [],
            "marks": ["assistant_statement"],
        }
    )

    (kept,) = _framed(view, record).memories
    backing = {one.points_at for one in kept.memory.supports if one.backs_as_worded}
    assert backing == {_P3.part}
    assert kept.memory.supports[0].points_at == _P3.part, "the create cites the message"
    assert _framed(view, claim).memories == (), "the claim is not kept as the person's"
