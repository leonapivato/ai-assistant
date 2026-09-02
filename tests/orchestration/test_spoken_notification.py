"""ADR-0206's rendering behind the poll: the placement, the four states, the budget.

Every row of ADR-0206 §12's table whose clause falls inside the contract lane —
the ``plays`` argument of §1, the placement of §3, the byte-for-byte summary of
§4, the withholding of §5, the four states and four degradations of §6, and the
budget rule of §7. §2's and §8's rows are the gateway lane's and are deliberately
absent: "a lane satisfies the rows of this table that fall inside its fence and
adds none".

The engine is built from the same canonical fakes ``test_engine.py``'s harness
uses and from ``test_engine_delivery.py``'s own wiring, so nothing here imports a
subsystem (CLAUDE.md golden rule 1).
"""

from __future__ import annotations

import asyncio
import inspect
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
import structlog
from test_engine import Harness
from test_engine_delivery import NOW, RecordingOutbox, _Advancing, _wired
from test_upcoming import Harness as UpcomingHarness
from test_upcoming import _occurrence

from ai_assistant.core import protocols as protocols_module
from ai_assistant.core.errors import SpeechError, SpeechTimeoutError
from ai_assistant.core.types import (
    DataTier,
    NotificationCandidate,
    NotificationDelivery,
    Placement,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenRendering,
)
from ai_assistant.orchestration.disclosure import (
    notification_is_speakable,
    speakable_notification_triple,
)
from ai_assistant.orchestration.upcoming import NOTIFICATION_CLASS, PRODUCER
from ai_assistant.testing import (
    FakeAssistantEngine,
    FakeContextProvider,
    FakeNotificationOutbox,
    FakeNotificationPolicy,
    FakeNotificationStore,
    FakeSpeechSynthesizer,
    FakeSpeechTranscriber,
)
from ai_assistant.wire.client import HubClient

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ai_assistant.orchestration.engine import Engine

#: One rendering, for the validator cases that need audio and never a seam.
_AUDIO = SpokenAudio(content="QUJDRA==", media_type=SpokenAudioFormat.WEBM_OPUS)

#: A payload limit a placed candidate's rendering-free delivery fits inside and its
#: rendered one does not, for §6's fourth degradation case. Measured rather than
#: guessed, so the case stays a near-ceiling one if the candidate fixture changes.
_NEAR_CEILING = 600

#: Every member, in ADR-0206 §2's shape — the gateway names the whole enumeration.
#: Named here so a case says "what a caller that can play everything asks for"
#: rather than repeating a tuple literal.
EVERYTHING = tuple(SpokenAudioFormat)

#: The two shapes a malformed ``plays`` comes in, which reach the same refusal by
#: different routes inside the enumeration: a string naming no member fails the value
#: comparison, and an **unhashable** member fails the lookup that precedes it (#1762).
#: Held together so §7's ordering is asserted over both rather than over the first.
_MALFORMED_PLAYS: tuple[tuple[object, ...], ...] = (("audio/ogg;codecs=vorbis",), ([],))
_MALFORMED_PLAYS_IDS = ("names-no-member", "unhashable")


def _placed(  # noqa: PLR0913 — one parameter per field a case may move, and no more
    key: str = "k1",
    *,
    summary: str = "your stand-up starts in ten minutes",
    detail: str | None = None,
    sensitivity: DataTier = DataTier.PERSONAL,
    producer: str = PRODUCER,
    notification_class: str = NOTIFICATION_CLASS,
) -> NotificationCandidate:
    """One candidate carrying ADR-0206 §3's placed triple unless a case moves it.

    The three fields the placement is decided from are the three parameters, so a
    case that withholds says which field it moved and nothing else changes with it.
    """
    return NotificationCandidate(
        candidate_key=key,
        producer=producer,
        notification_class=notification_class,
        summary=summary,
        detail=detail,
        noticed_at=NOW,
        expires_at=NOW + timedelta(hours=2),
        confidence=0.5,
        sensitivity=sensitivity,
    )


def _speaking(
    outbox: FakeNotificationOutbox | RecordingOutbox,
    *,
    formats: Iterable[SpokenAudioFormat] | None = None,
    synthesizer: FakeSpeechSynthesizer | None | object = None,
    **kwargs: object,
) -> tuple[Engine, FakeSpeechSynthesizer | None]:
    """An engine with speech wired over ``outbox``, and the synthesizer it holds.

    Returned as a pair because almost every case here asserts on what reached the
    seam — that it was called with one exact string, or that it was not called at
    all, which is what ADR-0206 §5's "nothing is spent" means operationally.
    """
    seam = FakeSpeechSynthesizer(formats=formats) if synthesizer is None else synthesizer
    harness = Harness(transcriber=FakeSpeechTranscriber(), synthesizer=seam)  # type: ignore[arg-type]
    engine = _wired(harness, outbox, transcriber=harness.transcriber, synthesizer=seam, **kwargs)
    return engine, seam  # type: ignore[return-value]


async def _poll_one(
    candidate: NotificationCandidate,
    *,
    plays: tuple[SpokenAudioFormat, ...] = EVERYTHING,
    formats: Iterable[SpokenAudioFormat] | None = None,
    **kwargs: object,
) -> tuple[NotificationDelivery, FakeSpeechSynthesizer]:
    """Offer one candidate and poll for it, returning the delivery and the seam."""
    outbox = FakeNotificationOutbox(now=lambda: NOW)
    await outbox.offer(candidate)
    engine, seam = _speaking(outbox, formats=formats, **kwargs)
    delivery = await engine.next_notification(plays=plays, budget=timedelta(0))
    assert delivery is not None
    assert isinstance(seam, FakeSpeechSynthesizer)
    return delivery, seam


