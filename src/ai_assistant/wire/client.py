"""The client: an ``AssistantEngine`` whose implementation is a socket.

This is the **second implementation** ADR-0042 §1's revisit trigger named — "a
remote engine" — and it is why the surface is a Protocol at all. An adapter holding
one of these and an adapter holding the in-process
:class:`~ai_assistant.orchestration.engine.Engine` run the same code, which is what
"hub and spokes" means (ADR-0084 §5). The shared conformance suite is what makes
that a fact rather than an intention.

**It is stateless, by decision rather than by description** (ADR-0084 §7). Under a
resident hub a continuation token *could* outlive a command — the engine lives on —
and the client nonetheless does not persist one; it re-enumerates through
``pending_confirmations()``. "A client that cached tokens would behave differently
depending on whether the hub happened to restart between two commands, and 'it
works unless something invisible happened' is the opposite of legible."

**One connection per call**, which falls out of that statelessness rather than
being a separate choice. ADR-0084 §3 makes a connection serial — "a connection
carries one outstanding request at a time" — and notes that closing is the cheap
answer to a violation precisely because "the client is stateless (§7), so
reconnecting costs it nothing". Taking that literally buys three things: the
handshake's published frame size is never stale, two concurrent calls cannot
interleave on one stream, and there is no session for a hub restart to invalidate.
It costs two extra frames on a Unix socket per call, which is not a figure a CLI
can measure.

**A closed door is an instruction, never a fallback** (ADR-0084 §9). When nothing
is listening the client raises
:class:`~ai_assistant.wire.errors.HubUnavailableError` naming the socket path and
how to start the hub. It does not spawn the hub (ruling 3) and does not build an
in-process engine (ruling 5) — the latter now also mechanically impossible, since
``interfaces`` may no longer import ``app``.

**One call may read many frames, and that is the largest single cost ADR-0173
carries** (§11). :meth:`HubClient._call` writes one frame and reads exactly one;
:meth:`HubClient._stream_call` reads until a terminal frame, checking **every**
frame's correlation id rather than only the last, and resolving the union it hands
back by frame kind rather than by inspecting a payload (ADR-0173 §4). The connection
is still one per call and still serial — there is one *request* — and closing the
iterator is what hangs it up, which is why the contract states that obligation on
the caller rather than leaving it to be discovered.

**Two transports, one client** (ADR-0124 §1). Everything above holds on the remote
transport too, so :class:`HubClient` carries it and the two concrete clients differ
in exactly one method: how a connection is opened, who is authenticated on the
other end, and what the connect frame carries. That is also the whole of what
ADR-0124 §9 needs to be true — "the remote listener adds no member to the connect
exchange, changes no frame's encoding, and changes no method's arguments or
results" — and it is why ``PROTOCOL_VERSION`` does not move for the hop. The remote
half lives in :mod:`ai_assistant.wire.remote`.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final

from ai_assistant.core.types import DEFAULT_PAGE_SIZE, SpokenDeliveryState, secret_value
from ai_assistant.wire import envelope as env
from ai_assistant.wire.codec import (
    ENVELOPE_RESERVE_BYTES,
    arguments_object,
    check_payload,
    grant_scope,
    identifier,
    non_blank_text,
    page_argument,
    positive_page_argument,
    project,
    usable_identity,
)
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    HubUnavailableError,
    ProtocolError,
    raise_from_payload,
)
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.peer import check_peer_is_self
from ai_assistant.wire.surface import chunk_adapter, return_adapter, terminal_adapter

if TYPE_CHECKING:
    import socket
    from collections.abc import AsyncIterator, Sequence
    from datetime import timedelta
    from pathlib import Path

    from ai_assistant.core.types import (
        AnswerOutcome,
        Belief,
        BeliefBand,
        BeliefSummary,
        Confirmation,
        ConnectedAccount,
        ConnectionAct,
        ContinuationToken,
        ConversationDigest,
        ConversationSummary,
        EncodableText,
        FeedbackEvent,
        GrantableSource,
        GrantScope,
        HeldNotification,
        Identifier,
        LearnOutcome,
        MemoryKind,
        NonBlankEncodableText,
        NotificationDelivery,
        NotificationPreferences,
        ObservationReport,
        PermissionDecision,
        Placement,
        Question,
        RecordedInvocation,
        ReplyChunk,
        SecretValue,
        SourceGrant,
        SourceReadRecord,
        SpendTotal,
        SpokenAudio,
        SpokenAudioFormat,
        SpokenDeliveryReport,
        SpokenTurn,
        TurnOutcome,
    )

#: The free-form name the connect frame carries, for the hub's logs (ADR-0084 §2).
DEFAULT_CLIENT_NAME: Final[str] = "assistant-cli"

#: How much of a frame the handshake may take before the hub is treated as stalled.
#: A ceiling on the *bootstrap* only: a response to a request is bounded by the
#: call's own semantics, not by a transport figure (:func:`read_frame`).
_HANDSHAKE_FRAME_BYTES: Final[int] = 64 * 1024


@dataclass(frozen=True, slots=True)
class Opened:
    """A connection a transport has opened, with the connect frame it will send.

    The one thing the two transports do not share, handed back as a value so that
    each of them decides its own order in local variables. That matters for exactly
    one member: ADR-0125 §3 puts the credential's single authorised unwrap
    "immediately before encoding the connect frame's credential member, and nowhere
    else", so the payload is built by whoever holds the secret rather than passed to
    a shared method as a plaintext argument.

    Attributes:
        reader: The open connection's reader.
        writer: Its writer. Whoever receives this owns hanging it up.
        connect_payload: The connect frame's members, already bounded by
            :func:`~ai_assistant.wire.envelope.connect_payload`.
    """

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    connect_payload: dict[str, Any]


class HubClient:
    """Everything a client of the promoted surface does once it has a connection.

    Every method the promoted surface declares — the set
    :data:`~ai_assistant.wire.surface.METHODS` reads off
    :class:`~ai_assistant.core.protocols.AssistantEngine` rather than a count
    written here — plus the request/reply exchange, the handshake and the frame
    limits, all of which ADR-0124 §9 requires to be *identical* on both transports,
    since the hop "adds no member to the connect exchange, changes no frame's
    encoding, and changes no method's arguments or results".

    A subclass supplies :meth:`_open`, which is where the two differ: a Unix socket
    and a peer-credential check (:class:`HubEngineClient`, ADR-0084 §1), or an
    overlay address, an identity the local agent attests and a credential from the
    keyring (:class:`~ai_assistant.wire.remote.RemoteHubEngineClient`, ADR-0124 §4,
    §7).
    """

    def __init__(
        self,
        *,
        read_timeout: timedelta,
        client_name: str = DEFAULT_CLIENT_NAME,
    ) -> None:
        """Prepare a client. Nothing is opened here.

        The first connection is made by the first call, or by :meth:`probe`. A
        constructor that connected would make "is the hub up" a question asked at a
        moment no command chose.

        Args:
            read_timeout: How long a frame's body may stall before the connection
                is abandoned.
            client_name: The free-form identifier the connect frame carries.
        """
        self._read_timeout = read_timeout
        self._client_name = client_name

    @property
    def where(self) -> str:
        """How this client's destination reads in a message.

        Returns:
            The socket path or the overlay address and port.
        """
        raise NotImplementedError

    async def _open(self) -> Opened:
        """Open a connection, authenticate the hub, and build the connect frame.

        Returns:
            The connection and the frame to send on it.

        Raises:
            HubUnavailableError: If there is nothing to connect to.
            TransportError: If the hub on the other end is not one this client may
                talk to. Nothing has been sent at that point, which is the direction
                both ADR-0084 §1 and ADR-0124 §4 fix.
        """
        raise NotImplementedError

    async def probe(self) -> None:
        """Connect, handshake and hang up, so a closed door is reported early.

        A command that is about to render a prompt should learn that the hub is
        down *before* it does anything else, which is ADR-0084 §9's legibility rule
        at the adapter's own boundary. It is a separate method rather than
        constructor behaviour because the failure belongs to the command, not to
        holding a reference.

        Raises:
            HubUnavailableError: If nothing is listening.
            ProtocolError: On a version mismatch, or a hub running as another user.
        """
        reader, writer, _limit = await self._connect()
        await hang_up(writer)
        del reader

    # --- the promoted surface's methods ------------------------------------

    async def converse(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # noqa: ASYNC109 — the caller's budget, relayed to the hub (ADR-0029 §4)
        conversation_id: Identifier | None = None,
    ) -> TurnOutcome:
        """Run one turn on the hub (ADR-0085 §3).

        Args:
            utterance: What the user said.
            timeout: The budget for the whole turn.
            conversation_id: The conversation to continue, or ``None``.

        Returns:
            What the turn did.
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        return await self._call(  # type: ignore[no-any-return]
            "converse", utterance=utterance, timeout=timeout, conversation_id=selected
        )

    def converse_streaming(
        self,
        utterance: EncodableText,
        *,
        timeout: timedelta,  # the caller's budget, relayed to the hub (ADR-0029 §4)
        conversation_id: Identifier | None = None,
    ) -> AsyncIterator[ReplyChunk | TurnOutcome]:
        """Run one turn on the hub, reading its answer as it is composed (ADR-0173 §4).

        **This is where the client stops being a one-frame-per-request transport.**
        :meth:`_call` writes one frame and reads exactly one; this reads until the
        terminal frame, which ADR-0173 §11 names as the honest cost of spending the
        correlation id's reserved second job.

        Args:
            utterance: What the user said.
            timeout: The budget for the whole turn.
            conversation_id: The conversation to continue, or ``None``.

        Returns:
            An async iterator over the answer's chunks and then the turn's outcome.
            Close it if you stop reading part-way (:func:`contextlib.aclosing`) —
            the connection is hung up by its own cleanup, which a generator nobody
            closes does not run.

        Raises:
            ValueError: If ``conversation_id`` is blank, or a value has no wire
                form — refused here, before any I/O, exactly as :meth:`_call`
                refuses it (ADR-0085 §9).
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        payload = arguments_object(utterance=utterance, timeout=timeout, conversation_id=selected)
        # Projected **before** the generator is even built, for :meth:`_call`'s own
        # reason: a value with no wire form must be refused the same way whether or
        # not a hub happens to be up, and a refusal raised from the first iteration
        # step instead would be one a caller that never iterates never sees.
        project(payload)
        return self._stream_call("converse_streaming", payload)

    async def converse_spoken(
        self,
        utterance: SpokenAudio,
        *,
        plays: tuple[SpokenAudioFormat, ...],
        timeout: timedelta,  # noqa: ASYNC109 - the caller's budget, relayed to the hub (ADR-0029 §4)
        conversation_id: Identifier | None = None,
        delivery: SpokenDeliveryReport | None = None,
    ) -> SpokenTurn:
        """Run one spoken turn on the hub (ADR-0200 §3, ADR-0205 §1).

        **One frame each way, and nothing under** ``wire/`` **carries audio
        specially** (ADR-0200 §9). The recording travels as
        :data:`~ai_assistant.core.types.Base64Audio` — text — inside the ordinary
        request envelope, so ``codec``'s ``project`` needs no ``bytes`` branch and
        the framing is untouched. This method exists because the client implements
        :class:`~ai_assistant.core.protocols.AssistantEngine`, and that is the whole
        of the client's change.

        Args:
            utterance: The recording.
            plays: What the caller can render, in preference order. Non-empty.
            timeout: The budget for the whole call.
            conversation_id: The conversation to continue, or ``None``.
            delivery: What a device played of an earlier turn, naming that turn by
                the ``episode_id`` a previous call disclosed (ADR-0205 §1). It
                crosses as the ordinary nested model it is — a frozen value of
                scalars, a ``StrEnum`` and two durations on ADR-0087 §2e's form — so
                ``codec``'s ``project`` needs no branch for it and
                ``wire/surface.py`` derives its adapter from the annotation as it
                derives every other. This method carries it and reads none of it.

        Returns:
            The transcript, the turn it drove, the rendering of its answer, and the
            id of the episode recording it.

        Raises:
            ValueError: If ``plays`` is empty, ``conversation_id`` is blank, a
                ``delivery`` is supplied beside a ``conversation_id`` of ``None``, or
                a supplied ``delivery`` carries a state of ``UNKNOWN`` — each refused
                here, before any I/O, so this client and the engine it stands in for
                refuse the same values without a round trip (ADR-0085 §9, ADR-0205
                §1, §2). It bites hardest on this method: a refusal deferred to the
                far side would put a **recording** on the network for a call the hub
                is bound to refuse. Spelled inline rather than shared with
                ``orchestration.payloads``' twin, because ``wire`` depends on
                ``core`` and nothing else; what keeps the two agreeing is the shared
                conformance suite, which drives this refusal against both.
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        if not plays:
            msg = (
                "plays must name at least one format the caller can render; an empty "
                "preference order is a call that could not be answered whatever the "
                "synthesizer produces (ADR-0200 §3)"
            )
            raise ValueError(msg)
        if delivery is not None:
            # ADR-0205 §1 and §2's two refusals, mirrored here for the reason the two
            # above are: a value the promoted surface refuses "locally, before any I/O"
            # must not cost a round trip — and on this path it would cost a *recording*
            # crossing the network for a call guaranteed to be refused at the far end.
            if selected is None:
                msg = (
                    "a delivery report names a turn of a conversation, and a fresh "
                    "conversation contains no turn one could name; supply the conversation "
                    "this report is about, or no report (ADR-0205 §1)"
                )
                raise ValueError(msg)
            if delivery.delivery.state is SpokenDeliveryState.UNKNOWN:
                msg = (
                    "a device that does not know reports nothing: UNKNOWN is what the hub "
                    "writes for an unreported turn, and the absence of a report is spelled "
                    "by omitting the argument (ADR-0205 §2)"
                )
                raise ValueError(msg)
        return await self._call(  # type: ignore[no-any-return]
            "converse_spoken",
            utterance=utterance,
            plays=plays,
            timeout=timeout,
            conversation_id=selected,
            delivery=delivery,
        )

    async def _stream_call(self, method: str, payload: dict[str, object]) -> AsyncIterator[Any]:
        """Read one streamed exchange: chunk frames, then one terminal frame.

        The order is :meth:`_call`'s, with the last step turned into a loop:
        connect and handshake, measure the arguments against the limit the hub
        published, send, then read frames until one of them is terminal.

        **Every frame's correlation id is checked, not just the first.** ADR-0084
        §3's mismatch rule is a rule about *frames*, and a stream is the first
        exchange on this transport where a desynchronisation could hide behind a
        frame that is not the last — so it is checked on each, and a mismatch is
        still the unrepairable state §3 makes it.

        **The union is resolved by frame kind and never by inspecting a payload**
        (ADR-0173 §4), so the kind stays the single discriminator §2 makes it.

        **The result is measured on this side too**, chunk and terminal alike:
        ADR-0173 §11 restates ADR-0085 §8c for a method with no single result, and
        the clause binds both halves so a client is never silently less capable than
        the engine it stands in for.
        """
        reader, writer, limit = await self._connect()
        try:
            check_payload(payload, max_bytes=limit, subject=f"the arguments to {method}()")
            correlation = str(uuid.uuid4())
            await write_frame(
                writer,
                env.encode_envelope(
                    env.Envelope(
                        kind=env.FrameKind.REQUEST,
                        id=correlation,
                        payload=payload,
                        method=method,
                    )
                ),
                max_frame_bytes=limit + ENVELOPE_RESERVE_BYTES,
            )
            while True:
                reply = await self._read(reader, limit=limit, idle=None, expecting=method)
                if reply.id != correlation:
                    msg = (
                        f"the hub answered with correlation id {reply.id!r} while "
                        f"{correlation!r} was outstanding; a desynchronised stream cannot be "
                        f"repaired by guessing"
                    )
                    raise ProtocolError(msg)
                if reply.kind is env.FrameKind.ERROR:
                    _raise_reply_error(reply.payload)
                if reply.kind is env.FrameKind.CHUNK:
                    chunk = chunk_adapter(method).validate_python(reply.payload)
                    check_payload(chunk, max_bytes=limit, subject=f"a chunk from {method}()")
                    yield chunk
                    continue
                if reply.kind is not env.FrameKind.RESULT:
                    msg = f"the hub answered a request with a {reply.kind.value} frame"
                    raise ProtocolError(msg)
                result = terminal_adapter(method).validate_python(reply.payload)
                check_payload(result, max_bytes=limit, subject=f"the result of {method}()")
                yield result
                return
        finally:
            await hang_up(writer)

    async def resume(
        self,
        token: ContinuationToken,
        *,
        approved: bool,
        timeout: timedelta,  # noqa: ASYNC109 - the caller's budget, relayed to the hub (ADR-0029 §4)
    ) -> TurnOutcome:
        """Relay the user's consent for a parked step (ADR-0042 §4).

        Args:
            token: The continuation the confirmation carried.
            approved: What the user said.
            timeout: The budget for the resumed turn.

        Returns:
            What the resumed pass did.
        """
        return await self._call(  # type: ignore[no-any-return]
            "resume", token=token, approved=approved, timeout=timeout
        )

    async def learn(self, event: FeedbackEvent) -> LearnOutcome:
        """Hand one piece of feedback to memory.

        Args:
            event: The feedback.

        Returns:
            What memory did with it.
        """
        return await self._call("learn", event=event)  # type: ignore[no-any-return]

    async def observe(self, *, conversation_id: Identifier | None = None) -> ObservationReport:
        """Distil beliefs from a conversation's recent turns.

        Args:
            conversation_id: Which conversation, or ``None`` for the most recently
                active one.

        Returns:
            What the pass proposed and what became of it.
        """
        selected = (
            None if conversation_id is None else identifier(conversation_id, name="conversation_id")
        )
        return await self._call("observe", conversation_id=selected)  # type: ignore[no-any-return]

    async def beliefs(
        self,
        *,
        bands: Sequence[BeliefBand] | None = None,
        kinds: Sequence[MemoryKind] | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> tuple[BeliefSummary, ...]:
        """One page of what is held about the user.

        **The filters are materialised here, before the first ``await``**
        (ADR-0085 §3d): a caller that mutates the sequence it passed cannot change
        which page it gets. ``None`` and empty stay different — ``None`` selects
        every band or kind, an empty sequence selects nothing.

        Args:
            bands: Which bands to include, or ``None`` for every one.
            kinds: Which kinds to include, or ``None`` for every one.
            limit: How many records this page holds.
            offset: How many to skip.

        Returns:
            The page.
        """
        snapshot_bands = None if bands is None else tuple(bands)
        snapshot_kinds = None if kinds is None else tuple(kinds)
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        return await self._call(  # type: ignore[no-any-return]
            "beliefs",
            bands=snapshot_bands,
            kinds=snapshot_kinds,
            limit=limit,
            offset=offset,
        )

    async def belief(self, record_id: Identifier) -> Belief | None:
        """One belief in full, with its surviving citations.

        Args:
            record_id: Which record.

        Returns:
            The belief, or ``None`` if nothing is held under that id.
        """
        named = identifier(record_id, name="record_id")
        return await self._call("belief", record_id=named)  # type: ignore[no-any-return]

    async def forget(self, record_id: Identifier) -> bool:
        """Destroy one belief.

        Args:
            record_id: Which record.

        Returns:
            Whether anything was held to destroy.
        """
        named = identifier(record_id, name="record_id")
        return await self._call("forget", record_id=named)  # type: ignore[no-any-return]

    async def guard(self, record_id: Identifier) -> Placement | None:
        """Keep one belief for the owner alone (ADR-0217 §7).

        Args:
            record_id: Which record.

        Returns:
            The placement it carries after the act, or ``None`` if nothing is held
            under that id.
        """
        named = identifier(record_id, name="record_id")
        return await self._call("guard", record_id=named)  # type: ignore[no-any-return]

    async def unguard(self, record_id: Identifier) -> Placement | None:
        """Let one belief be spoken to anyone again (ADR-0217 §7).

        The placement that comes back is the record's **after** the act, so a hub
        that declined the widening — the setter is ``DERIVED``, and ADR-0204 §5's
        closing prohibition is not lifted by an act — answers with that placement
        rather than with an error, and a surface reads its reach and setter to say
        why nothing moved.

        Args:
            record_id: Which record.

        Returns:
            The placement it carries after the act, or ``None`` if nothing is held
            under that id.
        """
        named = identifier(record_id, name="record_id")
        return await self._call("unguard", record_id=named)  # type: ignore[no-any-return]

    async def questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """One page of the deferred questions awaiting an answer.

        Args:
            limit: How many questions this page holds.
            offset: How many to skip.

        Returns:
            The page.
        """
        return await self._page("questions", limit=limit, offset=offset)  # type: ignore[no-any-return]

    async def interrupted_questions(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[Question, ...]:
        """One page of the questions whose answering was interrupted.

        Args:
            limit: How many questions this page holds.
            offset: How many to skip.

        Returns:
            The page.
        """
        return await self._page("interrupted_questions", limit=limit, offset=offset)  # type: ignore[no-any-return]

    async def answer(self, question_id: Identifier, *, accept: bool) -> AnswerOutcome:
        """Answer one deferred question.

        Args:
            question_id: Which question.
            accept: What the user said.

        Returns:
            What became of the question.
        """
        named = identifier(question_id, name="question_id")
        return await self._call(  # type: ignore[no-any-return]
            "answer", question_id=named, accept=accept
        )

    async def forget_question(self, question_id: Identifier) -> bool:
        """Destroy one deferred question.

        Args:
            question_id: Which question.

        Returns:
            Whether anything was held to destroy.
        """
        named = identifier(question_id, name="question_id")
        return await self._call("forget_question", question_id=named)  # type: ignore[no-any-return]

    async def notifications(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[HeldNotification, ...]:
        """One page of the notifications the assistant is holding, oldest first.

        Args:
            limit: How many notifications this page holds.
            offset: How many to skip.

        Returns:
            The page.
        """
        return await self._page("notifications", limit=limit, offset=offset)  # type: ignore[no-any-return]

    async def dismiss_notification(self, notification_id: Identifier) -> bool:
        """Dispose of one notification without destroying it.

        Args:
            notification_id: Which notification.

        Returns:
            Whether an actionable notification was dismissed.
        """
        named = identifier(notification_id, name="notification_id")
        return await self._call("dismiss_notification", notification_id=named)  # type: ignore[no-any-return]

    async def forget_notification(self, notification_id: Identifier) -> bool:
        """Destroy one notification.

        Args:
            notification_id: Which notification.

        Returns:
            Whether anything was held to destroy.
        """
        named = identifier(notification_id, name="notification_id")
        return await self._call("forget_notification", notification_id=named)  # type: ignore[no-any-return]

    async def notification_preferences(self) -> NotificationPreferences:
        """The three standing settings that tune proactive contact.

        Returns:
            The settings in force, defaulted where the user has set nothing.
        """
        return await self._call("notification_preferences")  # type: ignore[no-any-return]

    async def set_notification_preferences(
        self, preferences: NotificationPreferences
    ) -> NotificationPreferences:
        """Write the standing settings, and re-arm what the change reaches.

        **The whole value goes over, not one field**, which is the contract's own
        shape rather than this client's — as is the last-write-wins it implies
        (see the Protocol).

        Args:
            preferences: The settings to hold from now on.

        Returns:
            The settings now in force, as the hub holds them.
        """
        return await self._call("set_notification_preferences", preferences=preferences)  # type: ignore[no-any-return]

    async def next_notification(
        self,
        *,
        acknowledging: Identifier | None = None,
        plays: tuple[SpokenAudioFormat, ...] = (),
        budget: timedelta,
    ) -> NotificationDelivery | None:
        """Park on the hub until a notification is due, or ``budget`` elapses.

        ADR-0131 §1's long poll, from the device's side. **This client already
        satisfies §2's isolation rule by construction**: :meth:`_call` opens a
        connection of its own for every call and hangs up in its ``finally``, so a
        poll never shares a connection with an ordinary request and a caller
        wanting a session while polling gets the second connection §2 requires
        without asking for one. A client that pooled connections would have to
        earn that back with a rule; this one cannot break it.

        **Nothing about the read deadline changes for a parked poll**, and that is
        also not new: :meth:`_read` already passes ``idle=None`` while a request is
        outstanding, because the hub is not idle while it is working. What
        ``hub_read_timeout`` still bounds is a *stalled frame* — bytes that started
        and stopped — which is the fault it was written for and is orthogonal to an
        answer that is legitimately late.

        Args:
            acknowledging: The ``delivery_id`` this device is confirming, or
                ``None``. Naming a superseded or unknown one is accepted and does
                nothing, so a device that reconnected may acknowledge blindly.
            plays: What this caller can render, in preference order (ADR-0206 §1).
                Empty — the default — asks for no rendering, so a device that
                cannot play audio omits it and this poll behaves exactly as it did
                before that ADR. Refused by the hub where it names something that
                is not a format, and refused **before** the acknowledgement is
                applied, so a poll carrying one retires nothing.
            budget: How long the hub may hold the request. Zero is an immediate
                poll. A value outside the hub's range comes back as
                :class:`~ai_assistant.core.errors.NotificationBudgetError`,
                reconstructed here from the hub's own refusal rather than guessed
                at locally — the ceiling is the hub's figure and this client is not
                told it. It bounds the hub's **waiting** and nothing else
                (ADR-0135 §3), so a poll that renders answers later than ``budget``
                — which is why nothing about the read deadline is derived from it.

        Returns:
            The notification to show and the token that retires it, or ``None``
            where the budget elapsed with nothing waiting. Where ``plays`` asked
            for a rendering, ``spoken`` carries it and ``spoken_rendering`` says
            why it is there or is not (ADR-0206 §6).
        """
        named = None if acknowledging is None else identifier(acknowledging, name="acknowledging")
        return await self._call(  # type: ignore[no-any-return]
            "next_notification", acknowledging=named, plays=plays, budget=budget
        )

    async def recent_conversations(
        self, *, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
    ) -> tuple[ConversationSummary, ...]:
        """One page of conversations, most recently active first.

        Args:
            limit: How many conversations this page holds.
            offset: How many to skip.

        Returns:
            The page.
        """
        return await self._page("recent_conversations", limit=limit, offset=offset)  # type: ignore[no-any-return]

    async def conversation(self, conversation_id: Identifier) -> ConversationDigest | None:
        """One conversation's digest.

        Args:
            conversation_id: Which conversation.

        Returns:
            The digest, or ``None`` if no such conversation is held.
        """
        named = identifier(conversation_id, name="conversation_id")
        return await self._call("conversation", conversation_id=named)  # type: ignore[no-any-return]

    async def forget_conversation(self, conversation_id: Identifier) -> bool:
        """Destroy one conversation.

        Args:
            conversation_id: Which conversation.

        Returns:
            Whether anything was held to destroy.
        """
        named = identifier(conversation_id, name="conversation_id")
        return await self._call(  # type: ignore[no-any-return]
            "forget_conversation", conversation_id=named
        )

    async def pending_confirmations(self) -> tuple[Confirmation, ...]:
        """Every parked confirmation the hub can currently resolve.

        ADR-0084 §7's remedy for a token a previous process life minted: enumerate
        the parks from durable state and take a freshly minted continuation.

        Returns:
            The parks, each with a token that resolves now.
        """
        return await self._call("pending_confirmations")  # type: ignore[no-any-return]

    # --- the four grant operations (ADR-0102 §12 item 4) --------------------

    async def grantable_sources(self) -> tuple[GrantableSource, ...]:
        """What the user may grant, with each source's location and live grant.

        **This is the response that carries §6's disclosure**, and a client that
        cannot show the user a ``location`` may not go on to call :meth:`grant`
        (ADR-0102 §6). The obligation is the client's and the hub cannot enforce it,
        which is why it is stated here as well as on the Protocol.

        Returns:
            One entry per grantable source the hub holds.
        """
        return await self._call("grantable_sources")  # type: ignore[no-any-return]

    async def grant(
        self, source: NonBlankEncodableText, *, scope: Sequence[GrantScope]
    ) -> SourceGrant:
        """Record the user's grant of one source, hub-side.

        **``source`` is validated and *not* normalised** — the local refusal
        ADR-0085 §9 requires, in the shape ADR-0102 §2 fixes. Reaching for
        :func:`~ai_assistant.wire.codec.identifier` here would strip the value
        before it was sent and make this client accept a call the in-process engine
        refuses, which is the substitutability failure §2 rejects the ``Identifier``
        annotation for.

        ``scope`` is **materialised before the first ``await``** and refused empty or
        duplicated, so a caller mutating the sequence it passed cannot change the
        grant that is recorded (ADR-0065, ADR-0097 §2).

        Args:
            source: The reader's declared identity, sent byte for byte.
            scope: The uses this grant authorises.

        Returns:
            The grant the hub recorded.
        """
        named = non_blank_text(source, name="source")
        uses = grant_scope(scope, name="scope")
        return await self._call("grant", source=named, scope=uses)  # type: ignore[no-any-return]

    async def revoke(self, source: NonBlankEncodableText) -> SourceGrant | None:
        """Withdraw the live grant on one source, hub-side.

        No admission check is applied here or on the hub (ADR-0102 §4): a source no
        reader declares is not refused for that, it simply has no live grant. Only
        the argument validation above is local.

        Args:
            source: The source to withdraw, sent byte for byte.

        Returns:
            The revoking record the hub appended, or ``None`` where no live grant
            covered the source.
        """
        named = non_blank_text(source, name="source")
        return await self._call("revoke", source=named)  # type: ignore[no-any-return]

    async def recent_grants(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceGrant, ...]:
        """One page of what the user granted and withdrew, newest first.

        ``limit`` is refused unless it is **strictly positive**, which is stricter
        than :meth:`questions`' page rule and is ADR-0102 §10's own clause: the
        store behind this refuses a non-positive limit, and ADR-0085 §9 forbids
        either implementation from being silently more permissive than the other.

        Args:
            limit: How many records this page holds.

        Returns:
            The page.
        """
        positive_page_argument(limit, name="limit")
        return await self._call("recent_grants", limit=limit)  # type: ignore[no-any-return]

    async def standing_grants(self) -> tuple[SourceGrant, ...]:
        """Every grant the user currently authorises, read hub-side from the store.

        **No local refusal to add**, because the method takes no argument
        (ADR-0139 §8): there is nothing to validate before the round trip, so this
        is a bare ``_call``. The refusal that matters is the hub's — a live set too
        large for the frame comes back as ``OversizedValueError`` rather than as a
        truncated set (ADR-0139 §2), and it arrives as a typed error frame like any
        other.

        Returns:
            Every live grant, whatever readers the hub currently holds. The order
            carries no meaning.
        """
        return await self._call("standing_grants")  # type: ignore[no-any-return]

    # --- the wire ----------------------------------------------------------

    async def _page(self, method: str, *, limit: int, offset: int) -> Any:
        """Refuse a malformed page argument locally, then call (ADR-0085 §9)."""
        page_argument(limit, name="limit")
        page_argument(offset, name="offset")
        return await self._call(method, limit=limit, offset=offset)

    async def _call(self, method: str, **arguments: object) -> Any:
        """Run one request against the hub, on a connection of its own.

        The order is fixed and each step earns its place: connect and handshake
        (which is where the hub's authoritative frame size arrives), *then* measure
        the arguments against the limit the hub published (ADR-0084 §3 — "the client
        enforces the number it was told"), then send, then read the one reply.

        Args:
            method: The ``AssistantEngine`` method being called.
            **arguments: Its arguments, named as the Python parameters are.

        Returns:
            The result, validated into the method's declared return type.

        Raises:
            AssistantError: Whatever the hub declined the call with, reconstructed.
            OversizedValueError: If the arguments, or the result, exceed the limit
                the hub published — enforced in **both** directions, so a client is
                never silently less capable than the engine it stands in for.
            TransportError: If there is no hub, or one that broke the protocol.
        """
        payload = arguments_object(**arguments)
        # **Projected before the socket is opened**, which is where ADR-0085 §9's
        # "refused locally, before any I/O" bites for a value that has no wire form
        # at all. ``project`` is what raises on a lone surrogate or a non-finite
        # float (ADR-0087 §2b, §2c), and running it after ``connect`` would make the
        # error a caller sees depend on whether a hub happened to be up: a
        # ``ValueError`` in-process, a ``HubUnavailableError`` over the wire, for one
        # value both implementations must refuse the same way.
        #
        # The *size* check cannot move with it, and does not need to: the limit is
        # the hub's to publish (ADR-0084 §3), so it is measured once the handshake
        # has said what it is — still locally, and still before any request frame.
        project(payload)
        reader, writer, limit = await self._connect()
        try:
            check_payload(payload, max_bytes=limit, subject=f"the arguments to {method}()")
            correlation = str(uuid.uuid4())
            await write_frame(
                writer,
                env.encode_envelope(
                    env.Envelope(
                        kind=env.FrameKind.REQUEST,
                        id=correlation,
                        payload=payload,
                        method=method,
                    )
                ),
                max_frame_bytes=limit + ENVELOPE_RESERVE_BYTES,
            )
            reply = await self._read(reader, limit=limit, idle=None, expecting=method)
            if reply.id != correlation:
                msg = (
                    f"the hub answered with correlation id {reply.id!r} while {correlation!r} "
                    f"was outstanding; a desynchronised stream cannot be repaired by guessing"
                )
                raise ProtocolError(msg)
            if reply.kind is env.FrameKind.ERROR:
                _raise_reply_error(reply.payload)
            if reply.kind is not env.FrameKind.RESULT:
                msg = f"the hub answered a request with a {reply.kind.value} frame"
                raise ProtocolError(msg)
            result = return_adapter(method).validate_python(reply.payload)
            # ADR-0087 §7: decode, validate, **then** measure — the same value, so
            # the same bytes and the same number the hub measured. The hub has
            # already refused an oversized result; measuring here is what makes the
            # clause true of *this* implementation rather than inherited from the
            # other one.
            check_payload(result, max_bytes=limit, subject=f"the result of {method}()")
        finally:
            await hang_up(writer)
        return result

    async def _connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, int]:
        """Open a connection through the transport, then complete the handshake.

        Everything after :meth:`_open` is the same exchange on both transports,
        which is ADR-0124 §9's ground for not bumping ``PROTOCOL_VERSION``: "a peer
        at version 2 on either listener exchanges exactly the frames it exchanges
        today".

        Returns:
            The reader, the writer, and the contract limit the hub published — its
            effective frame size less ADR-0085 §8b's envelope reserve.

        Raises:
            HubUnavailableError: If nothing is listening.
            TransportError: If the hub is not one this client may talk to, claims
                another protocol version, or refuses the connect frame.
        """
        opened = await self._open()
        reader, writer = opened.reader, opened.writer
        try:
            correlation = str(uuid.uuid4())
            await write_frame(
                writer,
                env.encode_envelope(
                    env.Envelope(
                        kind=env.FrameKind.CONNECT,
                        id=correlation,
                        payload=opened.connect_payload,
                    )
                ),
                max_frame_bytes=_HANDSHAKE_FRAME_BYTES,
            )
            reply = await self._read(
                reader,
                limit=_HANDSHAKE_FRAME_BYTES,
                idle=self._read_timeout,
                expecting="the handshake",
            )
            if reply.kind is env.FrameKind.ERROR:
                _raise_handshake_error(reply.payload)
            if reply.kind is not env.FrameKind.CONNECT_ACK:
                msg = f"the hub answered a connect with a {reply.kind.value} frame"
                raise ProtocolError(msg)
            version, frame_bytes = env.read_connect_ack(reply.payload)
            if version != env.PROTOCOL_VERSION:
                msg = (
                    f"this client speaks protocol version {env.PROTOCOL_VERSION} and the hub "
                    f"at {self.where} speaks version {version}; the two halves ship "
                    f"together, so upgrade whichever of the two is behind"
                )
                raise ProtocolError(msg)
        except BaseException:
            await hang_up(writer)
            raise
        return reader, writer, frame_bytes - ENVELOPE_RESERVE_BYTES

    async def _read(
        self,
        reader: asyncio.StreamReader,
        *,
        limit: int,
        idle: timedelta | None,
        expecting: str,
    ) -> env.Envelope:
        """Read one frame and decode its envelope, or say what was lost.

        ADR-0084 §3: "A close with no response is reported as what the client was
        attempting when the connection went away" — which is why ``expecting`` is
        threaded down rather than left to a generic message.
        """
        try:
            body = await read_frame(
                reader, max_frame_bytes=limit, timeout=self._read_timeout, idle_timeout=idle
            )
        except ConnectionClosedError as exc:
            msg = (
                f"the hub closed the connection while {expecting} was outstanding, without "
                f"answering; the request may or may not have been carried out"
            )
            raise HubUnavailableError(msg) from exc
        return env.decode_envelope(body)

    # --- the five connection operations (ADR-0151 §16 item 5) ---------------
    #
    # **Each one refuses before it does anything, unless this client is on
    # ADR-0084 §1's loopback socket** (:meth:`_refuse_off_loopback`). ADR-0151 §13
    # is normative that "No lane exposes these operations over any transport other
    # than ADR-0084 §1's loopback socket — in particular not over ADR-0124's remote
    # listener — before a ratified decision rules the credential's hop from an
    # enrolled device to the hub", and ``RemoteHubEngineClient`` subclasses this
    # class — so without the guard an enrolled device would inherit five methods
    # that unwrap a Tier 0 credential and put it across an overlay network, which
    # is exactly the hop §13 refuses until it is ruled.
    #
    # **The guard is on the class rather than the methods being moved down to
    # :class:`HubEngineClient`**, and the reason is ADR-0084 §4's substitutability.
    # Moving them would leave ``RemoteHubEngineClient`` no longer satisfying
    # ``AssistantEngine`` at all — which ADR-0084 §5 and ADR-0124 §1 each rely on,
    # and which ``interfaces/cli.py`` reads directly, since ``_client_for``
    # returns whichever client configuration names as one engine. Making a
    # ratified Protocol unsatisfiable by a ratified implementation is a contract
    # change owing its own ADR; refusing an operation the transport may not carry
    # is not.
    #
    # **The refusal is the client's half only.** A client that lacks a method is
    # not a check, so ``wire/server.py`` refuses the same five on any connection
    # the remote listener admitted — §13's prohibition binds the hub as well as
    # the spoke, and a non-conforming peer is exactly what the hub half is for.
    #
    # **This weakens no clause of ADR-0124 §9**, which is about frames: "the remote
    # listener adds no member to the connect exchange, changes no frame's encoding,
    # and changes no method's arguments or results". None of those moves.

    #: Whether this transport may carry ADR-0151 §1's connection operations.
    #: ``True`` here because ADR-0084 §1's ``0600`` socket is what every disclosure
    #: argument on that surface rests on, and overridden to ``False`` on
    #: :class:`~ai_assistant.wire.remote.RemoteHubEngineClient` — where ADR-0124 §3
    #: accepts a specific, enumerated disclosure to a coordination service, and a
    #: Tier 0 credential is not on that list.
    carries_connection_operations: ClassVar[bool] = True

    def _refuse_off_loopback(self, method: str) -> None:
        """Refuse a connection operation this transport may not carry (ADR-0151 §13).

        Called as the **first** statement of each of the five, so it runs before
        the credential is revalidated, before it is unwrapped, and before any
        socket is opened. Nothing derived from the secret exists by the time this
        raises.

        Args:
            method: The operation being refused, for the message.

        Raises:
            ProtocolError: If this client's transport is not ADR-0084 §1's
                loopback socket. A transport error rather than an
                ``AssistantError``, and that is its own docstring's case — "a
                credential this transport does not carry" — because no ratified
                code in ADR-0085 §10a's vocabulary means "not on this transport",
                and inventing one would be authoring contract surface this lane
                may not author.
        """
        if self.carries_connection_operations:
            return
        msg = (
            f"{method}() is not carried on this transport. ADR-0151 §13 keeps the "
            f"connection operations on the hub's local socket until a ratified decision "
            f"rules the credential's hop from an enrolled device to the hub, so no "
            f"credential is sent from here. Run it on the machine the hub is on"
        )
        raise ProtocolError(msg)

    # **The unwrap lives in the two methods below and nowhere else** (ADR-0151 §6,
    # ADR-0124 §7's shape). ADR-0087's canonical projection is deliberately **not**
    # extended to ``SecretStr``: ``project`` is a total dispatch that ends in
    # ``TypeError`` for a type it has no form for, and ``SecretStr`` is not a
    # ``str`` subclass, so a credential that reached it fails loudly here, before
    # the socket is opened. Teaching the codec to unwrap one is refused because it
    # is general where the need is specific — it would silently encode every secret
    # any promoted value ever came to carry, removing exactly the property ADR-0125
    # §3 bought, that "a disclosure requires somebody to write the unwrapping call,
    # which makes it deliberate and reviewable rather than accidental".
    #
    # **The hazard the by-hand unwrap forecloses is invisible, which is why it is
    # written down here.** A ``TypeAdapter`` over ``SecretValue`` serialises to
    # ``"**********"``. An implementation reaching for pydantic's serialiser rather
    # than this project's own projection would send ten asterisks as the
    # credential; the hub would validate them as a well-formed ``SecretValue``, the
    # provisioner would write them into the keyring, the record would go active,
    # and **every in-process test would pass**, because the in-process engine never
    # serialises anything. The failure would surface only at the first egress call,
    # as an authentication error against a credential nobody could find a fault in
    # by inspection.

    async def connect_account(
        self, *, identity: NonBlankEncodableText, credential: SecretValue
    ) -> ConnectedAccount:
        """Connect a fresh account, hub-side, under a reference the hub mints.

        **This client takes no reference and offers no way to propose one**
        (ADR-0151 §3). Every act after the first goes through
        :meth:`connected_accounts`, which is the price of a reference the corpus
        licenses to be logged, paid deliberately.

        **The three local refusals are this client's own, not the hub's**
        (ADR-0085 §9, ADR-0151 §5). They run before the socket is opened, so a
        credential is never sent for a call the hub would refuse — which is the
        whole reason the identity's bound lives in ``core`` as one constant both
        implementations name rather than in the store alone.

        Args:
            identity: The account's user-recognisable name, sent verbatim.
            credential: The account's secret. Unwrapped **once**, immediately
                below, after being revalidated through ``secret_value``.

        Returns:
            The record the hub wrote, ``ACTIVE`` at its minted reference.

        Raises:
            ValueError: If ``identity`` is blank or unwritable, or ``credential``
                is blank, unencodable or oversized.
            UnusableIdentityError: If ``identity`` is one ADR-0149 §4 does not
                admit. **No frame is sent and no credential leaves this process.**
            OversizedValueError: If the arguments exceed the limit the hub
                published. Nothing is truncated and nothing falls back to another
                route; raising ``hub_max_frame_bytes`` is the operator's remedy
                (ADR-0151 §11).
        """
        self._refuse_off_loopback("connect_account")
        secret = secret_value(credential)
        named = non_blank_text(identity, name="identity")
        usable_identity(named, credential=secret)
        return await self._call(  # type: ignore[no-any-return]
            "connect_account", identity=named, credential=secret.get_secret_value()
        )

    async def reprovision_account(
        self,
        reference: Identifier,
        *,
        identity: NonBlankEncodableText,
        credential: SecretValue,
    ) -> ConnectedAccount:
        """Replace the credential under a reference the hub returned, hub-side.

        Args:
            reference: The connection to re-provision, validated and normalised
                here as every id argument on this surface is (ADR-0085 §3c).
            identity: The account identity for the new revision, sent verbatim.
            credential: The replacement secret, unwrapped once immediately below.

        Returns:
            The record the hub wrote, ``ACTIVE`` at the new revision.

        Raises:
            ValueError: If ``reference`` or ``identity`` is blank or unwritable,
                or ``credential`` is blank, unencodable or oversized.
            UnusableIdentityError: On :meth:`connect_account`'s terms.
            OversizedValueError: On :meth:`connect_account`'s terms.
        """
        self._refuse_off_loopback("reprovision_account")
        secret = secret_value(credential)
        handle = identifier(reference, name="reference")
        named = non_blank_text(identity, name="identity")
        usable_identity(named, credential=secret)
        return await self._call(  # type: ignore[no-any-return]
            "reprovision_account",
            reference=handle,
            identity=named,
            credential=secret.get_secret_value(),
        )

    async def disconnect_account(self, reference: Identifier) -> ConnectedAccount | None:
        """Disconnect a reference hub-side, or report that nothing was removed.

        A ``None`` says one thing — no live record was removed by this call — and
        is **not** a report of a disconnection, a confirmation that a credential
        was deleted, or a statement that the reference does not exist
        (ADR-0151 §8).

        Args:
            reference: The connection to disconnect.

        Returns:
            The live record the hub removed, or ``None``.

        Raises:
            ValueError: If ``reference`` is blank or unwritable.
            ResidualCredentialError: If the reference **is** disconnected and a
                credential deletion failed. Never rendered as a failed
                disconnection.
        """
        self._refuse_off_loopback("disconnect_account")
        named = identifier(reference, name="reference")
        return await self._call("disconnect_account", reference=named)  # type: ignore[no-any-return]

    async def connected_accounts(self) -> tuple[ConnectedAccount, ...]:
        """Every connection with a live record, read hub-side from the store.

        **Unpaged, so a bare ``_call``.** The refusal that matters is the hub's —
        a live set too large for the frame is an ``OversizedValueError`` and no set
        at all, because a truncated answer to "what is connected" is a false answer
        rather than a partial one (ADR-0151 §9).

        Returns:
            Every live record, pending ones included and carrying ``PENDING``. No
            client presents such a record as a working connection.
        """
        self._refuse_off_loopback("connected_accounts")
        return await self._call("connected_accounts")  # type: ignore[no-any-return]

    async def recent_connection_acts(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[ConnectionAct, ...]:
        """One page of what was done to connections, newest first.

        ``limit`` is refused when not strictly positive, locally, on
        :meth:`recent_grants`' reason (ADR-0151 §2a).

        Args:
            limit: The most acts to return.

        Returns:
            Up to ``limit`` acts. **The order carries no timing claim** — there is
            no instant on a connection record, so a position means only where the
            store recorded the act (ADR-0151 §9).

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
        """
        self._refuse_off_loopback("recent_connection_acts")
        positive_page_argument(limit, name="limit")
        return await self._call("recent_connection_acts", limit=limit)  # type: ignore[no-any-return]

    # --- the audit trail's two reads (ADR-0186 §1) -------------------------
    #
    # **Hand-written here because the client is, where the server is reflected**
    # (ADR-0186 §5). ``wire/surface.py`` reads the Protocol, so ``wire/server.py``'s
    # dispatch and both adapters grow with it by construction — but every promoted
    # method is its own ``async def`` here, so a client that grew none would raise
    # ``AttributeError`` before a frame was ever sent, and §5's "both listeners
    # carry both operations" would be satisfied by a hub nothing could ask.
    # ADR-0151 §11 states the precedent in the same form, with a different number.

    async def recent_decisions(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[PermissionDecision, ...]:
        """One page of what the permission layer ruled, newest first (ADR-0186 §1).

        **Not a connection method**, so no :meth:`_refuse_off_loopback` and no entry
        in ``wire/server.py``'s ``CONNECTION_METHODS`` (ADR-0186 §5). The five that
        are withheld are withheld because they carry a Tier 0 credential, and a
        ``PermissionDecision`` carries none: every class of fact one holds already
        crosses ADR-0124's hop inside a ``Confirmation``'s ``ConfirmationEgress``.

        ``limit`` is refused when it is **not strictly positive**, locally and
        before a frame is sent, on :meth:`recent_grants`' reason (ADR-0186 §3) — the
        clause ``AssistantEngineContract`` holds all three implementations to, so a
        client that shipped ``limit=0`` to the hub would be exactly the silently
        more permissive implementation ADR-0085 §9 forbids.

        Args:
            limit: How many rows this page holds.

        Returns:
            The page, newest first, ties broken by ``id`` ascending — the first
            ``limit`` rows of :meth:`export_decisions`. **The order is a claim about
            when a ruling was made and about nothing else** (ADR-0186 §2), and a
            resolution may fall outside a bounded page (§7).

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
        """
        positive_page_argument(limit, name="limit")
        return await self._call("recent_decisions", limit=limit)  # type: ignore[no-any-return]

    async def export_decisions(self) -> tuple[PermissionDecision, ...]:
        """The whole trail, in :meth:`recent_decisions`' order (ADR-0186 §1).

        **No local refusal to add**, because the method takes no argument — the
        shape :meth:`standing_grants` already has: there is nothing to validate
        before the round trip, so this is a bare ``_call``. The refusal that matters
        is the hub's: a trail too large for the frame comes back as an
        ``OversizedValueError`` carrying the limit and the measured size rather than
        as a truncated artifact (ADR-0186 §3), and it arrives as a typed error frame
        like any other. The remedy is ``hub_max_frame_bytes``, the number the
        connect reply already published to this client.

        Returns:
            Every recorded decision, sorted hub-side. A row whose binding records no
            origin comes back carrying an ``OriginUnrecordedBinding`` with **no**
            ``planned_with_external_content`` key under it — the union
            re-discriminates structurally at this end, so the third origin state
            survives the wire with no discriminator member and nothing transcribed
            into a wire-side schema (ADR-0186 §5, ADR-0184 §3).
        """
        return await self._call("export_decisions")  # type: ignore[no-any-return]

    # --- the read trail's two reads (ADR-0186 §10) -------------------------
    #
    # Hand-written for the pair above's reason, unchanged: the server is reflected
    # off the Protocol and this class is not, so a client that grew no methods
    # would raise ``AttributeError`` before a frame was ever sent.

    async def recent_reads(self, *, limit: int = DEFAULT_PAGE_SIZE) -> tuple[SourceReadRecord, ...]:
        """One page of what this system read from a source (ADR-0186 §10).

        **Not a connection method**, so no :meth:`_refuse_off_loopback` and no entry
        in ``wire/server.py``'s ``CONNECTION_METHODS``. That is the mechanism's own
        default rather than an ADR-0186 §5 clause inherited — §10's inheritance list
        does not name §5 — and the only decision withholding anything from the
        remote listener is ADR-0151 §13, whose ground is a **Tier 0 credential**. A
        ``SourceReadRecord`` carries none, and by ADR-0185 §10's own exclusion no
        content either: it states the source's declared identity, the use, the
        instant the grant check resolved, the outcome, the grant it ran under and
        how many items the reading carried — and nothing of what was read. ADR-0186
        §5 reaches the same conclusion for the decision pair on the same reasoning.

        ``limit`` is refused when it is **not strictly positive**, locally and
        before a frame is sent (ADR-0186 §3, §10), which is the clause
        ``AssistantEngineContract`` holds all three implementations to.

        Args:
            limit: How many rows this page holds.

        Returns:
            The page, **newest-recorded first** — the first ``limit`` rows of
            :meth:`export_reads`. Recording order and never ``checked_at``
            (ADR-0185 §6), so a position is a claim about the order the hub wrote
            rows in and about nothing else.

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
        """
        positive_page_argument(limit, name="limit")
        return await self._call("recent_reads", limit=limit)  # type: ignore[no-any-return]

    async def export_reads(self) -> tuple[SourceReadRecord, ...]:
        """Every read attempt the trail still holds (ADR-0186 §10).

        **No local refusal to add**, because the method takes no argument — the
        shape :meth:`export_decisions` already has.

        **What comes back is a horizon and not a history**, which is the one place
        this pair is not the decision pair's mirror (ADR-0186 §10, ADR-0185 §9).
        The hub's store prunes oldest-first at ``source_read_trail_max_rows``, so
        this reconstructs every attempt **still held**; ADR-0004 §6's export right
        is satisfied to that extent and no further. A caller composing this with
        :meth:`export_decisions` states that horizon on the artifact's face:
        presenting a pruned half and an unpruned half as one record would claim a
        completeness half of it does not have.

        Returns:
            Every record still held, newest-recorded first, reversed hub-side.

        Raises:
            OversizedValueError: Raised by the hub, and arriving as a typed error
                frame, if the whole trail exceeds the contract limit — never a
                truncated artifact (ADR-0186 §3). The remedies are
                ``hub_max_frame_bytes``, the number the connect reply already
                published to this client, and the horizon setting itself.
        """
        return await self._call("export_reads")  # type: ignore[no-any-return]

    # --- the trail's two invocation reads (ADR-0192 §4) --------------------
    #
    # Hand-written for the two pairs above's reason, unchanged: the server is
    # reflected off the Protocol and this class is not.

    async def recent_invocations(
        self, *, limit: int = DEFAULT_PAGE_SIZE
    ) -> tuple[RecordedInvocation, ...]:
        """One page of what this system did on an authorisation (ADR-0192 §4).

        **Not a connection method**, so no :meth:`_refuse_off_loopback` and no entry
        in ``wire/server.py``'s ``CONNECTION_METHODS``. That is the mechanism's own
        default, and the only decision withholding anything from the remote listener
        is ADR-0151 §13, whose ground is a **Tier 0 credential**. A
        :class:`~ai_assistant.core.types.RecordedInvocation` carries none, and by
        ADR-0192 §2's own exclusion no content either: the row restates nothing its
        decision fixes, carries no argument value, no payload, no output, no failure
        message and no digest of any of them, and the join adds a tool identifier, a
        capability and a boolean that every ``recent_decisions`` row already crosses
        this hop carrying.

        ``limit`` is refused when it is **not strictly positive**, locally and
        before a frame is sent (ADR-0192 §4), which is the clause
        ``AssistantEngineContract`` holds all three implementations to — a client
        shipping ``limit=0`` to the hub would be exactly the silently more
        permissive implementation ADR-0085 §9 forbids.

        Args:
            limit: How many rows this page holds.

        Returns:
            The page, newest first, ties broken by the row's ``id`` ascending — the
            first ``limit`` rows of :meth:`export_invocations`. **A row is an act
            begun on an authorisation and never a statement that the tool callable
            was entered** (ADR-0192 §4), one attempt is up to two rows, and the
            absence of either half from a bounded page is a fact about the page.

        Raises:
            TypeError: If ``limit`` is not an integer, or is a ``bool``.
            ValueError: If ``limit`` is not in ``[1, 2**63)``.
        """
        positive_page_argument(limit, name="limit")
        return await self._call("recent_invocations", limit=limit)  # type: ignore[no-any-return]

    async def export_invocations(self) -> tuple[RecordedInvocation, ...]:
        """Every invocation row the trail holds (ADR-0192 §4).

        **No local refusal to add**, because the method takes no argument — the
        shape :meth:`export_decisions` already has. This is the read discharging
        ADR-0004 §6's portability obligation for **this row kind**; the decision
        export discharges it for the decision rows and, after ADR-0192 §2, for those
        alone, so a caller wanting the whole trail composes the two.

        **Unlike ``export_reads`` this store prunes nothing**, so what comes back is
        a history rather than a horizon (#108).

        Returns:
            Every invocation row, sorted hub-side, joined hub-side.

        Raises:
            OversizedValueError: Raised by the hub, and arriving as a typed error
                frame, if the whole trail exceeds the contract limit — never a
                truncated artifact (ADR-0192 §4). The remedy is
                ``hub_max_frame_bytes``, the number the connect reply already
                published to this client.
        """
        return await self._call("export_invocations")  # type: ignore[no-any-return]

    async def spend_totals(self) -> tuple[SpendTotal, ...]:
        """What each calendar period has cost, in ``SpendPeriod``'s fixed order.

        **No local refusal to add**, the method taking no argument — the shape
        ``export_decisions`` already has. Both entries come back whatever is
        configured, and each carries the bounds ADR-0194 §1's rule computed **in the
        hub's zone**, with the offsets in force at those two instants. A renderer
        prints each bound from the value's own offset: this client resolves no zone,
        reads no ``tzdata`` and consults no configuration of its own, which is what
        lets it render a value a hub on a different zone database computed
        correctly (ADR-0194 §5, §6).

        Returns:
            Exactly two totals, computed hub-side from one clock read and one row
            snapshot.

        Raises:
            SpendUndeterminedError: Raised by the hub, and arriving as a typed error
                frame, where the ledger could not produce the values at all. An
                indeterminate *period* is not that case and comes back as a value.
            HubUnavailableError: If no hub is listening, or the connection goes away
                mid-request. **Unwrapped, and never translated** to
                ``SpendUndeterminedError`` (ADR-0194 §6): a connection that was not
                there is not one of the six grounds §4 enumerates, and reporting it
                as one would tell a user their spend is indeterminate when the truth
                is that there is no hub.
            ProtocolError: On a malformed or truncated reply, likewise unwrapped.
            OversizedValueError: Raised by the hub if the pair exceeds the contract
                limit.
        """
        return await self._call("spend_totals")  # type: ignore[no-any-return]


class HubEngineClient(HubClient):
    """The hub on this machine, over ADR-0084 §1's Unix socket.

    Attributes:
        socket_path: Where the hub listens — ``<data_dir>/hub.sock``, derived from
            the one setting that locates both the data and the door (ADR-0084 §9).
    """

    def __init__(
        self,
        socket_path: Path,
        *,
        read_timeout: timedelta,
        client_name: str = DEFAULT_CLIENT_NAME,
    ) -> None:
        """Point a client at the hub on this machine.

        Args:
            socket_path: Where the hub listens.
            read_timeout: How long a frame's body may stall before the connection
                is abandoned.
            client_name: The free-form identifier the connect frame carries.
        """
        super().__init__(read_timeout=read_timeout, client_name=client_name)
        self.socket_path = socket_path

    @property
    def where(self) -> str:
        """The socket path, for a message."""
        return str(self.socket_path)

    async def _open(self) -> Opened:
        """Connect, read the peer's credentials from the kernel, and refuse a stranger.

        ADR-0084 §1's check, and it runs "after ``connect()`` and before sending
        anything" — "a direct check on *who is actually on the other end*, not an
        inference from who could have written where".

        **The connect frame carries no credential**, which ADR-0124 §7 leaves
        exactly where ADR-0084 §2 put it: "on the loopback transport… a non-empty
        credential is still refused with ``credential_not_supported``. The two
        listeners hold opposite rules, and a hub running both applies each rule to
        its own listener."

        Returns:
            The connection and a credential-free connect frame.

        Raises:
            HubUnavailableError: If nothing is listening on the socket.
            ProtocolError: If the hub runs as another user, or this platform cannot
                say who it runs as.
        """
        try:
            reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
        except (FileNotFoundError, ConnectionRefusedError) as exc:
            msg = (
                f"no assistant hub is listening at {self.socket_path}. Start it with "
                f"'ai-assistant-hub' and leave it running, then try again. "
                f"(This client never starts one for you, and never falls back to "
                f"running the assistant in-process.)"
            )
            raise HubUnavailableError(msg) from exc
        except OSError as exc:
            msg = f"cannot reach the assistant hub at {self.socket_path}: {exc}"
            raise HubUnavailableError(msg) from exc
        try:
            raw: socket.socket | None = writer.get_extra_info("socket")
            if raw is None:  # pragma: no cover — asyncio always supplies one here
                msg = "the connection exposes no socket, so the hub cannot be authenticated"
                raise ProtocolError(msg)
            check_peer_is_self(raw)
            payload = env.connect_payload(client=self._client_name)
        except BaseException:
            await hang_up(writer)
            raise
        return Opened(reader=reader, writer=writer, connect_payload=payload)


def _raise_handshake_error(payload: object) -> None:
    """Report a refused handshake as the transport failure it is.

    ADR-0085 §9 puts a version mismatch and a credential refusal among the
    conditions that "are not ``AssistantEngine`` failures and no Protocol method
    declares them", so neither is reconstructed as an exception from
    ``core/errors.py``.

    **The message is rendered as the hub wrote it, and the code is appended.**
    ADR-0124 §7 requires the remote listener to distinguish an unenrolled device, a
    revoked one and a credential that did not verify "in the error it returns **and
    in what the hub logs**", against the login-surface reflex of saying only "no" —
    "an owner who cannot tell 'I never enrolled this laptop' from 'I revoked it last
    week' from 'I pasted the wrong string' is ADR-0083's ruling 4 failure". The
    sentence carries the diagnosis; the token is what makes the owner's screen and
    the hub's log two records of one event. Neither ever carries the credential or
    the verifier (§7).

    **It does not switch on the code**, and that is deliberate rather than a gap
    (ADR-0124 §Context): a handshake refusal an older client cannot name still
    renders, because it renders from the message. The closed set lives on the *call*
    path, in :func:`_raise_reply_error`, where an unknown token would otherwise be
    handed to a reconstruction expecting a class name.

    Raises:
        ProtocolError: Always.
    """
    message = ""
    code = ""
    if isinstance(payload, dict):
        raw = payload.get("message")
        message = raw if isinstance(raw, str) else ""
        token = payload.get("code")
        code = token if isinstance(token, str) else ""
    rendered = message or "the hub refused the connection without saying why"
    raise ProtocolError(f"{rendered} [{code}]" if code else rendered)


def _raise_reply_error(payload: object) -> None:
    """Raise whatever an error frame carries, as the right kind of failure.

    A handshake-vocabulary code arriving on the *call* path is a protocol fault
    rather than a declared failure, and telling the two apart by the code is what
    the lowercase spelling of ADR-0084 §2's and §3's refusals is for.

    **The set is** :data:`~ai_assistant.wire.envelope.HANDSHAKE_REFUSALS` **rather
    than a literal here**, which is ADR-0124 §7's named enforcement point closed by
    construction: "a new refusal code that is not added to that set would reach an
    older client's reconstruction path as an unknown class". A literal would have
    to be found and edited by every lane that adds a refusal; a shared constant is
    edited where the refusal itself is declared.

    Raises:
        AssistantError: The declared failure, reconstructed (ADR-0085 §10a).
        ProtocolError: If the frame carries a handshake refusal instead.
    """
    if isinstance(payload, dict) and payload.get("code") in env.HANDSHAKE_REFUSALS:
        _raise_handshake_error(payload)
    raise_from_payload(payload)


async def hang_up(writer: asyncio.StreamWriter) -> None:
    """Close one connection, tolerating a peer that has already gone.

    A stateless client holds nothing a close can lose, so a failure to shut a
    socket down cleanly is not a failure of the call it belonged to — and a close
    that reported one would replace the failure the caller actually needs to read
    with a footnote about the socket.
    """
    writer.close()
    with contextlib.suppress(Exception, asyncio.CancelledError):
        await writer.wait_closed()
