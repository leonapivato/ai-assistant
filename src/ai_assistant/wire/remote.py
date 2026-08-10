"""The client half of the hop: a hub on another machine, over the overlay.

ADR-0124 §1 authorises a third egress boundary and names **both** its halves,
because "a rule naming one of them authorises half a protocol":

> **Normative.** The client half transmits only to a hub whose overlay identity it
> has confirmed under §4, over a transport satisfying §2, and sends only two
> things: the connect frame §7 requires, and the request it was asked to make. It
> obtains its destination from configuration and never from a discovery mechanism,
> a redirect, or anything a peer tells it.

Every clause of that sentence is a line of :meth:`RemoteHubEngineClient._open`, and
they run in the order the sentence puts them: the destination comes from
:mod:`ai_assistant.wire.address` before this object exists, the identity is
confirmed before the socket is opened, and the connect frame is the first byte
sent. What comes after is :class:`~ai_assistant.wire.client.HubClient`'s, unchanged
— "changes no method's arguments or results" (ADR-0124 §9).

**Mutual authentication, and the second clause is the one that is easy to omit.**
ADR-0084 §1 has the client read the peer's uid from the kernel; ``SO_PEERCRED`` has
no analogue across a network, so ADR-0124 §4 restates the obligation in terms of
the fact rather than the syscall. Without it, "any node on the overlay that can
occupy the hub's address — or that the client can be pointed at by a configuration
edit — receives the utterance and everything the session carries". What keeps the
check from being circular is that the two values live in different places: the
address is ordinary configuration, and the identity is in the keyring beside the
credential, where no setting reaches it.

**The enrolment is read on every connect, and not cached.** ADR-0084 §7 makes this
client stateless by decision and ADR-0084 §3 gives it one connection per call, so a
command that makes three calls reads the keyring three times. Holding the value
between calls would be the only way to avoid that, and it is the wrong trade: it
keeps a Tier 0 secret in a process's memory for longer than the frame that carries
it, to save a call to a service that on every mainstream platform is unlocked once
per login session. What the owner would notice is a keyring that prompts per
operation, and the remedy for that is unlocking it — not this client keeping the
secret instead.

**The credential is unwrapped on one line and nowhere else** (ADR-0125 §3, ADR-0124
§7). It is read through :class:`~ai_assistant.core.protocols.Secrets` — the reading
face and nothing wider (ADR-0125 §8) — on the connect path and for no other
purpose, and ``get_secret_value`` is called immediately before the member is
encoded. It appears in no frame but the connect frame, is never passed to the
engine surface, and reaches no log, audit record or error message (ADR-0124 §6).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from ai_assistant.wire import envelope as env
from ai_assistant.wire.client import DEFAULT_CLIENT_NAME, HubClient, Opened, hang_up
from ai_assistant.wire.enrolment import read_enrolment
from ai_assistant.wire.errors import HubIdentityMismatchError, HubUnavailableError

if TYPE_CHECKING:
    from datetime import timedelta

    from ai_assistant.core.protocols import Secrets
    from ai_assistant.wire.address import RemoteDestination
    from ai_assistant.wire.overlay import OverlayAgent


class RemoteHubEngineClient(HubClient):
    """A hub reached across a device boundary, admitted by two independent facts.

    Attributes:
        destination: The overlay address and port, from configuration alone
            (ADR-0124 §1).
    """

    def __init__(
        self,
        destination: RemoteDestination,
        *,
        read_timeout: timedelta,
        agent: OverlayAgent,
        secrets: Secrets,
        client_name: str = DEFAULT_CLIENT_NAME,
    ) -> None:
        """Point a client at a hub on another machine. Nothing is opened or read here.

        Args:
            destination: Where the hub's remote listener is.
            read_timeout: How long a frame's body may stall before the connection
                is abandoned.
            agent: This machine's overlay agent, which is the only thing asked whose
                device holds the destination (ADR-0124 §4). Never the peer.
            secrets: The reading face of the keyring seam, bound to ``ENROLMENT``
                and to this installation. **Not** a
                :class:`~ai_assistant.core.protocols.SecretStore`: the connect path
                "is given ``Secrets`` and nothing wider" (ADR-0125 §8), so this
                object cannot express a write or a delete of the credential it
                reads.
            client_name: The free-form identifier the connect frame carries.
        """
        super().__init__(read_timeout=read_timeout, client_name=client_name)
        self.destination = destination
        self._agent = agent
        self._secrets = secrets

    @property
    def where(self) -> str:
        """The overlay address and port, for a message."""
        return f"{self.destination.host}:{self.destination.port}"

    async def _open(self) -> Opened:
        """Confirm the hub, then dial it, then build the frame that presents a credential.

        The order is ADR-0124 §4's — "**before sending anything**… refuses unless it
        equals the enrolled hub identity" — read at its word: the identity is
        settled before a socket exists, so a client pointed at another overlay
        member has sent that member nothing at all. §11's step 5 is that check.

        The enrolment is read **once**, as a pair, and the pair is what the read
        refuses to be incomplete (ADR-0124 §6). Reading it before the identity check
        is what lets the check happen at all: the value compared is the enrolled hub
        identity, and it lives beside the credential rather than in configuration.

        Returns:
            The connection and a connect frame carrying the credential.

        Raises:
            NotEnrolledError: If this device holds no enrolment, or half of one.
            OverlayIdentityUnavailableError: If this machine's overlay agent will
                not say whose device holds the destination.
            HubIdentityMismatchError: If it says something other than the hub this
                device was enrolled at.
            HubUnavailableError: If nothing is listening at the destination, or it
                does not answer within this client's read deadline.
            SecretStoreUnavailableError: If this device's keyring cannot be reached —
                which ADR-0125 §7 keeps distinct from holding no enrolment, because
                otherwise "a client would report the owner as unenrolled while they
                are enrolled".
        """
        enrolment = await read_enrolment(self._secrets)
        host, port = self.destination.host, self.destination.port
        answered = await self._agent.identify(host, port)
        if answered != enrolment.hub_identity:
            msg = (
                f"{self.where} is the overlay node {answered!r}, and this device was "
                f"enrolled at {enrolment.hub_identity!r}. Nothing has been sent. Changing "
                f"the address does not change the identity it has to match (ADR-0124 §4): "
                f"point ASSISTANT_REMOTE_HUB_ADDRESS at your hub, or enrol this device at "
                f"the hub you meant"
            )
            raise HubIdentityMismatchError(msg)
        try:
            # **Bounded, because on this transport nothing else bounds it.** A Unix
            # socket with no listener refuses at once; an overlay address whose peer
            # is asleep or unrouted drops the SYN, and the operating system retries
            # for minutes before it gives up. That is not an edge case here — #879
            # prices the hub's duty cycle as a laptop that sleeps, so it is the
            # ordinary way this call fails, and ADR-0084 §9's "a closed door is an
            # instruction" is not served by a command that hangs instead of saying
            # so. The figure is this client's existing patience for this hub rather
            # than a new setting: a connect that stalls is a connection that stalls.
            async with asyncio.timeout(self._read_timeout.total_seconds()):
                reader, writer = await asyncio.open_connection(host=host, port=port)
        except (OSError, TimeoutError) as exc:
            stalled = isinstance(exc, TimeoutError)
            detail = (
                f"it did not answer within {self._read_timeout.total_seconds():g}s"
                if stalled
                else str(exc)
            )
            msg = (
                f"cannot reach the assistant hub at {self.where}: {detail}. Check that the "
                f"hub is running with ASSISTANT_HUB_REMOTE_ADDRESS set, that both devices "
                f"are on the overlay and awake, and that ASSISTANT_REMOTE_HUB_PORT matches "
                f"the hub's hub_remote_port. (This client never starts one for you, and "
                f"never falls back to running the assistant in-process.)"
            )
            raise HubUnavailableError(msg) from exc
        try:
            # **The one authorised unwrap** (ADR-0125 §3, ADR-0124 §7): immediately
            # before the member is encoded, on the connect path, and nowhere else.
            # The member is a JSON string, which §7 fixes so that the two-fact rule
            # stays decidable from the frame.
            payload = env.connect_payload(
                client=self._client_name,
                credential=enrolment.credential.get_secret_value(),
            )
        except BaseException:
            await hang_up(writer)
            raise
        return Opened(reader=reader, writer=writer, connect_payload=payload)