class _AnnouncingOutbox(FakeNotificationOutbox):
    """A canonical outbox that says when a poll has parked in its wait.

    The synchronisation point ADR-0135 §2's elapsed-time reading needs a case to be
    able to aim at: the engine reads its clock **once**, at the poll's start, and a
    case that advanced the clock before that read would move the start rather than
    the elapsed time — and would then pass while exercising nothing, because the
    entry it offers is claimed on the first pass either way. A sleep cannot rule that
    out; entering the wait is proof the start instant has already been taken.
    """

    def __init__(self, **kwargs: object) -> None:
        """Create the outbox with an unset arrival-parked event."""
        super().__init__(**kwargs)  # type: ignore[arg-type]
        #: Set the first time a caller parks in :meth:`wait_for_arrival`.
        self.parked = asyncio.Event()

    async def wait_for_arrival(
        self,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's own poll budget, as the seam declares it
    ) -> bool:
        """Announce that a poll has parked, then wait exactly as the fake does."""
        self.parked.set()
        return await super().wait_for_arrival(timeout)


class TestTheArgument:
    """§1: ``plays`` on ``next_notification``, keyword-only, defaulting to ``()``."""

    @pytest.mark.parametrize(
        "subject",
        [protocols_module.AssistantEngine, FakeAssistantEngine, HubClient],
        ids=["protocol", "fake", "client"],
    )
    def test_plays_is_keyword_only_and_defaults_to_the_empty_tuple(self, subject: type) -> None:
        """The signature ADR-0206 §1 shows, on every implementation of it.

        **The order is asserted, not only the membership.** §1 shows the signature
        rather than describing it (ADR-0089 §2), and a keyword-only argument's
        position is still what a reader of the Protocol sees and what a diff of a
        later change is read against. Every parameter is keyword-only, which is
        ADR-0085 §2's convention and is what makes the position a documentation
        fact rather than a calling one.
        """
        parameters = inspect.signature(subject.next_notification).parameters  # type: ignore[attr-defined]
        assert [name for name in parameters if name != "self"] == [
            "acknowledging",
            "plays",
            "budget",
        ]
        plays = parameters["plays"]
        assert plays.kind is inspect.Parameter.KEYWORD_ONLY
        assert plays.default == ()

    async def test_an_omitted_plays_produces_not_requested_and_calls_no_synthesizer(self) -> None:
        """§1: "An empty ``plays`` asks for no rendering, and none is produced."

        No placement is decided and no synthesizer is called — which is why the
        candidate here is the *placed* one: a caller that omits the argument gets
        ``NOT_REQUESTED`` even where §3 would have placed what it was handed.
        """
        delivery, seam = await _poll_one(_placed(), plays=())

        assert delivery.spoken_rendering is SpokenRendering.NOT_REQUESTED
        assert delivery.spoken is None
        assert seam.calls == []

    async def test_an_omitted_plays_changes_nothing_else_about_the_poll(self) -> None:
        """§1: "nothing about the poll's behaviour differs from what §4 already fixes."

        The acknowledgement still retires, the selection still leases, and the
        delivery still carries the candidate — the three things ADR-0131 §4 fixes,
        driven through a poll that asked for no rendering.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        await outbox.offer(_placed("k2"))
        held = await outbox.claim()
        assert held is not None
        engine, seam = _speaking(outbox)

        delivery = await engine.next_notification(
            acknowledging=held.delivery_id, budget=timedelta(0)
        )

        assert delivery is not None
        assert delivery.notification.candidate_key == "k2"
        assert seam is not None
        assert seam.calls == []
        # The first entry was retired by the acknowledgement, so its key is free.
        assert await outbox.claim() is None


class TestTheRenderingIsProducedAtThePoll:
    """§1: produced inside the answering call, after selection, and never before."""

    async def test_no_synthesizer_is_called_at_offer_or_at_reconsideration(self) -> None:
        """§1: "No entry is rendered in advance of a poll that asked for one."

        Both of the two points before a poll that hold a candidate: the hand-off
        that enqueues one, and the reconsideration run that re-rules a held record
        to ``INTERRUPT`` and enqueues it by the same path (ADR-0131 §3b). Neither
        has a ``plays`` to be given one, and neither reaches the seam.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        engine, seam = _speaking(
            outbox,
            notifications=FakeNotificationStore(now=lambda: NOW),
            notification_policy=FakeNotificationPolicy(),
        )

        await outbox.offer(_placed())
        assert await engine.reconsider_notifications() == 0

        assert seam is not None
        assert seam.calls == []

    async def test_a_redelivery_renders_afresh(self) -> None:
        """§1: "a redelivery of the same entry renders afresh."

        The entry is delivered, its lease expires with no acknowledgement — ADR-0131
        §3's at-least-once — and the second poll reaches the seam a second time. A
        rendering cached against the entry would show up as one call, and a
        rendering retained between polls would show up as the second delivery
        carrying audio the seam never produced.
        """
        clock = _Advancing()
        outbox = FakeNotificationOutbox(now=clock, lease=timedelta(seconds=1))
        await outbox.offer(_placed())
        engine, seam = _speaking(outbox)
        assert seam is not None

        first = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))
        clock.advance(timedelta(seconds=5))
        second = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert first is not None
        assert second is not None
        assert first.spoken_rendering is second.spoken_rendering is SpokenRendering.RENDERED
        assert len(seam.calls) == 2
        # A fresh rendering of the same text is the same bytes; what distinguishes
        # "rendered twice" from "cached" is the seam's own record, not the octets.
        assert first.spoken == second.spoken
        assert first.delivery_id != second.delivery_id


