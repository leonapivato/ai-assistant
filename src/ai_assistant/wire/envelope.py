"""The envelope every frame travels in, and the connect exchange (ADR-0084 §2-§3).

The envelope is a JSON object with the members ADR-0085 §8a fixes — ``kind``,
``id``, ``method`` on a request, and ``payload`` — and no others. It carries **no
length member of its own**: the frame's length is :mod:`ai_assistant.wire.framing`'s
prefix, which covers envelope and payload together, so "a second length inside the
envelope would be a value that can disagree with the one already read".

**Member order is not significant here**, and that is ADR-0084 §3's own sentence
about its own subject. ADR-0087 §2 is scoped to the *payload*, so an implementation
that emits envelope members in any order conforms — and one that sorts the whole
frame in a single pass, as this one does, conforms too, because "not significant"
permits both.

**Duplicate member names are rejected**, in the envelope and in payload objects
alike. JSON permits them and decoders disagree about which one wins, so
``{"kind":"request","kind":"error",…}`` "could decode as a request in one
implementation and an error in another — the same bytes, two meanings".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Final, NoReturn

from ai_assistant.wire.codec import CONNECT_PAYLOAD_BYTES, canonical_payload, encode_projection
from ai_assistant.wire.credential import is_well_formed
from ai_assistant.wire.errors import (
    CredentialNotSupportedError,
    CredentialRejectedError,
    CredentialRequiredError,
    ProtocolError,
    UndecodableFrameError,
)

#: The protocol version, exchanged once in the connect handshake and nowhere else
#: (ADR-0084 §3). It becomes connection state; it is not repeated on subsequent
#: frames. Client and server must agree **exactly** — "there is no supported
#: deployment in which they differ except a half-finished upgrade, and a
#: half-finished upgrade is precisely the state ruling 4 wants legible rather than
#: papered over".
#:
#: **2 since ADR-0122 §1**, which made ``FeedbackEvent.memory_kind`` optional. That
#: is an *incompatible payload* change in the one direction the handshake exists to
#: catch: the codec renders a defaulted field, so an unpinned correction crosses as
#: ``"memory_kind": null``, and a version 1 hub's validation refuses ``null`` for a
#: required ``MemoryKind``. Left at 1 both peers would still say ``1``, the
#: handshake would pass, and the operator would get a decode error inside a
#: ``learn`` instead of §3's message naming both versions and the action — the
#: half-finished upgrade made illegible rather than legible (ADR-0087 §8's
#: precedent for the same reason). Bumping applies ADR-0084 §3's mechanism; it does
#: not change it.
#:
#: **3 since ADR-0130 §9**, which added five methods to the promoted
#: ``AssistantEngine`` surface — the notification read, the dismissal, the
#: per-notification delete, and the two preference operations. ADR-0124 §9 makes
#: that a bump in as many words: the rule reaches "any change to the promoted
#: surface's method set", and "adding a method bumps, and that is the honest
#: consequence rather than an oversight. A sixteenth method on the promoted
#: surface is a request an older hub answers with a failure the client did not ask
#: for." ``wire/surface.METHODS`` is derived from the Protocol, so a version 3
#: client sending ``notifications`` to a version 2 hub is refused there — which is
#: exactly the frame-one-peer-may-send-that-the-other-refuses test, and exactly
#: the half-finished upgrade §3 wants legible at the handshake rather than
#: arriving as an unexplained error inside a call.
#:
#: **4 since ADR-0131 §4**, which adds ``next_notification`` — the long poll a
#: notification travels on, and the twenty-fifth method on the promoted surface.
#: The same clause of ADR-0124 §9 decides it and ADR-0131 §4 records the
#: consequence rather than weighing it: "Landing this seam bumps
#: ``PROTOCOL_VERSION``, and the obligation falls on the change that adds the
#: method, in that same change." Nothing about this seam offers a way out — a poll
#: from a new client to an old hub is refused by ``_dispatch`` as a method "this
#: build's engine surface does not declare", which closes the connection with no
#: reply, so the operator sees a hub that hangs up rather than §3's message naming
#: both versions. That is the half-finished upgrade this constant exists to make
#: legible, and it is why the bump is not optional.
#:
#: **5 since ADR-0133 §6**, which adds ``NOTIFY`` to
#: :class:`~ai_assistant.core.types.GrantScope`. This is the **first bump that is
#: not a method-set change**, and it lands under ADR-0124 §9's *second* limb
#: rather than its first: "a change to a wire-carried ``core`` type that makes a
#: value one peer emits invalid for the other, whether the change widens or
#: narrows the type". ADR-0133 §6 states that it "bites in both directions — a new
#: client's ``grant`` argument carrying ``"notify"`` is refused by an old hub, and
#: an old client decoding a ``SourceGrant`` result whose scope names ``"notify"``
#: is refused at the client", the second of which ``wire/codec.grant_scope``
#: already names in its own docstring. So the promoted surface stays at
#: twenty-five methods and this number still moves; ADR-0124 §9 makes that
#: compliance a **review obligation** on the change and decides no mechanical
#: check, and #891 carries the check that does not exist.
#:
#: **6 since ADR-0139 §2**, which adds ``standing_grants`` — what the user
#: currently authorises, read from the grant store rather than from the readers the
#: hub holds, and the twenty-sixth method on the promoted surface. Back under
#: ADR-0124 §9's *first* limb, "any change to the promoted surface's method set",
#: which ADR-0139 §8 restates in its own words and which §9 states again in
#: ADR-0124's: "Adding a method bumps, and that is the honest consequence rather
#: than an oversight." The half-finished upgrade is ``next_notification``'s
#: unchanged — a ``standing_grants`` call from a new client to an old hub is a
#: method that build's engine surface does not declare, so ``_dispatch`` closes the
#: connection with no reply — and the bump is what turns that into §3's message
#: naming both versions.
#:
#: **7 since ADR-0151 §1**, which adds the five connection operations —
#: ``connect_account``, ``reprovision_account``, ``disconnect_account``,
#: ``connected_accounts`` and ``recent_connection_acts``. ADR-0124 §9's **first**
#: limb again, and the largest single move the method set has made: five at once
#: rather than one. Nothing about them offers a way out either, and one of them
#: makes the half-finished upgrade worse than it has been before — a
#: ``connect_account`` from a new client to an old hub is a method that build's
#: surface does not declare, so ``_dispatch`` closes the connection with no reply,
#: and the call the operator retries is **the one carrying a credential**. A
#: dropped socket is the worst available outcome there precisely because the
#: natural response to one is to send it again (ADR-0151 §2a), which is why the
#: handshake refusal this number buys is worth more on this surface than on any
#: before it.
#: **8 since ADR-0170 §3**, which adds ``reply`` and ``reply_degraded`` to
#: :class:`~ai_assistant.core.types.TurnOutcome` — the natural-language answer a
#: turn composes, and whether composing it failed. ADR-0124 §9's **second** limb,
#: as ADR-0133 §6's bump was: "a change to a wire-carried ``core`` type that makes a
#: value one peer emits invalid for the other, whether the change widens or narrows
#: the type". A single reading of the tree confirms it bites rather than merely
#: applying — ``TurnOutcome`` is ``extra="forbid"`` and ``wire.surface``'s
#: ``return_adapter`` validates a result against the method's declared return
#: annotation, so an older client handed a ``TurnOutcome`` carrying ``reply`` fails
#: with ``extra_forbidden`` on that member and a turn it asked for arrives as an
#: unexplained decode error. ADR-0122's optional ``FeedbackEvent.memory_kind`` is
#: the precedent ADR-0124 §9 cites for exactly this shape, a widening an old peer
#: refuses. The promoted surface's method set is untouched and this number still
#: moves; ADR-0170 §7 records the obligation as falling on this same change, and
#: **no other module under** ``wire/`` **changes for it** — a result payload takes
#: the shape of the method's own declared return annotation (ADR-0085 §10), so the
#: field crosses without a second declaration and nothing transcribes it into a
#: wire-side schema.
#:
#: **9 since ADR-0173 §11**, which adds ``converse_streaming`` to the promoted
#: surface *and* :attr:`FrameKind.CHUNK` to the envelope. ADR-0124 §9 is reached
#: **twice over, and each limb bites independently** — the first time a bump has
#: had two grounds rather than one. The first limb is the familiar one: "any change
#: to the promoted surface's method set", and "adding a method bumps, and that is
#: the honest consequence rather than an oversight". The second is sharper than any
#: type widening before it, because a chunk frame is a frame an older peer cannot
#: decode *at all*: :func:`decode_envelope` refuses a ``kind`` naming no known
#: :class:`FrameKind`, and an undecodable frame closes the connection with **no
#: response** (ADR-0084 §3) — so a version 8 client asked to read a stream would see
#: its socket hang up rather than §3's message naming both versions. That is
#: precisely the "would be refused by a conforming peer at the old version" limb,
#: reached at the framing layer instead of inside a payload.
#:
#: Unlike ADR-0170 §7's bump, this one does **not** leave the rest of ``wire/``
#: alone, and ADR-0173 §11 says so rather than letting a lane discover it: the
#: frame-kind enum, the server's one-envelope dispatch, the client's one-reply read
#: and the surface reflection that builds a single result adapter all move with it.
#: What does not move is ADR-0084 §3's permanent freeze — the 4-byte big-endian
#: length prefix, the UTF-8 JSON codec and the connect frame's version member keep
#: their representation, the connect exchange gains no member, and a chunk frame is
#: framed and decoded by the existing rules.
#:
#: **10 since ADR-0178 §6**, which adds ``egress`` to
#: :class:`~ai_assistant.core.types.Confirmation` — the connected account's
#: identity and the binding's payload description, the content ADR-0148 §8's
#: fourth clause requires a ``CONFIRM`` on an egress call to name, or ``None``
#: where the ruling was taken over no egress binding. ADR-0124 §9's **second**
#: limb, on ADR-0170 §3's precedent exactly: "a change to a wire-carried ``core``
#: type that makes a value one peer emits invalid for the other, whether the
#: change widens or narrows the type". It bites rather than merely applying, and
#: ADR-0178 §6 reads the tree rather than asserting it — ``Confirmation`` sets
#: ``extra="forbid"``, ``wire.surface``'s ``return_adapter`` validates every
#: result against the method's declared return annotation, and ``wire.codec``'s
#: ``project`` renders a model by ``model_dump()``, which **includes** a ``None``
#: member rather than omitting it. So a version 10 hub emits ``"egress": null`` on
#: **every** confirmation, egress or not, and a version 9 client fails with
#: ``extra_forbidden`` on it — a confirmation it asked for arriving as a decode
#: error. Both delivery routes are affected, because a ``Confirmation`` reaches a
#: client on ``TurnOutcome.step.confirmation`` (``converse``,
#: ``converse_streaming``) and as the element type of ``pending_confirmations``.
#:
#: **Nothing else under** ``wire/`` **changes for it**, as at 8 and for the same
#: reason: the connect exchange gains no member, no frame's encoding changes, no
#: :class:`FrameKind` is added, and the promoted surface's method set is untouched
#: (ADR-0084 §3's permanent freeze, ADR-0085 §3). A result payload takes the shape
#: of the method's own declared return annotation (ADR-0085 §10), so the member
#: crosses without a second declaration and nothing transcribes it into a
#: wire-side schema. ``ConfirmationDestination`` is **not** described by this
#: number at all: it is the member type of a derived property ADR-0178 §3 forbids
#: storing or transmitting, so no peer ever receives one.
#:
#: **A version 9 peer and a version 10 peer do not interoperate**, and no lane
#: adds a compatibility shim, an optional-member negotiation, a per-member
#: capability flag or a lenient decode to make them: ADR-0084 §3's exact-match
#: handshake is the mechanism, and the refusal naming both versions is the
#: intended user-visible outcome. The operational cost is one redeployment —
#: hub and clients upgrade together — which ADR-0178 §6 names rather than
#: minimises.
#:
#: **11 since ADR-0181 §3**, which adds a third field,
#: ``planned_with_external_content``, to
#: :class:`~ai_assistant.core.types.ConfirmationEgress`. The same limb of ADR-0124
#: §9 decides it as decided 10, and ADR-0181's Consequences name the obligation
#: rather than weigh it: "``PROTOCOL_VERSION`` moves, because ``ConfirmationEgress``
#: is a wire type (ADR-0178 §6's rule), and the implementing lane owes that
#: arithmetic." It bites in **both** directions, which is what makes it a bump
#: rather than a widening one side can absorb. The field is **required with no
#: default** (ADR-0181 §3), so a version 11 client decoding a version 10 hub's
#: confirmation fails with ``missing``; and ``ConfirmationEgress`` sets
#: ``extra="forbid"`` while ``wire.codec``'s ``project`` renders a model by
#: ``model_dump()``, so a version 11 hub emits the member on every egress
#: confirmation and a version 10 client fails with ``extra_forbidden`` on it. Both
#: delivery routes are affected for 10's reason and by 10's route — a
#: ``Confirmation`` reaches a client on ``TurnOutcome.step.confirmation``
#: (``converse``, ``converse_streaming``) and as the element type of
#: ``pending_confirmations``.
#:
#: **Nothing else under** ``wire/`` **changes for it**, as at 8 and at 10 and for
#: the same reason: the connect exchange gains no member, no frame's encoding
#: changes, no :class:`FrameKind` is added, and the promoted surface's method set is
#: untouched. A result payload takes the shape of the method's own declared return
#: annotation (ADR-0085 §10), so the member crosses without a second declaration and
#: nothing transcribes it into a wire-side schema.
#:
#: **12 since ADR-0186 §1**, which adds two methods to the promoted
#: ``AssistantEngine`` surface — ``recent_decisions``, the bounded listing of what
#: the permission layer ruled, and ``export_decisions``, the whole-trail read that
#: discharges ADR-0004 §6's portability obligation for that store. This is
#: ADR-0124 §9's **first** limb, the one that decided 3, 4 and 6: the rule reaches
#: "any change to the promoted surface's method set", and "adding a method bumps,
#: and that is the honest consequence rather than an oversight. A sixteenth method
#: on the promoted surface is a request an older hub answers with a failure the
#: client did not ask for." ADR-0186 §5 states the obligation in the deciding ADR
#: and §11 puts it on this change rather than leaving a lane to discover it.
#: ``wire/surface.METHODS`` is derived from the Protocol, so a version 12 client
#: sending ``export_decisions`` to a version 11 hub is refused there — the
#: frame-one-peer-may-send-that-the-other-refuses test, and the half-finished
#: upgrade §3 wants legible at the handshake rather than inside a call.
#:
#: **Nothing else under** ``wire/`` **changes for it but the client's two methods**
#: (ADR-0186 §5, on ADR-0151 §11's precedent). The connect exchange gains no member,
#: no frame's encoding changes, no :class:`FrameKind` is added, and no ``core`` type
#: is added or altered: ``PermissionDecision`` is unchanged and reaches this surface
#: by being named in a return annotation rather than by being minted, so the second
#: limb is not what is being invoked here. ``METHODS``, ``STREAMING_METHODS``, both
#: adapters and the error mapping are all derived from the Protocol;
#: ``wire/client.py`` is hand-written, so its two forwarding methods are the one
#: edit, and a client that grew none would raise ``AttributeError`` before a frame
#: was ever sent. Neither method joins ``wire/server.py``'s ``CONNECTION_METHODS``:
#: both listeners carry both (ADR-0186 §5).
#:
#: **13 since ADR-0189 §2**, which gives the four user-facing projections the
#: origin of what they show: ``attestation`` and
#: ``rests_on_recorded_external_content`` on each of
#: :class:`~ai_assistant.core.types.Belief`,
#: :class:`~ai_assistant.core.types.BeliefSummary` and
#: :class:`~ai_assistant.core.types.Question`, and ``warrant`` — the new
#: :class:`~ai_assistant.core.types.Warrant` value object — on
#: :class:`~ai_assistant.core.types.Retirement`. Back under ADR-0124 §9's
#: **second** limb, the one that decided 5, 8, 10 and 11: "a change to a
#: wire-carried ``core`` type that makes a value one peer emits invalid for the
#: other, whether the change widens or narrows the type". ADR-0189 §9 states the
#: bump in the deciding ADR and puts it on the contract lane, rather than leaving
#: either to be discovered here.
#:
#: **It bites in the direction that bites, and reading the tree is what shows
#: it.** Every one of the four models sets ``extra="forbid"``,
#: ``wire.surface``'s ``return_adapter`` validates a result against the method's
#: declared return annotation, and ``wire.codec``'s ``project`` renders a model by
#: ``model_dump()``, which **includes** a ``None`` member rather than omitting it —
#: exactly as at 10. So a version 13 hub emits ``"attestation": null`` and
#: ``"rests_on_recorded_external_content": false`` on **every** belief, listed or
#: single, and ``"warrant": null`` on every retirement, and a version 12 client
#: fails ``extra_forbidden`` on the first of them: a belief page it asked for
#: arriving as a decode error. The other direction is quiet rather than absent —
#: every field is additive with a default (ADR-0189 §9), so a version 13 client
#: decoding a version 12 hub's ``Belief`` gets the defaults instead of ``missing``
#: — which is why this is 10's shape rather than 11's, where a required member made
#: it bite both ways.
#:
#: The delivery routes are the widest this constant has moved for: a ``Belief``
#: and a ``BeliefSummary`` reach a client from the two halves of ADR-0077 §6's
#: inspection surface, and a ``Question`` and its ``Retirement`` entries from the
#: question reads and from ``TurnOutcome``'s deferrals.
#:
#: **Nothing else under** ``wire/`` **changes for it**, as at 8, at 10 and at 11
#: and for the same reason: the connect exchange gains no member, no frame's
#: encoding changes, no :class:`FrameKind` is added, and the promoted surface's
#: method set is untouched at the thirty-four it stood at when 13 landed. A result
#: payload takes the shape of the
#: method's own declared return annotation (ADR-0085 §10), so the members cross
#: without a second declaration and nothing transcribes them into a wire-side
#: schema — ``Warrant`` included, which is a new *promoted* type rather than a new
#: wire declaration (ADR-0085 §5's closure is what carries it).
#:
#: **14 since ADR-0186 §10**, which adds the second of that ADR's two pairs to the
#: promoted ``AssistantEngine`` surface — ``recent_reads``, the bounded listing of
#: what this system read from a source, and ``export_reads``, the whole-trail read
#: over ADR-0185 §12's ``SourceReadTrail``. ADR-0124 §9's **first** limb again, on
#: 12's reasoning exactly: the rule reaches "any change to the promoted surface's
#: method set", and ``wire.surface``'s ``METHODS`` is derived from the Protocol, so
#: a version 14 client sending ``export_reads`` to a version 13 hub is refused
#: there — the half-finished upgrade §3 wants legible at the handshake rather than
#: inside a call. The obligation is **ADR-0124 §9's own**, which reaches "any change
#: to the promoted surface's method set" without needing a clause about these two
#: methods in particular; ADR-0186 §5's third clause is the precedent for putting
#: the note on the change that adds them rather than an inheritance §10 states —
#: §10's inheritance list names §2, §3, §7 and §8, and not §5.
#:
#: **The method set moves from thirty-four to thirty-six**, and that number is what
#: this note is about. ADR-0177 §1's browser enumeration does **not** move: it
#: stands at thirty, because it counts what a browser may reach rather than what
#: the promoted surface carries, and ADR-0186 §6 — inherited by §10 — states that
#: no browser request resolves to either of these.
#:
#: **Nothing else under** ``wire/`` **changes for it but the client's two
#: methods**, as at 12 and for that entry's reason: no ``core`` type is added or
#: altered — ``SourceReadRecord`` and ``ReadOutcome`` were promoted by ADR-0185 and
#: reach this surface by being named in a return annotation rather than by being
#: minted — so the second limb is not what is being invoked. ``METHODS``,
#: ``STREAMING_METHODS``, both adapters and the error mapping are all derived from
#: the Protocol; ``wire/client.py`` is hand-written, so its two forwarding methods
#: are the one edit. Neither method joins ``wire/server.py``'s
#: ``CONNECTION_METHODS``, so both listeners carry both — by the default
#: ``METHODS`` and ``CONNECTION_METHODS`` already produce, ADR-0151 §13 being the
#: only decision that withholds anything and a ``SourceReadRecord`` carrying none of
#: the Tier 0 credential that is its ground.
PROTOCOL_VERSION: Final[int] = 14

#: ADR-0085 §8a: "The correlation id is a UUID string and is at most 36 bytes.
#: Bounding it is what makes the reserve a constant rather than an aspiration; a
#: frame whose ``id`` is longer is a protocol violation and takes ADR-0084 §3's
#: undecodable-frame close, because the length is part of what makes the frame
#: decodable within budget."
MAX_CORRELATION_ID_BYTES: Final[int] = 36

#: ADR-0085 §8d bounds the build identifier and the client identifier at 64 bytes
#: each. The aggregate bound on either connect payload
#: (:data:`~ai_assistant.wire.codec.CONNECT_PAYLOAD_BYTES`) is what actually closes
#: the floor's proof; this is the per-member bound the same clause states.
MAX_IDENTIFIER_BYTES: Final[int] = 64

#: ADR-0085 §8d's floor on a hub's frame size, and ADR-0084 §3's ceiling — what the
#: 4-byte prefix can express. Repeated here rather than imported because ``wire``
#: depends on ``core`` and nothing else (ADR-0084 §6) and the setting that carries
#: them is ``core.config``'s private business; the client needs them to judge the
#: number a hub *publishes*, which is a fact about a peer rather than about this
#: deployment's own configuration.
MIN_FRAME_BYTES: Final[int] = 1024
MAX_FRAME_BYTES: Final[int] = 2**32 - 1

_KIND: Final = "kind"
_ID: Final = "id"
_METHOD: Final = "method"
_PAYLOAD: Final = "payload"

#: Connect request members (ADR-0084 §2).
CONNECT_VERSION: Final = "version"
CONNECT_CLIENT: Final = "client"
CONNECT_CREDENTIAL: Final = "credential"

#: Connect reply members (ADR-0084 §2, §3).
ACK_VERSION: Final = "version"
ACK_BUILD: Final = "build"
ACK_READY: Final = "ready"
ACK_MAX_FRAME_BYTES: Final = "max_frame_bytes"

#: The two handshake refusals ADR-0084 names, as error codes.
#:
#: **They are deliberately not class names**, which is what ADR-0085 §10a's rule
#: gives a *call-path* error. That rule's subject is a declared failure of the
#: promoted surface — "the wire's error vocabulary is therefore exactly the
#: ``AssistantError`` subtree" — and neither of these is one: ADR-0085 §9 lists a
#: version mismatch and a credential refusal among the transport conditions that
#: "are not ``AssistantEngine`` failures and no Protocol method declares them". A
#: lowercase token cannot collide with a class name, so a client can tell a
#: reconstructable failure from a transport refusal by looking at the code alone.
VERSION_MISMATCH: Final = "protocol_version_mismatch"
CREDENTIAL_NOT_SUPPORTED: Final = "credential_not_supported"

#: The four refusals ADR-0124 §7 adds, on the **remote** listener only. Same
#: spelling rule and the same reason: "a refusal code this section introduces is a
#: lowercase token, not a class name, so a client can tell a transport refusal from
#: a reconstructable ``AssistantError`` by the code alone (ADR-0085 §9, §10a). It
#: appears on the handshake path and never on the call path."
#:
#: **Three of the four are distinct because §7 requires them to be**, against the
#: login-surface reflex of saying only "no": "an owner who cannot tell 'I never
#: enrolled this laptop' from 'I revoked it last week' from 'I pasted the wrong
#: string' is ADR-0083's ruling 4 failure", and §2 has already made the audience
#: the owner's own devices.
CREDENTIAL_REQUIRED: Final = "credential_required"
CREDENTIAL_REJECTED: Final = "credential_rejected"
DEVICE_NOT_ENROLLED: Final = "device_not_enrolled"
DEVICE_REVOKED: Final = "device_revoked"

#: Every handshake-vocabulary code, as one set.
#:
#: **This is ADR-0124 §7's named enforcement point**, and it is a constant here
#: rather than a literal at the call site so that it cannot go stale:
#: ``_raise_reply_error`` (:mod:`ai_assistant.wire.client`) carries this set so
#: that a handshake code arriving on the *call* path is raised as a protocol fault
#: rather than handed to ``raise_from_payload``, "which expects a class name. A new
#: refusal code that is not added to that set would reach an older client's
#: reconstruction path as an unknown class." Adding a code beside the six above is
#: therefore the whole of what a future refusal has to do.
HANDSHAKE_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        VERSION_MISMATCH,
        CREDENTIAL_NOT_SUPPORTED,
        CREDENTIAL_REQUIRED,
        CREDENTIAL_REJECTED,
        DEVICE_NOT_ENROLLED,
        DEVICE_REVOKED,
    }
)


class FrameKind(StrEnum):
    """What a frame is (ADR-0085 §8a, ADR-0173 §2).

    **Six members, not the five ADR-0085 §8a enumerated "and no others".**
    ADR-0173 §11 partially supersedes that clause to admit :attr:`CHUNK` as a sixth
    value of ``kind``, and every other row of §8a's table stands: a chunk frame
    carries ``id`` and ``payload`` like every frame, carries no ``method`` like
    every non-request frame, and adds no member to the envelope. §8b's 512-byte
    reserve is **unchanged and is not recomputed** — ``chunk`` is five bytes
    against ``connect_ack``'s eleven, so it does not touch the worst case that
    arithmetic is built on.
    """

    CONNECT = "connect"
    CONNECT_ACK = "connect_ack"
    REQUEST = "request"
    RESULT = "result"
    ERROR = "error"
    CHUNK = "chunk"
    """One instalment of a streamed answer (ADR-0173 §2).

    **Solicited, and that is what keeps ADR-0131 §1 intact.** A chunk answers the
    request whose correlation id it carries, so it is not the hub writing to a
    device unsolicited — it is the most solicited byte on the wire. It also spends
    exactly half of the second job ADR-0084 §3 reserved the correlation id for, "a
    progress stream", leaving multiplexing unspent and the connection serial.
    """


@dataclass(frozen=True, slots=True)
class Envelope:
    """One decoded frame.

    Attributes:
        kind: What the frame is.
        id: The correlation id, which "has one job today and one reason to exist
            tomorrow" (ADR-0084 §3) — today it detects desynchronisation, tomorrow
            it is what lets multiplexing or a progress stream be added additively.
        payload: The request arguments, the result value, the handshake body, or
            the error body.
        method: The ``AssistantEngine`` method name, on a request and nowhere else.
    """

    kind: FrameKind
    id: str
    payload: Any
    method: str | None = None


def _no_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object, refusing a name that appears twice (ADR-0084 §3).

    Rejecting "is also the only option compatible with the rule that an
    undecodable frame closes the connection: a decoder that silently picked one
    would not be undecodable, merely wrong."

    Args:
        pairs: The object's members, in the order they were parsed.

    Returns:
        The object.

    Raises:
        ValueError: If a member name appears more than once.
    """
    seen: dict[str, Any] = {}
    for name, value in pairs:
        if name in seen:
            msg = f"duplicate member {name!r}"
            raise ValueError(msg)
        seen[name] = value
    return seen


