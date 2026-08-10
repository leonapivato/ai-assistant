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
from typing import TYPE_CHECKING, Any, Final

from ai_assistant.core.types import DEFAULT_PAGE_SIZE
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
)
from ai_assistant.wire.errors import (
    ConnectionClosedError,
    HubUnavailableError,
    ProtocolError,
    raise_from_payload,
)
from ai_assistant.wire.framing import read_frame, write_frame
from ai_assistant.wire.peer import check_peer_is_self
from ai_assistant.wire.surface import return_adapter

if TYPE_CHECKING:
    import socket
    from collections.abc import Sequence
    from datetime import timedelta
    from pathlib import Path

    from ai_assistant.core.types import (
        AnswerOutcome,
        Belief,
        BeliefBand,
        BeliefSummary,
        Confirmation,
        ContinuationToken,
        ConversationDigest,
        ConversationSummary,
        EncodableText,
        FeedbackEvent,
        GrantableSource,
        GrantScope,
        Identifier,
        LearnOutcome,
        MemoryKind,
        NonBlankEncodableText,
        ObservationReport,
        Question,
        SourceGrant,
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

    The nineteen methods, the request/reply exchange, the handshake and the frame
    limits — all of which ADR-0124 §9 requires to be *identical* on both transports,
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

    # --- the nineteen methods ---------------------------------------------

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