class TestNothingRetainsARendering:
    """§1: no rendering reaches the outbox, a store, a trail, a trace or a log."""

    async def test_no_audio_reaches_a_store_a_trace_or_either_log_tier(self) -> None:
        """§1's retention clause, over everything this engine's state can hold.

        **What stands in for "the data directory" is every store the engine was
        wired with**, which is the strongest form the canonical fakes admit: they
        hold objects rather than bytes, so the assertion is that no held value
        anywhere in them repeats the rendering's octets. Tier 1 is
        ``structlog``'s own capture and tier 2 is the trace sink (ADR-0119), and
        ``next_notification`` passes no observation to the tracer, so a trace
        carries the operation's name and outcome and no part of its result.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        harness = Harness(transcriber=FakeSpeechTranscriber(), synthesizer=FakeSpeechSynthesizer())
        engine = _wired(
            harness,
            outbox,
            transcriber=harness.transcriber,
            synthesizer=harness.synthesizer,
        )

        with structlog.testing.capture_logs() as captured:
            delivery = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert delivery is not None
        assert delivery.spoken is not None
        audio = delivery.spoken.content
        assert audio not in repr(captured)
        assert audio not in repr(harness.trace_sink.recorded)
        assert audio not in repr(await harness.memory.export())
        # The outbox still holds the leased entry, and it holds the candidate the
        # producer wrote — never the rendering the poll made of it.
        held = await outbox.claim()
        assert held is None  # leased, not returned twice
        assert audio not in repr(outbox.__dict__)


class TestThePlacement:
    """§3: exactly one triple is placed, and every other triple is withheld."""

    def test_the_placed_triple_is_the_one_adr_0206_names(self) -> None:
        """§3's three literals, pinned against the constants the module names.

        The predicate is built from ``orchestration/upcoming.py``'s own constants so
        the placement and the producer cannot drift apart. That makes a *rename* of
        either constant invisible to every other case here, and silently moves what
        this hub says out loud — so the literals ADR-0206 §3 fixes are asserted
        directly, once, here.
        """
        assert speakable_notification_triple() == (
            "calendar-upcoming",
            "upcoming_event",
            DataTier.PERSONAL,
        )

    async def test_the_placed_triple_renders(self) -> None:
        """§3: the candidate carrying all three fields is spoken."""
        delivery, seam = await _poll_one(_placed())

        assert delivery.spoken_rendering is SpokenRendering.RENDERED
        assert delivery.spoken is not None
        assert len(seam.calls) == 1

    @pytest.mark.parametrize(
        "tier",
        [tier for tier in DataTier if tier is not DataTier.PERSONAL and tier.name != "SECRET"],
    )
    async def test_the_same_producer_and_class_at_another_tier_is_withheld(
        self, tier: DataTier
    ) -> None:
        """§3: "the same producer and the same class at any other ``sensitivity``".

        ``OPERATIONAL`` is the case ADR-0206 §3 names as making the exit test's
        withheld half demonstrable "against the producer the tree actually has,
        rather than against a fixture that exists only to be refused" — the type
        admits the value even though the producer never emits it. The other tiers
        ride the same parametrisation because §3's clause is about *any* other one.
        ``SECRET`` is absent because ADR-0130 §2 refuses it at validation.
        """
        delivery, seam = await _poll_one(_placed(sensitivity=tier))

        assert delivery.spoken_rendering is SpokenRendering.WITHHELD
        assert delivery.spoken is None
        assert seam.calls == []

    async def test_an_unnamed_producer_is_withheld(self) -> None:
        """§3: "every class of a producer this ADR does not name"."""
        delivery, seam = await _poll_one(_placed(producer="some-later-producer"))

        assert delivery.spoken_rendering is SpokenRendering.WITHHELD
        assert seam.calls == []

    async def test_an_unnamed_class_of_the_placed_producer_is_withheld(self) -> None:
        """§3: the producer alone does not carry the placement; the triple does."""
        delivery, seam = await _poll_one(_placed(notification_class="calendar-conflict"))

        assert delivery.spoken_rendering is SpokenRendering.WITHHELD
        assert seam.calls == []

    def test_the_predicate_reads_only_the_three_recorded_fields(self) -> None:
        """§3: "decided from those three recorded fields and from nothing else".

        Two candidates identical in the triple and different in every other field
        the type carries — summary, detail, confidence, expiry, key — are placed
        alike. A predicate that read any of them would separate these two.
        """
        spare = _placed(
            "k2",
            summary="a completely different sentence about something else entirely",
            detail="and a second paragraph the room never hears",
        ).model_copy(update={"confidence": 0.99, "expires_at": NOW + timedelta(days=1)})

        assert notification_is_speakable(_placed()) is notification_is_speakable(spare) is True

    async def test_a_summary_naming_an_unplaced_subject_still_renders(self) -> None:
        """§3 (no inspection): the content is never read to decide a placement.

        The one case §12 names for this row. A candidate whose summary is about the
        most obviously unspeakable subject available still renders, because its
        triple is placed — which is ADR-0199 §2's "no keyword, no pattern, no
        classifier" being *true* rather than merely intended.
        """
        delivery, seam = await _poll_one(
            _placed(
                summary="your test results from the clinic arrived, and your password is hunter2"
            )
        )

        assert delivery.spoken_rendering is SpokenRendering.RENDERED
        assert len(seam.calls) == 1


class TestThePlacementsConditionOnTheStamp:
    """§3 (stamp): ADR-0204 §3's test stays on the producer, not on the delivery."""

    async def test_the_placed_producers_proposals_carry_the_warrant_as_false(self) -> None:
        """§3: "A producer whose inputs are not records of this store … writes ``False``."

        The placed producer's inputs are what a ``Reader`` proposed over a configured
        calendar source, and what it speaks is that proposal's own sentence: ADR-0206
        §3's clause holds because the summary is the proposal's ``content`` byte for
        byte, and the proposal carries the default placement. Both halves are
        asserted, because either alone would leave the derivation open — a producer
        that composed its summary from something else would satisfy the second and
        break the clause.

        **And the producer holds nothing it could inherit a stamp from**: ADR-0132 §1
        enumerates its collaborators as a ``Reader``, a ``SourceGrants``, a clock and
        the notification writer, and the signature is asserted so a lane that handed
        it a ``MemoryStore`` would have to come back to this clause.
        """
        proposal = _occurrence(starts_in=timedelta(minutes=10))
        harness = UpcomingHarness([proposal])

        await harness.stage.notice()

        assert proposal.proposed.placement == Placement()
        assert [candidate.summary for candidate in harness.offered] == [proposal.proposed.content]
        collaborators = set(inspect.signature(harness.stage.__class__).parameters)
        assert collaborators == {"reader", "grants", "writer", "reads", "now", "lead"}

    async def test_the_delivery_path_issues_no_store_query_while_answering(self) -> None:
        """§3: "The delivery path issues no store query, holds no ``MemoryStore`` and
        no ``ContextProvider``, and reads no record."

        Every method of both Protocols is replaced with one that fails the test, so
        the assertion is total over the surface rather than over a list this case
        chose — a method added to either Protocol is covered on the day it lands.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        context = FakeContextProvider()
        harness = Harness(
            context=context,
            transcriber=FakeSpeechTranscriber(),
            synthesizer=FakeSpeechSynthesizer(),
        )
        engine = _wired(
            harness,
            outbox,
            transcriber=harness.transcriber,
            synthesizer=harness.synthesizer,
        )
        _refuse_every_call(harness.memory, protocols_module.MemoryStore)
        _refuse_every_call(context, protocols_module.ContextProvider)

        delivery = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.RENDERED


def _refuse_every_call(subject: object, protocol: type) -> None:
    """Replace every method the Protocol declares with one that fails the test."""

    async def refuse(*args: object, **kwargs: object) -> None:
        del args, kwargs
        msg = f"the delivery path reached {protocol.__name__} (ADR-0206 §3)"
        raise AssertionError(msg)

    for name, member in inspect.getmembers(protocol):
        if name.startswith("_") or not callable(member):
            continue
        object.__setattr__(subject, name, refuse)


class TestWhatIsSpoken:
    """§4: the summary, byte for byte, and nothing composes it."""

    @pytest.mark.parametrize(
        "summary",
        [
            "your stand-up starts in ten minutes",
            "  leading and trailing spaces are carried  ",
            "punctuation? Kept. Case Folded? No.",
        ],
        ids=["plain", "spaces", "punctuation"],
    )
    async def test_the_value_handed_to_synthesize_is_byte_identical(self, summary: str) -> None:
        """§4: "no prefix, no announcement, no salutation, no punctuation added or
        removed, no case folding, no trimming, and no second value composed from it".

        The spaces case is the one §12 names, and it is the discriminating one: a
        stage that trimmed would pass every other spelling here.
        """
        _, seam = await _poll_one(_placed(summary=summary))

        assert [text for text, _ in seam.calls] == [summary]

    async def test_a_candidate_with_a_detail_speaks_only_the_summary(self) -> None:
        """§4: "``detail`` is **not** spoken, on any candidate, under any placement."

        And it still travels: the page stays strictly more informative than the room,
        which is the direction every clause of ADR-0199 §5 pushes.
        """
        detail = "the room is booked until eleven and Priya cannot make the first half"
        delivery, seam = await _poll_one(_placed(detail=detail))

        assert [text for text, _ in seam.calls] == ["your stand-up starts in ten minutes"]
        assert delivery.notification.detail == detail


class TestAWithheldNotificationArrivesUnspoken:
    """§5: no rendering, no substitute, and the delivery still travels."""

    async def test_a_withheld_delivery_carries_no_audio_and_no_substitute(self) -> None:
        """§5: "no synthesizer is called, nothing is spent, and the delivery carries
        no audio", and "this ADR adds no audible substitute of any kind".

        The members of the delivery are enumerated rather than spot-checked, because
        "no substitute value of any kind is produced" is a claim about the *whole*
        value: a chime smuggled onto a fifth member would pass an assertion that only
        read ``spoken``.
        """
        delivery, seam = await _poll_one(_placed(producer="some-later-producer"))

        assert delivery.spoken_rendering is SpokenRendering.WITHHELD
        assert delivery.spoken is None
        assert seam.calls == []
        assert set(delivery.model_dump()) == {
            "delivery_id",
            "notification",
            "spoken",
            "spoken_rendering",
        }

    async def test_a_withheld_notification_is_returned_and_acknowledgeable(self) -> None:
        """§5: "The delivery is still returned by the poll", and it retires normally.

        ADR-0199 §5's "delivered on a channel that can carry it **if and when a
        device asks on one**" is satisfied by the very request that asked: one poll
        serves both of that device's channels.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed(producer="some-later-producer"))
        engine, _ = _speaking(outbox)

        delivery = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))
        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.WITHHELD

        assert (
            await engine.next_notification(
                acknowledging=delivery.delivery_id, plays=EVERYTHING, budget=timedelta(0)
            )
            is None
        )
        # Retired: the key is free again, which is what the outbox holding nothing
        # means when the store is one that holds objects rather than rows.
        assert await outbox.offer(_placed()) is not None