def _refuse_a_non_json_constant(token: str) -> NoReturn:
    """Refuse ``NaN``, ``Infinity`` and ``-Infinity`` (ADR-0084 §3).

    **These are not JSON.** RFC 8259 has three literals — ``true``, ``false`` and
    ``null`` — and CPython's decoder accepts the three IEEE tokens as an extension.
    Refusing them is therefore not a new rule but ADR-0084 §3's existing one applied
    where a permissive parser was letting it slip: "text that is not valid JSON" is
    already a member of the closed undecodable class.

    Raises:
        ValueError: Always; :func:`decode_json` maps it to the close it is owed.
    """
    msg = f"{token} is not JSON"
    raise ValueError(msg)


def _finite(text: str) -> float:
    """Decode one JSON number, refusing one whose value is not finite.

    ``1e999`` is *syntactically* well-formed JSON that CPython decodes to
    ``float("inf")``, and ADR-0087 §2c gives a non-finite float no wire form at all.
    ADR-0087 §7 fixes the order as **decode, validate, then measure**, and says why
    measuring first is unsatisfiable — "a receiver that measured before validating
    would have to produce a size for a value that has none". It answers the payload
    path by making the *type* refuse it.

    **The handshake has no type to do that**, which is what makes this necessary
    rather than defensive: ADR-0085 §8d obliges the connect exchange to be measured
    on receipt, and there is no schema between the bytes and that measurement. So
    the value is refused where it is decoded, and the frame takes the close that a
    frame which cannot become a value this contract carries is already owed.

    Args:
        text: The number as it appeared in the frame.

    Returns:
        Its value.

    Raises:
        ValueError: If the value is not finite.
    """
    value = float(text)
    if not isfinite(value):
        msg = f"the number {text} has no finite value, so it has no form on this wire"
        raise ValueError(msg)
    return value


