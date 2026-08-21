"""Shared conformance suite for the StreamingCompleter Protocol (ADR-0173 §5).

Every ``StreamingCompleter`` implementation must pass this suite (CONTRIBUTING,
"Protocol conformance suites"). A concrete test subclasses
:class:`StreamingCompleterContract`, overrides the ``completer`` fixture, and
implements :meth:`StreamingCompleterContract.world` — the hook that lets the
suite *script the seam underneath the subject*, which is what makes ADR-0173
§5's commit boundary assertable rather than assumed.

**The boundary cases are the reason this suite exists, and they are the ones a
natural test of a stream omits.** Every obvious case uses a cooperative double
that yields tidy word-sized deltas and never fails, and such a double cannot
distinguish a design whose guarantee is structural from one whose guarantee is a
hope about well-behaved inputs (ADR-0173 §14). So the suite scripts *attempts*:
what a route yields before it fails, and what a second route would yield if the
subject were permitted to reach it.

Named ``*_contract`` (not ``test_*``) so pytest collects it only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

import pytest

from ai_assistant.core.errors import ModelError
from ai_assistant.core.protocols import StreamingCompleter
from ai_assistant.core.types import Message, Role
from ai_assistant.testing import StreamAttempt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Sequence

#: One conversation turn's full identity — role, content, and optional name. The
#: same space ``model_provider_contract`` fingerprints in, and for its reason: a
#: caller can *replace* a turn with one of identical text but a different role, a
#: tear a content-only fingerprint records as no change at all.
type Turn = tuple[Role, str, str | None]

#: The shapes ADR-0066 §1's precondition refuses, as role sequences. Identical to
#: ``ModelProvider``'s, deliberately: ADR-0173 §5 widens the model seam's
#: admissible history by nothing, so a shape one seam refuses the other refuses.
#:
#: The lone assistant turn is not a redundant copy of the two-message case: a
#: plausible ``len(messages) > 1 and messages[-1].role is Role.ASSISTANT`` guard
#: passes the two-message case and leaves this one live.
_REFUSED_SHAPES = [
    pytest.param([], id="empty"),
    pytest.param([Role.USER, Role.ASSISTANT], id="ends-on-assistant"),
    pytest.param([Role.ASSISTANT], id="lone-assistant"),
]

#: Both spellings of "this delta published nothing" (ADR-0173 §5). They are
#: parametrised rather than collapsed because they are not the same fact about
#: the seam: the empty string is the one a transport may legitimately drop before
#: it ever reaches the implementation, and a whitespace delta is one it must
#: carry, since a caller has to be able to join it to the text on either side.
_BLANK_DELTAS = [
    pytest.param("", id="empty-delta"),
    pytest.param("   ", id="whitespace-delta"),
]

#: A ``str`` Python holds happily and no UTF-8 encoder will accept: half of a
#: character rather than a character (``core.types.encodable_text``).
_UNENCODABLE = "\ud800"

#: What a failure of the input-observation case means, in one place (ADR-0065).
_TORN_INPUT = (
    "the stream derived its request from more than one observation of its "
    "conversation: a caller's mutation reached one attempt and not another, so "
    "no single version of the input describes what was sent"
)


class StreamingWorld(Protocol):
    """A scripted streaming subject, and what the seam under it did.

    The binding builds one of these from a script of :class:`StreamAttempt`. What
    plays the script is the implementation's business and not the suite's — the
    canonical fake *is* its own script, and a provider-backed implementation
    stands up a programmable transport (ADR-0069 §3's reasoning, one seam over).
    """

    @property
    def completer(self) -> StreamingCompleter:
        """The subject under test, scripted with this world's attempts."""
        ...

    @property
    def attempts(self) -> int:
        """How many underlying attempts the subject actually started."""
        ...

    @property
    def observed(self) -> tuple[tuple[Turn, ...], ...]:
        """The conversation each attempt was handed, oldest attempt first."""
        ...


def _history(roles: Sequence[Role]) -> list[Message]:
    """Build a conversation of ``roles``, one message per role, in order."""
    return [Message(role=role, content=f"{role.name.lower()} turn") for role in roles]


def _a_question() -> list[Message]:
    """The shortest history this seam answers."""
    return [Message(role=Role.USER, content="hi")]


def _conversation() -> list[Message]:
    """A multi-turn history over the system/user/assistant roles.

    Tool-role handling is *not* excluded the way ``ModelProviderContract``
    excludes it: ADR-0173 §5 makes the ``Role.TOOL`` refusal a clause of this
    Protocol rather than an implementation's own choice, so it is asserted below.
    """
    return [
        Message(role=Role.SYSTEM, content="be terse"),
        Message(role=Role.USER, content="hi"),
        Message(role=Role.ASSISTANT, content="hello"),
        Message(role=Role.USER, content="how are you?"),
    ]


def _fingerprint(messages: Sequence[Message]) -> tuple[Turn, ...]:
    """The full identity of every turn in ``messages`` — role, content, and name."""
    return tuple((m.role, m.content, m.name) for m in messages)


async def _drain(stream: AsyncIterator[str]) -> list[str]:
    """Read a stream to exhaustion, returning every delta it yielded."""
    return [delta async for delta in stream]


async def drain_into(stream: AsyncIterator[str], seen: list[str]) -> None:
    """Read a stream to exhaustion, appending each delta to ``seen`` as it arrives.

    Incremental on purpose: a stream that raises part-way has still handed the
    caller everything before the failure, and that is half of what the boundary
    cases assert.
    """
    async for delta in stream:
        seen.append(delta)


async def _drain_until_it_fails(
    start: Callable[[], AsyncIterator[str]],
) -> tuple[list[str], ModelError]:
    """Drive a stream expecting it to raise, returning the deltas and the failure.

    **It takes the call rather than the iterator, and that is the contract
    speaking rather than a convenience.** ADR-0173 §5 lets an implementation raise
    a precondition failure "from the call or from the iteration", so a suite that
    took an already-built iterator would pass for one shape and error out on the
    other before a single assertion ran. Holding the call inside the ``raises``
    block makes both shapes one case.

    Both halves are returned because both are asserted: which failure came out,
    and — the half a bare ``pytest.raises`` throws away — exactly what the caller
    had already been handed when it did.
    """
    seen: list[str] = []
    with pytest.raises(ModelError) as caught:
        await drain_into(start(), seen)
    return seen, caught.value


class StreamingCompleterContract:
    """The behavioural contract every ``StreamingCompleter`` implementation satisfies."""

    @pytest.fixture
    def completer(self) -> StreamingCompleter:
        """Override in a subclass to supply the implementation under test."""
        raise NotImplementedError

    def world(self, *attempts: StreamAttempt) -> StreamingWorld:
        """Override to supply a subject whose seam plays ``attempts`` in order.

        An attempt yields its deltas and then either completes or fails with a
        ``retryable``, ``routable`` :class:`~ai_assistant.core.errors.ModelError`.
        A second attempt is reached only if the subject substitutes — which
        ADR-0173 §5 permits before the first non-blank delta and forbids after it,
        and which is the whole thing this hook exists to make observable.
        """
        raise NotImplementedError

    #: Whether this implementation ever takes a **second** attempt at one
    #: ``stream`` call. ``False`` is the conforming answer for a direct
    #: provider-backed seam: ADR-0173 §5 says an implementation *may* substitute
    #: before it commits, never that it must, and one that never substitutes
    #: satisfies the boundary the strong way. It is also the only re-read window
    #: this seam has, so the two cases below reduce for such a subject exactly as
    #: ``ModelProviderContract``'s input case reduces for a provider that never
    #: suspends (ADR-0069 §3).
    substitutes_before_commit: bool = False

    def test_conforms_to_protocol(self, completer: StreamingCompleter) -> None:
        assert isinstance(completer, StreamingCompleter)

    async def test_stream_yields_the_reply_as_text_deltas(
        self, completer: StreamingCompleter
    ) -> None:
        deltas = await _drain(completer.stream(_a_question()))

        assert all(isinstance(delta, str) for delta in deltas)
        # The join is the only thing about the deltas the contract promises
        # (ADR-0173 §5): not their count, not their size, not a token boundary.
        assert "".join(deltas).strip()

    async def test_stream_handles_a_multi_turn_conversation(
        self, completer: StreamingCompleter
    ) -> None:
        deltas = await _drain(completer.stream(_conversation()))

        assert "".join(deltas).strip()

    async def test_stream_accepts_the_model_keyword(self, completer: StreamingCompleter) -> None:
        # The ``model`` override is part of the contract's surface; passing it
        # explicitly (here as ``None``, the "use the default" value) must be
        # accepted without resolving a real model. That an override is actually
        # honoured can only be checked offline per implementation.
        deltas = await _drain(completer.stream(_a_question(), model=None))

        assert "".join(deltas).strip()

    # ADR-0066 §1, unwidened by ADR-0173 §5. The three cases below pin every
    # shape the rule refuses, the shape it admits by omission that a plausible
    # over-broad guard would reject, and the ``Role.TOOL`` refusal — which,
    # unlike on ``ModelProvider``, is this Protocol's own clause and not an
    # implementation's private choice.

    @pytest.mark.parametrize("roles", _REFUSED_SHAPES)
    async def test_stream_refuses_a_conversation_awaiting_nothing(
        self, completer: StreamingCompleter, roles: list[Role]
    ) -> None:
        seen, failure = await _drain_until_it_fails(lambda: completer.stream(_history(roles)))

        assert seen == []
        # The *disposition*, not the class. ``pytest.raises(ModelError)`` alone is
        # satisfied by ModelUnavailableError, which is retryable and routable — so
        # an implementation could pass this case while a caller walked a malformed
        # conversation down every fallback route (ADR-0066 §3, §6).
        assert failure.retryable is False
        assert failure.routable is False

    async def test_stream_refuses_a_history_carrying_a_tool_turn(
        self, completer: StreamingCompleter
    ) -> None:
        history = [
            Message(role=Role.USER, content="what is the weather"),
            Message(role=Role.TOOL, content="sunny", name="weather"),
            Message(role=Role.USER, content="and tomorrow?"),
        ]

        seen, failure = await _drain_until_it_fails(lambda: completer.stream(history))

        assert seen == []
        assert failure.retryable is False
        assert failure.routable is False

    async def test_stream_accepts_a_history_ending_on_a_system_turn(
        self, completer: StreamingCompleter
    ) -> None:
        # The other side of the boundary, and the reason it is worth a case: the
        # rule is "does not end on an assistant turn", *not* "ends on a user
        # turn". Every other positive case here ends on a user turn, so an
        # implementation writing the over-broad ``if messages[-1].role is not
        # Role.USER: raise`` would satisfy the refusals and the conversation
        # cases alike while rejecting a call that works (ADR-0066 §1).
        deltas = await _drain(completer.stream(_history([Role.USER, Role.SYSTEM])))

        assert "".join(deltas).strip()

    # --- the blank stream (ADR-0173 §5, ADR-0170 §8, #1324) ------------------

    @pytest.mark.parametrize("blank", _BLANK_DELTAS)
    async def test_a_stream_that_publishes_nothing_is_not_a_failure(self, blank: str) -> None:
        """A stream of only blank deltas completes; classifying it is the caller's.

        ADR-0173 §5 sends the blank case to ADR-0170 §8's above-the-seam
        classification and changes no ``ModelProvider`` postcondition, so the seam
        must **not** invent a refusal here — which is exactly what #1324 holds
        open, and what an implementation that raised ``ModelResponseError`` on an
        empty answer would decide unilaterally.
        """
        world = self.world(StreamAttempt(deltas=(blank, blank)))

        deltas = await _drain(world.completer.stream(_a_question()))

        assert not "".join(deltas).strip()

    # --- the commit boundary (ADR-0173 §5, §14) ------------------------------

    async def test_no_substitution_after_the_first_non_blank_delta(self) -> None:
        """Past the boundary a failure is raised, never repaired underneath.

        The second attempt is scripted with text the caller must never see: a
        substitute route answering a question already half-answered produces a
        reply that does not begin with what the user has read, and no clause
        anywhere says which of the two was the answer (ADR-0173 §5).
        """
        world = self.world(
            StreamAttempt(deltas=("hello",), fails=True),
            StreamAttempt(deltas=("a second route's answer",)),
        )

        seen, _failure = await _drain_until_it_fails(lambda: world.completer.stream(_a_question()))

        assert "".join(seen) == "hello"
        assert "a second route's answer" not in "".join(seen)
        assert world.attempts == 1

    @pytest.mark.parametrize("blank", _BLANK_DELTAS)
    async def test_a_blank_delta_leaves_the_failure_actionable(self, blank: str) -> None:
        """Before the boundary the dispositions survive, so a caller may still act.

        The universal half of the boundary's other side. A subject that never
        substitutes must still hand the failure up **undowngraded**, because
        ADR-0173 §5 makes ``retryable`` and ``routable`` actionable right up to
        the first non-blank delta — and a seam that flattened them to the bare
        class here would silently retire that resilience for every caller.
        """
        world = self.world(StreamAttempt(deltas=(blank,), fails=True))

        seen, failure = await _drain_until_it_fails(lambda: world.completer.stream(_a_question()))

        assert not "".join(seen).strip(), "nothing non-blank may have been published"
        assert failure.retryable is True
        assert failure.routable is True

    @pytest.mark.optional_obligation
    @pytest.mark.parametrize("blank", _BLANK_DELTAS)
    async def test_a_blank_delta_still_permits_substitution(self, blank: str) -> None:
        """A subject that substitutes at all may still substitute after a blank delta.

        This is the case ADR-0173 §14 says a suite must not omit: one asserting
        only that substitution *stops* is satisfied by an implementation that
        commits on any delta at all, which gives away the resilience the boundary
        was drawn at the first **non-blank** delta to keep. Skipped for a subject
        that substitutes at no point, which conforms the strong way and has
        nothing here to observe.
        """
        if not self.substitutes_before_commit:
            pytest.skip("this implementation never substitutes, so it commits nothing early")
        world = self.world(
            StreamAttempt(deltas=(blank,), fails=True),
            StreamAttempt(deltas=("recovered",)),
        )

        deltas = await _drain(world.completer.stream(_a_question()))

        assert "".join(deltas).strip() == "recovered"
        assert world.attempts == 2

    # --- encodability at the seam (ADR-0085 §4c, ADR-0173 §5, §14) -----------

    @pytest.mark.parametrize(
        ("deltas", "label"),
        [
            pytest.param((_UNENCODABLE,), "first", id="first-delta"),
            pytest.param(("ok ", _UNENCODABLE), "later", id="later-delta"),
        ],
    )
    async def test_a_delta_with_no_utf8_encoding_is_refused_at_the_seam(
        self, deltas: tuple[str, ...], label: str
    ) -> None:
        """Half a character is refused here, not several layers above.

        Asserted as a ``ModelError`` and not merely as "something raised": the
        defect this closes is a bare pydantic ``ValidationError`` surfacing out of
        whatever the caller built from the delta, which is a different exception
        type, reaches a different handler, and names the caller's own type rather
        than the model that produced the fault (ADR-0173 §14).
        """
        world = self.world(StreamAttempt(deltas=deltas))

        seen, _failure = await _drain_until_it_fails(lambda: world.completer.stream(_a_question()))

        assert _UNENCODABLE not in "".join(seen), f"the {label} unencodable delta escaped the seam"

    # --- input observation (ADR-0065) ---------------------------------------

    @pytest.mark.optional_obligation
    async def test_every_attempt_rests_on_one_observation_of_the_conversation(self) -> None:
        """``core.protocols``' input clause, on ``stream`` (ADR-0065, ADR-0069 §3).

        A stream suspends between reading its conversation and finishing with it,
        so a caller may mutate the ``Sequence`` it still owns while the stream is
        in flight. What the clause buys is that the outcome is *coherent* — not
        that any chosen version wins — so the assertion is that every attempt
        describes **one** version, which is only observable where a second attempt
        exists. Skipped otherwise, exactly as ``ModelProviderContract`` reduces
        for a provider that never suspends: a call that reads its argument once
        and never again has no window to tear in.
        """
        if not self.substitutes_before_commit:
            pytest.skip("a subject with one attempt per call has no re-read window to tear")
        world = self.world(
            StreamAttempt(deltas=("   ",), fails=True),
            StreamAttempt(deltas=("recovered",)),
        )
        conversation = _a_question()
        before = _fingerprint(conversation)

        stream = world.completer.stream(conversation)
        first = await anext(stream)
        # Mid-flight: the subject is suspended between its two attempts, which is
        # the only window the clause is about. A post-call mutation cannot tell a
        # subject that snapshots from one that re-reads.
        conversation.append(Message(role=Role.USER, content="wait, actually"))
        rest = await _drain(stream)

        assert world.attempts == 2, "the case never reached the second attempt"
        assert len(set(world.observed)) == 1, _TORN_INPUT
        assert _fingerprint(conversation) != before, "the caller's list was never mutated"
        assert "".join([first, *rest]).strip() == "recovered"