class TestTheEnumerationAndTheValidator:
    """§6: the four members, their fixed values, and the biconditional both ways."""

    def test_the_four_serialized_values_are_the_ones_adr_0206_fixes(self) -> None:
        """§6: "whose serialized values are fixed here and are exactly these".

        Named rather than left to the member names, because this enumeration crosses
        the wire inside a delivery: two implementations choosing ``"withheld"`` and
        ``"WITHHELD"`` would both conform to a clause naming only the members and
        would not interoperate. The membership is asserted as a whole, so a fifth
        member fails here rather than in a reader's decoder.
        """
        assert {member.name: member.value for member in SpokenRendering} == {
            "NOT_REQUESTED": "not_requested",
            "RENDERED": "rendered",
            "WITHHELD": "withheld",
            "DEGRADED": "degraded",
        }

    def test_the_values_cross_the_wire_as_the_clause_spells_them(self) -> None:
        """§6 (values): a round trip through ``wire/codec.py``, on the value itself.

        The enumeration's own membership says nothing about what a peer receives:
        what decides that is the codec's projection of a delivery carrying one. So
        the assertion is on the encoded bytes and on what validating them back
        produces, which is the pair ADR-0087 §4's normalises-nothing rule makes
        meaningful.
        """
        from ai_assistant.wire.codec import project  # noqa: PLC0415 — asserted about

        for member in SpokenRendering:
            spoken = None if member is not SpokenRendering.RENDERED else _AUDIO
            delivery = NotificationDelivery(
                delivery_id="1.abcdef",
                notification=_placed(),
                spoken=spoken,
                spoken_rendering=member,
            )
            projected = project(delivery)
            assert isinstance(projected, dict)
            assert projected["spoken_rendering"] == member.value
            assert NotificationDelivery.model_validate(projected) == delivery

    @pytest.mark.parametrize(
        ("spoken", "rendering"),
        [
            (None, SpokenRendering.NOT_REQUESTED),
            (None, SpokenRendering.WITHHELD),
            (None, SpokenRendering.DEGRADED),
        ],
        ids=lambda value: getattr(value, "name", "none"),
    )
    def test_every_admissible_shape_constructs(
        self, spoken: SpokenAudio | None, rendering: SpokenRendering
    ) -> None:
        """§6: the three unspoken members each stand beside ``spoken`` ``None``."""
        delivery = NotificationDelivery(
            delivery_id="1.abcdef",
            notification=_placed(),
            spoken=spoken,
            spoken_rendering=rendering,
        )

        assert delivery.spoken_rendering is rendering

    def test_rendered_beside_audio_constructs(self) -> None:
        """§6: the fourth admissible shape, and the only one carrying a rendering."""
        delivery = NotificationDelivery(
            delivery_id="1.abcdef",
            notification=_placed(),
            spoken=_AUDIO,
            spoken_rendering=SpokenRendering.RENDERED,
        )

        assert delivery.spoken == _AUDIO

    @pytest.mark.parametrize(
        "rendering",
        [
            SpokenRendering.NOT_REQUESTED,
            SpokenRendering.WITHHELD,
            SpokenRendering.DEGRADED,
        ],
        ids=lambda member: member.name,
    )
    def test_audio_beside_every_non_rendered_member_is_refused(
        self, rendering: SpokenRendering
    ) -> None:
        """§6: the direction that makes "audio of a withheld candidate" unconstructible.

        ``spoken`` beside every non-``RENDERED`` member, which is the enumeration
        §12's row names explicitly — a fault here would be ADR-0206 §5 defeated by a
        value rather than by a code path.
        """
        with pytest.raises(ValueError, match="carries audio exactly when"):
            NotificationDelivery(
                delivery_id="1.abcdef",
                notification=_placed(),
                spoken=_AUDIO,
                spoken_rendering=rendering,
            )

    def test_rendered_with_no_audio_is_refused(self) -> None:
        """§6, the other direction: a rendering reported and not carried."""
        with pytest.raises(ValueError, match="carries audio exactly when"):
            NotificationDelivery(
                delivery_id="1.abcdef",
                notification=_placed(),
                spoken_rendering=SpokenRendering.RENDERED,
            )

    def test_the_delivery_reserve_still_covers_the_wrapper(self) -> None:
        """§6's arithmetic, checked rather than taken.

        The two members add at most 49 bytes in ADR-0087 §2's canonical form, for a
        worst case of 179 against a 256-byte reserve. The figure is a *bound*, so
        the longest of the four values is what it is measured with — which is what
        makes this fail if a later member's value is longer rather than only if the
        wrapper grows a field.
        """
        from ai_assistant.core.types import DELIVERY_RESERVE_BYTES  # noqa: PLC0415
        from ai_assistant.orchestration.payloads import _encode, project  # noqa: PLC0415

        longest = max(len(member.value) for member in SpokenRendering)
        wrapper = len(_encode(project({"spoken": None, "spoken_rendering": "x" * longest})))
        # The measured object carries its own braces; the members inside a delivery
        # cost two commas instead, so the two structural bytes cancel.
        assert wrapper + 130 <= DELIVERY_RESERVE_BYTES