def decode_json(data: bytes) -> Any:
    """Decode one frame's bytes into JSON values (ADR-0084 §3's codec).

    Args:
        data: The frame's bytes, without the length prefix.

    Returns:
        The decoded JSON value.

    Raises:
        UndecodableFrameError: If the bytes are not valid UTF-8, are not valid
            JSON, carry a duplicate member name, or carry a number with no finite
            value. All are members of ADR-0084 §3's closed undecodable class, whose
            answer is a close.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        msg = "a frame's bytes are not valid UTF-8"
        raise UndecodableFrameError(msg) from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_members,
            parse_constant=_refuse_a_non_json_constant,
            parse_float=_finite,
        )
    except ValueError as exc:
        msg = f"a frame is not decodable JSON: {exc}"
        raise UndecodableFrameError(msg) from exc


def encode_envelope(envelope: Envelope) -> bytes:
    """Render one frame's bytes, without the length prefix.

    The payload's bytes are ADR-0087's canonical encoding; the envelope's own
    members are written by the same recipe, which "not significant" permits and
    which keeps one code path rather than two.

    Args:
        envelope: The frame to write.

    Returns:
        The frame's UTF-8 JSON bytes.
    """
    members: dict[str, Any] = {
        _KIND: envelope.kind.value,
        _ID: envelope.id,
        _PAYLOAD: envelope.payload,
    }
    if envelope.method is not None:
        members[_METHOD] = envelope.method
    return canonical_payload(members)


def decode_envelope(data: bytes) -> Envelope:
    """Decode one frame into an :class:`Envelope`.

    **Unknown members are refused.** ADR-0085 §8a fixes the envelope as carrying
    "these members, and no others", and ADR-0084 §3's exact-match version means the
    two halves ship together — so a member nobody declared is a bug on the writing
    side, not a later version to accommodate. Accepting it silently would leave the
    one thing the envelope is for, telling frames apart, decided by a field nobody
    reviewed.

    Args:
        data: The frame's bytes, without the length prefix.

    Returns:
        The decoded envelope.

    Raises:
        UndecodableFrameError: If no envelope decodes — the whole class ADR-0084 §3
            closes, whose answer is to close the connection without a response.
    """
    decoded = decode_json(data)
    if not isinstance(decoded, dict):
        msg = f"a frame's envelope must be a JSON object, got {type(decoded).__name__}"
        raise UndecodableFrameError(msg)

    unknown = set(decoded) - {_KIND, _ID, _METHOD, _PAYLOAD}
    if unknown:
        msg = f"a frame carries members no protocol version declares: {sorted(unknown)}"
        raise UndecodableFrameError(msg)
    missing = {_KIND, _ID, _PAYLOAD} - set(decoded)
    if missing:
        msg = f"a frame is missing required members: {sorted(missing)}"
        raise UndecodableFrameError(msg)

    raw_kind = decoded[_KIND]
    if not isinstance(raw_kind, str):
        msg = f"a frame's kind must be a string, got {type(raw_kind).__name__}"
        raise UndecodableFrameError(msg)
    try:
        kind = FrameKind(raw_kind)
    except ValueError as exc:
        msg = f"a frame names no known kind: {raw_kind!r}"
        raise UndecodableFrameError(msg) from exc

    correlation = decoded[_ID]
    if not isinstance(correlation, str):
        msg = f"a frame's correlation id must be a string, got {type(correlation).__name__}"
        raise UndecodableFrameError(msg)
    if len(correlation.encode("utf-8")) > MAX_CORRELATION_ID_BYTES:
        msg = (
            f"a frame's correlation id is longer than the {MAX_CORRELATION_ID_BYTES}-byte "
            f"bound the envelope reserve is computed against"
        )
        raise UndecodableFrameError(msg)

    method = decoded.get(_METHOD)
    if method is not None and not isinstance(method, str):
        msg = f"a request's method must be a string, got {type(method).__name__}"
        raise UndecodableFrameError(msg)
    if (method is None) is (kind is FrameKind.REQUEST):
        obligation = "must" if kind is FrameKind.REQUEST else "must not"
        msg = f"a {kind.value} frame {obligation} name a method"
        raise UndecodableFrameError(msg)

    return Envelope(kind=kind, id=correlation, payload=decoded[_PAYLOAD], method=method)


def connect_payload(*, client: str, credential: str | None = None) -> dict[str, Any]:
    """Build the client's half of the handshake (ADR-0084 §2).

    The **credential field is optional on the wire**: "on this transport a
    conforming client either omits the member or sends it empty, and both are
    accepted" (ADR-0084 §2). Which listener the frame is bound for decides what
    belongs there, and the member's shape is the same either way — which is why
    ADR-0124 §9 bumps no version for the remote listener.

    Args:
        client: A free-form name for logs — ``assistant-cli``.
        credential: Omitted on the loopback transport, where a non-empty value is
            refused by the server (ADR-0084 §2); carried on the remote transport,
            where a connect without one is refused (ADR-0124 §7).

    Returns:
        The connect payload's members.

    **The client identifier is refused rather than trimmed**, where the *build*
    identifier below is trimmed. The two are not alike: a build identifier is
    ``__version__``, so refusing it would break every connect on a deployment whose
    version string grew, while a client name is this caller's own literal and an
    over-long one is a programming error worth reporting.

    Raises:
        ValueError: If the identifier or the whole payload exceeds ADR-0085 §8d's
            bounds, which is a configuration fault "on the side that would send it
            rather than a frame to send".
    """
    if len(client.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        msg = (
            f"a client identifier of {len(client.encode('utf-8'))} bytes is over the "
            f"{MAX_IDENTIFIER_BYTES}-byte bound ADR-0085 §8d fixes"
        )
        raise ValueError(msg)
    payload: dict[str, Any] = {CONNECT_VERSION: PROTOCOL_VERSION, CONNECT_CLIENT: client}
    if credential is not None:
        payload[CONNECT_CREDENTIAL] = credential
    _check_connect_payload(payload, sender="the client")
    return payload


def connect_ack_payload(*, build: str, max_frame_bytes: int) -> dict[str, Any]:
    """Build the server's half of the handshake (ADR-0084 §2, §3).

    ``max_frame_bytes`` is the third job the handshake does, "and it is the one
    that would have been most annoying to retrofit: without a connect exchange
    there is nowhere to publish a server-side limit, and every client would have to
    discover it by being refused." The server's value is authoritative and **the
    client enforces the number it was told** rather than one of its own.

    ``ready`` is always true here, and that is ADR-0083 §14.2 rather than a
    constant: the listener does not accept until step 6, so a connection that got
    far enough to be answered is a connection to a hub that is ready.

    Args:
        build: This build's identifier, for an operator reading two logs.
        max_frame_bytes: The hub's effective maximum frame size.

    Returns:
        The connect reply's members.

    Raises:
        ValueError: If the payload exceeds ADR-0085 §8d's 256-byte bound.
    """
    payload: dict[str, Any] = {
        ACK_VERSION: PROTOCOL_VERSION,
        ACK_BUILD: _bounded(build),
        ACK_READY: True,
        ACK_MAX_FRAME_BYTES: max_frame_bytes,
    }
    _check_connect_payload(payload, sender="the hub")
    return payload


def _bounded(identifier: str) -> str:
    """Trim a build identifier to ADR-0085 §8d's 64 **bytes**, not 64 characters.

    A character count is the tempting spelling and the wrong one: the bound exists
    so the reply fits inside the frame-size floor, and a floor is measured in bytes.
    Trimmed rather than refused because this value is ``__version__`` — refusing it
    would make every connect fail on a deployment whose version string grew, which
    is a worse answer than a shortened identifier in a log line.
    """
    encoded = identifier.encode("utf-8")[:MAX_IDENTIFIER_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def _check_connect_payload(payload: dict[str, Any], *, sender: str) -> None:
    """Hold either handshake payload to ADR-0085 §8d's aggregate bound.

    Stated over the payload rather than member by member because that is what
    closes: "a member nobody thought about cannot silently widen either handshake
    frame past the floor, because the aggregate is what is checked, on both sides."
    """
    size = len(encode_projection(payload))
    if size > CONNECT_PAYLOAD_BYTES:
        msg = (
            f"{sender}'s connect payload encodes to {size} bytes, over the "
            f"{CONNECT_PAYLOAD_BYTES}-byte bound ADR-0085 §8d fixes so the frame-size "
            f"floor holds; shorten the identifier"
        )
        raise ValueError(msg)


def _refuse_an_oversized_handshake(payload: dict[str, Any], *, member: str) -> None:
    """Refuse a *received* handshake payload the contract does not admit (§8d).

    **The bound binds the reader as well as the writer, and the asymmetry is what
    made this worth closing.** ADR-0085 §8d states it flatly — "each
    connect-exchange payload — the request and the reply alike — is at most 256
    bytes encoded" — and this module already refuses to *build* one that exceeds
    it. A reader that accepted what the contract forbids would be more permissive
    than the contract on the one exchange whose whole job is to bound itself, and
    would let a peer spend up to ``hub_max_frame_bytes`` on a frame that has told
    the hub nothing yet: the cheapest state for a misbehaving peer to accumulate,
    which is precisely what §3's pending-handshake ceiling exists to bound.

    **It closes rather than answering with a typed error**, which is the narrow
    reading of ADR-0084 §3: a decoded frame gets a typed error "provided it is not
    itself a violation of the connection's own rules", and a handshake that
    overruns the handshake's own bound is one. Inventing a code for it would be
    this lane adding vocabulary to a ratified list.

    Raises:
        UndecodableFrameError: If the payload, or its identifier member, is over
            the bound.
    """
    size = len(encode_projection(payload))
    if size > CONNECT_PAYLOAD_BYTES:
        msg = (
            f"a connect-exchange payload of {size} bytes is over the "
            f"{CONNECT_PAYLOAD_BYTES}-byte bound ADR-0085 §8d fixes"
        )
        raise UndecodableFrameError(msg)
    identifier = payload.get(member)
    if isinstance(identifier, str) and len(identifier.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        msg = (
            f"a connect-exchange {member} identifier is over the "
            f"{MAX_IDENTIFIER_BYTES}-byte bound ADR-0085 §8d fixes"
        )
        raise UndecodableFrameError(msg)


class _AbsentMember:
    """The type of :data:`_ABSENT`, so that "not there" has a type of its own."""

    __slots__ = ()

    def __repr__(self) -> str:
        """Name it for a traceback; it never reaches a wire frame or a log line."""
        return "<absent>"


#: What :func:`_read_connect_members` reports for a connect member that **is not
#: there**, as distinct from one that is there and is JSON ``null``.
#:
#: **The two are different frames and ADR-0124 §7 gives them different answers**,
#: so ``dict.get``'s ``None`` cannot stand for both: §7 refuses an "absent or empty"
#: credential with ``credential_required``, and a member "present and… not a
#: string" — which a ``null`` is — "as a credential that did not verify". A reader
#: that collapses them tells an operator its client sent *no* credential when it
#: sent a malformed one, which is exactly the distinction §7 requires "in the error
#: it returns **and in what the hub logs**".
_ABSENT: Final = _AbsentMember()


def _read_connect_members(payload: object) -> tuple[int, str, object]:
    """Read the members every connect frame carries, whichever listener it reached.

    Everything up to the credential is the same on both transports, and ADR-0124
    §9 rests on its being so: "the remote listener adds no member to the connect
    exchange, changes no frame's encoding… A peer at version 2 on either listener
    exchanges exactly the frames it exchanges today." One reader is what makes that
    a property of the code rather than of two implementations that agree today.

    **The 256-byte bound is applied here, first**, which is what ADR-0124 §7 relies
    on when it says the width "is already bounded and nothing new is needed for
    it": an oversized credential is refused as an oversized handshake and never
    reaches either transport's credential rule.

    Args:
        payload: The connect frame's payload, as decoded.

    Returns:
        The version, the client identifier, and the credential member exactly as
        it was decoded — or :data:`_ABSENT` where the frame carries no such member.
        **A present ``null`` comes back as ``None``**, which is a different frame
        from one that omits the member and, on the remote listener, a different
        refusal (ADR-0124 §7).

    Raises:
        UndecodableFrameError: If the payload is not an object, is over ADR-0085
            §8d's bound, or is missing a required member.
    """
    if not isinstance(payload, dict):
        msg = f"a connect payload must be an object, got {type(payload).__name__}"
        raise UndecodableFrameError(msg)
    _refuse_an_oversized_handshake(payload, member=CONNECT_CLIENT)
    version = payload.get(CONNECT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        msg = "a connect payload's version must be an integer"
        raise UndecodableFrameError(msg)
    client = payload.get(CONNECT_CLIENT)
    if not isinstance(client, str):
        msg = "a connect payload must name its client"
        raise UndecodableFrameError(msg)
    return version, client, payload.get(CONNECT_CREDENTIAL, _ABSENT)


def read_connect(payload: object) -> tuple[int, str]:
    """Read a **loopback** connect payload, applying ADR-0084 §2's credential rule.

    ADR-0124 §7 leaves this rule exactly where it was: "ADR-0084 §2's rule is
    unchanged on the loopback transport: there a non-empty credential is still
    refused with ``credential_not_supported``. The two listeners hold opposite
    rules, and a hub running both applies each rule to its own listener."

    Args:
        payload: The connect frame's payload, as decoded.

    Returns:
        The version the client claims, and its identifier.

    Raises:
        UndecodableFrameError: If the payload is not an object, is over ADR-0085
            §8d's bound, or is missing a required member. These close the
            connection; they do not earn a reply.
        CredentialNotSupportedError: If the credential member carries something.
            "Accepting-and-ignoring is the alternative and it is the dangerous one:
            a client that presents a credential and is admitted has been told, by
            admission, that its credential was checked. Nothing on this transport
            checks anything." This one *is* reported before the close, being "a
            member of an envelope that parsed" (ADR-0084 §3).
    """
    version, client, credential = _read_connect_members(payload)
    # **A present ``null`` stays on the "carries nothing" side here**, which is
    # where this reader has always put it, and ADR-0124 §7 is why it stays: "ADR-0084
    # §2's rule is unchanged on the loopback transport", and that rule refuses a
    # **non-empty** credential. A ``null`` is not a non-empty credential — it is a
    # client saying it has none — so refusing it would be this module widening a rule
    # the same section froze. The remote listener's opposite answer is not a
    # contradiction: §7 gives it a type rule *and* a code of its own, and neither
    # exists on this transport.
    if credential not in (_ABSENT, None, ""):
        msg = (
            "this transport carries no credential, and admitting one would tell the client "
            "its credential had been checked when nothing checked anything; the 0600 bit on "
            "the socket is what restricts connection here"
        )
        raise CredentialNotSupportedError(msg)
    return version, client


def read_remote_connect(payload: object) -> tuple[int, str, str]:
    """Read a **remote** connect payload, applying ADR-0124 §7's credential rules.

    The inversion of :func:`read_connect`, and one principle stands behind both —
    ADR-0084 §2's own: **admission never asserts a check that did not happen.**

    **The type rule is here rather than at the verifier, because the connect
    payload is untrusted decoded JSON.** ADR-0124 §7: on loopback "an object, a
    boolean or a number is already refused and the question never arises. On the
    remote listener the same value would otherwise reach a verifier written for
    text, and three implementations could diverge three ways: an uncaught type
    error that closes the connection with no refusal, a hash over some
    serialisation of the object, or a generic refusal."

    **Absent and malformed are different refusals and that is deliberate.** An
    absent or empty member is "refused, with a distinct error naming the reason";
    a present member that is not a well-formed credential "is refused as a
    credential that did not verify", which is the same answer a wrong credential
    gets — so a peer learns nothing from the shape of its own mistake that it
    could not learn by guessing.

    **A present ``null`` is on the malformed side of that line, and it is the one
    place the distinction is easy to lose.** ``null`` is *present* and is *not a
    string*, which is §7's own wording for the rejected arm; only a member that is
    not there at all — or is the empty string — is the required arm. The two look
    alike through ``dict.get``, which answers ``None`` for both, so the member is
    read against :data:`_ABSENT` instead. Getting it wrong is fail-closed either way
    — both codes refuse and close — but it tells an operator debugging a
    non-conforming client that it sent *no* credential when it sent a malformed one,
    and §7 requires the reasons distinguished "in the error it returns **and in what
    the hub logs**".

    Args:
        payload: The connect frame's payload, as decoded.

    Returns:
        The version the client claims, its identifier, and a credential already
        known to be a well-formed value of the scheme (ADR-0124 §6).

    Raises:
        UndecodableFrameError: As :func:`read_connect`.
        CredentialRequiredError: If the credential member is absent or empty.
        CredentialRejectedError: If it is present and is not a string — ``null``
            included — or is a string that is not a well-formed value of the
            scheme. The value is discarded here and never reaches a verifier.
    """
    version, client, credential = _read_connect_members(payload)
    if credential is _ABSENT or credential == "":
        msg = (
            "this listener admits a device on two facts and a credential is one of them; "
            "a connect carrying none is refused rather than admitted on the overlay's "
            "membership alone, which is a decision the owner never made at this hub"
        )
        raise CredentialRequiredError(msg)
    if not isinstance(credential, str) or not is_well_formed(credential):
        msg = (
            "a connect frame's credential is not a value this hub could have minted, so it "
            "is refused as one that did not verify; check that the whole credential the "
            "enrolment printed was pasted, and re-enrol the device if it was lost"
        )
        raise CredentialRejectedError(msg)
    return version, client, credential


def read_connect_ack(payload: object) -> tuple[int, int]:
    """Read the server's connect reply.

    Args:
        payload: The reply frame's payload, as decoded.

    Returns:
        The version the hub claims, and its effective maximum frame size.

    Raises:
        UndecodableFrameError: If the payload is not an object or is missing a
            required member.
        ProtocolError: If the hub reports itself not ready, which cannot happen
            through a listener that only accepts after ADR-0083 §3's step 6 and is
            therefore reported rather than assumed away.
    """
    if not isinstance(payload, dict):
        msg = f"a connect reply must be an object, got {type(payload).__name__}"
        raise UndecodableFrameError(msg)
    _refuse_an_oversized_handshake(payload, member=ACK_BUILD)
    version = payload.get(ACK_VERSION)
    frame_bytes = payload.get(ACK_MAX_FRAME_BYTES)
    ready = payload.get(ACK_READY)
    if not isinstance(version, int) or isinstance(version, bool):
        msg = "a connect reply's version must be an integer"
        raise UndecodableFrameError(msg)
    if not isinstance(payload.get(ACK_BUILD), str):
        # ADR-0084 §2 requires the reply to carry one, and it is the only thing in
        # the exchange that tells an operator reading two logs which build answered.
        msg = "a connect reply must name the build that answered"
        raise UndecodableFrameError(msg)
    if not isinstance(frame_bytes, int) or isinstance(frame_bytes, bool):
        msg = "a connect reply must carry the hub's effective maximum frame size"
        raise UndecodableFrameError(msg)
    if not MIN_FRAME_BYTES <= frame_bytes <= MAX_FRAME_BYTES:
        # **A published limit outside its own legal range is worse than useless.**
        # The client enforces the number it was told (ADR-0084 §3), so a reply of
        # ``0`` would make the contract limit negative and every ordinary argument
        # would be refused as oversized — a malformed handshake misreported as the
        # caller's fault. The bounds are the ones the setting itself carries:
        # ADR-0085 §8d's floor and what the 4-byte prefix can express.
        msg = (
            f"a connect reply advertises a maximum frame size of {frame_bytes} bytes, "
            f"outside the [{MIN_FRAME_BYTES}, {MAX_FRAME_BYTES}] range a hub may serve"
        )
        raise UndecodableFrameError(msg)
    if ready is not True:
        msg = "the hub answered the handshake but reports that it is not ready to serve"
        raise ProtocolError(msg)
    return version, frame_bytes