class TestTheFourDegradations:
    """§6: the four ``DEGRADED`` cases, and the delivery travels in every one."""

    async def test_an_empty_format_intersection_degrades_and_spends_nothing(self) -> None:
        """§6's second case, "discovered before the call rather than reported by one".

        The synthesizer produces only the member the caller cannot play, so the
        intersection is empty; nothing reaches the seam, which is what "the only one
        of the four that spends nothing" means operationally.
        """
        delivery, seam = await _poll_one(
            _placed(),
            plays=(SpokenAudioFormat.MP4,),
            formats=(SpokenAudioFormat.WEBM_OPUS,),
        )

        assert delivery.spoken_rendering is SpokenRendering.DEGRADED
        assert delivery.spoken is None
        assert delivery.notification.candidate_key == "k1"
        assert seam.calls == []

    async def test_a_hub_with_no_synthesizer_reaches_the_same_case(self) -> None:
        """The empty intersection where the seam itself is absent.

        A deployment that composed no speech seams can produce no format, so the
        intersection of ``plays`` with what it can produce is empty. Raising instead
        would fail every poll of a speech-less hub the moment a caller that can play
        audio asked — losing the notification to a deployment choice, which ADR-0131
        §3's durability and ADR-0206 §6's "a failure to speak never fails the poll"
        both refuse.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        engine = _wired(Harness(transcriber=None, synthesizer=None), outbox)

        delivery = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.DEGRADED
        assert delivery.spoken is None

    async def test_a_speech_error_degrades(self) -> None:
        """§6's first case: "synthesis raised a ``SpeechError``"."""
        seam = FakeSpeechSynthesizer()
        seam.fail_next_synthesize(SpeechError("the voice is unavailable"))
        delivery, _ = await _poll_one(_placed(), synthesizer=seam)

        assert delivery.spoken_rendering is SpokenRendering.DEGRADED
        assert delivery.notification.candidate_key == "k1"

    async def test_a_synthesis_timeout_degrades_as_a_speech_error(self) -> None:
        """§6, §7: the decorator's expiry "is a ``SpeechError`` and is the first case".

        The clause that keeps §7's "an elapsed budget is not among them" from being
        a hole: the *decorator's* deadline still degrades, and it does so through
        the ``SpeechError`` arm rather than through a budget arm that does not exist.
        """
        seam = FakeSpeechSynthesizer()
        seam.fail_next_synthesize(SpeechTimeoutError("the rendering did not complete"))
        delivery, _ = await _poll_one(_placed(), synthesizer=seam)

        assert delivery.spoken_rendering is SpokenRendering.DEGRADED

    async def test_a_rendering_over_the_audio_bound_degrades(self) -> None:
        """§6's third case: "the rendering breached ADR-0200 §6's bound"."""
        delivery, seam = await _poll_one(_placed(), max_spoken_audio_bytes=8)

        assert delivery.spoken_rendering is SpokenRendering.DEGRADED
        assert delivery.spoken is None
        # Spent, unlike the empty intersection: the bound is measured on what came
        # back, so the seam was reached.
        assert len(seam.calls) == 1

    async def test_a_delivery_over_the_payload_limit_degrades_rather_than_raising(self) -> None:
        """§6's fourth case, and §12's near-ceiling row.

        The candidate is lawful for ``offer`` — the delivery carrying it and no
        rendering encodes well inside the limit — and the rendering is what puts the
        whole projected result over. It degrades rather than raising, because
        ADR-0131 §4's reserve guarantees the rendering-free delivery fits and there
        is nothing further to drop.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        engine, seam = _speaking(outbox, max_payload_bytes=_NEAR_CEILING)

        delivery = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.DEGRADED
        assert delivery.spoken is None
        assert delivery.notification.candidate_key == "k1"
        assert seam is not None
        assert len(seam.calls) == 1


class TestWithholdingIsNeverDegradation:
    """§6: the two are never collapsed, and a withholding is never retried."""

    async def test_a_withheld_delivery_is_not_retried_into_speech_on_the_next_poll(self) -> None:
        """§6: "the placement of §3 is a property of the candidate and not of the
        attempt".

        The entry is delivered unspoken, its lease expires, and the second poll
        withholds it again — with the seam never reached on either. A fault invites a
        retry, and a withholding retried is a disclosure rule defeated by a loop,
        which is the whole reason this is a closed enumeration rather than a boolean.
        """
        clock = _Advancing()
        outbox = FakeNotificationOutbox(now=clock, lease=timedelta(seconds=1))
        await outbox.offer(_placed(producer="some-later-producer"))
        engine, seam = _speaking(outbox)
        assert seam is not None

        first = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))
        clock.advance(timedelta(seconds=5))
        second = await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))

        assert first is not None
        assert second is not None
        assert first.spoken_rendering is SpokenRendering.WITHHELD
        assert second.spoken_rendering is SpokenRendering.WITHHELD
        assert seam.calls == []


class TestTheTranslationIsTotal:
    """§6: ``SpeechError`` degrades, and every other exception propagates."""

    async def test_a_speech_error_degrades_and_never_fails_the_poll(self) -> None:
        """§6: "A failure to speak never fails the poll."

        A poll that raised because a synthesizer failed would spend an entry's lease
        on a fault, and the owner would see the notification later or not at all —
        losing a notification to a speech engine, which is what ADR-0131 §3's
        durability exists to prevent.
        """
        seam = FakeSpeechSynthesizer()
        seam.fail_next_synthesize(SpeechError("the voice is unavailable"))
        delivery, _ = await _poll_one(_placed(), synthesizer=seam)

        assert delivery.spoken_rendering is SpokenRendering.DEGRADED

    async def test_every_other_exception_propagates_unchanged(self) -> None:
        """§6: "the stage catches ``SpeechError`` and does not catch ``Exception``".

        A stage that could be wholly broken while every call reported the same
        classified-looking degradation is the state hardest to notice (ADR-0170 §8's
        own shape), so a defect arrives as itself.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        seam = FakeSpeechSynthesizer()
        seam.fail_next_synthesize(RuntimeError("the seam is wired to nothing"))
        engine, _ = _speaking(outbox, synthesizer=seam)

        with pytest.raises(RuntimeError, match="wired to nothing"):
            await engine.next_notification(plays=EVERYTHING, budget=timedelta(0))


class TestCancellation:
    """§6: a cancellation is neither a withholding nor a degradation."""

    async def test_a_cancel_inside_a_blocked_synthesis_propagates_and_sets_nothing(self) -> None:
        """§6: "It propagates after cancellation-safe cleanup … and it never sets
        ``spoken_rendering``."

        The four things §12's row asks for: the ``CancelledError`` propagates, no
        delivery is returned, none is acknowledged, and the leased entry returns to
        the outbox on lease expiry — which is ADR-0131 §2a's "a cancel arriving
        during or after [the selection] leaves the lease standing", reached one step
        later than it used to be and unchanged by that.
        """
        clock = _Advancing()
        outbox = FakeNotificationOutbox(now=clock, lease=timedelta(seconds=1))
        await outbox.offer(_placed())
        seam = FakeSpeechSynthesizer()
        engine, _ = _speaking(outbox, synthesizer=seam)
        held = seam.suspend_next_synthesize()

        poll = asyncio.ensure_future(
            engine.next_notification(plays=EVERYTHING, budget=timedelta(seconds=30))
        )
        await held.reached()
        poll.cancel()
        with pytest.raises(asyncio.CancelledError):
            await poll
        held.release()

        # Nothing came back and nothing was retired: the entry is still leased, and
        # it returns to the outbox when that lease runs out.
        assert await outbox.claim() is None
        clock.advance(timedelta(seconds=5))
        again = await outbox.claim()
        assert again is not None
        assert again.notification.candidate_key == "k1"


class TestTheBudget:
    """§7: the rendering is the request's own work, whatever the budget says."""

    async def test_an_entry_selected_with_the_budget_already_elapsed_still_renders(self) -> None:
        """§7: "It is performed after the selection step, [and] runs to completion
        whatever the state of the budget."

        **The engine's own clock is moved past the budget while the poll is parked**,
        which is what makes this the boundary case rather than a late arrival. The
        sequence the poll actually runs is: read the start instant, find nothing,
        park on ``wait_for_arrival``; the clock jumps a minute past a one-second
        budget and the entry is offered, waking the wait; the loop's next act is
        ``claim()``, which is reached **before** any budget arithmetic and produces a
        delivery. ADR-0135 §3's "an elapsed budget is no ground for withholding a
        delivery that selection produced" therefore governs, and ADR-0206 §7 adds the
        rendering to the same list.

        A stage that consulted the budget before rendering would see it long gone and
        degrade, and this is the case that catches it — a fixed clock cannot, because
        the elapsed time is then zero however long the poll really waits.
        """
        clock = _Advancing()
        outbox = _AnnouncingOutbox(now=lambda: NOW, lease=timedelta(seconds=30))
        seam = FakeSpeechSynthesizer()
        harness = Harness(transcriber=FakeSpeechTranscriber(), synthesizer=seam)
        engine = _wired(
            harness,
            outbox,
            now=clock,
            transcriber=harness.transcriber,
            synthesizer=seam,
        )

        async def outlive_the_budget() -> None:
            # **Waited for rather than slept past.** The poll being parked in
            # ``wait_for_arrival`` is proof it has already read its start instant, so
            # advancing now really moves the *elapsed* time rather than the start. A
            # sleep would leave the case passing on a poll that began after the
            # advance, which is the same silent weakening the round before this one
            # had — it would claim the entry on its first pass with a budget that had
            # never elapsed.
            await outbox.parked.wait()
            clock.advance(timedelta(minutes=1))
            await outbox.offer(_placed())

        delivery, _ = await asyncio.gather(
            asyncio.wait_for(
                engine.next_notification(plays=EVERYTHING, budget=timedelta(seconds=1)), 3
            ),
            outlive_the_budget(),
        )

        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.RENDERED
        assert delivery.spoken is not None
        assert len(seam.calls) == 1
        # The ordering is guaranteed rather than raced: the clock is advanced
        # *before* the entry is offered, and no ``claim()`` can produce it before it
        # is offered — so the budget really had run out when selection produced this
        # delivery, by a minute against a one-second budget.
        assert clock() - NOW > timedelta(seconds=1)

    async def test_a_zero_budget_selects_at_once_and_still_renders(self) -> None:
        """§7: "a zero budget renders exactly as any other budget does".

        ADR-0131 §4's immediate poll under ADR-0135 §3: it selects at once and then
        does the request's own work, which a stage that read the budget would have
        declined outright.
        """
        delivery, seam = await _poll_one(_placed(), plays=EVERYTHING)

        assert delivery.spoken_rendering is SpokenRendering.RENDERED
        assert len(seam.calls) == 1

    @pytest.mark.parametrize(
        "budget",
        [timedelta(0), timedelta(microseconds=1), timedelta(seconds=30)],
        ids=["zero", "sliver", "generous"],
    )
    async def test_degraded_is_never_returned_for_a_placed_candidate_at_any_budget(
        self, budget: timedelta
    ) -> None:
        """§7 (no budget degradation): "No implementation degrades on an elapsed budget."

        The synthesizer succeeds at every budget, so the only way ``DEGRADED`` could
        appear is a stage that read one — which is the fifth degradation case ADR-0206
        §6 removed after adversarial review found it contradicted ADR-0135 §3.
        """
        delivery, _ = await _poll_one(_placed(), plays=EVERYTHING)
        assert delivery.spoken_rendering is SpokenRendering.RENDERED

        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed("k2"))
        engine, _ = _speaking(outbox)

        second = await engine.next_notification(plays=EVERYTHING, budget=budget)

        assert second is not None
        assert second.spoken_rendering is SpokenRendering.RENDERED


class TestTheOrdering:
    """§7: a malformed ``plays`` is refused before any outbox state changes."""

    @pytest.mark.parametrize("malformed", _MALFORMED_PLAYS, ids=_MALFORMED_PLAYS_IDS)
    async def test_a_malformed_plays_retires_nothing_leases_nothing_and_mints_nothing(
        self, malformed: tuple[object, ...]
    ) -> None:
        """§7: ADR-0131 §4's ordering rule reaching this ADR's own argument.

        The poll carries a valid ``acknowledging`` beside a ``plays`` that is not a
        format. Without the ordering, the acknowledgement would
        land and permanently retire a delivery while the call reported failure, so
        the device's retry would find the notification gone. The outbox records the
        order it was driven in, and the assertion is that it was not driven at all.

        Both malformed shapes are here because they fail on **different lines inside
        the enumeration**: a string naming no member fails the value comparison, and
        an unhashable member fails the lookup that precedes it and used to escape as
        an undeclared ``TypeError`` (#1762). The refusal a caller sees is one refusal
        either way, and the ordering it is refused before is the same.
        """
        outbox = RecordingOutbox()
        engine, seam = _speaking(outbox)

        with pytest.raises(ValueError, match="not one of them"):
            await engine.next_notification(
                acknowledging="1.abcdef",
                plays=malformed,  # type: ignore[arg-type]  # the malformed value is the subject
                budget=timedelta(0),
            )

        assert outbox.calls == []
        assert seam is not None
        assert seam.calls == []

    @pytest.mark.parametrize("malformed", _MALFORMED_PLAYS, ids=_MALFORMED_PLAYS_IDS)
    async def test_the_canonical_fake_refuses_it_the_same_way(
        self, malformed: tuple[object, ...]
    ) -> None:
        """Parity: the double a consumer tests against holds the same ordering.

        ADR-0084 §4's substitutability clause — a clause either binds both
        implementations or binds neither — reaching this argument, over both shapes
        the concrete engine is held to above.
        """
        engine = FakeAssistantEngine()

        with pytest.raises(ValueError, match="not one of them"):
            await engine.next_notification(
                plays=malformed,  # type: ignore[arg-type]  # the malformed value is the subject
                budget=timedelta(0),
            )

    async def test_a_member_s_own_value_is_not_malformed(self) -> None:
        """The line between the two, and why it is where the wire puts it.

        ADR-0087 §7 fixes the order as decode, validate into the declared type, then
        measure — so ``wire.surface``'s adapter turns ``"audio/mp4"`` into
        :attr:`~ai_assistant.core.types.SpokenAudioFormat.MP4` before the hub sees
        it, and a client spelling a member's value is a conforming caller. An
        in-process engine that refused the same spelling would be strictly less
        capable than the client standing in for it, which ADR-0084 §4 forbids "in
        **either** direction". So it is coerced, and the format that reaches the seam
        is the member either way.
        """
        outbox = FakeNotificationOutbox(now=lambda: NOW)
        await outbox.offer(_placed())
        engine, seam = _speaking(outbox)

        delivery = await engine.next_notification(
            plays=("audio/mp4",),  # type: ignore[arg-type]  # a member's value, which is admitted
            budget=timedelta(0),
        )

        assert delivery is not None
        assert delivery.spoken_rendering is SpokenRendering.RENDERED
        assert delivery.spoken is not None
        assert delivery.spoken.media_type is SpokenAudioFormat.MP4
        assert seam is not None
        assert [media_type for _, media_type in seam.calls] == [SpokenAudioFormat.MP4]
