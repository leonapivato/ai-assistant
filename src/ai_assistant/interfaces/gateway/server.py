"""The browser gateway: a spoke that serves one device's browsers (ADR-0168).

**What this is.** "The browser gateway is a spoke under ADR-0094 §1 — an
attachment reaching the hub across a process boundary over ADR-0084's wire — and
it is a spoke of the **client** profile, carrying a person" (ADR-0168 §1). It
obtains the hub only through the promoted ``AssistantEngine``, by the same client
the CLI uses and the same selection between transports; it builds no engine and
never falls back from one transport to another.

**What it may not do.** "The gateway holds no assistant logic: it composes no
behaviour the promoted engine surface does not offer, authors no permission
ruling, mints no confirmation, and opens no store" (ADR-0168 §1). The one thing it
adds that is not translation is its own door policy, "which is the same class of
thing as the CLI's exit code — a property of the adapter, not of the assistant".

**The routing rule is a biconditional, and it is checkable here.** "A browser
request reaches the promoted engine surface **if and only if** the gateway has
admitted it under §4 *and* it asks the assistant for something." :meth:`Gateway.
_respond` is where that holds: a static asset, the bootstrap exchange, an
unadmitted request and a refused one each return before :meth:`Gateway._ask`, the
only method on this class that touches the engine.

**The loopback listener is loopback and nothing else** (ADR-0168 §2). The address
is :data:`_LOOPBACK`, a constant of this module rather than a setting, so there is
no configuration that could have it bind a wildcard, an interface or an overlay
address — which is the stronger form of §2's "a configuration that would have it
bind anything else is refused at load rather than bound".

**A second listener may serve browsers on the owner's other devices, and it is off
unless it is configured on** (ADR-0174). It is the fourth egress boundary §1 of
that ADR authorises: the gateway's remote browser transport, bound to an overlay
address the owner configured and reachable only over an overlay satisfying
ADR-0124 §2. :data:`_LOOPBACK` stays a constant through all of it, because §2 of
ADR-0174 supersedes ADR-0168 §2 only "as it reaches a **separately configured**
remote browser listener" — the loopback listener is bound whether or not this one
is, on the same address, under every clause of ADR-0168 §2 that survives. A
gateway with no ``gateway_remote_address`` behaves byte for byte as it did.

**That second listener serves HTTPS, and it is the listener rather than a setting
that decides so** (ADR-0202). It terminates TLS in this process, on a certificate
the overlay obtained for this machine's own overlay name and a key that never left
it; there is no setting that makes it serve plain HTTP, no fallback to plain HTTP
on any condition, and no redirect — "serving a redirect would require the
plain-HTTP listener it refuses" (§2). A gateway whose certificate or key is absent,
unreadable, unusable, mismatched, or outside its validity period does not start and
reports why, which takes the loopback listener down with it: §2 weighs that
explicitly and prefers it to "silent degradation moved to a different place".
:mod:`.tls` holds every one of those refusals, and it runs at construction because
§8 orders them "before it binds or discloses a bootstrap value". The loopback
listener is untouched by all of it and still speaks plain HTTP, "potentially
trustworthy for free" (§9).

**What the second listener adds is a fact the first one never had.** Before serving
anything on it — a static asset and the bootstrap exchange included — the gateway
asks the overlay agent on its **own** machine who holds the connecting address, and
takes that identity from nothing the peer asserts (ADR-0174 §3). Admission is then
two facts rather than one (§4): the device is one the owner listed in
``gateway_remote_browser_devices``, *and* the request carries a live web session.
The assets alone are served on overlay membership, because they are the bundle this
repository ships to anyone who installs it.

**A browser reaches a closed enumeration of thirty operations** (ADR-0177 §1,
superseding ADR-0175 §6's first clause and its figure of five). Twenty-eight of
them are served here today: milestone 14's ``converse``, ``converse_streaming``,
``recent_conversations``, ``conversation`` and ``forget_conversation``, together
with the grant surface — ``grantable_sources``, ``grant``, ``revoke``,
``recent_grants``, ``standing_grants`` — the belief surface — ``beliefs``,
``belief``, ``forget`` — the deferred-question surface — ``questions``,
``interrupted_questions``, ``answer``, ``forget_question`` — ``observe``, the
notification *review* surface — ``notifications``, ``dismiss_notification``,
``forget_notification``, ``notification_preferences``,
``set_notification_preferences`` — and the connection surface —
``connect_account``, ``reprovision_account``, ``disconnect_account``,
``connected_accounts``, ``recent_connection_acts``.
``next_notification`` remains the gateway's **own** poll and is none of the thirty,
because no browser request resolves to it — :class:`.delivery.DeliveryFanOut`
originates it, no browser request names it, and no browser argument reaches it
(ADR-0175 §6's second clause, bound unchanged by ADR-0177 §1).

**The residual is two and the enumeration is no weaker for it.** ``resume`` and
``pending_confirmations`` are admitted by ADR-0177 §1 and are not served here yet,
because §8 of that ADR blocks the confirmation surface until ADR-0148 §8's content
can be met; ``learn`` is admitted by nothing and stays unreached until its own
ratified decision (§11). The form is what ADR-0168 §6 chose it for — "naming what
may appear is the only form that stays right when a later lane adds a request shape
nobody has thought of yet".

**Two of the twenty-eight are narrower than the rest, and the narrowing is about
the page's own origin rather than about who is asking** (ADR-0177 §3). A credential
reaches this system through ``connect_account`` and ``reprovision_account`` and
through no other operation on any surface, and those two are admitted on the
loopback listener and refused on the remote browser one, on a condition of their
own. **ADR-0202 does not reach that condition**, and the distinction is worth
holding: §3's refusal was *argued* from the remote page not being a potentially
trustworthy origin (ADR-0174 §7), and ADR-0202 changes that fact — the remote page
is served over HTTPS and is such an origin. What it does not change is a single
clause of ADR-0177 §3, which ADR-0202 §9 leaves where it found it and §10 records
no supersession against. So the refusal stands as written, and lifting it is
ADR-0177's own decision to reopen rather than a consequence of this one.

**And a gateway that reaches its *hub* over ADR-0124's remote listener** serves
none of the five to any browser on either listener, because ADR-0151 §13's own
question — the credential's hop from an enrolled device to the hub — is untouched
by ADR-0177 §3 and stays refused. :meth:`Gateway._connections_refused` is where
both live, and neither is decided from anything a browser asserts.

**Two of those shapes answer on a stream** (ADR-0175 §1): the body of the response
to the request the browser made, written in pieces, with no socket, no upgrade and
nothing an ``EventSource`` reaches. The reason is mechanical rather than
architectural — ADR-0168 §6 requires the header half of a session on every admitted
request and requires it to travel "only as a request header the front end sets",
and a `WebSocket` handshake and an `EventSource` request are the two requests a page
cannot set a header on at all. :mod:`.streams` carries what a stream value is and
:mod:`.delivery` carries the one poll and its fan-out.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import json
import os
import re
import signal
import socket
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import structlog
from pydantic import SecretStr, ValidationError

from ai_assistant.core.errors import (
    AssistantError,
    ConfigurationError,
    ConnectionStoreError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    TranscriptionFailedError,
    UnknownConnectionError,
    UnusableIdentityError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    DEFAULT_PAGE_SIZE,
    AnswerOutcome,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    ClassReach,
    Confirmation,
    ConfirmationDestination,
    ConfirmationEgress,
    ConnectedAccount,
    ConnectionAct,
    ContinuationToken,
    ConversationDigest,
    ConversationSummary,
    Disposition,
    EgressSpan,
    Evidence,
    FrozenJson,
    GrantableSource,
    GrantScope,
    HeldNotification,
    MemoryKind,
    NotificationPreferences,
    NotificationReach,
    ObservationReport,
    ObservedProposal,
    OriginUnrecordedBinding,
    PermissionDecision,
    Question,
    QuietWindow,
    RecordedInvocation,
    SourceGrant,
    SourceReadRecord,
    SpeechFailure,
    SpendTotal,
    SpokenAudio,
    SpokenAudioFormat,
    SpokenDelivery,
    SpokenDeliveryReport,
    SpokenDeliveryState,
    SpokenTurn,
    StepOutcome,
    SuccessorLink,
    TurnOutcome,
    Warrant,
    routed_listing_arm,
    secret_value,
)
from ai_assistant.interfaces.gateway import streams
from ai_assistant.interfaces.gateway.delivery import DeliveryFanOut, DeliveryStream, write_stream
from ai_assistant.interfaces.gateway.http import (
    IncompleteRequestError,
    MalformedRequestError,
    Request,
    RequestTooLargeError,
    Response,
    StreamHead,
    read_request,
    render,
    render_chunk,
    render_stream_end,
    render_stream_head,
)
from ai_assistant.interfaces.gateway.records import (
    AdmissionRecorder,
    RefusalCondition,
    RequestClass,
)
from ai_assistant.interfaces.gateway.sessions import (
    Admission,
    BootstrapMint,
    Cancellable,
    Defer,
    SessionHandle,
    SessionTable,
    mint_value,
)
from ai_assistant.interfaces.gateway.tls import remote_tls
from ai_assistant.wire.errors import OverlayIdentityUnavailableError, TransportError
from ai_assistant.wire.overlay import (
    CLIENT_AGENT_SOCKET,
    MAX_OVERLAY_IDENTITY_BYTES,
    local_agent,
)

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Awaitable, Callable, Mapping

    from pydantic import BaseModel

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        CanonicalDestination,
        EgressBinding,
        RoutableOperation,
        RoutedListing,
        RoutedOperation,
    )
    from ai_assistant.interfaces.gateway.tls import RemoteTls
    from ai_assistant.wire.overlay import OverlayAgent

_log = structlog.get_logger(__name__)

#: The address the **loopback** listener binds (ADR-0168 §2). Not a setting, and
#: still not one after ADR-0174: §2 of that ADR supersedes ADR-0168 §2's bind clause
#: only as it reaches "a separately configured remote browser listener", and keeps
#: the loopback listener bound "whether or not this one is, under every clause of
#: ADR-0168 §2 that this ADR does not supersede". So no configuration moves *this*
#: address, and the remote address is a second field rather than a widening of the
#: first — which is what makes ADR-0168 §2's reader right about the door they built.
_LOOPBACK: Final = "127.0.0.1"

#: The scheme each listener speaks, which is a property of the listener rather than
#: a setting. The loopback listener speaks plain HTTP and is "untouched" by ADR-0202
#: — "it speaks plain HTTP, it is bound whether or not the remote listener is, and no
#: clause of this ADR adds a certificate, a key or a scheme requirement to it" (§2).
#: The remote browser listener "serves HTTPS and nothing else. No setting makes it
#: serve plain HTTP, and the gateway may not fall back to plain HTTP on any condition
#: — an absent file, an unreadable file, an expired certificate, or a failed
#: handshake." So there are two constants and no third state, and neither is
#: configurable.
_LOOPBACK_SCHEME: Final = "http"
_REMOTE_SCHEME: Final = "https"

#: Spelled once for :func:`_offset_text`, so it carries no bare literal a reader has
#: to recognise. ``interfaces.cli`` holds the same pair for the same helper.
_SECONDS_A_DAY: Final = 86_400
_MICROS_A_SECOND: Final = 1_000_000

#: The paths the browser-facing surface uses. ADR-0168 §12 leaves the surface to
#: this lane — "the request shapes, the paths, the document, and whether a push
#: carrier such as a WebSocket is among them… no ADR is owed for it and the
#: implementing lane decides it" — and ADR-0175 §2 restates that division for the
#: two shapes it adds: "the exact framing of a value on a stream, the media type a
#: stream is served with, and the paths the surface uses are the implementing
#: lane's".
#:
#: **Every argument travels in a JSON request body, and none in a URL.** No path
#: here carries a parameter and no handler reads a query string, which is why
#: :class:`.http.Request` still discards one: a door built on "a request this module
#: cannot parse is refused rather than guessed at" gains a path-template parser and
#: a query parser for nothing, since every one of these is a same-origin ``fetch``
#: the front end writes. ADR-0168 §6 separately forbids a session value ever
#: appearing in a URL, and a surface with no URL arguments at all cannot acquire one
#: by accident.
_SESSION_PATH: Final = "/session"
_ASK_PATH: Final = "/ask"

#: ADR-0175 §3's streamed turn. A **second** entry beside :data:`_ASK_PATH` rather
#: than a replacement, and keeping the non-streaming one is a decision rather than
#: inertia: ADR-0173 §5 makes a provider that cannot stream "a ``ModelError`` from
#: the call — before any delta", degrading to ``reply`` ``None`` with
#: ``reply_degraded`` ``True``, so a browser offered only the streaming entry would
#: answer nothing at all on a build where the CLI on the same machine answered
#: normally. The gateway never chooses between them and never falls back from one to
#: the other — ADR-0168 §9 forbids it retrying silently and ADR-0173 §7 refuses the
#: same fallback one layer in. A second attempt is the front end asking again.
_ASK_STREAM_PATH: Final = "/ask/stream"

#: ADR-0200 §10's spoken turn. A **third** entry beside the two above and never a
#: replacement for either: "It is a third entry rather than a replacement, and the
#: gateway never chooses between the three, never falls back from one to another, and
#: never retries silently (ADR-0168 §9)."
#:
#: **One request, answered whole.** The recording is uploaded complete and the
#: rendering comes back on that request's response — no WebSocket, no protocol
#: upgrade, no ``EventSource`` and no chunked upload, the first three forbidden by
#: ADR-0175 §1 and the fourth by ``http.py``'s refusal of ``Transfer-Encoding``. Push
#: to talk needs none of them: the press ends before the request begins. So this is
#: **not** in :data:`_STREAMED_SHAPES` and it is a plain entry in
#: :attr:`Gateway._unary` beside :data:`_ASK_PATH`.
_ASK_SPOKEN_PATH: Final = "/ask/spoken"

#: ADR-0175 §4's delivery stream. ``GET`` because it carries no argument: the poll
#: is the gateway's own and takes none from a browser.
_DELIVERIES_PATH: Final = "/deliveries"

#: ADR-0175 §6's three conversation operations. "Resume" in milestone 14's own line
#: is resuming a *conversation* — reading it and continuing it — which is these two
#: plus a turn call carrying a ``conversation_id``. ``AssistantEngine.resume`` is a
#: different method that resumes a parked **turn**, and ADR-0175 §10 defers it with
#: ``pending_confirmations`` and the CONFIRM prompt to milestone 15.
_CONVERSATIONS_PATH: Final = "/conversations"
_CONVERSATION_PATH: Final = "/conversation"
_FORGET_CONVERSATION_PATH: Final = "/conversation/forget"

#: ADR-0177 §6's grant surface. **Five paths for five operations, and the two
#: readings are two paths rather than one answered twice**: ADR-0139 §3's fourth
#: clause forbids a view presenting a source's configuration state as part of a
#: grant or a grant as a statement about whether a source is being read, and
#: ADR-0139 §1 is that neither answer is derivable from the other. A single
#: ``/grants`` shape that merged :data:`_SOURCES_PATH`'s answer into
#: :data:`_STANDING_PATH`'s would perform that merge in the gateway, where the
#: front end could no longer keep the two apart.
_SOURCES_PATH: Final = "/sources"
_GRANT_PATH: Final = "/grant"
_REVOKE_PATH: Final = "/revoke"
_RECENT_GRANTS_PATH: Final = "/grants/recent"
_STANDING_PATH: Final = "/grants/standing"

#: ADR-0177 §5's belief surface, in the shape the conversation surface already
#: uses: a listing, a single read, and a destruction that the single read is the
#: ceremony for. §5's second clause is why the pair is two paths and not one — the
#: render the ceremony rests on "is taken from a ``belief`` read issued immediately
#: before the confirmation is offered, and never from an entry of a ``beliefs``
#: listing the page rendered earlier".
_BELIEFS_PATH: Final = "/beliefs"
_BELIEF_PATH: Final = "/belief"
_FORGET_BELIEF_PATH: Final = "/belief/forget"

#: ADR-0078 §8's four façade methods, reached as ADR-0177 §1 admits them. The two
#: listings are separate paths because they answer different questions — one is
#: what is waiting for an answer, the other is what was begun and never recorded
#: (ADR-0078 §9) — and no single read of one question exists (#495), which is what
#: §5's ``forget_question`` ceremony is met with instead.
_QUESTIONS_PATH: Final = "/questions"
_INTERRUPTED_PATH: Final = "/questions/interrupted"
_ANSWER_PATH: Final = "/question/answer"
_FORGET_QUESTION_PATH: Final = "/question/forget"

#: ADR-0077 §8's passive half, explicit as that section makes it: "nothing triggers
#: it but a caller", and here the caller is the owner pressing a button.
_OBSERVE_PATH: Final = "/observe"

#: ADR-0177 §8's CONFIRM pair, unblocked by ADR-0178's merge and no sooner: §8's
#: precondition is "discharged rather than replaced, on its own stated firing
#: condition" (ADR-0178 §8), and what the surface owes once it is unblocked is §8's
#: other clauses plus ADR-0178 §7's floor.
#:
#: **Two paths, and the listing is a path of its own rather than an empty answer of
#: the other**, for the reason the question surface states one panel over: a recovery
#: read and an act on one recovered park answer different questions, and a door that
#: classifies "from its method and path alone" (ADR-0168 §6) must not have a body that
#: failed to parse read as a listing.
#:
#: **``/confirmation/resume`` rather than ``/resume``**, because "resume" is already
#: ambiguous at this surface and the path is where the ambiguity would land:
#: :data:`_CONVERSATIONS_PATH` records that resuming a *conversation* is a read plus a
#: turn, while ``AssistantEngine.resume`` resumes a parked **turn**. The path names the
#: thing resumed, so neither can be reached by guessing the other.
_CONFIRMATIONS_PATH: Final = "/confirmations"
_RESUME_PATH: Final = "/confirmation/resume"

#: ADR-0177 §10's notification review surface. Five paths for five operations, and
#: **none of them is** :data:`_DELIVERIES_PATH`: what these operate on is the
#: notification *record* (ADR-0130), where a delivery is what the gateway's own poll
#: hands to an open stream. §10's first three clauses turn that distinction into
#: rules — nothing here acknowledges, retires, withdraws or completes a delivery, no
#: ``delivery_id`` is read or written on any of them, and neither
#: ``dismiss_notification`` nor ``forget_notification`` is a route by which one could
#: reach a browser.
#:
#: The write is its own path rather than a second method on the read, because the
#: door classifies "from its method and path alone" (ADR-0168 §6) and a surface whose
#: read and whose whole-value write share a shape is one where a body that failed to
#: parse could be read as the read.
_NOTIFICATIONS_PATH: Final = "/notifications"
_DISMISS_NOTIFICATION_PATH: Final = "/notification/dismiss"
_FORGET_NOTIFICATION_PATH: Final = "/notification/forget"
_NOTIFICATION_PREFERENCES_PATH: Final = "/notification/preferences"
_SET_NOTIFICATION_PREFERENCES_PATH: Final = "/notification/preferences/set"

#: ADR-0177 §3's connection surface. Five paths for ADR-0151 §1's five operations,
#: and the split into *what is connected now* and *what was done* is the same one
#: :data:`_STANDING_PATH` and :data:`_RECENT_GRANTS_PATH` already carry — ADR-0139
#: §1 rules neither derivable from the other, and ADR-0151 §9 adds the reason it
#: bites hardest here: a reference whose latest act falls outside the log's page is
#: one a reader walking the page would report by an *earlier* act.
#:
#: **Connecting and re-provisioning are two paths and never one with an optional
#: reference**, which is ADR-0151 §1's own shape: a fresh connection cannot fail
#: with an unknown reference or lose a compare-and-swap, and folding them would
#: hand a browser one shape whose outcomes depend on which member it filled in.
#: They are also the two that carry a credential, so keeping them apart is what
#: makes :data:`_CREDENTIAL_PATHS` a set of paths rather than a rule about bodies.
_CONNECT_PATH: Final = "/connection/connect"
_REPROVISION_PATH: Final = "/connection/reprovision"
_DISCONNECT_PATH: Final = "/connection/disconnect"
_CONNECTIONS_PATH: Final = "/connections"
_CONNECTION_ACTS_PATH: Final = "/connections/recent"

#: Which method admits which path. A mapping rather than a chain of comparisons,
#: because ADR-0168 §6 classifies "from its method and path alone" and the set of
#: shapes the surface has is now large enough that reading it off one table is what
#: keeps ADR-0175 §6's enumeration checkable.
_ASSISTANT_PATHS: Final[Mapping[tuple[str, str], str]] = {
    ("POST", _ASK_PATH): "converse",
    ("POST", _ASK_STREAM_PATH): "converse_streaming",
    ("POST", _ASK_SPOKEN_PATH): "converse_spoken",
    ("GET", _DELIVERIES_PATH): "delivery-stream",
    ("POST", _CONVERSATIONS_PATH): "recent_conversations",
    ("POST", _CONVERSATION_PATH): "conversation",
    ("POST", _FORGET_CONVERSATION_PATH): "forget_conversation",
    ("POST", _SOURCES_PATH): "grantable_sources",
    ("POST", _GRANT_PATH): "grant",
    ("POST", _REVOKE_PATH): "revoke",
    ("POST", _RECENT_GRANTS_PATH): "recent_grants",
    ("POST", _STANDING_PATH): "standing_grants",
    ("POST", _BELIEFS_PATH): "beliefs",
    ("POST", _BELIEF_PATH): "belief",
    ("POST", _FORGET_BELIEF_PATH): "forget",
    ("POST", _QUESTIONS_PATH): "questions",
    ("POST", _INTERRUPTED_PATH): "interrupted_questions",
    ("POST", _ANSWER_PATH): "answer",
    ("POST", _FORGET_QUESTION_PATH): "forget_question",
    ("POST", _OBSERVE_PATH): "observe",
    ("POST", _CONFIRMATIONS_PATH): "pending_confirmations",
    ("POST", _RESUME_PATH): "resume",
    ("POST", _NOTIFICATIONS_PATH): "notifications",
    ("POST", _DISMISS_NOTIFICATION_PATH): "dismiss_notification",
    ("POST", _FORGET_NOTIFICATION_PATH): "forget_notification",
    ("POST", _NOTIFICATION_PREFERENCES_PATH): "notification_preferences",
    ("POST", _SET_NOTIFICATION_PREFERENCES_PATH): "set_notification_preferences",
    ("POST", _CONNECT_PATH): "connect_account",
    ("POST", _REPROVISION_PATH): "reprovision_account",
    ("POST", _DISCONNECT_PATH): "disconnect_account",
    ("POST", _CONNECTIONS_PATH): "connected_accounts",
    ("POST", _CONNECTION_ACTS_PATH): "recent_connection_acts",
}

#: ADR-0151 §1's five, as a set the refusals below are decided over. They stay in
#: :data:`_ASSISTANT_PATHS` on every listener and in every deployment: ADR-0177 §3
#: requires a refusal "reported as its own condition and never flattened into an
#: absent path", and a shape dropped from the table above would be exactly that
#: absent path — ADR-0168 §6's residual fourth class, answered with a `404`.
_CONNECTION_PATHS: Final = frozenset(
    {
        _CONNECT_PATH,
        _REPROVISION_PATH,
        _DISCONNECT_PATH,
        _CONNECTIONS_PATH,
        _CONNECTION_ACTS_PATH,
    }
)

#: The two of the five that carry a ``SecretValue`` (ADR-0151 §6: "No other
#: operation on any surface accepts one"), and therefore the two ADR-0177 §3 refuses
#: on a page whose origin the browser will not protect a secret on. The other three
#: carry a *reference*, which ADR-0151 §3 designed so that it is not a credential —
#: which is why §3 splits the five rather than refusing all of them, and why the
#: split is stated over paths rather than over what a body happens to hold.
_CREDENTIAL_PATHS: Final = frozenset({_CONNECT_PATH, _REPROVISION_PATH})

#: The two shapes that answer on a stream (ADR-0175 §1). They are held apart from
#: the rest because only they outlive the request that established them, so only
#: they need the handle of the session that admitted them (§7).
_STREAMED_SHAPES: Final = frozenset({("POST", _ASK_STREAM_PATH), ("GET", _DELIVERIES_PATH)})

#: The cookie the gateway sets, and the header the front end sends. Two values
#: rather than one because "a cookie is not scoped to a port" (ADR-0168 §6).
_COOKIE_NAME: Final = "assistant_session"
_SESSION_HEADER: Final = "x-assistant-session"

#: The policy every response carries (ADR-0168 §6): scripts, styles, fonts,
#: images, media and connections from the gateway's own origin alone, and no
#: inline script. `default-src 'none'` is what makes the enumeration exhaustive
#: rather than a list someone has to keep abreast of.
_POLICY: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self'; media-src 'self'; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)

#: The budget one turn is given, mirroring the CLI's own ``--timeout`` default. It
#: is a constant rather than an eleventh `Settings` field on purpose: ADR-0168 §8
#: names the ten figures this milestone owes and ADR-0172 adds none, and a turn
#: budget is the *caller's* budget (ADR-0029 §4) rather than one of the gateway's
#: resource bounds. Whoever measures that a browser needs its own buys the field.
_TURN_BUDGET: Final = timedelta(seconds=60)

#: What a refusal answers with. Each condition keeps its own status, because
#: ADR-0168 §6 requires the cookie-half fault "reported to the owner as its own
#: condition, and never flattened into an expiry, a ceiling refusal or an ordinary
#: absent session" — and a status shared with another condition is that flattening
#: performed by the response rather than by the record.
_REFUSAL_STATUS: Final[Mapping[RefusalCondition, tuple[int, str]]] = {
    RefusalCondition.HOST_NOT_BOUND: (421, "Misdirected Request"),
    RefusalCondition.ORIGIN_NOT_OWN: (403, "Forbidden"),
    RefusalCondition.NO_LIVE_SESSION: (401, "Unauthorized"),
    RefusalCondition.COOKIE_HALF_MISMATCH: (409, "Conflict"),
    # Recorded but never written back: ADR-0182 §4 has the browser told only that
    # the exchange failed, so :meth:`Gateway._refuse` answers this one as
    # ``BOOTSTRAP_EXCHANGE_FAILED``. The entry stays so the table is total over the
    # enumeration — a condition missing from it would be a ``KeyError`` in the one
    # place a gateway must not raise — and it is what a future refusal on the
    # ceiling at some other door would answer with.
    RefusalCondition.SESSION_CEILING: (429, "Too Many Requests"),
    RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED: (400, "Bad Request"),
    # ADR-0174 §4. `403` rather than `401`, and the distinction is the one the two
    # status codes exist for: the caller is authenticated — the gateway's own agent
    # attested which device this is — and that device is not one the owner listed.
    # A `401` would invite a browser to present something, and there is nothing it
    # could present that would change the answer.
    RefusalCondition.DEVICE_NOT_LISTED: (403, "Forbidden"),
}

#: How many parts a peer address must have before its host and port can be read.
#: An IPv6 ``peername`` is a four-tuple, so this is a floor rather than a length.
_ADDRESS_PARTS: Final = 2

#: The bundle's paths and media types (ADR-0168 §10). The gateway "serves only
#: assets that shipped in the installed distribution", so the map is fixed here
#: and the files are package data — nothing is fetched, listed or resolved from a
#: path a request supplies.
_BUNDLE: Final[Mapping[str, tuple[str, str]]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}


def _authority(host: str, port: int) -> str:
    """One ``host:port`` authority, in the form a browser writes it in a `Host`.

    Bracketed for IPv6, because that is what a browser sends and what ADR-0174 §6
    compares literally — an unbracketed ``fd7a::1:8422`` is not an authority any
    browser produces, and a set holding one would refuse every real request.

    Args:
        host: The address or name.
        port: The port.

    Returns:
        The authority.
    """
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _hold_what_the_peer_sent_for_tls(writer: asyncio.StreamWriter) -> None:
    """Stop reading this connection until :meth:`Gateway._handshake` takes it over.

    **Called before the first ``await`` on a remote connection, and that is the
    whole of the requirement.** ``asyncio.start_server`` adds the socket's reader
    and schedules the connection's task in one pass of the loop, in that order, so a
    pause taken before the coroutine yields runs before the socket is ever polled —
    and every byte the peer sent is still in the kernel, unread, for TLS.

    ``loop.start_tls`` pauses and resumes reading itself, so it inherits a paused
    transport and hands it back reading under the TLS protocol; pausing twice is a
    no-op. A connection refused before the handshake is closed rather than resumed,
    which is what a refusal at ADR-0174 §3 or ADR-0168 §8 already does.

    Args:
        writer: The accepted connection.
    """
    transport = writer.transport
    if isinstance(transport, asyncio.ReadTransport):  # pragma: no branch — always is
        transport.pause_reading()


def _cookie(half: str, *, remote: bool) -> str:
    """The `Set-Cookie` value for one minted session (ADR-0168 §6, ADR-0202 §7).

    One function rather than an interpolation at the call site, so the attribute set
    is one thing to read against the two ADRs that decide it — and so a second mint
    path could never grow a different set.

    Args:
        half: The cookie half the session table minted.
        remote: Whether the exchange arrived on the remote browser listener, which is
            the only thing that decides `Secure`.

    Returns:
        The header value, with every attribute ADR-0168 §6 requires and, on the
        remote listener alone, the one ADR-0202 §7 adds.
    """
    attributes = "HttpOnly; SameSite=Strict; Path=/"
    if remote:
        attributes = f"{attributes}; Secure"
    return f"{_COOKIE_NAME}={half}; {attributes}"


def _refuse_an_address_this_machine_does_not_hold(address: str) -> None:
    """Check 3 of ADR-0174 §2: the address is one this machine actually holds.

    **The kernel is the only thing that knows**, and the way to ask it is to bind.
    So this binds a throwaway socket on an ephemeral port at that address and closes
    it: a success says the address is assigned to a local interface, and
    ``EADDRNOTAVAIL`` says it is not. Asked on a port of the kernel's choosing rather
    than on ``gateway_port``, so it cannot collide with the listener that follows and
    cannot turn "that port is in use" into an answer about the address.

    **Why the real bind is not left to answer it.** ``asyncio.start_server`` iterates
    the addresses ``getaddrinfo`` returns and *drops* one that answers
    ``EADDRNOTAVAIL`` — "assume the family is not enabled (bpo-30945)" — then raises
    a plain ``OSError`` with **no errno** once none is left. So the one condition
    ADR-0174 §2 has a rule about is exactly the one that arrives from there
    unidentifiable, and a gateway reading the errno would have reported it as an
    accident. Asking directly is what makes this a check rather than an
    interpretation.

    **What it is not.** It is not a claim that the address is the overlay's — that is
    check 2's, and neither check stands in for the other. Together they are §2: an
    overlay assigns each node its own address, so an address that is both on the
    overlay and assigned locally is this machine's overlay address. It is also not a
    reservation: the address could be removed between here and the bind, and then the
    bind fails with the raw errno, which is the stay-down fault
    ``service/remote.py`` leaves raw for the same reason.

    Args:
        address: The address the remote browser listener is about to bind.

    Raises:
        ConfigurationError: If the address is not one this machine holds.
        OSError: If the probe fails for any other reason, which is a fault about the
            machine rather than a statement about the configured address.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((address, 0))
    except OSError as exc:
        if exc.errno != errno.EADDRNOTAVAIL:
            raise
        msg = (
            f"the remote browser listener is configured to bind {address}, which is not "
            f"an address of this machine ({exc}). ADR-0174 §2 binds an address that "
            f"exists on the overlay *and* is this machine's own — the overlay agent "
            f"answers the first and only the kernel answers the second; set "
            f"ASSISTANT_GATEWAY_REMOTE_ADDRESS to the address your agent reports for "
            f"this machine, not for the device you want to browse from"
        )
        raise ConfigurationError(msg) from exc


def _check_the_remote_listener_can_serve(settings: Settings, *, agent: OverlayAgent | None) -> None:
    """Refuse a remote browser listener that could never admit anything (ADR-0174 §8).

    Two conditions, both stay-down and both cheaper here than at the door:

    - **An identity over the byte bound.** ``Settings`` refuses a blank element and
      one with no UTF-8 form; this is §8's other half, "reading the constant the wire
      seam owns" rather than restating it in ``core`` — which golden rule 2 forbids,
      because ``MAX_OVERLAY_IDENTITY_BYTES`` lives in ``ai_assistant.wire.overlay``
      and ``core`` may import nothing. An identity failing the invariant is one the
      agent can never report, so the owner's named device would be refused at every
      exchange with nothing saying why.
    - **No agent.** §3 makes the agent the sole source of a browsing device's
      identity and refuses every connection whose identity cannot be obtained, so a
      gateway configured on with no agent binds a door that answers nobody.

    Args:
        settings: The loaded configuration.
        agent: The overlay agent, or ``None``.

    Raises:
        ConfigurationError: On either condition.
    """
    if settings.gateway_remote_address is None:
        return
    if agent is None:
        msg = (
            "gateway_remote_address is set, so the gateway serves browsers on the "
            "overlay and must take each one's device identity from the overlay agent "
            "on this machine (ADR-0174 §3) — but no agent was supplied. Compose the "
            "gateway with one, or unset ASSISTANT_GATEWAY_REMOTE_ADDRESS"
        )
        raise ConfigurationError(msg)
    for position, identity in enumerate(settings.gateway_remote_browser_devices):
        size = len(identity.encode("utf-8"))
        if size > MAX_OVERLAY_IDENTITY_BYTES:
            msg = (
                f"gateway_remote_browser_devices[{position}] encodes to {size} bytes, over "
                f"the {MAX_OVERLAY_IDENTITY_BYTES} an overlay identity may occupy — no "
                f"overlay this system accepts produces one, so it could never equal an "
                f"identity the agent reports and the device it names could never exchange "
                f"a bootstrap value (ADR-0174 §8). Use the stable identity your overlay "
                f"agent reports for that device"
            )
            raise ConfigurationError(msg)


def packaged_bundle() -> Mapping[str, tuple[bytes, str]]:
    """Read the front end out of the installed distribution (ADR-0168 §10).

    Read once, at start, rather than per request: the bundle ships with the
    package and cannot change under a running process, and a gateway that read a
    file per request would have a filesystem in its request path for no gain.

    Returns:
        Each served path's bytes and media type.
    """
    root = resources.files(__package__) / "assets"
    return {
        path: ((root / name).read_bytes(), media_type)
        for path, (name, media_type) in _BUNDLE.items()
    }


@dataclass(eq=False)
class _Connection:
    """One browser connection: which door it arrived at, and who holds the far end.

    Compared by identity — ``eq=False`` — because the population §8 bounds is a
    set of *connections* and two of them in the same state are not one connection.
    ADR-0174 §8 makes that population the gateway's rather than each listener's, so
    both listeners put their connections in the same set and the ceilings are
    totals: "a connection on either listener counts against the same figure".

    "A browser connection is **admitted** from the moment it carries a request the
    gateway admitted under §4, and **unadmitted** before that… no rule of this ADR
    returns an admitted connection to the unadmitted population" (ADR-0168 §8) —
    read with ADR-0174 §4 on the remote listener, where admitting a request takes
    two facts rather than one.

    Attributes:
        admitted: Whether it has carried an admitted request.
        remote: Whether it arrived on the remote browser listener. The whole of what
            selects ADR-0174's rules, and ``False`` reproduces ADR-0168's gateway
            exactly.
        device: The overlay identity ADR-0174 §3 obtained for it, attested by the
            gateway's own agent and taken from nothing the peer asserts. ``None`` on
            a loopback connection, which has no such fact — and a remote connection
            never reaches a request with it still ``None``, because §3 refuses and
            closes one whose identity could not be obtained.
    """

    admitted: bool = False
    remote: bool = False
    device: str | None = None


@dataclass(frozen=True)
class MintAct:
    """How the owner mints a further bootstrap value at a running gateway.

    "The mint act is the delivery of ``SIGUSR1`` to the gateway process, and it is
    the whole of the act" (ADR-0182 §1), and every disclosure of a gateway that can
    perform it "names the act and the gateway's own process id, so that the act is
    discoverable from the disclosure rather than from a document".

    **A gateway that cannot perform the act discloses no instance of this**, which
    is why the field on :class:`Disclosure` is nullable: §1 forbids a gateway that
    could not make ``SIGUSR1`` safe from naming the act at all, because "an
    advertisement the gateway cannot make safe is an instruction to kill it".

    Attributes:
        signal: The signal's name, as an owner types it.
        pid: The gateway's own process id — a Tier 2 fact about itself, and not a
            record, so ADR-0168 §6's enumeration is not engaged.
    """

    signal: str
    pid: int


@dataclass(frozen=True)
class Disclosure:
    """One bootstrap value and everything the owner is handed beside it.

    ADR-0168 §5 fixes the channel — "once, on the gateway's own standard output,
    and nowhere else" — and ADR-0182 adds two things to what travels with the
    value: §1's act and process id, and §4's live session count and ceiling
    "**as information and not a refusal**, so that an owner minting into a full
    table learns it where they are standing".

    **The count is advisory and nothing turns on it**, which §4 says is what makes
    it safe to state: "it is a fact about the instant it was written and no act of
    the gateway turns on it". The mint act in particular "makes **no** decision
    that depends on the live session count".

    Attributes:
        value: The value to disclose, exactly once.
        origins: Every origin a browser can reach this gateway at.
        live_sessions: How many sessions were live when this was written.
        max_sessions: ``gateway_max_sessions``, the ceiling the *exchange* enforces.
        mint_act: How to mint another, or ``None`` on a gateway that could not
            install the disposition (ADR-0182 §1).
    """

    value: str
    origins: tuple[str, ...]
    live_sessions: int
    max_sessions: int
    mint_act: MintAct | None


class Note(StrEnum):
    """What a gateway tells its owner about the mint act, in words the CLI writes.

    Three conditions ADR-0182 §1 obliges a gateway to report, carried as an
    enumeration rather than as prose because golden rule 3 keeps the rendering in
    the interface: the gateway decides *which* condition holds and the adapter
    decides how it reads, exactly as ADR-0042 §7 has an error cross the boundary
    rendered.
    """

    MINT_ACT_IGNORED = "mint-act-ignored"
    """The disposition could not be installed, so the act is unavailable — and
    ``SIGUSR1`` has been set to **ignored**, "because the signal's default action is
    to terminate, and a process holding live sessions may not be left killable by
    the one signal its own disclosure names"."""

    MINT_ACT_UNSAFE = "mint-act-unsafe"
    """Neither could be done, so the gateway "reports at start that the mint act is
    unavailable **and that the signal is unsafe to send**, and names the act in no
    disclosure"."""

    MINT_NOT_DISCLOSED = "mint-not-disclosed"
    """A later mint could not be disclosed, so it "is **not** minted": the candidate
    was destroyed, any previously outstanding value is "exactly as it was — still
    outstanding, still on its own clock", and the gateway keeps serving."""


@dataclass(eq=False)
class _OpenStream:
    """One stream a session admitted, and how the gateway ends it (ADR-0175 §7).

    "A stream ends no later than the session that admitted it, and the gateway ends
    every stream a session held at the moment that session ends." A held-open stream
    sends no further request, so the gateway would otherwise learn of the session's
    death only from a request that never comes.

    Ending it is closing the connection the response body is being written on, which
    *is* the stream (§1). A delivery stream is abandoned first, so its writer stops
    waiting on a browser rather than on a socket that is about to go.

    Compared by identity, because two streams in the same state are not one stream.
    """

    writer: asyncio.StreamWriter
    delivery: DeliveryStream | None = None
    driver: asyncio.Task[Any] | None = None

    def end(self) -> None:
        """End this stream now, tolerating a connection that is already gone.

        **Closing the writer is not enough on its own, and the case that shows it is
        an answer stream waiting on its first value.** ``converse_streaming`` may be
        composing when the session expires; a closed socket does not interrupt an
        ``async for``, so the iteration — and with it the hub connection ADR-0175 §7
        counts against ``gateway_max_hub_connections`` — would outlive the session by
        however long the turn took. Cancelling the task that drives the stream is what
        makes §7's "the gateway ends every stream a session held at the moment that
        session ends" true of the resources as well as of the bytes: the cancellation
        unwinds through ``closing_stream``, which closes the engine's iterator, and
        through the body's own ``finally``, which gives the slot back.

        The driver is the connection's handler task, so cancelling it ends the
        connection too — which is right, because the stream *is* the response body on
        it. A task never cancels itself: a request that finds its own session expired
        is being served on a connection that has no stream open, so the guard is
        belt-and-braces rather than load-bearing, and it is cheaper than reasoning
        about it again later.
        """
        if self.delivery is not None:
            self.delivery.abandon()
        if self.driver is not None and self.driver is not asyncio.current_task():
            self.driver.cancel()
        with contextlib.suppress(ConnectionError, OSError):
            self.writer.close()


@dataclass(frozen=True)
class _Streamed:
    """A response whose body the connection handler writes itself (ADR-0175 §1).

    The second thing :meth:`Gateway._respond` can decide. Everything decidable
    before the engine is reached — an unadmitted request, a malformed body, a
    ceiling — is still an ordinary :class:`.http.Response` carrying its own status;
    a stream's head is written only once the gateway has committed to answering on
    one, and every fault after that travels as the stream's terminal value.

    **Deciding to stream takes resources, and one place gives them back.** Both
    shapes take a hub connection before this is built — the answer stream directly,
    the delivery stream through the poll its first reader opens — and both are
    registered against the session that admitted them. :meth:`Gateway._write_stream`
    owns the whole of that: it registers before the first awaited write and releases
    in a ``finally``, so a peer that went away before the head landed, a session that
    ended mid-stream and an ordinary completion all take the same path out. Splitting
    it between the decision and the body is what round 2 of this PR's review found a
    window in.

    Attributes:
        handle: The session that admitted the request. ADR-0175 §7 ends every stream
            a session held at the moment that session ends, and a held-open stream
            sends no further request — so the association is what makes that clause
            reachable at all.
        head: The head to write before the first piece.
        body: Writes the pieces.
        delivery: The delivery stream this answers on, or ``None`` for an answer
            stream. Ending a delivery stream abandons it as well as closing the
            connection, so its writer stops waiting on a browser rather than on a
            socket that is about to go.
        release: Gives back what deciding to stream took — the hub slot, or the
            fan-out's registration and the poll that goes with the last reader.
            Called exactly once, on every exit.
    """

    handle: SessionHandle
    head: StreamHead
    body: Callable[[asyncio.StreamWriter], Awaitable[None]]
    release: Callable[[], None]
    delivery: DeliveryStream | None = None


class Gateway:
    """Serves one device's browsers, and reaches the hub as any spoke does."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam: config, hub, clock, timer, bundle, agent, entropy
        self,
        *,
        settings: Settings,
        engine: AssistantEngine,
        now: Callable[[], datetime],
        defer: Defer,
        bundle: Mapping[str, tuple[bytes, str]],
        agent: OverlayAgent | None = None,
        mint_value: Callable[[], str] = mint_value,
    ) -> None:
        """Build a gateway that has minted nothing and bound nothing.

        **This is "start" for ADR-0174 §8's second refusal**, and it is before the
        two things §8 names: nothing has been bound and no bootstrap value has been
        minted, let alone disclosed. §8 splits the identity invariant across two
        places "because golden rule 2 puts the bound outside ``core``" — ``Settings``
        refuses a blank element and one with no UTF-8 form, both decidable without
        importing anything, and the gateway refuses an element over
        ``MAX_OVERLAY_IDENTITY_BYTES`` by reading the constant the wire seam owns.
        Refusing in the constructor rather than in :func:`run_gateway` is what makes
        it unskippable: every composition of a gateway runs it, not just the one this
        module ships.

        **ADR-0202 §8's refusals are here for the same reason, and its ordering
        requires it.** §8 has the gateway refuse "at start, before it binds or
        discloses a bootstrap value" everything about the certificate and key that
        only the machine can answer, and :func:`.run_gateway` mints and discloses
        between this constructor and the bind — so the pair is read here, once, and
        the listener is built from what this read produced (:mod:`.tls`).

        Args:
            settings: The loaded configuration, read for ADR-0168 §8's ten figures,
                ADR-0175 §8's eleventh, ADR-0174 §8's three fields, ADR-0202 §8's two
                paths, and nothing else.
            engine: The hub, as the promoted ``AssistantEngine`` (ADR-0168 §1).
            now: The clock, injected. ADR-0202 §8's validity check is about "the
                moment of binding", so it is a reading of this one.
            defer: How a session's death and a record interval's close are
                scheduled, injected for the same reason.
            bundle: The front end's assets, already read.
            agent: The overlay agent on **this** machine, which ADR-0174 §3 makes the
                sole source of a browsing device's identity. Required when
                ``gateway_remote_address`` is set and unused when it is not —
                :func:`run_gateway` builds the real one, and a test supplies a fake.
            mint_value: The entropy source for the bootstrap value and both
                session halves.

        Raises:
            ConfigurationError: If the remote browser listener is configured on with
                no agent to satisfy ADR-0174 §3, if a listed device's identity is
                over the byte bound the wire seam holds every overlay identity to, or
                if its TLS material fails any condition ADR-0202 §§2, 3, 6 and 8 put
                at start. Each is a stay-down deployment fault (ADR-0083 §5): a
                gateway that bound the door anyway would refuse every connection on
                it, refuse the owner's own named device at every exchange with
                nothing saying why, or serve a certificate no browser accepts.
        """
        _check_the_remote_listener_can_serve(settings, agent=agent)
        tls = remote_tls(settings, now=now)
        self._settings = settings
        self._engine = engine
        self._now = now
        self._defer = defer
        self._bundle = bundle
        self._mint_value = mint_value
        self._sessions = SessionTable(
            max_sessions=settings.gateway_max_sessions,
            ttl=settings.gateway_session_ttl,
            idle_timeout=settings.gateway_session_idle_timeout,
            now=now,
            defer=defer,
            mint_value=mint_value,
            on_ended=self._session_ended,
        )
        self._records = AdmissionRecorder(
            interval=settings.gateway_record_interval, now=now, defer=defer
        )
        self._connections: set[_Connection] = set()
        self._hub_in_flight = 0
        self._open_streams: dict[SessionHandle, set[_OpenStream]] = {}
        self._deliveries = DeliveryFanOut(
            engine=engine,
            budget=settings.gateway_notification_budget,
            acquire=self._take_hub_slot,
            release=self._give_hub_slot,
            defer=defer,
        )
        self._bootstrap = BootstrapMint(
            ttl=settings.gateway_bootstrap_ttl, defer=defer, mint_value=mint_value
        )
        self._authority = _authority(_LOOPBACK, settings.gateway_port)
        self._origin = f"http://{self._authority}"
        self._agent = agent
        self._remote_address = settings.gateway_remote_address
        #: The certificate, the key and the two facts ADR-0202 §5 discloses about
        #: them, read once at start and never re-read: "no clause of this ADR obliges
        #: a reload, and no lane may present the gateway as renewing, watching or
        #: reloading anything" (§4). ``None`` exactly where no remote listener is
        #: configured, in which case nothing was read and no path was touched.
        self._remote_tls: RemoteTls | None = tls
        #: Whether this gateway's own connection to its hub is ADR-0084 §1's loopback
        #: socket, which is the only transport ADR-0151 §13 lets the five connection
        #: operations cross and which ADR-0177 §3's first clause leaves "whole and
        #: unamended". Read from the one setting that already decides it —
        #: ``wire.address.destination`` returns a ``LoopbackDestination`` exactly when
        #: ``remote_hub_address`` is unset, and ADR-0124 §1 has that be "the switch,
        #: … because two settings that can disagree about which transport is in use is
        #: one more state than a deployment has". No field of this gateway's own is
        #: added for it, and nothing about the engine object is inspected: golden rule
        #: 1 has this adapter depend on the ``AssistantEngine`` contract rather than on
        #: which implementation was injected, and the contract says nothing about a
        #: transport (ADR-0098 §5).
        self._hub_carries_connections = settings.remote_hub_address is None
        #: Read as a set, "compared for equality against the identity §3 obtained. A
        #: repeated element changes nothing and is not refused; order carries no
        #: meaning; and no element is matched by prefix, suffix, pattern or any form
        #: of partial comparison" (ADR-0174 §8).
        self._listed_devices = frozenset(settings.gateway_remote_browser_devices)
        #: What a `Host` may name on the remote listener (ADR-0174 §6): "the overlay
        #: address it bound, with the port it bound; or a name the owner configured
        #: in ``gateway_remote_host_names``, with that port". Compared literally, and
        #: nothing here is ever resolved or dialled.
        self._remote_authorities = frozenset(
            _authority(name, settings.gateway_port)
            for name in (self._remote_address, *settings.gateway_remote_host_names)
            if name is not None
        )
        #: The shapes answered whole, by path. A table rather than a chain of
        #: comparisons, so ADR-0177 §1's enumeration is one thing to read against the
        #: ADR — and so a path :data:`_ASSISTANT_PATHS` admits but nothing here
        #: serves is a ``KeyError`` in this process rather than a silent fallthrough
        #: onto whichever handler happened to be last.
        #:
        #: **One entry per operation, and never one entry performing two.** ADR-0168
        #: §1 forbids the gateway composing behaviour the promoted surface does not
        #: offer, and ADR-0177 §7 names the one place a lane would be tempted to: an
        #: amendment is ``revoke`` then ``grant``, composed in the front end as two
        #: browser requests reaching the two entries below, and there is deliberately
        #: no third entry that performs both.
        self._unary: Mapping[str, Callable[[Request], Awaitable[Response]]] = {
            _ASK_PATH: self._ask,
            _ASK_SPOKEN_PATH: self._ask_spoken,
            _CONVERSATIONS_PATH: self._recent_conversations,
            _CONVERSATION_PATH: self._conversation,
            _FORGET_CONVERSATION_PATH: self._forget_conversation,
            _SOURCES_PATH: self._grantable_sources,
            _GRANT_PATH: self._grant,
            _REVOKE_PATH: self._revoke,
            _RECENT_GRANTS_PATH: self._recent_grants,
            _STANDING_PATH: self._standing_grants,
            _BELIEFS_PATH: self._beliefs,
            _BELIEF_PATH: self._belief,
            _FORGET_BELIEF_PATH: self._forget_belief,
            _QUESTIONS_PATH: self._questions,
            _INTERRUPTED_PATH: self._interrupted_questions,
            _ANSWER_PATH: self._answer,
            _FORGET_QUESTION_PATH: self._forget_question,
            _OBSERVE_PATH: self._observe,
            _CONFIRMATIONS_PATH: self._pending_confirmations,
            _RESUME_PATH: self._resume,
            _NOTIFICATIONS_PATH: self._notifications,
            _DISMISS_NOTIFICATION_PATH: self._dismiss_notification,
            _FORGET_NOTIFICATION_PATH: self._forget_notification,
            _NOTIFICATION_PREFERENCES_PATH: self._notification_preferences,
            _SET_NOTIFICATION_PREFERENCES_PATH: self._set_notification_preferences,
            _CONNECT_PATH: self._connect_account,
            _REPROVISION_PATH: self._reprovision_account,
            _DISCONNECT_PATH: self._disconnect_account,
            _CONNECTIONS_PATH: self._connected_accounts,
            _CONNECTION_ACTS_PATH: self._recent_connection_acts,
        }

    @property
    def origin(self) -> str:
        """The loopback origin this gateway serves, and the one it admits there."""
        return self._origin

    @property
    def origins(self) -> tuple[str, ...]:
        """Every origin a browser can reach this gateway at, loopback first.

        More than one only where ADR-0174's remote browser listener is configured on,
        and then one per authority §6 of that ADR admits — the overlay address it
        binds, and each name the owner configured. The owner needs all of them: the
        exit test milestone 14 names is a phone, and the address to type into it is
        not the loopback one this gateway has always printed.

        **The two listeners disclose two different schemes** (ADR-0202 §2). The
        remote authorities are ``https://`` because that listener "serves HTTPS and
        nothing else"; the loopback one is untouched and still ``http://``. An origin
        is scheme, host and port, so this is also what makes an owner upgrading a
        deployment exchange a fresh bootstrap value rather than silently carrying an
        old session across the change — the migration ADR-0202's Consequences names.

        **A remote authority the certificate does not cover is not filtered out
        here**, because there is none: ADR-0202 §6 refuses to start unless every
        element of ``gateway_remote_host_names`` is a name the certificate presents.
        The bound address stays on this list under ADR-0174 §6 unchanged, and §6 of
        ADR-0202 records that reaching the gateway by it "stops working in practice"
        as a consequence rather than a rule — the browser refuses the name mismatch
        before a request exists, and the gateway is told nothing about it.

        Returns:
            The origins, in the order a disclosure should list them.
        """
        remote = sorted(self._remote_authorities)
        return (self._origin, *(f"{_REMOTE_SCHEME}://{one}" for one in remote))

    def mint_bootstrap(
        self, disclose: Callable[[Disclosure], None], *, act: MintAct | None
    ) -> None:
        """Mint a candidate, disclose it, and promote it — in that order (ADR-0182 §1).

        "The mint act is **ordered**, and the order is part of the rule: the gateway
        mints a candidate, discloses it, and only on a **successful** disclosure does
        that candidate become the outstanding value of §2 and the previously
        outstanding value cease."

        **The order is here rather than at the two call sites**, because getting it
        wrong is the failure §1 was amended on its third round to remove: replacing
        before disclosing "left the owner with **no** usable value after a failure
        they did not cause", and replacing after disclosing "left the old value
        live". One method that cannot be called out of order is what stops the start
        path and the signal path diverging on it.

        **Nothing here reads the live session count as an input.** §4: "The mint act
        makes **no** decision that depends on the live session count. It is not
        refused at the ceiling, it mints and discloses exactly as §1 requires
        whatever the count is." The count below is written *into* the disclosure and
        is not consulted.

        Args:
            disclose: How the value reaches the owner. Raising from it is what makes
                the candidate one the gateway "cannot disclose".
            act: The mint act to name, or ``None`` where this gateway could not
                install the disposition — in which case §1 requires the act named in
                no disclosure.

        Raises:
            Exception: Whatever ``disclose`` raised, after the candidate has been
                destroyed. The caller decides what that means: at start it is
                ADR-0168 §5's "does not start, and reports why"; at a later mint it
                is ADR-0182 §1's report-and-keep-serving.
        """
        candidate = self._bootstrap.mint()
        disclosure = Disclosure(
            value=candidate.value,
            origins=self.origins,
            live_sessions=len(self._sessions),
            max_sessions=self._settings.gateway_max_sessions,
            mint_act=act,
        )
        try:
            disclose(disclosure)
        except BaseException:
            self._bootstrap.discard(candidate)
            raise
        self._bootstrap.promote(candidate)

    async def start(self) -> asyncio.Server:
        """Bind the loopback listener (ADR-0168 §2, §9).

        The listener is bound **whether or not the hub is reachable**, and nothing
        here probes it: "a gateway that refused to start without a hub would
        present the two failures identically", so serving regardless is what turns
        a stopped hub into a message a browser can read (ADR-0168 §9).

        Separate from :meth:`serve` so that the bind and the serving loop can be
        driven apart — which is what a test needs to send a request and read the
        answer rather than wait for a signal.

        Returns:
            The bound server, whose lifetime the caller owns.
        """
        server = await asyncio.start_server(
            partial(self._handle, remote=False), host=_LOOPBACK, port=self._settings.gateway_port
        )
        _log.info("gateway.listening", origin=self._origin, served_paths=sorted(self._bundle))
        return server

    async def start_remote(self) -> asyncio.Server | None:
        """Bind the remote browser listener, if the owner configured one (ADR-0174 §2).

        > The remote browser listener is **off unless it is configured on**. A
        > gateway with no remote-browser-listener configuration binds only ADR-0168
        > §2's loopback listener.

        **§2's bind rule is decided by three checks in three places, and neither of
        the two here claims the other's ground.** §2 admits only "an address that
        exists on that overlay" and forbids a wildcard, a physical interface, a
        loopback address and a public one.

        1. ``Settings`` refuses what ``ipaddress`` can decide — the wildcard, the
           name, the loopback, the multicast, the link-local and the globally
           routable address (ADR-0174 §8).
        2. :meth:`_confirm_the_address_is_on_the_overlay` asks the agent on this
           machine whether the overlay places a node at the address, which is the
           only way to tell an overlay address from an ``eth0`` one — nothing in
           ``192.168.1.5`` says which it is, and no conforming overlay agent
           (ADR-0124 §2) reports a node at an address that is not on the overlay.
        3. :func:`_refuse_an_address_this_machine_does_not_hold` requires the
           address to be assigned to this machine, which only the kernel knows and
           only a bind can ask.

        **The conjunction is what satisfies §2, and each check on its own does
        not** — the distinction adversarial review found on the first round of this
        PR, correctly. The agent's answer says *the overlay places a node at this
        address*; it does not say *and that node is us*, because the seam a client
        holds asks one question ("who is at this address") where the hub's own asks
        two (:class:`ai_assistant.wire.overlay.OverlayAgent`, which this lane
        consumes rather than widens). So check 3 supplies the missing half
        mechanically: an overlay assigns each node its own address, so an address
        that is both on the overlay and assigned locally is this machine's overlay
        address. Check 2 alone would admit another node's address, and check 3 alone
        would admit ``eth0``'s.

        **It is also the earliest moment the agent's absence can be reported.** Every
        connection on this listener needs §3's identity, and a connection whose
        identity cannot be obtained is refused and closed — so a gateway that bound
        this door with no reachable agent would present an open port that refuses
        everything, which is exactly the pair of failures ADR-0168 §9 refuses to
        present identically.

        **This listener serves HTTPS and the socket is bound without a TLS context
        all the same** (ADR-0202 §2, §5). The handshake is performed per connection
        in :meth:`_handshake`, one step *after* ADR-0174 §3's identity check, because
        §5 of ADR-0202 orders it there: "ADR-0174 §3's overlay-identity check runs on
        the connection **before** the TLS handshake, so a connection whose overlay
        identity cannot be obtained is closed without the certificate being
        presented." Handing the context to ``start_server`` would put the handshake
        before the accept callback runs and make that ordering unreachable. Nothing
        is served in plain HTTP by the gap: :meth:`_handle` reaches
        :meth:`_serve_connection` on this listener only through both checks.

        **What binds is what the constructor already read** (§4). The pair is not
        re-read here and is not re-read while the process runs, so a renewal takes
        effect at the next start and nothing watches a file.

        **Its validity is asked about again here, and four rounds of adversarial
        review on this PR are why the arrangement is written down rather than
        assumed.** §8's one sentence says two things that cannot both be literal once
        the bind is later than the start: the gateway "refuses at start, **before it
        binds or discloses a bootstrap value**", and what it refuses on is "that the
        moment of binding lies inside the certificate's validity period at both
        bounds". Rounds 2, 4 and 5 read the second half as obliging a check
        immediately before the bind; round 3 found what implementing that costs —
        :func:`run_gateway` mints and discloses between the constructor and here
        (ADR-0168 §5, deliberately), so a refusal here is a refusal *after* a
        bootstrap value has been handed to the owner.

        **Both, which is what satisfies both halves rather than choosing one.** The
        constructor's check is where every condition decidable at start is refused,
        so ADR-0168 §5's "does not start, and reports why" still lands before the
        owner is handed anything for every fault the configuration actually has. This
        one covers the single condition the constructor cannot decide: a clock that
        moved. It fires only when the certificate expires *inside* that interval, and
        what it costs then is a value the owner has just read becoming dead — which
        ADR-0182 §2 already makes true of a gateway that fails to start for any
        reason, and which the alternative trades for a listener no browser can
        complete a handshake with. §8's own imprecision is filed as #1684.

        **It reads nothing, which is what keeps §4 whole.** The bounds are the ones
        :mod:`.tls` parsed at start; no file is opened, and a renewal that landed in
        the interval is still invisible until the next start. Nor does it become a
        continuous check: once bound, this gateway serves the certificate it has for
        as long as it runs, expiry included — §4 says so, and §5's disclosure is what
        makes that a date the owner already knows.

        Returns:
            The bound server, or ``None`` where the listener is off.

        Raises:
            ConfigurationError: If the overlay agent places no node at the configured
                address or cannot be asked, if the address is not one this machine
                holds, or if the certificate's validity has stopped covering this
                moment since it was read. Each is a stay-down deployment fault
                (ADR-0083 §5): restarting unchanged never succeeds, and what has to
                change is the configuration, the overlay, or the certificate.
            OSError: If the bind fails for any other reason. Left to propagate for
                the reason :mod:`ai_assistant.service.remote` leaves it — "the raw
                errno distinguishes a stay-down fault from a transient one" — and an
                address in use is exactly such a case.
        """
        address = self._remote_address
        tls = self._remote_tls
        if address is None or tls is None:
            return None
        await self._confirm_the_address_is_on_the_overlay(address)
        _refuse_an_address_this_machine_does_not_hold(address)
        tls.refuse_outside_its_validity(self._now())
        server = await asyncio.start_server(
            partial(self._handle, remote=True), host=address, port=self._settings.gateway_port
        )
        # ADR-0202 §5's disclosure: "When the remote browser listener binds, the
        # gateway discloses on its own standard output, beside the address it bound:
        # that the listener speaks HTTPS, the name the certificate carries, and the
        # instant the certificate's validity ends." Three Tier 2 facts and nothing of
        # the key — "a name of the gateway's own machine, an instant, and a scheme" —
        # so ADR-0004 §5's rule that logs carry Tier 2 only is satisfied rather than
        # stretched. It is **not** a record under ADR-0168 §6, whose enumeration
        # governs requests, exactly as §5 of that ADR's bootstrap disclosure is not.
        #
        # **The expiry is the whole of the renewal story's mechanism** (§4, §5).
        # Renewal is the owner's act and the gateway watches nothing, and what makes
        # that workable "rather than a trap is that every start tells the owner how
        # long they have".
        #
        # **``origins`` rather than ``authorities``, and the rename is load-bearing.**
        # ``core.logging`` masks every key containing ``auth``, so the address this
        # disclosure has to stand beside was reaching the owner as ``'[REDACTED]'``.
        # That module's own instruction for an over-matched key is to rename it —
        # "that is a local fix, where an exemption is a global one" — and ``origins``
        # is the word the loopback listener's own line and every disclosure already
        # use for the same value.
        _log.info(
            "gateway.remote_listening",
            scheme=_REMOTE_SCHEME,
            origins=[f"{_REMOTE_SCHEME}://{one}" for one in sorted(self._remote_authorities)],
            certificate_names=list(tls.names),
            certificate_expires=tls.not_after.isoformat(),
            listed_devices=len(self._listed_devices),
        )
        return server

    async def _confirm_the_address_is_on_the_overlay(self, address: str) -> None:
        """Check 2: the overlay places a node at the address (ADR-0174 §2).

        This is the half no string can decide, and §2's own words are that "the
        gateway binds an address the agent provides". It says nothing about *which*
        node — see :meth:`start_remote` for why that is check 3's job rather than a
        gap.

        Args:
            address: The address about to be bound.

        Raises:
            ConfigurationError: If the agent places no node there, or will not say.
        """
        agent = self._agent
        if agent is None:  # pragma: no cover — the constructor refuses this pairing
            msg = "the remote browser listener is configured on with no overlay agent"
            raise ConfigurationError(msg)
        try:
            await agent.identify(address, self._settings.gateway_port)
        except OverlayIdentityUnavailableError as exc:
            msg = (
                f"the remote browser listener is configured to bind {address}, and the "
                f"overlay agent on this machine places no node there ({exc}). "
                f"ADR-0174 §2 binds only an address that exists on the overlay and "
                f"forbids an address of a physical interface, so the gateway will not "
                f"bind one it cannot confirm; start the overlay agent and use the address "
                f"it reports for this machine, or unset ASSISTANT_GATEWAY_REMOTE_ADDRESS "
                f"to serve browsers over the loopback listener alone"
            )
            raise ConfigurationError(msg) from exc

    async def serve(self) -> None:
        """Bind every configured listener and serve until cancelled.

        The loopback listener is bound whether or not the remote one is (ADR-0174
        §2), and both are torn down together — with every session ended on the way
        out, whichever listener minted it (ADR-0168 §4).

        **The stack is what makes a failed second bind clean.** A gateway whose
        remote listener will not start must not leave a loopback listener answering
        behind it: the owner asked for a gateway serving two doors, and one serving
        one of them silently is a deployment that does something its configuration
        does not say.
        """
        async with contextlib.AsyncExitStack() as stack:
            # Registered first so it runs *last* — after both sockets are closed —
            # and so it runs at all when the remote bind is what fails.
            stack.callback(self.close)
            bound = [await stack.enter_async_context(await self.start())]
            remote = await self.start_remote()
            if remote is not None:
                bound.append(await stack.enter_async_context(remote))
            await asyncio.gather(*(one.serve_forever() for one in bound))

    def close(self) -> None:
        """End every session and flush the interval in progress (ADR-0168 §4, §6).

        "Every session ends when the gateway process ends", and the interval's
        counters are emitted rather than dropped so a gateway stopping does not
        swallow the refusals it had counted.

        Clearing the table announces every handle, so each session's streams end
        with it (ADR-0175 §7); the fan-out is then shut down for the streams no
        session held — there are none, but a shutdown that depended on that would be
        one more invariant to keep true.

        **The outstanding bootstrap value goes with them**, which is ADR-0182 §2's
        fourth cessation event: "the end of the gateway process (ADR-0168 §4)". A
        process on the way down leaves no timer armed and nothing that could admit
        a browser to a gateway that is no longer there.
        """
        self._sessions.clear()
        self._bootstrap.clear()
        self._deliveries.shutdown()
        self._records.flush()

    def _session_ended(self, handle: SessionHandle) -> None:
        """End every stream one session held, the moment it ends (ADR-0175 §7)."""
        for stream in self._open_streams.pop(handle, set()):
            stream.end()

    def _register(self, handle: SessionHandle, stream: _OpenStream) -> None:
        """Hold a stream against the session that admitted it (ADR-0175 §7)."""
        self._open_streams.setdefault(handle, set()).add(stream)

    def _unregister(self, handle: SessionHandle, stream: _OpenStream) -> None:
        """Drop a stream that has ended, and the session's entry with the last one."""
        held = self._open_streams.get(handle)
        if held is None:
            return
        held.discard(stream)
        if not held:
            del self._open_streams[handle]

    def _take_hub_slot(self) -> bool:
        """Take one of ``gateway_max_hub_connections``, or report the ceiling.

        The delivery poll counts against it exactly as a turn does (ADR-0175 §7,
        ADR-0131 §5): no lane gives delivery its own budget at this door. A gateway
        serving a delivery stream therefore holds one of the eight permanently, so
        the ceiling is one smaller for turns than it reads — no figure moves, and a
        gateway configured with a ceiling of one can serve a delivery stream or a
        turn and not both.
        """
        if self._hub_in_flight >= self._settings.gateway_max_hub_connections:
            return False
        self._hub_in_flight += 1
        return True

    def _give_hub_slot(self) -> None:
        """Give one back."""
        self._hub_in_flight -= 1

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, remote: bool
    ) -> None:
        """Serve one connection under ADR-0168 §8's two ceilings and one deadline.

        **On the remote listener the identity comes first, and before the ceilings it
        does not.** ADR-0174 §3 orders the identity check "before ADR-0168 §7's
        ``Host`` and ``Origin`` checks and before any session is read", which is where
        it sits; §8's ceilings are ahead of it because a ceiling refusal *serves*
        nothing — "it refuses to accept a further connection rather than queueing it"
        — and asking the agent about a connection the gateway is closing unread would
        put a local query on the one path a flood can drive.

        Args:
            reader: The connection's reader.
            writer: The connection's writer.
            remote: Whether this is the remote browser listener's door.
        """
        connection = _Connection(remote=remote)
        if remote:
            # Before the first `await` on this connection, and see `_handshake` for
            # why that is the whole of the requirement: the peer's first bytes are
            # the TLS handshake's and must not be read as though they were a
            # request's while the identity query is out.
            _hold_what_the_peer_sent_for_tls(writer)
        if not self._admit_connection(connection):
            await _close(writer)
            return
        try:
            if remote and not await self._identify(writer, connection):
                return
            if remote and not await self._handshake(writer):
                return
            await self._serve_connection(reader, writer, connection)
        finally:
            self._connections.discard(connection)
            await _close(writer)

    async def _identify(self, writer: asyncio.StreamWriter, connection: _Connection) -> bool:
        """Take the connecting device's overlay identity from this machine's agent.

        > Before serving anything on the remote browser listener — a static asset and
        > the bootstrap exchange included — the gateway obtains the connecting
        > device's overlay identity from the overlay agent running on the gateway's
        > **own** machine, over a local interface. It may not take that identity from
        > anything the peer asserts — a header, a cookie, a query parameter, a request
        > body — and it may not obtain it by a call that leaves the machine. A
        > connection whose overlay identity cannot be obtained is refused and closed.
        > (ADR-0174 §3)

        **Nothing is recorded for a refusal here**, and §3 is explicit about why: a
        connection refused on it "reaches no clause of ADR-0168 §3, §4, §5 or §6 at
        all", so it is outside §6's recorded set exactly as §8's ceilings are. The
        warning below is a fault the owner may need to act on — their agent is not
        answering — and carries no fact about the request, which has not been read.

        **Nothing is written back either.** The peer is refused by the connection
        closing, because the gateway has not yet read a request and so has nothing to
        answer; a status line here would be a response to a request that does not
        exist.

        **A connection waiting on this query is already counted**, which is what
        bounds an agent that has stopped answering: it was admitted to
        :attr:`_connections` a line earlier, so ``gateway_max_browser_connections``
        and ``gateway_max_pending_connections`` hold while the query is out, and the
        query itself is bounded by the agent client's own five-second deadline
        (``wire.overlay``). ``gateway_read_timeout`` does not reach here, because
        there is no read yet to bound.

        Args:
            writer: The accepted connection, for its peer address.
            connection: The connection to record the identity on.

        Returns:
            Whether an identity was obtained.
        """
        agent = self._agent
        peer = writer.get_extra_info("peername")
        if agent is None or not isinstance(peer, tuple) or len(peer) < _ADDRESS_PARTS:
            _log.warning(
                "gateway.remote_peer_unaddressed",
                detail=(
                    "a connection on the remote browser listener carried no peer address "
                    "to ask the overlay agent about, so it is refused (ADR-0174 §3)"
                ),
            )
            return False
        try:
            connection.device = await agent.identify(str(peer[0]), int(peer[1]))
        except OverlayIdentityUnavailableError as exc:
            _log.warning(
                "gateway.remote_identity_unavailable",
                reason=str(exc),
                detail=(
                    "the gateway takes a browsing device's identity from its own overlay "
                    "agent and never from the peer, so a peer it cannot name is refused "
                    "(ADR-0174 §3)"
                ),
            )
            return False
        return True

    async def _handshake(self, writer: asyncio.StreamWriter) -> bool:
        """Terminate TLS on one remote connection, in this process (ADR-0202 §1, §2).

        > ADR-0174 §3's overlay-identity check runs on the connection **before** the
        > TLS handshake, so a connection whose overlay identity cannot be obtained is
        > closed without the certificate being presented. (ADR-0202 §5)

        That ordering is why this is a step of the connection rather than an argument
        to ``asyncio.start_server``: a context handed to the bind is applied before
        the accept callback runs, and §3's check could then only ever be after it.
        §5 states what the ordering buys and what it does not — "the certificate is
        public (§4), so declining to present it to an unidentified peer protects
        nothing of consequence. What it does is keep ADR-0174 §3's 'before serving
        anything' at its strongest reading rather than leaving a lane to decide
        whether a handshake counts as serving."

        **A failed handshake is recorded nowhere** (ADR-0202 §5). "A connection that
        yields no request is not a request refused, and no lane may add a record
        class, a condition or a counter for it under that section" — so this is
        outside ADR-0168 §6's enumeration exactly as §8's ceilings and §3's identity
        refusal are, and nothing is counted. The warning below carries no fact about
        a request, because none has been read.

        **Nothing is written back, and there is nothing that could be.** A peer whose
        handshake failed is not speaking HTTP, so a status line would be bytes it
        cannot parse; and a peer that spoke plain HTTP to this door gets the refusal
        §2 requires — no fallback and no redirect, because "serving a redirect would
        require the plain-HTTP listener it refuses".

        **The peer's first bytes are held for this and not read before it**, which
        :func:`_hold_what_the_peer_sent_for_tls` is the whole of. A browser sends its
        `ClientHello` the moment the connection is accepted, and ADR-0174 §3's
        identity query sits between the accept and this — so without the pause those
        bytes are read off the socket as though they were a request's, and the
        handshake below waits for what has already arrived.

        **The standard library closes that gap today and this does not rely on it.**
        CPython's ``loop.start_tls`` moves a ``StreamReader``'s buffered bytes into
        the TLS layer on the server side, which arrived in a 3.14 patch release
        (``gh-142352``); ``requires-python`` is ``>=3.14``, so an interpreter without
        it is a deployment this project admits. Adversarial review raised the timing
        on the first round of this PR, and the claim as stated is false of the
        interpreter this repository runs and true of one it permits — which is the
        same defect from the deployment's point of view. Pausing costs one call, is
        correct on both, and stops the door depending on a patch number.

        **The handshake is bounded by ``gateway_read_timeout``**, which is ADR-0168
        §8's figure applied to the one thing that can now stall before a request
        exists. §8 states the deadline over "how long a connection may stall", and a
        peer that connects and then sends nothing is exactly that — the case the
        figure already bounds one step later, where the request would be read. Left
        to the standard library's own minute this door would hold a connection
        against ADR-0168 §8's two ceilings for twice as long as the same silence
        costs on the loopback listener.

        Args:
            writer: The accepted connection, upgraded in place.

        Returns:
            Whether TLS was established.
        """
        tls = self._remote_tls
        if tls is None:  # pragma: no cover — a remote listener binds only with one
            return False
        try:
            await writer.start_tls(
                tls.context,
                ssl_handshake_timeout=self._settings.gateway_read_timeout.total_seconds(),
            )
        except OSError as exc:
            # `ssl.SSLError` and `TimeoutError` are both `OSError`, and so is the
            # abort a peer that went away produces. None of them says anything about
            # this gateway's own configuration — the certificate was checked at start
            # — so all three are one condition here: a peer that did not complete a
            # handshake, which is a fact about that peer.
            _log.warning(
                "gateway.remote_handshake_failed",
                reason=str(exc),
                detail=(
                    "a connection on the remote browser listener did not complete a TLS "
                    "handshake, so it is closed unread. This listener serves HTTPS and "
                    "nothing else, with no fallback and no redirect (ADR-0202 §2) — a "
                    "browser sent to it with http:// arrives here"
                ),
            )
            return False
        return True

    def _admit_connection(self, connection: _Connection) -> bool:
        """Take a connection, or refuse it at either ceiling (ADR-0168 §8).

        Refusing is closing without reading: "while that many exist it refuses to
        accept a further connection rather than queueing it". A refusal here
        records nothing — §8's conditions are outside §6's recorded set.

        Args:
            connection: The connection being accepted.

        Returns:
            Whether it was taken.
        """
        pending = sum(1 for held in self._connections if not held.admitted)
        if len(self._connections) >= self._settings.gateway_max_browser_connections:
            return False
        if pending >= self._settings.gateway_max_pending_connections:
            return False
        self._connections.add(connection)
        return True

    async def _serve_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: _Connection,
    ) -> None:
        """Read, answer, and decide whether the connection survives the answer.

        **The deadline bounds idleness, and the clock starts when the gateway has
        finished answering.** ADR-0168 §8 states it as
        ``gateway_read_timeout`` "after the last complete request it carried"; read
        as wall-clock from the request's arrival it would close a connection while
        the gateway was still working on that very request, which is the request
        the deadline exists to make room for. The hub's own clause is a *read*
        deadline — "how long a connection may stall — mid-frame, or waiting for the
        next frame's prefix" (ADR-0084 §3) — and this is that rule at this door.

        **That reading is what ADR-0175 §7 makes a ruling, and this loop is already
        it.** §7 supersedes §8's read-deadline sentence "only as it reaches a
        connection carrying a response the gateway has not finished writing", keying
        the deadline on the completion of the last *response* in place of the last
        complete request — and the deadline here is armed around the read alone,
        which begins once the previous response has been written and drained. So no
        deadline runs while a stream is open, and none can cut one: a reader holding
        only §8 would have ended every stream ADR-0175 §1 defines thirty seconds
        after its request arrived, which is not a stricter gateway but one on which
        the surface cannot exist. Nothing here changes for it; PR #1331 disclosed the
        reading and §7 ratified it.
        """
        timeout = self._settings.gateway_read_timeout.total_seconds()
        while True:
            answer = await self._next(reader, connection, timeout)
            if answer is None:
                return
            # **The header is written from the decision, not beside it.** §8 closes
            # an unadmitted connection "once that request's response is complete"
            # whatever the response was, so a `Connection: keep-alive` on one would
            # be the rule announced and then disobeyed — and the peer would hold a
            # socket the gateway had already given up on.
            closing = answer.head.close if isinstance(answer, _Streamed) else answer.close
            closing = closing or not connection.admitted
            if isinstance(answer, _Streamed):
                if not await self._write_stream(writer, answer, closing=closing):
                    return
            else:
                try:
                    writer.write(render(replace(answer, close=closing), policy=_POLICY))
                    await writer.drain()
                except ConnectionError, OSError:
                    # The same ordinary end, on the writing half. `_write_stream`
                    # answers a peer that went away mid-stream with `False` and the
                    # connection ends; a whole response owes the same answer, and
                    # without it the one response shape that is not a stream still
                    # raises out of `client_connected_cb` (issue #1370).
                    return
            if closing:
                return

    async def _write_stream(
        self, writer: asyncio.StreamWriter, answer: _Streamed, *, closing: bool
    ) -> bool:
        """Write one streamed response whole (ADR-0175 §1).

        The head, then whatever the body writes, then the zero-length chunk that
        ends a chunked body. A body that stops without that marker and without a
        terminal value is what ADR-0175 §2 makes a **transport failure** the front
        end reports as one, so a connection that dies mid-stream is legible at the
        browser rather than looking like a stream that finished with nothing to say.

        Args:
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.

        **The stream is registered before the first awaited write, and that ordering
        is the whole of ADR-0175 §7's reachability.** Nothing between
        :meth:`SessionTable.admit` and this line yields to the event loop — the
        decision is a chain of coroutine calls with no suspension point in it — so a
        stream registered here cannot have missed its own session's death. Registered
        one line later, after the head has drained, it could: a drain that yields
        (a paused transport is enough) lets the session's scheduled death run first,
        find no stream against that handle, and leave the one that follows with
        nothing that will ever end it. That is the window round 2 of this PR's review
        found, and it is closed by ordering rather than by a second check.

        **The release is a ``finally`` for the same reason it is not the body's.** A
        peer that went away before the head landed never reaches ``body`` at all, and
        a session ending mid-stream cancels the task driving it — so the two paths a
        body-owned release would miss are exactly the two that leak: a hub slot held
        for the process's whole life (ADR-0175 §7), and a poll left running for a
        reader that never existed, which is §4's "while and only while at least one
        delivery stream is open" broken by an error path rather than by a rule.

        Args:
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.

        Returns:
            Whether the connection survived. ``False`` where the peer went away,
            which is an ordinary end for a stream and not a fault to report.
        """
        held = _OpenStream(writer=writer, delivery=answer.delivery, driver=asyncio.current_task())
        self._register(answer.handle, held)
        try:
            writer.write(render_stream_head(replace(answer.head, close=closing), policy=_POLICY))
            await writer.drain()
            await answer.body(writer)
            writer.write(render_stream_end())
            await writer.drain()
        except ConnectionError, OSError:
            return False
        finally:
            self._unregister(answer.handle, held)
            answer.release()
        return True

    async def _next(
        self,
        reader: asyncio.StreamReader,
        connection: _Connection,
        timeout: float,  # noqa: ASYNC109 — ADR-0168 §8's own deadline, relayed to the read it bounds
    ) -> Response | _Streamed | None:
        """The answer to the next request, or ``None`` where there is nothing to answer."""
        try:
            request = await asyncio.wait_for(
                read_request(reader, max_bytes=self._settings.gateway_max_request_bytes),
                timeout=timeout,
            )
        except TimeoutError, IncompleteRequestError, ConnectionError, OSError:
            # **A peer that went away is the ordinary end of a connection, not a
            # fault to raise out of it** — the reading `_write_stream` already
            # takes one response shape over, applied to the read that precedes
            # every response. `_handle` is asyncio's `client_connected_cb`, so an
            # `OSError` escaping here is reported as an unhandled exception with a
            # traceback an operator reads as a defect; issue #1370 is that
            # traceback, once per connection the phone reset. There is nothing to
            # answer either way: the deadline, an early end of stream and a reset
            # all leave this door without a request.
            return None
        except RequestTooLargeError:
            return _fault(
                413,
                "Content Too Large",
                "request-too-large",
                limit="gateway_max_request_bytes",
            )
        except MalformedRequestError:
            return _fault(400, "Bad Request", "malformed-request")
        return await self._respond(request, connection)

    async def _respond(self, request: Request, connection: _Connection) -> Response | _Streamed:
        """Decide one request (ADR-0168 §3, §7, §1's biconditional; ADR-0174 §4).

        The order is §7's: "Both checks run before the session is read, and a
        request failing either is refused without the session being consulted at
        all." Classification is not a check — it decides which of §6's four classes
        a record would name — so it happens first and refuses nothing.

        **The device check sits between the assets and everything else, and that
        position is ADR-0174 §4's whole content.** §4 admits a request on the remote
        listener only when the device is listed *and* a live session is presented,
        and separates §3's two pre-session exceptions because "they are not alike in
        what they hand back": the assets are "the bundle this repository ships to
        anyone who installs it", so an overlay member obtains nothing from them they
        could not obtain from the distribution; the bootstrap exchange hands back a
        session, "and a session is the whole of what admits a browser to the device's
        authority". So the assets are answered above this line and every other class
        below it — the exchange included, which is what stops a hostile overlay
        member phishing a value from a mistyped address and spending it from its own
        device.

        The check is ahead of the session read for §3's reason one level in: an
        unlisted device is refused without the gateway consulting a session at all.
        """
        request_class = self._classify(request)
        condition = self._check_door(request, connection)
        if condition is not None:
            return self._refuse(request_class, condition, connection)
        if request_class is RequestClass.ASSET:
            body, media_type = self._bundle[request.path]
            return Response(200, "OK", body=body, content_type=media_type, close=False)
        if connection.remote and connection.device not in self._listed_devices:
            return self._refuse(request_class, RefusalCondition.DEVICE_NOT_LISTED, connection)
        if request_class is RequestClass.BOOTSTRAP:
            return self._exchange(request, connection)
        return await self._session_bound(request, connection, request_class)

    def _classify(self, request: Request) -> RequestClass:
        """Which of ADR-0168 §6's four kinds this request is, decided from it alone.

        **Still four, and ADR-0175 adds no fifth** (§12): "A streamed turn and a
        delivery stream both 'ask the assistant for something' and are
        ``assistant-request``", so the six shapes of :data:`_ASSISTANT_PATHS` share
        one class and §6's enumeration is untouched. A fifth value for a delivery
        stream would supersede an enumeration that says every request is "of exactly
        one class, out of four" while buying no rule the four cannot carry.
        """
        if request.method == "GET" and request.path in self._bundle:
            return RequestClass.ASSET
        if request.method == "POST" and request.path == _SESSION_PATH:
            return RequestClass.BOOTSTRAP
        if (request.method, request.path) in _ASSISTANT_PATHS:
            return RequestClass.ASSISTANT
        return RequestClass.OTHER

    def _check_door(self, request: Request, connection: _Connection) -> RefusalCondition | None:
        """Run ADR-0168 §7's two checks, both decidable from the request alone.

        The `Host` check is what closes DNS rebinding — "a page the owner visits
        from a name the attacker controls can have that name re-resolve to
        `127.0.0.1`" — one step earlier than the session would, "on a fact
        decidable from the request alone rather than on the session logic being
        right". A repeated `Host` or `Origin` reads as absent
        (:meth:`Request.header`) and is refused, because a door that picked the
        first of two would let the peer choose which one it is judged on.

        **The job is unchanged on the remote listener and the set is larger**
        (ADR-0174 §6): the gateway refuses any `Host` that is not "the overlay
        address it bound, with the port it bound; or a name the owner configured in
        ``gateway_remote_host_names``, with that port. The comparison is literal
        against the configured set. **The gateway resolves nothing**". §7's reason
        survives whole — "rebinding is a property of the attacker's own name rather
        than of the target", so an attacker's name is refused on either listener
        because it is not in the owner's set. Admitting a configured name is not
        #912's posture reversed: a `Host` header is a string the browser reports
        about the URL the owner typed, never a destination anything is sent to.

        **The `Origin` is compared against the authority this request's own `Host`
        named**, which is §6's rule and, on the loopback listener, the one origin
        this gateway has always admitted — a `Host` there is admitted only when it
        equals :attr:`_authority`, so the comparison is byte for byte the one
        ADR-0168 §7 made.

        **The scheme comes from the listener rather than from the request**
        (ADR-0202 §2), because an origin is scheme, host and port and the two
        listeners speak two schemes. Reading it from the request is not an option
        that exists: nothing a browser sends says which scheme it used, and a peer
        that could choose would be choosing what it is judged against. So a page on
        the remote listener is `https://` and one on the loopback listener is
        `http://`, each decided by the socket that accepted the connection.

        Args:
            request: The request as parsed.
            connection: The connection it arrived on, which decides which set of
                authorities its `Host` is judged against.

        Returns:
            The condition it fails, or ``None`` where it passes both.
        """
        admitted = self._remote_authorities if connection.remote else frozenset({self._authority})
        scheme = _REMOTE_SCHEME if connection.remote else _LOOPBACK_SCHEME
        host = request.header("host")
        if host is None or host not in admitted:
            return RefusalCondition.HOST_NOT_BOUND
        origin = request.header("origin")
        if origin is not None and origin != f"{scheme}://{host}":
            return RefusalCondition.ORIGIN_NOT_OWN
        return None

    def _exchange(self, request: Request, connection: _Connection) -> Response:
        """The one exchange that mints a session (ADR-0168 §5).

        "A failed exchange discloses only that it failed — never whether the value
        was well-formed, whether one is still outstanding, or whether a session
        already exists", so every way of failing returns the same refusal on the
        same condition.

        **The value is consumed by the exchange rather than by the session it
        produced**, which ADR-0182 §4 reverses from this method's first reading. An
        exchange refused at ``gateway_max_sessions`` has "the value the exchange
        carried… consumed exactly as a spent value is, so a refused exchange is not
        a value the caller may present again" — because "the alternative leaves a
        live ticket outstanding after a failure the caller can drive, which turns
        the ceiling into a way to keep a value alive".

        **The ceiling is enforced here and nowhere else**, on §4's own ground: the
        exchange "is the only act that raises the live session count", so "there is
        exactly one place to check and one place to test, and no ordering between
        minting and exchanging can produce a state the text does not describe".

        **An undisclosed candidate is refused here by construction** (ADR-0182 §2):
        :meth:`~ai_assistant.interfaces.gateway.sessions.BootstrapMint.spend`
        compares against the outstanding value alone, and a candidate no disclosure
        has promoted is not one.

        **On the remote listener this is reached only from a listed device**, and
        :meth:`_respond` is where that is decided — one line earlier, so an unlisted
        device's exchange is "refused without the value being read, compared or
        consumed" (ADR-0174 §4). Reading the payload here at all would break the
        first of those three; consuming it would break the third, leaving the owner
        holding a value an attacker had spent.

        Args:
            request: The exchange as parsed.
            connection: The connection it arrived on, for the identity ADR-0174 §3
                puts on the record a mint or a refusal writes.

        Returns:
            The two session values, or the refusal.
        """
        presented = _string(_payload(request), "bootstrap_value")
        if presented is None or not self._bootstrap.spend(presented):
            return self._refuse(
                RequestClass.BOOTSTRAP, RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED, connection
            )
        values = self._sessions.mint()
        if values is None:
            return self._refuse(
                RequestClass.BOOTSTRAP,
                RefusalCondition.SESSION_CEILING,
                connection,
                answered_as=RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED,
            )
        self._records.session_minted(device=connection.device)
        return Response(
            200,
            "OK",
            body=_json({"header_half": values.header_half}),
            content_type="application/json",
            # `HttpOnly` so no script reads it, `SameSite=Strict` so no other site
            # causes it to be sent, `Path=/` and no `Domain` so a second cookie of
            # this name is detectable as the anomaly it is, and no persistent
            # expiry — none of which the guarantee rests on, because "a session's
            # lifetime is decided by the gateway alone" (ADR-0168 §6).
            #
            # **`Secure` on the remote listener and only there** (ADR-0202 §7), which
            # is a stacked addition to §6 rather than a change to it: every other
            # attribute is unchanged and the loopback listener is untouched. It
            # defends a narrow residual — "a downgrade a future lane might introduce,
            # or an attacker who can make the browser attempt `http://` at the same
            # authority" — and it is a clause rather than a lane's choice because
            # once the listener is HTTPS-only its absence would look deliberate.
            set_cookie=_cookie(values.cookie_half, remote=connection.remote),
            close=True,
        )

    async def _session_bound(
        self, request: Request, connection: _Connection, request_class: RequestClass
    ) -> Response | _Streamed:
        """Everything ADR-0168 §3 serves only to an admitted browser."""
        header_half = request.header(_SESSION_HEADER)
        outcome = self._sessions.admit(
            header_half=header_half, cookie_halves=request.cookies(_COOKIE_NAME)
        )
        if outcome is Admission.NO_LIVE_SESSION:
            return self._refuse(request_class, RefusalCondition.NO_LIVE_SESSION, connection)
        if outcome is Admission.COOKIE_HALF_MISMATCH:
            return self._refuse(request_class, RefusalCondition.COOKIE_HALF_MISMATCH, connection)
        connection.admitted = True
        if request_class is RequestClass.ASSISTANT:
            return await self._assistant(request, header_half, connection)
        # Admitted, and asking the assistant for nothing: answered, and the engine
        # is not reached (ADR-0168 §1's biconditional). Not a refusal on any of
        # §3 to §7's conditions, so nothing is recorded and the connection survives.
        return _fault(404, "Not Found", "no-such-path", close=False)

    async def _assistant(
        self, request: Request, header_half: str | None, connection: _Connection
    ) -> Response | _Streamed:
        """Resolve one admitted assistant request onto ADR-0177 §1's enumeration.

        **The enumeration is here and it is closed.** Every operation outside it is
        unreached from a browser, and no lane adds one without its own ratified
        decision — which is what keeps ADR-0174's permission to run a gateway on the
        hub's own machine from quietly handing a browser the connection operations
        ADR-0177 §3 splits by listener, now that a loopback-dialling gateway no
        longer meets the hub's remote refusal (ADR-0174 §11).

        **ADR-0177 §3's two refusals are taken here, before the handler and before
        the body is read.** A credential the surface is about to refuse must not be
        parsed, held or relayed on the way to being refused, so the decision is made
        from the shape and the listener alone and nothing of the payload is touched.

        **Every handler answers or raises** :class:`_Refused`, and this is where the
        second becomes the first. A handler therefore reads as one engine call with
        the arguments the browser supplied, which is the form ADR-0168 §1's
        biconditional is checkable in — and the catch covers the streamed branch as
        well as the unary one, so a mistyped argument is refused identically on every
        shape the surface serves rather than on the ones a lane remembered.

        Args:
            request: The admitted request.
            header_half: The value it was admitted on. The two streamed shapes need
                the session's own handle, because ADR-0175 §7 ends every stream a
                session held at the moment that session ends.
            connection: The connection it arrived on, for the record a refusal writes.

        Returns:
            The response, or the stream to write.
        """
        shape = (request.method, request.path)
        barred = self._connections_refused(request.path, connection)
        if barred is not None:
            return barred
        try:
            if shape not in _STREAMED_SHAPES:
                return await self._unary[request.path](request)
            handle = None if header_half is None else self._sessions.handle(header_half)
            if handle is None:  # pragma: no cover — admitted means a session verified it
                return self._refuse(
                    RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION, connection
                )
            if shape == ("POST", _ASK_STREAM_PATH):
                return self._ask_streaming(request, handle)
            return self._delivery_stream(handle)
        except _Refused as refused:
            return refused.response

    def _connections_refused(self, path: str, connection: _Connection) -> Response | None:
        """ADR-0177 §3's two refusals, decided from the listener and the shape alone.

        **Neither is decided from anything the browser asserts** — "not from a header,
        an origin value, a body field, or a device identity" — and neither is lifted by
        ADR-0174 §4's admission, by a device appearing in
        ``gateway_remote_browser_devices``, or by any configuration §3 does not name.
        :attr:`_Connection.remote` is which socket accepted the connection and
        :attr:`_hub_carries_connections` is one setting of this process's own, so a
        peer has nothing to say about either.

        **The hub's transport is asked about first, because it is the wider refusal.**
        §3's second clause takes *all five* off a gateway that reaches its hub over
        ADR-0124's remote listener, "on either listener" — so a loopback browser on
        such a gateway is refused here too, and the listener split below never gets to
        answer a question that has already been settled.

        **This is the third refusal shape this class answers with and it is neither of
        the other two.** It is not one of ADR-0168 §3 to §7's conditions, so
        :class:`.records.RefusalCondition` does not grow and **nothing is recorded**:
        §6 records "a request refused on a condition of §3, §4, §5, §6 or §7" and
        "nothing for a refusal on any other ground", and ADR-0177 §11 adds no clause to
        ADR-0168. And it is not a relay fault, because no relay was attempted — §3
        forbids it being "flattened into … a fault attributed to the hub", which a
        ``502`` or a ``422`` from :func:`_relay_fault` would be. What is left is what
        the residual `404` beside it already is: an answer to an admitted request,
        carrying its own name, on a connection that survives.

        **`403` rather than `404`**, which §3 forbids by name ("never flattened into an
        absent path"): the path exists, this gateway serves it, and what is refused is
        this request on this listener. The condition is read off the ``fault`` member
        rather than off the status, exactly as it is for the two ADR-0168 §7 conditions
        that already share ``403``.

        Args:
            path: The admitted request's path.
            connection: The connection it arrived on, which says which listener
                accepted it.

        Returns:
            The refusal, or ``None`` where the request is not one of the five or is one
            this gateway serves on this listener.
        """
        if path not in _CONNECTION_PATHS:
            return None
        if not self._hub_carries_connections:
            return _fault(
                403,
                "Forbidden",
                "connections-need-a-local-hub",
                detail=(
                    "This gateway reaches its hub over the remote listener, and the "
                    "connection surface is carried only on the hub's own machine "
                    "(ADR-0151 §13). Run a gateway there to connect an account."
                ),
                close=False,
            )
        if connection.remote and path in _CREDENTIAL_PATHS:
            return _fault(
                403,
                "Forbidden",
                "credential-entry-loopback-only",
                detail=(
                    "Entering a credential is available on a loopback origin only. "
                    "This page is not one, so the browser cannot protect a secret "
                    "typed into it. Disconnecting and reading the connections are "
                    "available here."
                ),
                close=False,
            )
        return None

    async def _relayed[T](
        self,
        call: Callable[[], Awaitable[T]],
        *,
        fault: Callable[[Exception], Response] | None = None,
    ) -> T:
        """Make one call on the promoted surface, or refuse instead of making it.

        The whole of what every unary handler shares, in one place: the hub-connection
        ceiling ADR-0168 §8 refuses rather than queues, and ADR-0168 §9's three
        conditions, each answered as its own. §9 requires a transport failure
        "distinguishable from a request the hub received and declined" and forbids
        ever presenting one "as an answer" — and ADR-0177 §7's third clause is what
        that distinction is *for* at this surface, because a browser composing an
        amendment reads which of ADR-0139 §4's three outcomes each act got from it and
        from nothing else.

        The gateway does not retry, does not queue, and answers from nothing of its
        own. The slot is returned whichever way the call ends, the refusal included.

        **How a failure is *named* is the caller's, and exactly one surface needs its
        own naming.** :func:`_relay_fault`'s three conditions are ADR-0168 §9's and
        they are total over "did the hub receive this" — which is the whole question
        everywhere but the connection surface, where ADR-0151 §7 and §8 rule that the
        *class* of the failure carries facts a caller may not derive from anything
        else: whether the act landed, whether the reference exists, and whether the
        state is readable. Collapsing those into one name would make the page infer
        them, which §7 forbids in terms. :func:`_connection_fault` is the one
        substitution, and it falls through to :func:`_relay_fault` for everything
        ADR-0151 does not classify.

        Args:
            call: The one engine call this request resolves to, with the arguments
                the browser supplied already bound.
            fault: How a failed call becomes a response, or ``None`` for
                :func:`_relay_fault` — ADR-0168 §9's three conditions. Resolved in the
                body rather than as a default value, because that function is defined
                below this class and a default is evaluated as the class is built.

        Returns:
            Whatever the promoted surface returned.

        Raises:
            _Refused: If no hub connection was free, or the call failed.
        """
        named = _relay_fault if fault is None else fault
        if not self._take_hub_slot():
            raise _Refused(_ceiling())
        try:
            return await call()
        except (TransportError, AssistantError, ValueError) as exc:
            raise _Refused(named(exc)) from exc
        finally:
            self._give_hub_slot()

    async def _ask(self, request: Request) -> Response:
        """Relay one turn to the hub and render what came back (ADR-0168 §1, §9).

        The budget is the gateway's own and no browser value reaches it: a turn budget
        is the **caller's** (ADR-0029 §4), which ADR-0177 §1 makes one of exactly two
        members of the one class of argument this adapter supplies of itself.
        """
        payload = _payload(request)
        outcome = await self._relayed(
            partial(
                self._engine.converse,
                _required_string(payload, "utterance"),
                timeout=_TURN_BUDGET,
                conversation_id=_optional_string(payload, "conversation_id"),
            )
        )
        return _rendered({"outcome": _outcome_view(outcome)})

    async def _ask_spoken(self, request: Request) -> Response:
        """Relay one spoken turn to the hub and render what came back (ADR-0200 §10).

        **Four members read by name, and no fifth.** ADR-0205 §7 partially supersedes
        ADR-0200 §10's enumeration in exactly that scope: the body carries "the
        **browser-owned** arguments of §1's signature and no others — ``utterance``,
        ``plays``, ``conversation_id`` and ``delivery``". The deadline is still not
        among them and the gateway still supplies it: a turn budget is the
        **caller's** (ADR-0029 §4), which ADR-0177 §1's fifth clause makes the one
        class of argument this adapter supplies of itself and ADR-0200 §12(b) widens
        to its third member for this call and by that ratified decision alone.

        **The report is the browser's own, whole** (ADR-0205 §7). This gateway
        derives, defaults, composes and invents no part of it: where the body carries
        no ``delivery``, no ``delivery`` reaches ``converse_spoken``. So ADR-0177 §1's
        fourth clause is *satisfied* here rather than widened — the deadline carve-out
        gains nothing, because nothing of this argument is supplied by the adapter.

        **A ``timeout`` in the body is therefore never *read*, rather than refused.** No
        other assistant handler inspects a member it does not use — :meth:`_ask` selects
        two members by name and is silent about the rest — so rejecting one key on one
        route would be machinery this surface does not otherwise have. What ADR-0177 §1
        forbids is a browser value *reaching* the deadline, and a member nothing reads
        reaches nothing.

        **The body is bounded whole before any member of it is read**, by
        ``gateway_max_request_bytes`` in :meth:`_next` — so a body big enough to breach
        that bound is refused on its *size*, whether the surplus bytes sit in
        ``utterance``, in a member no clause names, or in whitespace. That refusal says
        nothing about the member carrying them, and no ``timeout`` is read on that path
        either.

        **Emptiness of ``plays`` is not decided here**, on :func:`_uses`' precedent:
        ADR-0200 §3 makes an empty ``plays`` a local ``ValueError`` at the promoted
        surface, "before any I/O", so every client gets one answer and a second rule at
        this layer could only differ from it.
        """
        payload = _payload(request)
        turn = await self._relayed(
            partial(
                self._engine.converse_spoken,
                _utterance(payload),
                plays=_plays(payload),
                timeout=_TURN_BUDGET,
                conversation_id=_optional_string(payload, "conversation_id"),
                delivery=_delivery(payload),
            ),
            fault=_spoken_fault,
        )
        return _rendered({"turn": _spoken_view(turn)})

    def _ask_streaming(self, request: Request, handle: SessionHandle) -> Response | _Streamed:
        """Relay one turn as a stream, one value per instalment (ADR-0175 §3).

        "A browser's streamed turn is one request, answered by a stream carrying the
        values ADR-0173 §1's frames carry, in the order they arrived: one value per
        ``ReplyChunk``, then one terminal value carrying the ``TurnOutcome``, or one
        terminal value carrying the fault the exchange ended in."

        The hub slot is taken **before** the head is written and given back when the
        body finishes, so a stream held open for a minute is a connection accounted
        for the whole time (§7). What cannot be decided before the head is written
        travels as the stream's terminal value instead of as a status.

        Args:
            request: The admitted request.
            handle: The session that admitted it (§7).

        Returns:
            The stream, or a refusal decidable before the engine is reached.
        """
        payload = _payload(request)
        utterance = _required_string(payload, "utterance")
        conversation = _optional_string(payload, "conversation_id")
        if not self._take_hub_slot():
            return _ceiling()
        return _Streamed(
            handle=handle,
            head=StreamHead(content_type=streams.MEDIA_TYPE),
            body=partial(self._pump_answer, utterance=utterance, conversation=conversation),
            release=self._give_hub_slot,
        )

    async def _pump_answer(
        self, writer: asyncio.StreamWriter, *, utterance: str, conversation: str | None
    ) -> None:
        """Drive ``converse_streaming`` onto the stream (ADR-0175 §3).

        **Every engine stream this gateway opens is closed, on every exit and early
        ones included**, through :func:`ai_assistant.core.streams.closing_stream` —
        the seam that exists because "Python does not close an abandoned async
        iterator at the point of abandonment". This surface is the first consumer
        that will routinely abandon one: a browser that navigated away and a write
        that failed are each an early exit here, where the CLI drives every stream to
        exhaustion. A lane consuming this with a bare ``async for`` and a ``break``
        leaks a turn's resources on the most common path this surface has.

        **A stream that ends without a terminal value is a transport failure and is
        left as one** (§2). The contract yields exactly one ``TurnOutcome`` unless it
        raises, so there is no third ending to invent a value for: a body that stops
        early is what the front end reports as a transport failure, which is
        ADR-0168 §9's distinction reaching the browser.
        """
        try:
            answering = self._engine.converse_streaming(
                utterance, timeout=_TURN_BUDGET, conversation_id=conversation
            )
            async with closing_stream(answering) as pieces:
                async for produced in pieces:
                    if isinstance(produced, TurnOutcome):
                        await _write_value(writer, streams.outcome(_outcome_view(produced)))
                        return
                    await _write_value(writer, streams.chunk(produced))
        except (TransportError, AssistantError, ValueError) as exc:
            await _write_value(writer, _stream_fault(exc))

    def _delivery_stream(self, handle: SessionHandle) -> Response | _Streamed:
        """Open one delivery stream, and the poll with the first (ADR-0175 §4).

        **The head states the cadence the stream will be written at** (#1442). §4
        obliges a write on every open delivery stream "at least once per
        ``gateway_notification_budget``", and §8 owns that figure — so silence past a
        multiple of it is the one thing the keep-alive exists to expose. The browser
        could not observe it, because the figure is gateway configuration and nothing
        the page read carried one: a ``fetch`` that never settled left the page reading
        "Watching for notifications" with its own control hidden, and ADR-0182 §7's
        announced re-arm could not fire, because §7 re-establishes a stream "only while
        it holds none".

        **It is a header and not a value**, which is
        :func:`~ai_assistant.interfaces.gateway.streams.keep_alive_header`'s own
        reasoning: a value would fall under §4's rule that at most one is pending per
        stream and that one still in flight when the next is due ends it, and that rule
        is written about a browser that stopped reading rather than about a preamble.
        The head is read before any value is, so it costs the body nothing at all — no
        ordering, no slot, no abandonment question. This handler is the only place a
        stream head carries one, and the figure is the same one the poll is given,
        which is §8's "one figure paces both".

        Returns:
            The stream, or the ceiling refusal where the poll's own hub connection
            would take ``gateway_max_hub_connections`` past its bound (§7).
        """
        opened = self._deliveries.open()
        if opened is None:
            return _ceiling()
        return _Streamed(
            handle=handle,
            head=StreamHead(
                content_type=streams.MEDIA_TYPE,
                headers=(streams.keep_alive_header(self._settings.gateway_notification_budget),),
            ),
            body=partial(write_stream, stream=opened, frame=_frame),
            release=partial(self._deliveries.close, opened),
            delivery=opened,
        )

    async def _recent_conversations(self, request: Request) -> Response:
        """List conversations, most recently active first (ADR-0074 §2, ADR-0177 §1)."""
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.recent_conversations,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"conversations": [_summary_view(one) for one in held]})

    async def _conversation(self, request: Request) -> Response:
        """Show what destroying one conversation would destroy (ADR-0074 §8).

        ADR-0073 §5's show-then-confirm at the unit the user thinks in, and the
        reason ADR-0175 §6 admits a destructive operation without adding a ceremony
        clause: "a front-end confirmation before a forget is not a control and is not
        required here", because the origin-resident script the residual is about
        defeats one. What the front end does about it is a rendering decision, and
        the CLI's own order — read the conversation, then forget it — is the pattern
        this pair makes available.
        """
        named = _required_string(_payload(request), "conversation_id")
        digest = await self._relayed(partial(self._engine.conversation, named))
        if digest is None:
            return _fault(404, "Not Found", "no-such-conversation", close=False)
        return _rendered({"conversation": _digest_view(digest)})

    async def _forget_conversation(self, request: Request) -> Response:
        """Destroy one conversation and the episodes its turns index (ADR-0175 §6).

        **This widens what a script on the gateway's own origin can spend, by less
        than what is already there**, and ADR-0175 §6 states the accounting rather
        than hiding it: ADR-0168 §6's residual — "script running on the gateway's own
        origin defeats both halves… it can simply issue requests the browser will
        authenticate" — has covered ``converse`` since milestone 13, and a turn can
        approve a tool, execute it and durably commit a non-idempotent effect. So
        this adds a destructive operation to a surface that already carried a more
        destructive one, and adds no new class of residual.
        """
        named = _required_string(_payload(request), "conversation_id")
        destroyed = await self._relayed(partial(self._engine.forget_conversation, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0177 §6: the grant surface -----------------------------------
    #
    # Five operations and five handlers. **None of them composes an amendment**
    # (§7): a browser amending a grant sends a `/revoke` and then a `/grant`, and
    # the gateway holds nothing between them — it does not know the two requests
    # are related and has nowhere to put the knowledge if it did. That is ADR-0139
    # §4's own reasoning arriving one hop out: composing the two calls client-side
    # "is what puts the intermediate state where a surface can report it".

    async def _grantable_sources(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Answer *what may I grant?* and nothing else (ADR-0097 §9, ADR-0139 §1).

        The location each entry carries "is on this response and on no stored record"
        (ADR-0102 §6), and it crosses because a client "renders each ``location`` and
        takes an explicit act from the user before it calls ``grant``". A gateway that
        dropped it would leave the front end unable to meet ADR-0139 §5 and therefore
        unable to grant at all.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            One entry per grantable source.
        """
        offered = await self._relayed(self._engine.grantable_sources)
        return _rendered({"sources": [_source_view(one) for one in offered]})

    async def _grant(self, request: Request) -> Response:
        """Record one grant, for the uses the browser named (ADR-0097 §2).

        ``source`` is relayed **verbatim** and normalised by nothing: ADR-0102 §2
        requires that "no implementation may strip, case-fold or otherwise normalise
        ``source`` at any point before it is compared", and an adapter that trimmed it
        here would make the gateway admit a call the in-process engine refuses.

        The scope is the browser's own, whole. This adapter neither defaults it, nor
        widens it, nor infers one member from another — ADR-0133 §2 forbids ranking
        them, and ADR-0097 §8 forbids anything deciding what the user permitted on
        their behalf.

        Args:
            request: The admitted request, carrying ``source`` and ``scope``.

        Returns:
            The recorded grant, as it was appended.
        """
        payload = _payload(request)
        recorded = await self._relayed(
            partial(
                self._engine.grant,
                _required_string(payload, "source"),
                scope=_uses(payload, "scope"),
            )
        )
        return _rendered({"grant": _grant_view(recorded)})

    async def _revoke(self, request: Request) -> Response:
        """Withdraw the live grant on one source, or report there was none.

        **No admission check, deliberately** (ADR-0102 §4): a value no reader declares
        finds no live grant and answers ``null``, which is what keeps a grant whose
        reader was later unconfigured revocable. So this handler applies none either —
        it would be the same refusal one layer out, and would make a grant permanently
        unrevokable from a browser.

        Args:
            request: The admitted request, carrying ``source``.

        Returns:
            The revoking record, or ``null`` where no live grant covered the source.
        """
        named = _required_string(_payload(request), "source")
        withdrawn = await self._relayed(partial(self._engine.revoke, named))
        return _rendered({"revoked": None if withdrawn is None else _grant_view(withdrawn)})

    async def _recent_grants(self, request: Request) -> Response:
        """List what was granted and withdrawn, newest first (ADR-0097 §4).

        **``limit`` and no ``offset``**, which is the surface's own departure from the
        other paging signatures (ADR-0102 §10) and is not repaired here: a gateway
        offering an offset it would have to implement by over-fetching and slicing
        would be composing a page the promoted surface does not offer.

        Args:
            request: The admitted request, carrying an optional ``limit``.

        Returns:
            The records, newest first.
        """
        payload = _payload(request)
        recorded = await self._relayed(
            partial(self._engine.recent_grants, limit=_page(payload, "limit", DEFAULT_PAGE_SIZE))
        )
        return _rendered({"grants": [_grant_view(one) for one in recorded]})

    async def _standing_grants(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Answer *what do I currently authorise?* (ADR-0139 §2).

        The second of ADR-0139 §1's two questions, and the answer to it. It is served
        on its own path because "neither answer is derivable from the other and no
        surface may present one as the other" — a gateway that annotated this set from
        ``grantable_sources``, or dropped a record because no held reader declares its
        source, would hide exactly the state this operation exists to show.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            Every grant live at the instant the response was computed.
        """
        standing = await self._relayed(self._engine.standing_grants)
        return _rendered({"standing": [_grant_view(one) for one in standing]})

    # --- ADR-0177 §5: the belief surface ----------------------------------

    async def _beliefs(self, request: Request) -> Response:
        """List what is believed, band-scoped, as summaries (ADR-0073 §1, ADR-0077 §6).

        **An absent filter and an empty one are different answers** and both cross:
        ``bands`` omitted selects every band, and ``bands: []`` selects nothing. The
        contract says so in terms, so a reader that folded the two would answer a
        question the browser did not ask.

        Args:
            request: The admitted request, carrying optional ``bands``, ``kinds``,
                ``limit`` and ``offset``.

        Returns:
            One summary per live belief the filters admit.
        """
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.beliefs,
                bands=_members(payload, "bands", BeliefBand),
                kinds=_members(payload, "kinds", MemoryKind),
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"beliefs": [_belief_summary_view(one) for one in held]})

    async def _belief(self, request: Request) -> Response:
        """Read one belief with its citations resolved (ADR-0077 §6).

        **This is the read ADR-0177 §5's ceremony rests on**, and the reason it is a
        separate path from the listing: §5's second clause requires the render "taken
        from a ``belief`` read issued immediately before the confirmation is offered,
        and never from an entry of a ``beliefs`` listing the page rendered earlier",
        because "a page holds its listing until it is navigated away from".

        Args:
            request: The admitted request, carrying ``record_id``.

        Returns:
            The belief, or the absent-record condition as its own.
        """
        named = _required_string(_payload(request), "record_id")
        held = await self._relayed(partial(self._engine.belief, named))
        if held is None:
            return _fault(404, "Not Found", "no-such-belief", close=False)
        return _rendered({"belief": _belief_view(held)})

    async def _forget_belief(self, request: Request) -> Response:
        """Destroy one belief, permanently (ADR-0073 §5).

        The ceremony is the **front end's** and this handler is not it: ADR-0073 §5
        puts the show-then-confirm on the surface, and ADR-0177 §5 binds it at the
        browser. A gateway that refused an unconfirmed ``forget`` would be authoring a
        control the promoted surface does not have, and could not tell a confirmed
        call from an unconfirmed one anyway.

        Args:
            request: The admitted request, carrying ``record_id``.

        Returns:
            Whether a record was destroyed — ``false`` where the id named nothing
            live, which the contract states is not an error.
        """
        named = _required_string(_payload(request), "record_id")
        destroyed = await self._relayed(partial(self._engine.forget, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0078 §8: the deferred-question surface -----------------------

    async def _questions(self, request: Request) -> Response:
        """List the questions waiting for an answer.

        Args:
            request: The admitted request, carrying optional ``limit`` and ``offset``.

        Returns:
            The answerable questions, each with what accepting would retire.
        """
        payload = _payload(request)
        waiting = await self._relayed(
            partial(
                self._engine.questions,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"questions": [_question_view(one) for one in waiting]})

    async def _interrupted_questions(self, request: Request) -> Response:
        """List the questions whose answer was begun and whose outcome is unrecorded.

        A **second** listing rather than a filter on the first, because it answers a
        different question: "not 'failed' and not 'retryable': the system does **not**
        know whether the memory write landed" (ADR-0078 §9).

        Args:
            request: The admitted request, carrying optional ``limit`` and ``offset``.

        Returns:
            The interrupted questions.
        """
        payload = _payload(request)
        begun = await self._relayed(
            partial(
                self._engine.interrupted_questions,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        return _rendered({"questions": [_question_view(one) for one in begun]})

    async def _answer(self, request: Request) -> Response:
        """Answer one deferred question, and render what the answer did (ADR-0078 §5).

        ``accept`` is required and is read as a boolean and nothing else: a missing or
        mistyped member is refused rather than defaulted, because a default would be
        this adapter deciding whether the user believes something.

        Args:
            request: The admitted request, carrying ``question_id`` and ``accept``.

        Returns:
            Which of the five outcomes happened, and what it left behind.
        """
        payload = _payload(request)
        outcome = await self._relayed(
            partial(
                self._engine.answer,
                _required_string(payload, "question_id"),
                accept=_flag(payload, "accept"),
            )
        )
        return _rendered({"answered": _answer_view(outcome)})

    async def _forget_question(self, request: Request) -> Response:
        """Destroy one deferred question, so its subject can be asked again.

        The ceremony ADR-0177 §5 gives this verb at *this* surface is the front end's,
        and it is met with the two listings rather than with a single-question read
        that ADR-0078 §8 does not have (#495, cited and not absorbed).

        Args:
            request: The admitted request, carrying ``question_id``.

        Returns:
            Whether a question was destroyed.
        """
        named = _required_string(_payload(request), "question_id")
        destroyed = await self._relayed(partial(self._engine.forget_question, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0077 §8: the passive half, driven by a caller ----------------

    async def _observe(self, request: Request) -> Response:
        """Read a bounded batch of a conversation's episodes and report what it did.

        ``conversation_id`` is "a **selector rather than a subject**" (ADR-0085 §2), so
        an absent one selects rather than being an error. What it selects is the first
        conversation holding a turn above its observation watermark, ordered
        ``last_active_at`` ascending (ADR-0212 §3) — it was "the most recently active
        conversation" until that decision replaced ADR-0077 §8's selection sentence.

        Args:
            request: The admitted request, carrying an optional ``conversation_id``.

        Returns:
            The proposals with their rulings, the counts kept apart, and the route.
        """
        named = _optional_string(_payload(request), "conversation_id")
        report = await self._relayed(partial(self._engine.observe, conversation_id=named))
        return _rendered({"observation": _observation_view(report)})

    # --- ADR-0177 §8, ADR-0178 §7: the CONFIRM prompt ---------------------
    #
    # ADR-0177 §8 blocked this surface "before a ratified decision supplies what
    # ADR-0148 §8's fourth clause requires", and ADR-0178 §8 discharges that
    # precondition "by this ADR's ratification and merge and not before". So the two
    # handlers below carry §8's surviving clauses — the token relayed opaquely,
    # ``resume`` answered with ``approved`` and nothing else, and
    # ``pending_confirmations`` as the one recovery route — and the view they render
    # through carries ADR-0178 §7's floor.
    #
    # **Neither handler rules on anything.** ADR-0042 §6 makes the adapter a conveyor
    # of consent: the browser's answer arrives as ``approved``, the engine decides what
    # it means, and a denial comes back as a result rather than as an exception.

    async def _pending_confirmations(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """List every park still answerable, each with a freshly minted token.

        ADR-0177 §8's recovery clause: "A browser that has been closed and reopened,
        and a gateway that has been restarted, both recover through this read and
        through no other route." The tokens are the engine's own and are re-minted per
        call (ADR-0052 §1), which is why nothing here or in the page caches one — a
        cached token names an entry in a handle table a restart emptied.

        Returns:
            One rendered confirmation per answerable park, each carrying ADR-0178 §7's
            floor where the ruling was taken over an egress binding.
        """
        pending = await self._relayed(self._engine.pending_confirmations)
        return _rendered({"confirmations": [_confirmation_view(one) for one in pending]})

    async def _resume(self, request: Request) -> Response:
        """Answer one parked confirmation and continue the step it belongs to.

        **``approved`` and nothing else** (ADR-0177 §8): the browser supplies the
        human's answer, and ``timeout`` is the caller-owned deadline §1 and §9 place
        with the gateway — ``resume`` "is given the same budget a turn is given at this
        surface", which is :data:`_TURN_BUDGET` and no second figure.

        **The token is relayed, not interpreted** (ADR-0042 §4): :func:`_token` wraps
        the bytes the browser sent in the carrier the surface declares and changes none
        of them, and this gateway mints none, rewrites none and substitutes none.

        Args:
            request: The admitted request, carrying ``token`` and ``approved``.

        Returns:
            What the resumption produced, rendered as any other turn is.
        """
        payload = _payload(request)
        outcome = await self._relayed(
            partial(
                self._engine.resume,
                _token(payload),
                approved=_flag(payload, "approved"),
                timeout=_TURN_BUDGET,
            )
        )
        return _rendered({"outcome": _outcome_view(outcome)})

    # --- ADR-0177 §10: the notification review surface --------------------
    #
    # Five operations on the notification **record** (ADR-0130 §7, §9) and none on a
    # delivery. The two objects are on one screen for the first time here — a browser
    # watching :data:`_DELIVERIES_PATH` *and* holding a list it can dismiss from — so
    # §10's first three clauses are what these handlers are checked against: nothing
    # below acknowledges, retires, withdraws or completes a delivery, and no
    # ``delivery_id`` is read from a request or written into a response.

    async def _notifications(self, request: Request) -> Response:
        """List every retained notification, oldest first (ADR-0130 §7).

        **The clock is read once for the whole page**, which is the CLI's own
        arrangement and for its reason: expiry is the one part of a record's state no
        field answers, so a page whose rows were judged at different instants could
        render two records either side of a boundary neither of them crossed.

        Args:
            request: The admitted request, carrying optional ``limit`` and ``offset``.

        Returns:
            The page, each record with what a person needs in order to act on it.
        """
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.notifications,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            )
        )
        now = self._now()
        return _rendered({"notifications": [_notification_view(one, now=now) for one in held]})

    async def _dismiss_notification(self, request: Request) -> Response:
        """Dispose of one notification without destroying it (ADR-0130 §9).

        **This is not an acknowledgement** (ADR-0177 §10). It ends the record's
        actionability; whether the notification was ever *delivered* to this browser
        or any other is a different question about a different object, and the
        ``delivery_id`` that would answer it reaches no browser and is carried by no
        member of this request.

        Args:
            request: The admitted request, carrying ``notification_id``.

        Returns:
            Whether an actionable notification was dismissed — ``false`` where the id
            named nothing, or named one already dismissed, expired or dropped, which
            the contract states is not an error.
        """
        named = _required_string(_payload(request), "notification_id")
        dismissed = await self._relayed(partial(self._engine.dismiss_notification, named))
        return _rendered({"dismissed": dismissed})

    async def _forget_notification(self, request: Request) -> Response:
        """Destroy one notification, so its subject can be proposed again (ADR-0130 §9).

        ADR-0004 §6's delete right, beside the dismissal deliberately: a dismissal
        leaves the record readable and in the user's export, and this is the surface
        the delete right reaches.

        **ADR-0177 §5's ceremony does not reach this verb and none is asserted here.**
        §5 binds ``forget``, ``forget_question`` and ``forget_conversation`` by name
        and stops there, and ADR-0073 §5 is about a belief — a notification is not one
        of any band. What the front end offers before it sends this is a plain
        confirmation of a destructive act, over the row it is displaying, and it does
        not claim to be that ceremony.

        Args:
            request: The admitted request, carrying ``notification_id``.

        Returns:
            Whether a notification was destroyed.
        """
        named = _required_string(_payload(request), "notification_id")
        destroyed = await self._relayed(partial(self._engine.forget_notification, named))
        return _rendered({"destroyed": destroyed})

    async def _notification_preferences(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Read the three standing settings that tune proactive contact (ADR-0130 §6).

        Answerable from an empty store on the first day: every field has a shipped
        default, and the gateway supplies none of them — what crosses is what the hub
        said is in force.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            The settings in force.
        """
        held = await self._relayed(self._engine.notification_preferences)
        return _rendered({"preferences": _preferences_view(held)})

    async def _set_notification_preferences(self, request: Request) -> Response:
        """Write the three standing settings whole (ADR-0130 §6, ADR-0177 §10).

        **A read-modify-write, and the whole value crosses.** The surface replaces
        what is held rather than merging into it, so a member this handler defaulted
        would silently clear a setting the browser never meant to touch — which is
        why every member is required here and none has a fallback. ADR-0177 §1's
        "the gateway derives none of them, defaults none of them" is the same rule
        arriving from the other side.

        **What is rendered back is what the call returned**, never what it was sent
        (§10's fourth clause). The last write wins and this surface carries no version
        token, so the value in force after a write is a fact only the hub can state.

        Args:
            request: The admitted request, carrying the whole preferences value.

        Returns:
            The settings now in force, as the store holds them.
        """
        asked = _preferences(_payload(request))
        written = await self._relayed(partial(self._engine.set_notification_preferences, asked))
        return _rendered({"preferences": _preferences_view(written)})

    # --- the connection surface (ADR-0151 §1, ADR-0177 §3, §4) ----------------
    #
    # **The credential is relayed and nothing else is done with it** (ADR-0177 §4,
    # third clause): it is read out of the JSON body, wrapped, passed as the
    # ``credential`` argument, and dropped. It is not logged, not retained beyond the
    # call, not copied into any other value, not retried with, and not read back —
    # ADR-0151 §6's `orchestration` clause one hop out, and "the gateway acquires no
    # standing over the value by carrying it".
    #
    # **The field is named ``credential``** so ``core/logging.py``'s key-name
    # redaction reaches it wherever a payload mapping is logged (§4's second clause).
    # Nothing here renames it, aliases it, or nests it under a key redaction does not
    # reach — and the gateway logs no request body at all, which is the belt the
    # naming is the braces for.
    #
    # **No response carries it or anything derived from it** (§4's sixth clause).
    # :func:`_account_view` renders four members and a credential is none of them, so
    # a read-back is unreachable rather than merely absent.

    async def _connect_account(self, request: Request) -> Response:
        """Connect a fresh account under a reference the hub mints (ADR-0151 §2).

        **No reference argument, and none is accepted under another name**: §3's mint
        makes this call unaimable at an existing record, which is what makes "I meant
        to replace a credential and created a second connection instead" unreachable
        rather than merely visible. A browser that wants the other act sends
        :data:`_REPROVISION_PATH`.

        The identity crosses byte for byte (ADR-0151 §5): nothing here strips,
        case-folds or normalises it, and the refusals that identity is subject to are
        raised by the implementation "locally, before any I/O" and arrive as
        :class:`~ai_assistant.core.errors.UnusableIdentityError`.

        Args:
            request: The admitted request, carrying ``identity`` and ``credential``.

        Returns:
            The live record this act wrote.
        """
        payload = _payload(request)
        account = await self._relayed(
            partial(
                self._engine.connect_account,
                identity=_required_string(payload, "identity"),
                credential=_credential(payload),
            ),
            fault=_connection_fault,
        )
        return _rendered({"account": _account_view(account)})

    async def _reprovision_account(self, request: Request) -> Response:
        """Replace the credential under a reference the hub returned (ADR-0151 §2).

        A separate entry from :meth:`_connect_account` and never the same one with an
        optional member, because ADR-0151 §1 kept the operations apart for a reason a
        browser makes sharper: two outcomes are reachable here that a fresh connection
        cannot produce — a reference the store does not hold, and a losing
        compare-and-swap — and a single shape would decide which act it was performing
        from whether a member was filled in.

        Args:
            request: The admitted request, carrying ``reference``, ``identity`` and
                ``credential``.

        Returns:
            The live record this act wrote, at the new revision.
        """
        payload = _payload(request)
        account = await self._relayed(
            partial(
                self._engine.reprovision_account,
                _required_string(payload, "reference"),
                identity=_required_string(payload, "identity"),
                credential=_credential(payload),
            ),
            fault=_connection_fault,
        )
        return _rendered({"account": _account_view(account)})

    async def _disconnect_account(self, request: Request) -> Response:
        """Disconnect a reference and delete its credentials (ADR-0149 §5).

        **A ``None`` is rendered as the absence it is and never as a disconnection**
        (ADR-0151 §8). It says one thing — no live record was removed by this call —
        and it is neither a confirmation that a credential was deleted nor a statement
        that the reference does not exist, so it crosses as ``removed: null`` beside
        no other member and the page says the one thing in words.

        Args:
            request: The admitted request, carrying ``reference``.

        Returns:
            The live record removed, or ``null`` where none was.
        """
        named = _required_string(_payload(request), "reference")
        removed = await self._relayed(
            partial(self._engine.disconnect_account, named), fault=_connection_fault
        )
        return _rendered({"removed": None if removed is None else _account_view(removed)})

    async def _connected_accounts(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """What is connected now, complete or refused (ADR-0151 §9).

        **It takes no argument and is not paged**, and this handler adds neither: the
        contract admits no ``limit`` and no ``offset`` because "a truncated answer to
        'what is connected' is a false answer rather than a partial one", and an
        adapter that offered one would be inventing the surface §9 refused. Where the
        set does not fit the frame the call raises and this answers a fault, which is
        the honest half of the same rule.

        Nothing is merged in and nothing is annotated: no ``recent_connection_acts``
        read joins this one (ADR-0139 §1), and no record is dropped because its
        integration is not built — "a connection the hub can do nothing with is
        exactly what this command exists to show".

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            Every live record, in the order the hub returned them.
        """
        connected = await self._relayed(self._engine.connected_accounts, fault=_connection_fault)
        return _rendered({"accounts": [_account_view(one) for one in connected]})

    async def _recent_connection_acts(self, request: Request) -> Response:
        """What was done to connections, newest first (ADR-0151 §9).

        **There is deliberately no ``offset``** and none is read: the contract has one
        argument, and an offset over a store that has none "is a paging surface that
        lies about its cost" (ADR-0102 §10). ``limit``'s strictly-positive rule is the
        *operation's* rather than the argument's, so it is left where ADR-0085 §9 puts
        it and refused by the implementation — the same division :meth:`_recent_grants`
        already stands on, and the reason :func:`_page` does not re-derive a bound.

        **This answers a different question from :meth:`_connected_accounts` and
        neither derives the other.** Nothing here is joined to that listing, and the
        rows carry no instant because a connection record has none (ADR-0149 §3).

        Args:
            request: The admitted request, carrying an optional ``limit``.

        Returns:
            Up to ``limit`` acts, newest first.
        """
        payload = _payload(request)
        acts = await self._relayed(
            partial(
                self._engine.recent_connection_acts,
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
            ),
            fault=_connection_fault,
        )
        return _rendered({"acts": [_connection_act_view(one) for one in acts]})

    def _refuse(
        self,
        request_class: RequestClass,
        condition: RefusalCondition,
        connection: _Connection,
        *,
        answered_as: RefusalCondition | None = None,
    ) -> Response:
        """Record one refusal and answer it (ADR-0168 §3, §6, §8; ADR-0174 §3).

        The body carries the condition and nothing else: no assistant content, no
        fact about the hub's state, and no fact about whether the hub is
        reachable, which is what ADR-0168 §3 requires of every refusal. The
        connection is closed, because §8 requires it of a refusal on any of §3's,
        §4's, §5's, §6's, §7's and §8's conditions alike.

        The record carries the connection's attested overlay identity where there is
        one, which is ADR-0174 §3's addition to §6's enumeration and the reason it is
        worth having: ADR-0124 §7 has the hub record "each admission and each refusal
        with the device it named", and here for the first time "an owner reading a
        refusal learns *which of their devices* was refused". It never reaches the
        response — the device already knows who it is, and the enumeration governs
        the record rather than what is written back.

        **The record and the response are the same condition everywhere but one
        place**, and ADR-0182 §4 is that place: a ceiling refusal is recorded as the
        ceiling, because "that record is the owner's channel for the fact the
        browser is not told", and answered as an ordinary failed exchange, because
        "ADR-0168 §5's disclosure rule governs the response, so a ceiling refusal is
        indistinguishable to the browser from every other failed exchange". Splitting
        them differently "would hand any local process a probe for how many browsers
        the owner has admitted". The split is a keyword rather than a table because
        there is one condition it applies to and the caller is the one place that
        knows why.

        Args:
            request_class: Which of ADR-0168 §6's four kinds the request was.
            condition: The single condition it was refused on, and the one recorded.
            connection: The connection it arrived on, for the identity the record
                carries.
            answered_as: The condition to *answer* with, where §4 requires the
                browser told less than the record says. Defaults to the recorded one.

        Returns:
            The refusal to write.
        """
        self._records.refused(request_class, condition, device=connection.device)
        answered = condition if answered_as is None else answered_as
        status, reason = _REFUSAL_STATUS[answered]
        return _fault(status, reason, answered.value)


class _Refused(Exception):  # noqa: N818 — it is not an error, it is the answer
    """One request the gateway answered instead of relaying (ADR-0168 §1, §3).

    Raised by a payload reader that found a member missing or of the wrong type, and
    by :meth:`Gateway._relayed` where no hub connection was free or the call failed.
    :meth:`Gateway._assistant` turns it back into the response it carries.

    **An exception rather than a returned union**, and the reason is legibility of
    the thing this module is judged on: with it, a handler is one engine call with
    the arguments the browser supplied, so ADR-0168 §1's biconditional — "the gateway
    composes no behaviour the promoted engine surface does not offer" — is read off
    the handler's shape. The alternative threads a "or the refusal" value through
    every argument position and buries the call in it.

    Attributes:
        response: What to answer instead.
    """

    def __init__(self, response: Response) -> None:
        """Carry one answer.

        Args:
            response: What to answer instead of relaying.
        """
        super().__init__(response.status)
        self.response = response


def _malformed() -> _Refused:
    """The one condition every payload reader below refuses on.

    A single condition rather than one per member, for the reason ADR-0168 §5 gives
    for the bootstrap exchange: naming *which* member was wrong tells a caller
    something about the surface's shape that it did not already have, and every
    caller of this surface ships in the same distribution as it (ADR-0168 §10) and
    therefore already knows.
    """
    return _Refused(_fault(400, "Bad Request", "malformed-request"))


def _required_string(payload: Mapping[str, Any], name: str) -> str:
    """One string member that must be there.

    Relayed **verbatim**: nothing here strips, case-folds or otherwise normalises a
    value, because ADR-0102 §2 forbids it before a ``source`` is compared and a
    reader that did it for one member would do it for all of them.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent or is not a string.
    """
    value = _string(payload, name)
    if value is None:
        raise _malformed()
    return value


#: One decimal integer, bounded in length. Twenty digits covers every member the
#: surface spells this way — ``interruption_budget`` stops below ``2**63`` (nineteen)
#: and the largest ``timedelta`` is twenty digits of microseconds — and the bound is
#: on the *string* rather than on the value it names, because converting a very long
#: run of digits to an ``int`` is quadratic work a request body should not be able to
#: ask for.
_DECIMAL: Final = re.compile(r"[0-9]{1,20}")

#: The unit :func:`_preferences_view` spells a duration in, named once so the view and
#: :func:`_microseconds` cannot disagree about it.
_MICROSECOND: Final = timedelta(microseconds=1)

#: The bound ADR-0085 §9 declares for every page argument on the promoted surface,
#: and ADR-0073 §2 refuses rather than clamps. Written here because the surface
#: contract asks for it here: "an adapter that lets a user supply either **should
#: refuse an out-of-range value at its own parse boundary**", and a browser is an
#: adapter that lets a user supply both.
_PAGE_CEILING: Final = 2**63


def _optional_string(payload: Mapping[str, Any], name: str) -> str | None:
    """One string member that may be absent, refusing one that is present and wrong.

    **Absent is a selector and a wrong type is not.** ``conversation_id`` is "a
    **selector** rather than a subject" (ADR-0085 §2) — this conversation, or the most
    recently active — so omitting it asks a well-formed question. Reading a number as
    an absence would answer a *different* well-formed question instead, which is the
    gateway defaulting an argument ADR-0177 §1 makes the browser's own.

    It matters most where the operation writes. ``observe`` proposes beliefs from the
    batch it reads, so a mistyped selector silently accepted would put proposals on a
    conversation nobody named.

    ``null`` is accepted as the absence it is: JSON has a way of saying "no selector"
    and a client using it is not getting the type wrong.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value, or ``None`` where the member is absent or null.

    Raises:
        _Refused: If the member is present and is neither a string nor null.
    """
    if name not in payload or payload[name] is None:
        return None
    return _required_string(payload, name)


def _page(payload: Mapping[str, Any], name: str, fallback: int) -> int:
    """One paging argument, or its default, refused at this adapter's own boundary.

    The type check is what tells a page of one from ``true`` — ``bool`` is an ``int``
    by inheritance, so ``{"limit": true}`` would otherwise be a page of one that
    nothing downstream could distinguish from a request for one.

    **The range is the surface's own and is not re-derived**: this is ADR-0085 §9's
    ``[0, 2**63)`` and nothing narrower. An operation with a tighter rule of its own —
    ``recent_grants`` requires a strictly positive ``limit`` (ADR-0102 §10) — keeps it,
    because that rule is the operation's rather than the argument's, and a bound
    invented here would be the second place ADR-0102 §2's reasoning warns about.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        fallback: What an absent member means.

    Returns:
        The value, or the fallback.

    Raises:
        _Refused: If the member is present and is not an integer in ``[0, 2**63)``.
    """
    value = _integer(payload, name, fallback)
    if value is None or not 0 <= value < _PAGE_CEILING:
        raise _malformed()
    return value


def _flag(payload: Mapping[str, Any], name: str) -> bool:
    """One boolean member that must be there, read as a boolean and nothing else.

    Neither defaulted nor coerced. ``answer``'s ``accept`` is the member this exists
    for, and a truthy string arriving as an acceptance would have this adapter decide
    what the user believes — which is the one thing ADR-0097 §8's reasoning forbids a
    surface anywhere in this system.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent or is not a boolean.
    """
    value = payload.get(name)
    if not isinstance(value, bool):
        raise _malformed()
    return value


def _members[T: StrEnum](
    payload: Mapping[str, Any], name: str, vocabulary: type[T]
) -> tuple[T, ...] | None:
    """One optional filter naming members of a closed vocabulary.

    **An absent member and an empty one are different answers**, which is the whole
    reason this returns ``None`` rather than an empty tuple for the first: ``bands``
    omitted means every band and ``bands: []`` "selects nothing, which is a different
    answer from ``None``" in the contract's own words.

    A value the vocabulary does not carry is refused rather than dropped. Dropping it
    would answer a narrower question than the browser asked and say nothing about
    having done so.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        vocabulary: The enumeration its entries must name.

    Returns:
        The selected members, or ``None`` where the filter is absent.

    Raises:
        _Refused: If the member is present and is not a list of names the vocabulary
            carries.
    """
    if name not in payload:
        return None
    value = payload[name]
    if not isinstance(value, list):
        raise _malformed()
    known = {member.value: member for member in vocabulary}
    # **A string first, and membership second.** JSON carries objects and arrays, and
    # neither is hashable, so ``{"bands": [{}]}`` asked of the mapping directly raises
    # a ``TypeError`` this module does not catch — a request the surface has no shape
    # for arriving as a fault of the process rather than as a refusal. The type check
    # is what makes the lookup total over what a body can contain.
    if any(not isinstance(one, str) or one not in known for one in value):
        raise _malformed()
    return tuple(known[one] for one in value)


def _uses(payload: Mapping[str, Any], name: str) -> tuple[GrantScope, ...]:
    """The uses a ``grant`` authorises, as the browser named them.

    Whether the set is empty or repeats a member is **not** decided here: ADR-0097 §2
    refuses an empty scope at construction and ADR-0097 §10 refuses a duplicate, both
    locally and before any I/O, so the promoted surface answers it identically for
    every client and a second rule here could only differ from it. What this refuses
    is a member of no vocabulary at all, which is not a scope the surface has an
    answer for.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The uses, in the order the browser sent them; the record's own validator
        normalises them to declaration order (ADR-0097 §2).

    Raises:
        _Refused: If the member is absent, is not a list, or names a use that is not
            a member of :class:`~ai_assistant.core.types.GrantScope`.
    """
    if name not in payload:
        raise _malformed()
    selected = _members(payload, name, GrantScope)
    if selected is None:  # pragma: no cover — the membership check above precedes it
        raise _malformed()
    return selected


def _rows(payload: Mapping[str, Any], name: str) -> list[Mapping[str, Any]]:
    """One required member that is a list of JSON objects, and nothing else.

    Required rather than defaulted, because ``set_notification_preferences``
    **replaces** what is held rather than merging into it (ADR-0130 §6): a member this
    reader defaulted to the empty list would clear every quiet window, or every reach
    the user has set, on a request that never mentioned them.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The rows, unread.

    Raises:
        _Refused: If the member is absent, is not a list, or holds anything that is
            not a JSON object.
    """
    value = payload.get(name)
    if not isinstance(value, list) or any(not isinstance(one, dict) for one in value):
        raise _malformed()
    return value


def _member[T: StrEnum](row: Mapping[str, Any], name: str, vocabulary: type[T]) -> T:
    """One required member of a closed vocabulary, on one row.

    The singular of :func:`_members`, and refusing rather than defaulting for the same
    reason ``answer``'s ``accept`` is: a reach the gateway chose would be this adapter
    deciding how far the assistant may go in reaching the user.

    Args:
        row: The object to read.
        name: The member to read.
        vocabulary: The enumeration it must name.

    Returns:
        The member.

    Raises:
        _Refused: If the member is absent or names nothing the vocabulary carries.
    """
    value = row.get(name)
    known = {member.value: member for member in vocabulary}
    if not isinstance(value, str) or value not in known:
        raise _malformed()
    return known[value]


def _count(payload: Mapping[str, Any], name: str) -> int:
    """One required count, as an ordinary JSON number.

    A quiet window's endpoints are what this reads, and ``[0, 1440)`` is a range every
    reader holds exactly — which is why they are numbers where the two members
    :func:`_decimal` reads are strings. Zero is a member of the range and is refused
    by nothing here: midnight is an hour like any other.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent, or is not an integer in ``[0, 2**63)``.
    """
    if name not in payload:
        raise _malformed()
    return _page(payload, name, 0)


def _decimal(payload: Mapping[str, Any], name: str) -> int:
    """One required non-negative integer, spelled as a decimal string.

    The counterpart of :func:`_preferences_view`'s spelling, and it exists for the
    same reason: a JSON number reaches a browser as an IEEE-754 double, so a value
    above ``2**53`` would not survive being read and handed back. Nothing here is
    coerced from a number — a member that arrives as one is refused, because
    accepting it would accept exactly the rounded value the spelling exists to
    prevent, and a client that ships in this distribution knows the shape (ADR-0168
    §10).

    **The length is bounded before the conversion**, which is not fussiness: turning a
    megabyte of digits into an ``int`` is quadratic work a request body can ask for
    free, and no member this reads is more than twenty digits.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value.

    Raises:
        _Refused: If the member is absent, is not a string, or is not a bounded run of
            decimal digits.
    """
    value = payload.get(name)
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise _malformed()
    return int(value)


def _microseconds(payload: Mapping[str, Any], name: str) -> timedelta:
    """One required duration, spelled as a whole number of microseconds.

    Microseconds because that is ``timedelta``'s own resolution: the integer is exact
    in both directions, and a browser holding it as a string hands back the duration
    it was given rather than one rounded on the way through. This is the member the
    page carries and never edits, so the spelling only has to round-trip.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The duration.

    Raises:
        _Refused: If the member is absent, is not a decimal string, or names a
            duration ``timedelta`` cannot hold.
    """
    try:
        return timedelta(microseconds=_decimal(payload, name))
    except OverflowError as exc:
        raise _malformed() from exc


def _preferences(payload: Mapping[str, Any]) -> NotificationPreferences:
    """The whole standing-settings value, as the browser read it and wrote it back.

    **The refusal here is the gateway's own and is named as such.** A body that cannot
    become a :class:`~ai_assistant.core.types.NotificationPreferences` leaves no call
    to relay, so answering it with ``rejected`` — the name :func:`_relay_fault` gives a
    refusal the *hub* authored — would attribute this adapter's refusal to a hub that
    was never asked, which is the fact about the hub ADR-0168 §3 keeps out of a
    refusal body.

    The type's own two refusals ride here for the same reason: two rows naming one
    class, and a quiet window with no readable extent, are refused at construction in
    every client (ADR-0085 §9's "locally and before any I/O"), so the gateway could
    not relay one if it tried. The front end says so in the user's words before it
    sends, which is where a person can act on it.

    Args:
        payload: The request's JSON object.

    Returns:
        The value to write.

    Raises:
        _Refused: If any member is absent, is of the wrong type, or the whole does not
            construct.
    """
    try:
        return NotificationPreferences(
            reaches=tuple(
                ClassReach(
                    notification_class=_required_string(row, "notification_class"),
                    reach=_member(row, "reach", NotificationReach),
                )
                for row in _rows(payload, "reaches")
            ),
            quiet_windows=tuple(
                QuietWindow(start=_count(row, "start"), end=_count(row, "end"))
                for row in _rows(payload, "quiet_windows")
            ),
            interruption_budget=_decimal(payload, "interruption_budget"),
            budget_window=_microseconds(payload, "budget_window_microseconds"),
        )
    except ValueError as exc:
        raise _malformed() from exc


def _credential(payload: Mapping[str, Any]) -> SecretStr:
    """One supplied credential, in its redacting holder (ADR-0125 §3, ADR-0177 §4).

    **Named ``credential`` and read from the body**, which is §4's first two clauses
    arriving together: the value travels in the body of the request that performs the
    act and nowhere else, and it is spelled with the one key ``core/logging.py``
    redacts by name — so a payload mapping that reached a log record anywhere would
    carry ``[redacted]`` rather than the secret. Nothing here renames it or nests it.

    **Wrapped before it is anything else.**
    :func:`~ai_assistant.core.types.secret_value` is ADR-0125 §3's only supported way
    to build one, and revalidating at this door is what makes a blank, unencodable or
    oversized credential a refusal *here* rather than after a frame was built around
    it — the same reasoning ``interfaces/cli._credential`` states one surface over.

    **The refusal is the gateway's own and is named as such**, on
    :func:`_preferences`' precedent: a value that cannot become a ``SecretValue``
    leaves no call to relay, so answering with ``rejected`` — :func:`_relay_fault`'s
    name for a refusal the *hub* authored — would attribute this adapter's refusal to
    a hub that was never asked. It is not ``malformed-request`` either: that name says
    the page and the gateway disagree about the shape (ADR-0168 §10), and a person who
    pasted an empty box has found no such disagreement and can fix this themselves.

    The message is safe to carry: ADR-0125 §6 guarantees it names neither the value
    nor its length.

    Args:
        payload: The request's JSON object.

    Returns:
        The credential, held in a ``SecretStr``.

    Raises:
        _Refused: If the member is absent, is not a string, or is not an admissible
            secret value.
    """
    plaintext = _required_string(payload, "credential")
    try:
        return secret_value(SecretStr(plaintext))
    except ValueError as exc:
        raise _Refused(
            _fault(400, "Bad Request", "credential-unusable", detail=str(exc), close=False)
        ) from exc


def _utterance(payload: Mapping[str, Any]) -> SpokenAudio:
    """One recording, and **never** the recording inside the refusal (ADR-0200 §9).

    §9's last clause binds "every entry point that constructs a ``SpokenAudio`` from a
    value it did not author — the wire server's argument adapter and **the gateway's
    body parse** among them", and it is stated because ``Base64Audio``'s own validator
    naming only the defect and the position "is necessary and not sufficient: a pydantic
    ``ValidationError`` carries the rejected **input** whatever the message says". So the
    construction failure is caught here and answered with a refusal this project wrote,
    ``from None``, carrying no input value and no chained cause.

    **The detail is a fixed sentence rather than the validator's**, which is where this
    differs from :func:`_credential`. ADR-0125 §6 guarantees that a rejected secret's
    message "names neither the value nor its length", so that reader may relay it; §9
    makes the opposite guarantee about this one, and a near-valid clip with one bad
    character is exactly the input an attacker or an unlucky browser produces. What is
    left is the class of defect, which is what a person holding a broken recording can
    act on and is the whole of what they need.

    **Its own condition rather than ``malformed-request``**, on :func:`_credential`'s
    test: ``malformed-request`` says the page and the gateway disagree about the shape
    (ADR-0168 §10), and a recording the browser encoded and this gateway would not take
    is not that disagreement. A member that is absent or is not a JSON object *is*, so
    that half is :func:`_malformed`.

    Args:
        payload: The request's JSON object.

    Returns:
        The recording, ready to relay.

    Raises:
        _Refused: If the member is absent or is not a JSON object, or if it is one the
            promoted surface's own type will not admit.
    """
    value = payload.get("utterance")
    if not isinstance(value, dict):
        raise _malformed()
    try:
        return SpokenAudio.model_validate(value)
    except ValidationError:
        raise _Refused(
            _fault(
                400,
                "Bad Request",
                "recording-unusable",
                detail=(
                    "That recording is not one this gateway can carry. It must name a "
                    "container this surface serves and hold padded, canonical RFC 4648 "
                    "base64 (ADR-0200 §9)."
                ),
                close=False,
            )
        ) from None


def _plays(payload: Mapping[str, Any]) -> tuple[SpokenAudioFormat, ...]:
    """What the browser says it can render, in the preference order it sent them.

    :func:`_uses`' shape and its reasoning, one surface over. **Emptiness is not decided
    here**: ADR-0200 §3 makes ``plays`` "required with no default, and non-empty", and
    the promoted surface refuses an empty one locally and before any I/O — so every
    client gets the same answer and a second rule at this layer could only differ from
    it. What is refused here is a member of no vocabulary at all, which is not a format
    the surface has an answer for.

    **Absent is refused rather than defaulted.** ADR-0177 §1 has the gateway default no
    argument expressing what the user asked for, and this one says what the *browser* can
    play — a value only the browser holds. A gateway that filled it in would be
    promising, on the browser's behalf, to render something it may not be able to.

    Args:
        payload: The request's JSON object.

    Returns:
        The formats, in the order the browser sent them (ADR-0200 §3: the engine renders
        in the first of them its synthesizer also names).

    Raises:
        _Refused: If the member is absent, is not a list, or names a format that is not
            a member of :class:`~ai_assistant.core.types.SpokenAudioFormat`.
    """
    if "plays" not in payload:
        raise _malformed()
    selected = _members(payload, "plays", SpokenAudioFormat)
    if selected is None:  # pragma: no cover — the membership check above precedes it
        raise _malformed()
    return selected


def _delivery(payload: Mapping[str, Any]) -> SpokenDeliveryReport | None:
    """The report the page sends about the answer it last played (ADR-0205 §7).

    **The gateway derives, defaults, composes and invents no part of it.** An absent
    member means no report, and no ``delivery`` then reaches ``converse_spoken`` —
    which is what keeps ADR-0177 §1's fourth clause satisfied rather than widened: the
    one class of argument this adapter supplies of itself is still the caller-owned
    deadline.

    **A member that is present and unusable is refused with this project's own
    words**, ``from None``, carrying no input value and no chained cause — ADR-0200
    §9's stated ground for a refused recording, applied here for its second reason
    rather than its first. A ``ValidationError`` "carries the rejected **input**
    whatever the message says", and while a report holds no audio it does hold an
    episode id, which is a durable name of one of this owner's turns and not a value
    to echo into a fault body a browser will render.

    **Its own condition rather than ``malformed-request``**, on :func:`_utterance`'s
    test: ``malformed-request`` says the page and the gateway disagree about the
    *shape* (ADR-0168 §10), and a well-shaped report whose durations do not satisfy
    ADR-0205 §2's partition is not that disagreement — it is a measurement the page
    took and this surface will not carry. A member that is not a JSON object, and one
    whose nested ``delivery`` is not one, *are* that disagreement, so those halves are
    :func:`_malformed`.

    **The durations are whole microseconds spelled as decimal strings**, which is
    :func:`_microseconds`' convention on this surface and ``timedelta``'s own
    resolution: exact in both directions, so what the page measured is what the row
    records. Each is optional, because ``UNKNOWN`` carries neither — a state this
    surface does not refuse of its own, since the promoted surface refuses it locally
    and before any I/O (ADR-0205 §2) and a second rule here could only differ from it.

    Args:
        payload: The request's JSON object.

    Returns:
        The report, or ``None`` where the body carries none.

    Raises:
        _Refused: If the member is present and is not a JSON object, if its nested
            ``delivery`` is absent or is not one, or if the whole does not construct.
    """
    value = payload.get("delivery")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise _malformed()
    played = value.get("delivery")
    if not isinstance(played, dict):
        raise _malformed()
    try:
        return SpokenDeliveryReport(
            episode_id=_required_string(value, "episode_id"),
            delivery=SpokenDelivery(
                state=_member(played, "state", SpokenDeliveryState),
                played=_optional_microseconds(played, "played_microseconds"),
                rendered=_optional_microseconds(played, "rendered_microseconds"),
            ),
        )
    except ValidationError:
        raise _Refused(
            _fault(
                400,
                "Bad Request",
                "delivery-unusable",
                detail=(
                    "That playback report is not one this gateway can carry. A report "
                    "says how much of one earlier answer was played and how long the "
                    "whole of it was, and the two must agree with the state it names "
                    "(ADR-0205 §2)."
                ),
                close=False,
            )
        ) from None


def _optional_microseconds(payload: Mapping[str, Any], name: str) -> timedelta | None:
    """One duration that may be absent, refusing one that is present and wrong.

    :func:`_microseconds`' spelling with :func:`_optional_string`'s posture: absent is
    ``None`` and never a default, and a member that is there and is not a bounded run
    of decimal digits is the page and the gateway disagreeing about the shape.

    Args:
        payload: The object to read.
        name: The member to read.

    Returns:
        The duration, or ``None`` where the member is absent.

    Raises:
        _Refused: If the member is present and is not a decimal string, or names a
            duration ``timedelta`` cannot hold.
    """
    if name not in payload:
        return None
    return _microseconds(payload, name)


def _token(payload: Mapping[str, Any]) -> ContinuationToken:
    """One continuation, relayed opaquely (ADR-0042 §4, ADR-0177 §8).

    **Wrapped, never read.** The bytes the browser sent are put back into the carrier
    the promoted surface declares and nothing here parses them, branches on them,
    derives anything from them or substitutes one for another — an adapter that
    branched on a token to decide allow/deny would be authoring a permission outcome
    in ``interfaces/``, which is the failure :class:`ContinuationToken` names.

    **A blank handle is ``malformed-request`` rather than a condition of its own.**
    Every token this surface can carry was minted by the engine and disclosed by
    :func:`_confirmation_view`, so a value that cannot be a handle means the page and
    the gateway disagree about the shape, which is exactly what :func:`_malformed`
    reports — unlike :func:`_credential`, where the unusable value was typed by a
    person who can fix it.

    Args:
        payload: The request's JSON object.

    Returns:
        The continuation, ready to relay.

    Raises:
        _Refused: If the member is absent, is not a string, or names nothing.
    """
    handle = _required_string(payload, "token")
    try:
        return ContinuationToken(handle=handle)
    except ValueError as exc:
        raise _malformed() from exc


def _payload(request: Request) -> Mapping[str, Any]:
    """The request's JSON object, or an empty mapping where there is not one.

    A body that is not an object is not distinguished from an absent one on
    purpose: every caller of this reads named members and refuses where one is
    missing, so a second failure mode would be a second way to say the same thing.
    """
    try:
        parsed = json.loads(request.body.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _string(payload: Mapping[str, Any], name: str) -> str | None:
    """One string member of a payload, or ``None`` where it is absent or not one."""
    value = payload.get(name)
    return value if isinstance(value, str) else None


def _integer(payload: Mapping[str, Any], name: str, fallback: int) -> int | None:
    """One integer member of a payload, its default where absent, ``None`` where wrong.

    ``bool`` is excluded rather than coerced, for the reason ``Settings`` excludes it
    from every count it holds: it is an ``int`` by inheritance, so ``{"limit": true}``
    would otherwise be a page of one that nothing downstream could tell from a
    request for a page of one.

    Args:
        payload: The request's JSON object.
        name: The member to read.
        fallback: What an absent member means.

    Returns:
        The value, the fallback, or ``None`` where the member is present and is not
        an integer.
    """
    if name not in payload:
        return fallback
    value = payload[name]
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _json(payload: Mapping[str, Any]) -> bytes:
    """Encode a response body."""
    return json.dumps(payload).encode("utf-8")


def _frame(value: Mapping[str, Any]) -> bytes:
    """One stream value, framed as a chunk of a chunked body (ADR-0175 §1, §2)."""
    return render_chunk(streams.encode(value))


async def _write_value(writer: asyncio.StreamWriter, value: Mapping[str, Any]) -> None:
    """Write one value on a stream and wait for it to leave.

    The drain is awaited rather than fired and forgotten, because it is what applies
    the browser's own backpressure to the turn: a page that cannot keep up should
    slow the writer down rather than have the gateway buffer an answer on its behalf.
    An answer stream "has one reader and nothing to protect from it", so ADR-0175
    §4's abandonment clause does not reach one and there is nothing here to race the
    drain against.
    """
    writer.write(_frame(value))
    await writer.drain()


def _rendered(payload: Mapping[str, Any]) -> Response:
    """A successful answer the engine returned, rendered as JSON (ADR-0168 §1)."""
    return _json_response(200, "OK", payload)


def _json_response(status: int, reason: str, payload: Mapping[str, Any]) -> Response:
    """One JSON body on a connection that survives it."""
    return Response(
        status, reason, body=_json(payload), content_type="application/json", close=False
    )


def _ceiling() -> Response:
    """``gateway_max_hub_connections`` reached, named as ADR-0168 §8 requires.

    "A browser request needing one beyond it is refused, naming the limit — never
    queued, and never served by opening a further connection." A gateway serving a
    delivery stream holds one of these permanently (ADR-0175 §7), so this is one
    request nearer than the figure reads.
    """
    return _fault(
        503,
        "Service Unavailable",
        "hub-connection-ceiling",
        limit="gateway_max_hub_connections",
        close=False,
    )


def _relay_fault(exc: Exception) -> Response:
    """One failed relay, kept apart from the other two (ADR-0168 §9).

    §9 requires a transport failure "distinguishable from a request the hub received
    and declined" and forbids ever presenting one "as an answer". The gateway does
    not retry, does not queue, and answers from nothing of its own.
    """
    if isinstance(exc, TransportError):
        return _fault(502, "Bad Gateway", "hub-unreachable", detail=str(exc), close=False)
    if isinstance(exc, AssistantError):
        return _fault(
            422, "Unprocessable Content", "assistant-declined", detail=str(exc), close=False
        )
    return _fault(400, "Bad Request", "rejected", detail=str(exc), close=False)


#: What this project says about each way a transcription can fail (ADR-0200 §4). A
#: table rather than a rendering of the exception, because §8's authorship rule reaches
#: whatever handler renders one: what may be written for a seam failure "is §4's
#: ``SpeechFailure`` classification and this project's own message for it".
#:
#: The messages are the owner's, not an operator's: the person reading this pressed a
#: button and spoke, and what they can do about it is press it again or type instead.
_TRANSCRIPTION_DETAIL: Final[Mapping[SpeechFailure, str]] = {
    SpeechFailure.TIMED_OUT: (
        "The recording was not turned into words in time. A shorter press is the "
        "thing most likely to work; typing the question works either way."
    ),
    SpeechFailure.UNCLASSIFIED: (
        "The recording could not be turned into words. Nothing was asked and nothing "
        "was answered; ask again, or type the question."
    ),
}


def _spoken_fault(exc: Exception) -> Response:
    """One failed spoken turn, named as ADR-0200 §4 classifies it.

    **The classification is the answer and no message carries it.** §4 puts a
    ``SpeechFailure`` on :class:`~ai_assistant.core.errors.TranscriptionFailedError`
    precisely because the seam's own exception does not cross — the error is raised
    ``from None`` so that "neither its message, nor its class name, nor its traceback
    reaches a caller" — and "what a caller can act on travels here instead". A gateway
    that flattened it into :func:`_relay_fault`'s single ``assistant-declined`` would
    leave the page inferring it from prose, which is the inference ADR-0151 §7 forbids
    one surface over for the same reason.

    **And the detail is this project's own text, never the exception's** (ADR-0200 §8).
    "No component on this path writes an exception message it did not author … not into a
    surfaced error", and that binds "whatever handler renders an exception that escapes
    them" — this one. :data:`_TRANSCRIPTION_DETAIL` is what is written instead;
    ``details_elided`` needs no reading here, because ``UNCLASSIFIED`` is answered with
    the same sentence whether the classification was lost in ADR-0085 §10a's reduction or
    the seam raised a bare ``SpeechError``, and neither gives the owner a different act.

    **A ``ValidationError`` is answered by its class and nothing else**, which is §8's
    own instruction for a handler that cannot render an exception without its message: a
    pydantic error carries the rejected input whatever the message says (ADR-0200 §9),
    and on this path that input is a recording. It reaches here only from a defect —
    :func:`_utterance` has already answered the browser's own malformed value — so what
    is owed is that it not carry audio out, not that it be classified.

    Everything else is ADR-0168 §9's three conditions, unchanged.

    Args:
        exc: What the relayed call raised.

    Returns:
        The response to answer instead.
    """
    if isinstance(exc, TranscriptionFailedError):
        return _fault(
            422,
            "Unprocessable Content",
            "transcription-failed",
            detail=_TRANSCRIPTION_DETAIL[exc.failure],
            failure=exc.failure.value,
            close=False,
        )
    if isinstance(exc, ValidationError):
        return _fault(400, "Bad Request", "rejected", detail=type(exc).__name__, close=False)
    return _relay_fault(exc)


def _stream_fault(exc: Exception) -> dict[str, Any]:
    """The same three conditions, as a stream's terminal value (ADR-0175 §2, §3).

    The names match :func:`_relay_fault`'s exactly, so the page describes a fault
    that arrived on a stream with the words it already has for one that arrived as a
    response — which is what keeps ADR-0168 §9's distinction alive on this carrier
    rather than leaving it at the status code a stream cannot revise.
    """
    if isinstance(exc, TransportError):
        return streams.fault("hub-unreachable", detail=str(exc))
    if isinstance(exc, AssistantError):
        return streams.fault("assistant-declined", detail=str(exc))
    return streams.fault("rejected", detail=str(exc))


def _fault(  # noqa: PLR0913 — one parameter per member a fault body may carry, and the enumeration is the point
    status: int,
    reason: str,
    fault: str,
    *,
    detail: str | None = None,
    limit: str | None = None,
    reference: str | None = None,
    failure: str | None = None,
    close: bool = True,
) -> Response:
    """A machine-readable refusal or failure the front end renders as its own condition."""
    body: dict[str, Any] = {"fault": fault}
    if detail is not None:
        body["detail"] = detail
    if limit is not None:
        body["limit"] = limit
    if reference is not None:
        body["reference"] = reference
    if failure is not None:
        body["failure"] = failure
    return Response(status, reason, body=_json(body), content_type="application/json", close=close)


def _connection_fault(exc: Exception) -> Response:  # noqa: PLR0911 — one return per condition ADR-0151 §7 and §8 classify, and the enumeration is the point
    """One failed connection act, classified as ADR-0151 §7 and §8 classify it.

    **The class is the answer and no other value carries it.** §7 has a client
    resolve a provisioning act's outcome "from two facts the act knows", both of
    which reach a caller only as the exception's type — so a surface that answered
    all seven with :func:`_relay_fault`'s single ``assistant-declined`` would oblige
    the page to infer them from a message, which §7 forbids by name. Each condition
    therefore keeps its own ``fault``, in the shape ADR-0168 §6 already requires of
    a refusal and §9 of a relay: its own condition, never flattened into another.

    **The one that must not be got wrong is the last.**
    :class:`~ai_assistant.core.errors.ResidualCredentialError` means the act
    **completed** — after a re-provisioning the reference is connected at the new
    revision, after a disconnection it has no live record — and what failed is a
    deletion. ADR-0151 §8 is explicit that "no client reports it as a failed
    connection or a failed disconnection", and a name shared with the failures above
    it is exactly that report.

    **The order is by specificity and not by preference.**
    :class:`~ai_assistant.core.errors.UnknownConnectionError` and
    :class:`~ai_assistant.core.errors.DisplacedProvisioningError` are subclasses of
    :class:`~ai_assistant.core.errors.ConnectionStoreError`, and the three say
    opposite things: the first is refused before the first write, the second means no
    record this act wrote is the live one, and the bare class leaves the act's outcome
    *not known*. A chain testing the base first would report all three as the third.

    **The reference crosses where the class carries one**, because after
    ``connect_account`` it is the only handle the caller will ever have — §3 minted it
    inside the act and no result came back. It is a non-secret value ADR-0149 §3 makes
    loggable, which is what makes it safe in a body the identity beside it is not.
    An **empty** member is not an absent one (ADR-0085 §10a nulls ``details`` before
    it truncates a message), so it is reported as lost rather than rendered as empty.

    **What is *not* here is a second call.** §7 resolves an unread state by reading
    ``connected_accounts``, and that read is the browser's own request: ADR-0177 §1
    forbids this adapter composing one operation out of two, so the page issues it and
    this function states only what the act itself said.

    Args:
        exc: The failure the act raised.

    Returns:
        The fault to answer with.
    """
    detail = str(exc)
    if isinstance(exc, UnusableIdentityError):
        return _fault(422, "Unprocessable Content", "identity-unusable", detail=detail, close=False)
    if isinstance(exc, ResidualCredentialError):
        return _fault(
            422,
            "Unprocessable Content",
            "residual-credential",
            detail=detail,
            reference=exc.reference or None,
            close=False,
        )
    if isinstance(exc, IncompleteProvisioningError):
        return _fault(
            422,
            "Unprocessable Content",
            "provisioning-incomplete",
            detail=detail,
            reference=exc.reference or None,
            close=False,
        )
    if isinstance(exc, ProvisioningOutcomeUnknownError):
        return _fault(
            422,
            "Unprocessable Content",
            "provisioning-outcome-unknown",
            detail=detail,
            reference=exc.reference or None,
            close=False,
        )
    if isinstance(exc, UnknownConnectionError):
        return _fault(
            422, "Unprocessable Content", "no-such-connection", detail=detail, close=False
        )
    if isinstance(exc, DisplacedProvisioningError):
        return _fault(
            422, "Unprocessable Content", "provisioning-displaced", detail=detail, close=False
        )
    if isinstance(exc, ConnectionStoreError):
        return _fault(
            422, "Unprocessable Content", "connection-store-unread", detail=detail, close=False
        )
    return _relay_fault(exc)


def _outcome_view(outcome: TurnOutcome) -> dict[str, Any]:
    """Translate one turn into what the page renders, member by member.

    An enumeration rather than a dump of the model, for ADR-0168 §6's reason one
    level out: the page renders what this returns, so what may appear in it is
    decided here rather than by whatever a future ``TurnOutcome`` happens to
    carry.

    **The answer is carried in addition to the step account, never in place of
    it** (ADR-0170 §6). ``reply`` and ``reply_degraded`` sit beside the notices,
    the plan and the step, and none of those is dropped on the ground that a reply
    is now present: the deterministic account is what this system guarantees about
    what it did, the composed answer is not, and where the two disagree the
    account is correct by construction. ``reply_degraded`` is carried rather than
    inferred from a ``None`` ``reply``, because §4 gives ``reply`` three ``None``
    shapes and only one of them is a composition that failed — the flag is what
    lets the page tell "no answer was owed" from "an answer was owed and could not
    be composed".

    The answer crosses to the page verbatim and is neutralised *there*, by being
    inserted as text and never as markup (ADR-0168 §6). That is this adapter's
    half of ADR-0170 §8's rule that every adapter neutralises engine-supplied
    text for its own output — what :func:`interfaces.cli._safe` is on the CLI's
    side, applied to the same value the plan's rationale already crosses under.

    It carries what the CLI's ``_render_turn`` renders, because the two adapters
    render the same turn — but that is a resemblance, not a mechanism, and this
    docstring used to claim the two mirrored each other *exactly*. They cannot:
    the enumeration above is what the page may see, so a member added to
    ``TurnOutcome`` reaches a browser only when it is added here as well.
    ``reply`` reached the CLI when ADR-0170 landed and did not reach this view
    until issue #1337 — a turn's answer was composed, returned, and dropped one
    layer short of the person who asked for it.
    """
    turn = outcome.turn
    plan = None if turn is None else turn.plan
    steps = () if plan is None else plan.steps
    return {
        "conversation_id": outcome.conversation_id,
        "capture_degraded": outcome.capture_degraded,
        "memory_degraded": turn is not None and turn.memory_degraded,
        "reply": outcome.reply,
        "reply_degraded": outcome.reply_degraded,
        "rationale": None if plan is None else plan.rationale,
        "steps": [{"intent": one.intent, "capability": one.capability} for one in steps],
        "step": _step_view(outcome.step),
        "routed": _routed_view(outcome.routed),
    }


def _spoken_view(turn: SpokenTurn) -> dict[str, Any]:
    """Translate one spoken turn into what the page renders (ADR-0200 §4).

    An enumeration for :func:`_outcome_view`'s reason, and **the turn inside it is that
    function's own answer** rather than a second rendering of one: ADR-0200 §4 makes the
    ``outcome`` "an ordinary ``TurnOutcome``, under every clause ADR-0170 §4, ADR-0173 §6
    and ADR-0197 §8 place on one", and "this call composes a turn; it does not create a
    second kind of one". A view that forked would be the second place #1337's failure can
    happen — a member added to the turn's own view reaching two of the three ask entries.

    **``heard`` crosses on every call that produced a transcript**, which is §4's own
    disclosure clause and not a convenience: "a push-to-talk surface that cannot show the
    user what it heard cannot be corrected by them, and a transcript the hub acted on but
    never showed is the one part of this path a user has no other way to inspect". It
    crosses byte for byte — nothing here strips, trims or case-folds it — and reaches the
    page as text and never as markup, exactly as ``reply`` does (ADR-0168 §6).

    **``spoken_degraded`` is carried rather than inferred from a ``None`` ``spoken``**,
    for the reason ``reply_degraded`` is: §4 gives ``spoken`` two ``None`` shapes and only
    one of them is an answer that could not be spoken, so the flag is what lets the page
    tell "there was nothing to say" from "there was, and saying it did not complete".

    **``episode_id`` crosses because the page has to hand it back** (ADR-0205 §1, §7).
    It is the name of the turn a later report is about, and §7 requires the page to send
    "the one the response carrying that rendering disclosed and never one it derived,
    counted or guessed" — so the value has to reach the page for there to be one to
    send. Disclosing it confers nothing: there is one principal on this hub (ADR-0099
    §1), no route of this surface takes an episode id, and this decision adds none.

    Args:
        turn: What the promoted surface returned.

    Returns:
        The five members, with the outcome rendered by :func:`_outcome_view`.
    """
    return {
        "heard": turn.heard,
        "outcome": None if turn.outcome is None else _outcome_view(turn.outcome),
        "spoken": None if turn.spoken is None else _audio_view(turn.spoken),
        "spoken_degraded": turn.spoken_degraded,
        "episode_id": turn.episode_id,
    }


def _audio_view(audio: SpokenAudio) -> dict[str, Any]:
    """One rendering, as the two members ADR-0200 §9 gives it.

    The base64 text crosses **unchanged**, which is `Base64Audio`'s own posture: "what a
    caller passed is what crosses the wire and what ``decoded()`` reverses", and a value
    this adapter re-encoded would be a second spelling of one recording. Nothing here
    decodes it either — §4 is explicit that "no component decodes, re-transcribes or
    otherwise inspects a rendering", and a gateway that measured one would be doing so
    on the one path ADR-0200 §8 keeps audio off every record of.
    """
    return {"content": audio.content, "media_type": audio.media_type.value}


def _step_view(step: StepOutcome | None) -> dict[str, Any] | None:
    """Translate the step this pass drove, keeping the gate's verdict apart from the outcome.

    **The disposition is the gate's verdict; the named step's ``status`` and
    ``failure`` are the outcome** — the rule ``AssistantEngine.converse`` states
    and issue #531 is the cost of ignoring. A ``status`` of ``None`` therefore
    means "not known here", never "fine": it is the parked step, the step the gate
    did not execute, and the execution record that could not be addressed.
    """
    if step is None:
        return None
    view: dict[str, Any] = {
        "disposition": step.disposition.value,
        "tool_id": step.tool_id,
        # **The confirmation whole, never a boolean** (#1404, ADR-0178 §10). This view
        # is an explicit enumeration, so nothing about it carrying ADR-0178 §7's
        # content is automatic: "a gateway that shipped the approval control while
        # enumerating none of it would satisfy every test above". What the page needs
        # in order to *put* ADR-0148 §8's question is here or it is nowhere.
        "confirmation": (
            None if step.confirmation is None else _confirmation_view(step.confirmation)
        ),
        "status": None,
        "failure": None,
    }
    if step.confirmation is not None or step.disposition is not Disposition.EXECUTED:
        return view
    named = [one for one in step.state.steps if one.step_id == step.step_id]
    if not named:
        return view
    execution = named[0]
    view["status"] = execution.status.value
    if execution.failure is not None:
        view["failure"] = {
            "message": execution.failure.message,
            "kind": None if execution.failure.kind is None else execution.failure.kind.value,
        }
    return view


def _confirmation_view(confirmation: Confirmation) -> dict[str, Any]:
    """One parked action, as the page must be able to put it (ADR-0178 §7).

    An enumeration for :func:`_outcome_view`'s reason, and here the reason is
    ADR-0178 §10's in terms: ``_step_view`` reduced a whole confirmation to one
    boolean, so a browser could show an approval control having rendered none of what
    ADR-0148 §8's fourth clause requires. **All five content members cross**, and the
    fifth is ``egress``.

    **Absence is carried as absence** (ADR-0178 §4). A ``CONFIRM`` whose recorded
    decision carries no egress binding crosses with ``egress`` ``null`` and nothing
    stands in for it — no empty span list, no placeholder identity. What that states is
    that the ruling was taken over no egress binding and nothing more, so neither this
    view nor the page reads it as a warrant that the call transmits nothing.

    **The token crosses because the page has to relay it back and for no other
    reason** (ADR-0177 §8). It is disclosed as the opaque handle it is; the page parses
    no part of it, renders it nowhere and stores it in no browser storage, and this
    gateway mints none, rewrites none and substitutes none.

    Every value crosses as **data** and is neutralised on the page by being inserted
    through a text node (ADR-0042 §4, ADR-0175 §9) — the new members included, because
    ``argument`` is a caller-influenced key (ADR-0150 §13) and a ``supplied`` form is a
    string a model produced.
    """
    return {
        "token": confirmation.token.handle,
        "tool_id": confirmation.tool_id,
        "tool_description": confirmation.tool_description,
        "parameters": [
            {"key": key, "value": _parameter_text(value)}
            for key, value in confirmation.parameters.items()
        ],
        "reason": confirmation.reason,
        "egress": None if confirmation.egress is None else _egress_view(confirmation.egress),
    }


def _parameter_text(value: FrozenJson) -> str:
    """One argument's value, spelled here rather than by the page.

    **Rendered whole and losslessly, which is why it is text and not the JSON value.**
    ADR-0177 §8 requires ``parameters`` rendered "every key and every value the mapping
    carries", and a JSON number crossing to a browser is read by ``JSON.parse`` into a
    double: an integer argument above 2**53 would reach the person *changed*, and a
    confirmation showing a value the call would not run with is worse than one showing
    none. This is :func:`_preferences_view`'s losslessness rule and :func:`_decimal`'s,
    reaching the one member of this surface whose contents nothing constrains.

    A string crosses as itself, so the common case reads as the person wrote it; every
    other JSON value is spelled in JSON, which is the notation it arrived in. Nothing
    here truncates, abbreviates or summarises.

    Args:
        value: The argument's value, as the tool would receive it.

    Returns:
        The text the page displays beside the key.
    """
    if isinstance(value, str):
        return value
    # ``default=dict`` is what carries a ``FrozenDict``: it is a ``Mapping`` and not a
    # ``dict``, so the encoder reaches for it exactly where one is nested, and a tuple
    # (which is what a frozen JSON array is) already encodes as an array.
    return json.dumps(value, ensure_ascii=False, default=dict)


def _egress_view(egress: ConfirmationEgress) -> dict[str, Any]:
    """ADR-0148 §8's fourth clause, as the page receives it (ADR-0178 §7).

    Three things, and a confirmation naming the tool and not the recipients is not a
    confirmation of an egress call: the connected account's **identity**, the canonical
    destination set **in both forms**, and the **payload description**.

    **The set is read from** :attr:`ConfirmationEgress.canonical_destination_set`
    **in this process** and crosses as `core` derived it. ADR-0178 §3 forbids a second
    derivation of one fact in another language: a deduplication, an account
    substitution and a code-point order reimplemented in a page's script are business
    logic in an adapter (golden rule 3), and a page that got any of the three wrong
    would show a recipient set the ruling was not taken over. So the arithmetic
    happens here, once, and the page renders what it was handed.

    **The set and the occurrences both cross, and that is not redundancy.** They answer
    different questions: the set is what the policy ruled over and is deduplicated, so
    it answers "how many people is this going to"; the occurrences are ADR-0150 §10's
    third clause, so one recipient named by ``to`` and again by ``bcc`` is one member
    of the set and **two** disclosures. A surface showing only the set has hidden a
    disclosure; one showing only the occurrences has shown a list the user must
    deduplicate in their head.

    **``planned_with_external_content`` is ADR-0181 §6's addition beside that floor,
    and is not a fourth member of it.** §6 extends ADR-0178 §7's first clause "by one
    fact and changes none of its others", so the three above keep their meaning, their
    derivation and their order, and this crosses alongside them. It crosses at all
    because the page cannot obtain it by any other route: ADR-0178 §3 forbids a
    surface inferring a fact with a rule of its own or reimplementing one in another
    language, so the value the ruling was taken over is read here, in this process,
    off the model `core` built, and the page renders what it was handed (#1445).

    **It is one boolean and it is not a verdict.** Nothing here scores, ranks or
    thresholds it, and no key beside it says what the page should conclude — the
    wording is the page's to render in both states (§6's fourth clause), and §7's
    first clause bars any surface from presenting it as a detection.
    """
    return {
        "account_identity": egress.account_identity,
        "destinations": [_destination_view(one) for one in egress.canonical_destination_set],
        "spans": [_span_view(one) for one in egress.spans],
        "planned_with_external_content": egress.planned_with_external_content,
    }


def _destination_view(member: ConfirmationDestination) -> dict[str, Any]:
    """One member of the derived set, in the two shapes and no third (ADR-0178 §3).

    A *selected recipient* carries a protocol and a canonical form; *the connected
    account* carries an account identity. The view keeps all three keys on both shapes
    with ``null`` where the member holds nothing, so the page branches on the same
    absence the model does rather than on a tag this adapter invented.

    Nothing here orders, deduplicates or substitutes: the order is
    ``canonical_destination_set``'s own — account members first, then selected
    recipients by protocol and then by canonical form — and it arrives that way.
    """
    return {
        "account_identity": member.account_identity,
        "protocol": None if member.protocol is None else member.protocol.value,
        "canonical": member.canonical,
    }


def _span_view(span: EgressSpan) -> dict[str, Any]:
    """One occurrence of the payload description, whole (ADR-0150 §4, ADR-0178 §7).

    **A description, never the payload.** A span states an argument, a position, a
    provenance, an extent and sometimes a tier; it holds no content, so nothing that
    crosses here is the text and nothing the page can build from it is a claim about
    what the text says.

    **Both forms where the occurrence carries a destination, and neither invented where
    it does not.** :attr:`EgressSpan.destination` is optional, and where it is absent
    this carries ``null`` rather than a fabricated recipient — the page renders such a
    span as the payload-description span it is. Where it is present both ``supplied``
    and ``canonical`` cross, because ADR-0148 §14 names reconstruction of one from the
    other as a failure in terms and the binding carries both so neither is guessed.
    """
    destination = span.destination
    return {
        "argument": span.argument,
        "index": span.index,
        "provenance": span.provenance.value,
        "extent": span.extent,
        "tier": None if span.tier is None else span.tier.value,
        "destination": (
            None
            if destination is None
            else {
                "protocol": destination.protocol.value,
                "supplied": destination.supplied,
                "canonical": destination.canonical,
            }
        ),
    }


def _summary_view(summary: ConversationSummary) -> dict[str, Any]:
    """One conversation, as a person choosing which to continue reads it (ADR-0074 §2).

    An enumeration for ``_outcome_view``'s reason: what may appear on the page is
    decided here rather than by whatever a future ``ConversationSummary`` carries.

    **Both instants cross, and they are different facts.** ``last_active_at`` is when
    someone was last here and is the listing's sort key; ``last_turn_at`` is when a
    turn was last *recorded*, and is what tells an empty conversation from one whose
    first turn landed instantly. A page showing only one of them would be unable to
    render that distinction, and ADR-0074 §2 is explicit that ordering by "has a turn
    landed" sinks a conversation the user opened a minute ago below one they
    abandoned last week.
    """
    return {
        "id": summary.id,
        "started_at": summary.started_at.isoformat(),
        "last_active_at": summary.last_active_at.isoformat(),
        "last_turn_at": None if summary.last_turn_at is None else summary.last_turn_at.isoformat(),
    }


def _digest_view(digest: ConversationDigest) -> dict[str, Any]:
    """What a person is shown before consenting to destroy one (ADR-0074 §8).

    "The count and the span" rather than a transcript — printing every turn would be
    something nobody can read, and printing nothing would be consent to destroy
    something unseen. ``recorded_turns`` counts recorded turns and not surviving
    episodes, which is the ceremony's own fact rather than a report on content.
    """
    return {
        "id": digest.id,
        "started_at": digest.started_at.isoformat(),
        "last_turn_at": None if digest.last_turn_at is None else digest.last_turn_at.isoformat(),
        "recorded_turns": digest.recorded_turns,
    }


def _source_view(source: GrantableSource) -> dict[str, Any]:
    """One grantable source, as the page that offers a grant reads it (ADR-0102 §6).

    ``location`` crosses because a client "renders each ``location`` and takes an
    explicit act from the user before it calls ``grant``" (ADR-0139 §5), and it comes
    to rest nowhere: it is on this response and on no stored record, in no log and in
    no export (ADR-0097 §9a).

    ``live`` is the hub's own computation from the ``revokes`` relation and is
    relayed rather than re-derived (ADR-0102 §3). A gateway that answered it by
    walking ``recent_grants`` would report a withdrawn grant as live the moment a
    clock had been corrected backwards.
    """
    return {
        "source": source.source,
        "location": source.location,
        "live": None if source.live is None else _grant_view(source.live),
    }


def _grant_view(grant: SourceGrant) -> dict[str, Any]:
    """One grant or revocation, as the record says it happened (ADR-0097 §4).

    ``scope`` carries **exactly** the uses the record names, in the record's own
    normalised order. Nothing is added and nothing is dropped: ADR-0139 §3's third
    clause forbids a rendering that adds a use a grant does not name or omits one it
    does, and a view that padded the tuple to three members would have made that
    failure the front end's only option.

    ``revokes`` crosses because it is what distinguishes a revocation from a grant on
    a history page, and it is **not** a liveness computation: ADR-0102 §3 forbids
    presenting a record from ``recent_grants`` as live or as withdrawn on its own,
    and the front end says so rather than inferring it from this field.
    """
    return {
        "id": grant.id,
        "source": grant.source,
        "scope": [use.value for use in grant.scope],
        "decided_at": grant.decided_at.isoformat(),
        "revokes": grant.revokes,
    }


def _belief_fields(belief: Belief | BeliefSummary) -> dict[str, Any]:
    """What ADR-0073 §4 requires **both** belief views to convey.

    The band, the confidence, the kind, the content, when it was last revised, the
    end of its validity window where one is set, and the id. The three citation
    counts travel too, because §4's floor for a ``DERIVED`` belief is that the
    surface conveys "how many citations stand behind it" and must not "present a
    derived belief as carrying a warrant it cannot show" — and ADR-0107 §5 owes the
    elision ceiling beside any rendered count, which needs ``evidence_elided``.

    **The confidence is the presented one**, already lowered for support that has
    gone (ADR-0077 §6). Nothing here computes it, which is what stops two surfaces
    quoting different figures for one belief.

    ``unsupported`` is carried rather than left to the page to compute, so the one
    definition ADR-0085 §4a states holds on both types and on this surface too.

    **ADR-0189 §2's two fields cross too, and without them the browser cannot render
    at all.** §9 obliges ``whyHeld`` to name the reporting source and state the instant
    that source said the fact was current, and this function is the whole of the wire
    to that page: a belief reaching the front end is what this dict says it is and
    nothing more. The pair is carried on **both** belief views under one name, which is
    ADR-0107 §3's ruling one field over — a listing row that answered less than the row
    it links to is the same projection defective in one place.
    """
    return {
        "id": belief.id,
        "band": belief.band.value,
        "kind": belief.kind.value,
        "content": belief.content,
        "confidence": belief.confidence,
        "last_updated": belief.last_updated.isoformat(),
        "valid_until": None if belief.valid_until is None else belief.valid_until.isoformat(),
        "evidence_count": belief.evidence_count,
        "lost_evidence": belief.lost_evidence,
        "evidence_elided": belief.evidence_elided,
        "unsupported": belief.unsupported,
        "attestation": _attestation_view(belief.attestation),
        "rests_on_recorded_external_content": belief.rests_on_recorded_external_content,
    }


def _attestation_view(attestation: Attestation | None) -> dict[str, Any] | None:
    """What reported a record and when that source said so (ADR-0092 §1, ADR-0189 §2).

    Carried **whole** rather than as two members beside each other, which is ADR-0092
    §2's argument reaching the wire: two independent nullable members admit four
    states, of which two are half-answers — a source with no instant renders "your
    calendar had this as of …" with a blank, and an instant with no source attributes
    it to nobody. One optional object with two required members makes both of those
    unconstructable here exactly as they are on the record.

    ``reported_at`` crosses as the **source's** clock and is never substituted for by
    ``last_updated``, which crosses separately and is declared to be ours (ADR-0073
    §4, ADR-0189 §4).

    ``extent`` is deliberately not carried. ADR-0189 §2 rides it along on the model —
    "``Attestation.extent`` rides along and nothing renders it, deliberately" — and §10
    leaves its rendering to ADR-0117, so no surface has a rule for it and putting it on
    this wire would ship a value with no consumer (ADR-0045 §1).
    """
    if attestation is None:
        return None
    return {
        "reported_by": attestation.reported_by,
        "reported_at": attestation.reported_at.isoformat(),
    }


def _warrant_view(warrant: Warrant | None) -> dict[str, Any] | None:
    """How a retired record is held, and where its warrant came from (ADR-0189 §2, §3).

    The one projection that carries no standing of its own, so its three facts cross as
    one object: a warrant that exists is always whole, because all three are resolved
    together by one ``MemoryStore.get`` or not at all. ``None`` is the case ADR-0045 §6
    produces — the store hides a closed window, ``content`` is ``null`` too, and the
    page renders it as *no longer held* while asserting nothing about band, origin or
    source.

    ``band`` crosses **inside** the warrant rather than beside it on the retirement,
    because ADR-0189 §3 rules that a projection carries each fact in exactly one place:
    a second path to one fact is a second thing that can disagree.
    """
    if warrant is None:
        return None
    return {
        "band": warrant.band.value,
        "rests_on_recorded_external_content": warrant.rests_on_recorded_external_content,
        "attestation": _attestation_view(warrant.attestation),
    }


def _belief_summary_view(summary: BeliefSummary) -> dict[str, Any]:
    """One row of the listing, which ships counts and **not** citations.

    The split is the type's rather than this function's (ADR-0085 §4a): a
    :class:`~ai_assistant.core.types.BeliefSummary` has nowhere to put a citation, so
    a conforming listing cannot ship the corpus on every page and this view could not
    render one if it tried.
    """
    return _belief_fields(summary)


def _belief_view(belief: Belief) -> dict[str, Any]:
    """The single-belief view: the same fields, plus the resolved warrant.

    A citation that no longer resolves crosses as an entry whose ``content`` is
    ``null`` — a **tombstone**, never a bare id and never a silent gap (ADR-0073 §4's
    floor, ADR-0077 §6). :class:`~ai_assistant.core.types.Evidence` carries no id at
    all, so no renderer downstream can pass one off as the warrant.
    """
    return _belief_fields(belief) | {"evidence": [_evidence_view(one) for one in belief.evidence]}


def _evidence_view(evidence: Evidence) -> dict[str, Any]:
    """One citation, resolved to what it says or tombstoned (ADR-0077 §6)."""
    return {"content": evidence.content}


def _question_view(question: Question) -> dict[str, Any]:
    """One deferred question, with everything ADR-0078 §8 requires it to convey.

    What accepting would have the assistant believe and the band it **would** enter —
    carried as the conditional it is, because "a pending question is not a belief of
    any band"; why the user is being asked; why the proposal was made; what accepting
    would retire, "which is not decoration but the exact scope the answer authorises";
    when it was asked and until when it is answerable; its state, which is what tells
    an interrupted question from an open one; and any successor an answer already
    raised, with **that** question's own state (§9).

    **Two origins cross, they are about different records, and confusing them is the
    error ADR-0189 §2 legislates against.** ``attestation`` and
    ``rests_on_recorded_external_content`` at the top level describe the **proposal** —
    the record that would be written if the question were accepted — on the same
    reading ``band`` already has here. Each entry in ``retires`` answers for itself
    through its own ``warrant``, which is the field that lets the page tell an
    attacker-authorable line the user is being asked to overrule from this system's own
    sentence (#673): a question proposing the user's own assertion routinely retires an
    attested calendar entry, so one answer could never have served for both.
    """
    return {
        "id": question.id,
        "state": question.state.value,
        "content": question.content,
        "kind": question.kind.value,
        "band": question.band.value,
        "rationale": question.rationale,
        "reason": question.reason,
        "retires": [
            {
                "record_id": one.record_id,
                "content": one.content,
                "warrant": _warrant_view(one.warrant),
            }
            for one in question.retires
        ],
        "asked_at": question.asked_at.isoformat(),
        "expires_at": None if question.expires_at is None else question.expires_at.isoformat(),
        "successor": _successor_view(question.successor),
        "attestation": _attestation_view(question.attestation),
        "rests_on_recorded_external_content": question.rests_on_recorded_external_content,
    }


def _successor_view(successor: SuccessorLink | None) -> dict[str, Any] | None:
    """The question an answer already raised, carried **with its state** (ADR-0078 §9).

    The state is not optional decoration: only a waiting successor is something the
    user can go and answer, and naming a declined or interrupted one as "the follow-on
    question" would advertise something they cannot act on.
    """
    if successor is None:
        return None
    return {"id": successor.id, "state": successor.state.value}


def _read_view(record: SourceReadRecord) -> dict[str, Any]:
    """One recorded read attempt, whole (ADR-0185 §2, ADR-0186 §7's last two clauses).

    **All seven of the record's fields cross**, because a surface that cannot render a
    row whole renders fewer rows and not partial ones. Nothing here truncates,
    summarises, samples or counts in place of any part of one.

    **What is deliberately absent is what the record does not hold.** There is no
    content, no entry, no path and no configured location, and no string derived from
    any of them: ``source`` is the reader's *declared identity* and ``produced`` is a
    count rather than a thing. A view reaching for "what did it say" would be reaching
    for something ADR-0004 §5 and ADR-0093 §8 forbid being written down.
    """
    return {
        "id": record.id,
        "source": record.source,
        "use": record.use.value,
        "checked_at": record.checked_at.isoformat(),
        "outcome": record.outcome.value,
        "grant": record.grant,
        "produced": record.produced,
    }


def _invocation_view(recorded: RecordedInvocation) -> dict[str, Any]:
    """One recorded act on an authorisation (ADR-0192 §4).

    **One attempt is up to two rows and they cross as the two rows they are.**
    ``completes`` is what tells a claim from a completion, carried rather than
    inferred, because nothing here pairs them, counts them as one or renders either
    in the other's vocabulary.

    **The cost crosses as text**, for :func:`_decimal`'s reason: an amount read by
    ``JSON.parse`` is a double, and a price the tool reported would reach the owner
    changed. ``basis`` is the discriminator and it is not derivable from the amount —
    ``FREE`` and ``UNKNOWN`` are different statements and neither is a number.
    """
    row = recorded.invocation
    cost = row.incurred_cost
    return {
        "id": row.id,
        "recorded_at": row.recorded_at.isoformat(),
        "completes": row.completes,
        "decision_id": row.decision_id,
        "tool": recorded.tool,
        "capability": recorded.capability,
        "egress_call": recorded.egress_call,
        "outcome": None if row.outcome is None else row.outcome.value,
        "failure_kind": None if row.failure_kind is None else row.failure_kind.value,
        "cost": (
            None
            if cost is None
            else {
                "basis": cost.basis.value,
                "amount": None if cost.amount is None else str(cost.amount),
                "currency": cost.currency,
            }
        ),
    }


def _decision_view(decision: PermissionDecision) -> dict[str, Any]:
    """One recorded ruling, as ADR-0186 §7 enumerates it.

    §7's own fields — the outcome, the reason, the instant, and the recorded
    declaration's identifier and capability, read from the row and never from a
    registry — plus the decision's own id, because §7's resolution clause obliges an
    answer to *name* the question it answers.

    **What is deliberately not carried is as load-bearing.** ``reads``, ``writes`` and
    ``discloses`` are absent (§8's fifth clause): they are ceilings on what a tool
    *may* reach rather than per-call measurements, and a tier reach beside a recipient
    list would assert the measurement ADR-0016 §3 declines to offer. Nothing here
    computes :meth:`PermissionDecision.authorises` either (§8's second clause).

    **The digest is a digest** (§8's fourth clause). It is what binds the arguments a
    ruling was taken over, and it is neither the payload nor expandable into one.

    **``authorised_by`` and ``resolves`` both cross, and the page reads the state off
    the pair** (ADR-0193 §6, §11). The discriminator is whether ``resolves`` is set,
    with no field added to carry the basis itself, so a view that pre-computed the
    state would be putting §6's discriminator in a second place.

    **A row carrying a ``resolves`` and a *different* ``authorised_by`` is not a
    ruling this surface reads at all**, and ``unreadable`` is that fact carried.
    ADR-0193 §11 names exactly three states and this pair is none of them; the trail
    refuses to record one (``InvalidResolutionError``), so a row reaching a reader
    with it is a value no store this system wrote would hold. ``interfaces.cli``
    raises there and the whole listing ends. This marks the **row** instead, for a
    reason that is about where the row is: a routed listing rides a turn, so raising
    would take the reply and the routed account with it — a reader losing what did
    happen because one row cannot be read. Either way nothing guesses: §11's line is
    not rendered, neither pointer is presented as the authorisation, and the row's
    other fields are not rendered beside a ruling this surface has declined to read.
    Adversarial review's round-2 blocker, and correct that a fourth state was being
    invented.
    """
    return {
        "id": decision.id,
        "unreadable": _is_unreadable_ruling(decision),
        "outcome": decision.ruling.outcome.value,
        "reason": decision.ruling.reason,
        "decided_at": decision.decided_at.isoformat(),
        "tool_id": decision.tool.id,
        "capability": decision.tool.capability,
        "parameters_digest": decision.parameters_digest,
        "resolves": decision.resolves,
        "authorised_by": decision.ruling.authorised_by,
        "binding": _recorded_binding_view(decision.egress_binding),
    }


def _is_unreadable_ruling(decision: PermissionDecision) -> bool:
    """Whether this row's authorisation pointers contradict each other (ADR-0193 §11).

    The condition ``interfaces.cli._authorisation_line`` raises
    :class:`~ai_assistant.core.errors.InvalidResolutionError` on, spelled as a
    predicate: a ruling that **answers** one decision while **resting on** another.
    §11 names three states and this is none of them, and no ruling an audit trail
    accepts carries both — ``InvalidResolutionError``'s own subject includes "when
    the resolving ruling's ``authorised_by`` does not match its ``resolves``".

    ``authorised_by`` unset is the policy's own rules and ``resolves`` unset is a
    standing authorisation, so neither is this: both must be present and differ.
    """
    authorised_by = decision.ruling.authorised_by
    resolves = decision.resolves
    return authorised_by is not None and resolves is not None and authorised_by != resolves


def _recorded_binding_view(
    binding: EgressBinding | OriginUnrecordedBinding | None,
) -> dict[str, Any] | None:
    """The binding a ruling was taken over, in ADR-0178 §7's facts (ADR-0186 §7).

    :func:`_egress_view`'s facts, because they *are* the same facts — ADR-0178 §5
    builds a ``ConfirmationEgress`` from the recorded decision, so a second wording
    would be a second vocabulary to keep in step with the first. What changes is the
    **labels**, and that change is ADR-0186 §8's third clause: a card says where a
    call is going because it has not gone; a row says what a ruling was taken over,
    because the trail bounds resolutions and no row knows whether anything ran.

    **A ``None`` binding asserts nothing** (§7's fourth clause): it means the request
    was not an egress call and continues to mean exactly that, so nothing stands in
    for it.

    **``origin_unrecorded`` is ADR-0184 §2's arm carried rather than inferred.** Such
    a row states nothing either way about the material the call was planned over, and
    a page reading a missing boolean as ``false`` would turn "not recorded" into "no
    external content", which is a claim the record does not make.
    """
    if binding is None:
        return None
    unrecorded = isinstance(binding, OriginUnrecordedBinding)
    return {
        "account_identity": binding.account.identity,
        "origin_unrecorded": unrecorded,
        "planned_with_external_content": (
            None
            if isinstance(binding, OriginUnrecordedBinding)
            else binding.planned_with_external_content
        ),
        "destinations": [
            _recorded_destination_view(member) for member in binding.canonical_destination_set
        ],
        "spans": [_span_view(span) for span in binding.spans],
    }


def _recorded_destination_view(member: CanonicalDestination) -> dict[str, Any]:
    """One member of a recorded canonical destination set (ADR-0186 §7).

    :func:`_destination_view`'s shape, so the page renders both sets through one
    function: the two member types differ only in their **account** arm, and
    flattening that here is what lets ADR-0178 §7's recipient wording be written once.
    """
    return {
        "account_identity": None if member.account is None else member.account.identity,
        "protocol": None if member.protocol is None else member.protocol.value,
        "canonical": member.canonical,
    }


def _spend_view(total: SpendTotal) -> dict[str, Any]:
    """One period's total, as ADR-0194 §5 and §6 require it to be read.

    **An absence is carried as the state it is, and ``currency`` is what tells the two
    apart.** ``currency`` ``null`` means no currency is configured and no total was
    computed; a present ``currency`` beside ``accounted`` ``null`` means the period
    could not be measured. A view that collapsed them would tell an owner "no total"
    while their calls are being refused.

    **The amounts cross as text**, for :func:`_decimal`'s reason: a ceiling read by
    ``JSON.parse`` is a double, and a ceiling the owner set would reach them changed.

    **Each bound crosses already rendered from its own offset**, which is ADR-0194 §6
    in terms: "each bound rendered from the value's **own**
    ``start_offset``/``end_offset`` and labelled with that offset — never from the
    client's zone and never through the client's ``tzdata``". So the arithmetic is
    ``interfaces.cli._bound``'s, done here rather than on the page: a browser doing it
    would be doing date arithmetic with a zone database beside it, and §5's bar is on
    exactly that. An earlier shape of this view crossed the UTC instant beside the
    offset label, which renders a bound in one offset labelled with another —
    adversarial review's round-2 blocker, and correct.
    """
    return {
        "period": total.period.value,
        "period_start": _bound_text(total.period_start, total.start_offset),
        "period_end": _bound_text(total.period_end, total.end_offset),
        "start_offset": _offset_text(total.start_offset),
        "end_offset": _offset_text(total.end_offset),
        "ceiling": None if total.ceiling is None else str(total.ceiling),
        "currency": total.currency,
        "accounted": None if total.accounted is None else str(total.accounted),
    }


def _bound_text(instant: datetime, offset: timedelta) -> str:
    """Spell one period bound in its own offset (ADR-0194 §6).

    ``interfaces.cli._bound``'s arithmetic, because it is the same fact reaching a
    second surface and §6 states it of the bound rather than of a command: the
    instant is shifted by the offset the value carries and rendered as wall time, so
    what a reader sees is the boundary the ledger used. **No zone database is
    consulted here or on the page** — §5 bars the client's ``tzdata`` and this is the
    only arithmetic that would have wanted one.

    **A fraction of a second survives, from either side of the addition**, exactly as
    it does on the CLI: the instant is a ``UtcInstant`` and may carry microseconds,
    and so may the offset, so a fixed ``%H:%M:%S`` states a boundary a microsecond
    off the one the ledger used.
    """
    shifted = instant.replace(tzinfo=None) + offset
    stamp = shifted.strftime("%Y-%m-%d %H:%M:%S")
    return stamp if not shifted.microsecond else f"{stamp}.{shifted.microsecond:06d}"


def _offset_text(offset: timedelta) -> str:
    """Spell a UTC offset as ``+HH:MM``, or ``+HH:MM:SS`` where seconds are in force.

    ``interfaces.cli._offset_label``'s rule, because it is the same fact reaching a
    second surface: a zone whose offset carries seconds is rare and real, and
    truncating one would state a bound the ledger did not use.

    **A sub-second offset keeps its fraction**, for that helper's own reason:
    :class:`~ai_assistant.core.types.SpendTotal` admits an offset "at whatever
    resolution it has", and reading it through ``total_seconds()`` truncated
    ``timedelta(microseconds=-500_000)`` to ``+00:00``, sign and all. Nothing
    produces such an offset today; what makes it worth closing is that the
    truncation is silent and states a bound the ledger did not use.
    """
    micros = (
        offset.days * _SECONDS_A_DAY + offset.seconds
    ) * _MICROS_A_SECOND + offset.microseconds
    sign = "-" if micros < 0 else "+"
    seconds, fraction = divmod(abs(micros), _MICROS_A_SECOND)
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    stem = f"{sign}{hours:02d}:{minutes:02d}"
    if not seconds and not fraction:
        return stem
    stem = f"{stem}:{seconds:02d}"
    return stem if not fraction else f"{stem}.{fraction:06d}"


#: A view for **every** arm of ADR-0197 §8's :data:`RoutedListing`, which is what
#: §10's "the listing where one is carried" requires of an adapter and admits no
#: exception for an arm this page had no panel for.
#:
#: **Four of the seven had no view before this lane and now do.** ADR-0177 §1's
#: enumeration has never admitted ``recent_reads``, ``recent_invocations``,
#: ``recent_decisions`` or ``spend_totals`` to a *browser request*, and ADR-0186 §6
#: and §10 keep it that way — but that bar is on the **route** and not on the
#: rendering. A routed pass makes no browser request for any of them: the hub decided
#: the route (ADR-0197 §12), and what reaches this adapter is a result it must render
#: or misreport. Withholding it and naming the CLI instead was this lane's first
#: shape and adversarial review blocked it correctly: §10 is unqualified, and a
#: referral is a turn that did something rendered as a turn that did nothing.
#:
#: What each of the four owes is inherited rather than invented — ADR-0186 §7's
#: enumeration and §8's bars for a ruling and a read, ADR-0192 §4's two-rows rule for
#: an act, ADR-0194 §5 and §6 for a total — and each view above states which.
#:
#: This does **not** widen ADR-0177 §1: no path resolves to any of the four, no
#: browser argument reaches one, and ``test_gateway_decisions.py`` and
#: ``test_gateway_reads.py`` still pin that. A browser *panel* for them is the later
#: consumer lane ADR-0186 §6 names, and is #1642.
_ROUTED_ARM_VIEWS: Final[Mapping[type[BaseModel], Callable[[Any], dict[str, Any]]]] = {
    Belief: _belief_view,
    Question: _question_view,
    SourceGrant: _grant_view,
    SourceReadRecord: _read_view,
    RecordedInvocation: _invocation_view,
    PermissionDecision: _decision_view,
    SpendTotal: _spend_view,
}


def _routed_view(routed: RoutedOperation | None) -> dict[str, Any] | None:
    """Translate what one routed pass did into what the page renders (ADR-0197 §10).

    An enumeration for :func:`_outcome_view`'s reason, and the roster guard in
    ``tests/interfaces/gateway/test_gateway.py`` is what makes the decision to carry
    it visible: ``routed`` reached ``TurnOutcome`` in PR #1634 and was recorded there
    as "not in this change", which this lane flips.

    **The discriminator is** ``operation`` **and never the value's shape** (§8). The
    arm is read through :func:`~ai_assistant.core.types.routed_listing_arm` — ``core``'s
    own total mapping — because "an empty tuple is a legal value of every arm, so the
    shape decides nothing on exactly the case a listing is most likely to take".

    **Every arm crosses as its records**, which is §10's "the listing where one is
    carried" and admits no exception for an arm this page had no panel for.
    :data:`_ROUTED_ARM_VIEWS` is total over the seven, and an earlier shape of this
    lane that withheld four of them was blocked on review: a referral where a listing
    should be is a turn that did something rendered as a turn that did nothing, which
    is ADR-0197's own stated cost of ignoring the member.

    **The token crosses because the page has to relay it back and for no other
    reason** (ADR-0177 §8), exactly as :func:`_confirmation_view`'s does: it is
    disclosed as the opaque handle it is, the page parses no part of it, renders it
    nowhere and stores it nowhere, and this gateway mints none and rewrites none.

    Every value crosses as **data** and is neutralised on the page by being inserted
    through a text node (ADR-0042 §4, ADR-0197 §10's last clause). A belief's content
    is the user's own words and a grant's source is the identity a reader declared,
    neither of which may reach a browser as markup.

    Args:
        routed: What the pass routed to, or ``None`` where it routed nothing.

    Returns:
        The routed account, or ``None`` where there is none.
    """
    if routed is None:
        return None
    confirmation = routed.confirmation
    return {
        "operation": routed.operation.value,
        "outcome": routed.outcome.value,
        "listing": (
            None if routed.listing is None else _routed_records(routed.operation, routed.listing)
        ),
        "confirmation": (
            None
            if confirmation is None
            else {
                "operation": confirmation.operation.value,
                "token": confirmation.token.handle,
                "subject": _routed_records(confirmation.operation, confirmation.subject),
            }
        ),
    }


def _routed_records(operation: RoutableOperation, listing: RoutedListing) -> list[dict[str, Any]]:
    """Render one routed listing, record by record (ADR-0197 §10).

    **The discriminator is** ``operation`` **and never the value's shape** (§8): the
    arm is read through :func:`~ai_assistant.core.types.routed_listing_arm` — ``core``'s
    own total mapping — because "an empty tuple is a legal value of every arm, so the
    shape decides nothing on exactly the case a listing is most likely to take".

    **Every record, in the listing's own order** (§5's last clause): "no surface
    renders fewer candidates than the outcome carries or summarises in place of
    them". There is no bound here, no slice and no count standing in for a row.

    Args:
        operation: The routed operation, which is the discriminator.
        listing: The records carried beside it.

    Returns:
        One view per record, in the order the listing carries them.
    """
    view = _ROUTED_ARM_VIEWS[routed_listing_arm(operation)]
    return [view(one) for one in listing]


def _answer_view(outcome: AnswerOutcome) -> dict[str, Any]:
    """What one answer did, as one of five outcomes (ADR-0078 §5, §9).

    ``successor_refused`` and ``disposed`` travel **beside** the outcome and never in
    place of it: a re-deferral that could queue no follow-up at all is not the same
    as one that did, and a question destroyed while its answer was being applied is a
    true statement about the bookkeeping rather than about the answer.
    """
    return {
        "kind": outcome.kind.value,
        "question_id": outcome.question_id,
        "record_id": outcome.record_id,
        "successor": _successor_view(outcome.successor),
        "successor_refused": outcome.successor_refused,
        "disposed": outcome.disposed,
    }


def _notification_view(record: HeldNotification, *, now: datetime) -> dict[str, Any]:
    """One held notification, as a person deciding what to do with it reads it.

    An enumeration for ``_outcome_view``'s reason, and a **different** one from
    :func:`ai_assistant.interfaces.gateway.streams.notification`: that view renders a
    *delivery* arriving on a stream and carries three members, this one renders the
    *record* the review surface acts on and carries the id those two verbs take.
    ADR-0177 §10 is why they are two functions rather than one reused — a
    ``delivery_id`` reaches no browser, and there is no member here that could carry
    one.

    **No confidence, no sensitivity, no references and no goal cross**, exactly as
    they do not on the delivery view: ADR-0130 §4 separates the evidence from the
    ruling, and a page showing a producer's confidence beside a notification would be
    presenting the first as though it were the second. ``candidate_key`` is the
    duplicate-suppression key and is nobody's business but the store's;
    ``reconsider_at`` and ``retention`` are the reconsideration job's bookkeeping and
    say nothing a person can act on.

    **The producer's own name crosses**, which the command line already renders
    ("noticed by …"): "who noticed this" is the first thing a person asks of an
    unexpected notification, and it is engine-supplied text the page neutralises
    exactly as it neutralises a summary (ADR-0177 §10's fifth clause, ADR-0099 §4).

    **``expired`` is the record's own predicate asked at one clock reading, not a
    comparison restated here.** ADR-0130 §7 requires a surface enumerating a record to
    say which side of its expiry it is on, and no field answers it — so
    :meth:`~ai_assistant.core.types.NotificationCandidate.is_perishable_at`, "spelled
    once so that a policy, a store and a suite cannot disagree about" the boundary, is
    asked rather than reimplemented, here or in JavaScript. What this adapter supplies
    is the reading, which is what the command line's own renderer supplies too.

    **The two stamped limbs of actionability are carried as stamps and not folded in**
    (ADR-0130 §7). A dismissal and a reconsideration's ``DROP`` were stamped by the
    hub; expiry is the limb with nothing stored. Asking
    :meth:`~ai_assistant.core.types.HeldNotification.is_actionable_at` for all three
    would put the two stamped ones behind this device's clock as well, so a gateway
    running behind the hub would offer a dismissal on a record the hub had already
    dismissed.

    Args:
        record: The record the engine returned.
        now: The instant the whole page is judged at, tz-aware.

    Returns:
        The value to render.
    """
    candidate = record.candidate
    return {
        "id": record.id,
        "notification_class": candidate.notification_class,
        "producer": candidate.producer,
        "summary": candidate.summary,
        "detail": candidate.detail,
        "noticed_at": candidate.noticed_at.isoformat(),
        "expires_at": None if candidate.expires_at is None else candidate.expires_at.isoformat(),
        "expired": candidate.expires_at is not None and not candidate.is_perishable_at(now),
        "kind": record.kind.value,
        "reason": record.reason.value,
        "failed": [condition.value for condition in record.failed],
        "ruled_at": record.ruled_at.isoformat(),
        "admitted_at": record.admitted_at.isoformat(),
        "dismissed_at": (None if record.dismissed_at is None else record.dismissed_at.isoformat()),
        "dropped_at": None if record.dropped_at is None else record.dropped_at.isoformat(),
    }


def _preferences_view(preferences: NotificationPreferences) -> dict[str, Any]:
    """The three standing settings, whole, so a browser can write them back (§6).

    **Every member the type carries crosses**, which is not this view's usual rule and
    is required by ADR-0177 §10's fourth clause: the write replaces what is held, so a
    browser that read a partial value and sent it back would clear whatever this view
    dropped. ``budget_window`` in particular is on no form the page offers and travels
    for exactly that reason.

    The window's endpoints are the type's own spelling — minutes since local midnight,
    carrying no zone and unable to smuggle one in — and are rendered rather than
    converted here. They are ordinary JSON numbers because ``[0, 1440)`` is a range
    every reader holds exactly.

    **The other two travel as decimal strings, and that is a losslessness decision
    rather than a stylistic one.** A JSON number is read into an IEEE-754 double by
    the one reader that matters here, so an integer above ``2**53`` does not survive
    the trip: ``interruption_budget`` is bounded at ``2**63`` and
    ``NotificationPreferences.budget_window`` is a ``timedelta`` whose resolution is a
    microsecond, and both would be silently rounded on their way to a browser that is
    only carrying them so it can hand them back. §10's fourth clause makes that a
    defect and not a rounding: a browser changing a reach would overwrite a budget
    nobody touched. A decimal string crosses exactly, and the page never converts one
    it did not ask the user for.

    **The duration is spelled in microseconds** because that is ``timedelta``'s own
    resolution, so the integer is exact in both directions and no fraction has to be
    parsed anywhere.
    """
    return {
        "reaches": [
            {"notification_class": row.notification_class, "reach": row.reach.value}
            for row in preferences.reaches
        ],
        "quiet_windows": [
            {"start": window.start, "end": window.end} for window in preferences.quiet_windows
        ],
        "interruption_budget": str(preferences.interruption_budget),
        "budget_window_microseconds": str(preferences.budget_window // _MICROSECOND),
    }


def _account_view(account: ConnectedAccount) -> dict[str, Any]:
    """One live connection record, member for member (ADR-0151 §4).

    **Four members, and the three the type does not have are the point.** There is no
    credential slot and no ``SecretName`` — the slot is `tools`-internal (ADR-0149 §3)
    and a caller holding one could reach the keyring by the route the seam was built
    to close — no endpoint, and no timestamp. This view adds none of them, and in
    particular adds no member derived from the credential (ADR-0177 §4's sixth
    clause), which is what makes a read-back unreachable rather than merely absent.

    **The identity crosses byte for byte** (ADR-0151 §5). Nothing here strips,
    case-folds, case-normalises or Unicode-normalises it, and the page inserts it as
    text and never as markup — this adapter's half of ADR-0170 §8, applied to a value
    that is Tier 1 personal data and reaches no log line on either side.

    **The revision crosses as a decimal string**, which is
    :func:`_preferences_view`'s losslessness rule reaching a member the browser only
    reads. ``revision`` is an ``int`` with no upper bound in the type, and ADR-0151 §4
    requires it "reported as the store holds it: nothing renumbers, compacts, offsets
    or resets it" — a JSON number cannot promise that above ``2**53``, because the one
    reader that matters here parses it into an IEEE-754 double. A rounded revision is
    a wrong fact shown to the owner rather than a rounding.
    """
    return {
        "reference": account.reference,
        "identity": account.identity,
        "revision": str(account.revision),
        "state": account.state.value,
    }


def _connection_act_view(act: ConnectionAct) -> dict[str, Any]:
    """One act on one reference, as the store recorded it (ADR-0151 §4, §9).

    **A removal is the absence of ``account`` and never a third state.** ADR-0149 §5
    forbids one, and ADR-0151 §4 records that an earlier draft's ``kind``
    discriminator was refused as "a fourth promoted type encoding a distinction one
    optional field already carries unambiguously" — so ``null`` crosses as the
    absence it is and the page reads the discrimination off it.

    **No instant is added**, because a connection record has none (ADR-0149 §3). The
    row's position is the order the store recorded the acts in and nothing more, and
    a view that stamped one here would manufacture the timing claim ADR-0151 §9
    forbids every client from making.
    """
    return {
        "reference": act.reference,
        "revision": str(act.revision),
        "account": None if act.account is None else _account_view(act.account),
    }


def _observation_view(report: ObservationReport) -> dict[str, Any]:
    """What one observation pass did (ADR-0077 §8).

    The three discard counts are kept **apart** because they are three different
    facts: what the producer could not use, what it dropped over its own limit, and
    what the write path refused for want of support. A single "not stored" figure
    would be this adapter deciding they are the same thing.

    ``route`` is absent where no model read the episodes at all, which is a fact
    about the pass rather than a missing field.
    """
    return {
        "proposals": [_proposal_view(one) for one in report.proposals],
        "discarded_unusable": report.discarded_unusable,
        "discarded_over_limit": report.discarded_over_limit,
        "dropped_unsupported": report.dropped_unsupported,
        "route": report.route,
        "conversation_id": report.conversation_id,
        "episodes_read": report.episodes_read,
    }


def _proposal_view(proposal: ObservedProposal) -> dict[str, Any]:
    """One proposal an observation pass made, with how memory folded it.

    ``decision`` is ``null`` where **no ruling was ever made** — the proposal never
    reached the write path — which is a different thing from a ruling that rejected
    it, and the two are not flattened into one.
    """
    return {
        "content": proposal.content,
        "kind": proposal.kind.value,
        "step": proposal.step.value,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "decision": None if proposal.decision is None else proposal.decision.value,
        "record_id": proposal.record_id,
        "reason": proposal.reason,
        "evidence": [_evidence_view(one) for one in proposal.evidence],
    }


async def _close(writer: asyncio.StreamWriter) -> None:
    """Close one connection, tolerating a peer that closed first.

    **The suppression here is not what stops a reset escaping `_handle`, and issue
    #1370 is the evidence.** `connection_lost` hands the *same* exception object to
    the reader and to the close waiter, so a reset noticed first by a read raises
    once out of :meth:`Gateway._next`, and then again out of ``wait_closed`` below
    — where it is caught, but not before the interpreter has prepended this frame
    to the traceback the first raise is still carrying. What an operator then reads
    names this function for an exception this function swallowed. The read and the
    response write are where it is actually answered.
    """
    writer.close()
    with contextlib.suppress(ConnectionError, OSError):
        await writer.wait_closed()


def default_defer() -> Defer:
    """Schedule on the running event loop.

    The gateway's own scheduling seam, injected rather than reached for so a test
    drives a twelve-hour session in an instant. This is the production half.

    Returns:
        A callable scheduling one callback after a delay.
    """

    def defer(delay: float, callback: Callable[[], None]) -> Cancellable:
        return asyncio.get_running_loop().call_later(delay, callback)

    return defer


def utcnow() -> datetime:
    """The wall-clock reading a gateway process stamps its records with.

    The same module-level clock convention every subsystem uses, named so that
    :func:`run_gateway` composes it and a test substitutes it.
    """
    return datetime.now(UTC)


#: The name of the signal ADR-0182 §1 makes "the whole of the act", written out
#: because the disclosure hands it to an owner to type. ``SIGHUP`` is deliberately
#: not it: ``service/hub.py`` already installs that as the ignored signal on
#: ADR-0083 §13's "a restart is the reload", "and a terminal hangup delivers it,
#: which would mint a live admission ticket every time an owner closed a window".
_MINT_SIGNAL: Final = "SIGUSR1"


def _mint_on_the_act(
    gateway: Gateway,
    disclose: Callable[[Disclosure], None],
    report: Callable[[Note], None],
    act: MintAct,
) -> None:
    """Perform one mint act, and survive a disclosure that fails (ADR-0182 §1).

    "A failed later mint does not stop the gateway, and the asymmetry with §5 is
    deliberate": §5's refusal to start "protects an owner from a gateway answering
    a port with a value nobody can present", where here "sessions are already live,
    and stopping would end all of them to punish a convenience act that failed".

    The two exceptions caught are the two a discloser has: the
    :class:`AssistantError` this system's own adapter raises when standard output
    refuses a write, and the raw ``OSError`` a plainer one would let through.
    Anything else is a fault in the composition rather than in the owner's terminal,
    and it reaches the loop's exception handler rather than being reported as a
    disclosure that failed.

    Args:
        gateway: The running gateway.
        disclose: How the value reaches the owner.
        report: How the failure reaches them instead.
        act: The act to name in the disclosure — this one, since a gateway that
            could not install it never reaches here.
    """
    try:
        gateway.mint_bootstrap(disclose, act=act)
    except AssistantError, OSError:
        report(Note.MINT_NOT_DISCLOSED)


def _install_the_mint_act(
    *,
    gateway: Gateway,
    disclose: Callable[[Disclosure], None],
    report: Callable[[Note], None],
) -> MintAct | None:
    """Install ADR-0182 §1's disposition, or degrade in the two ways §1 names.

    **Called before the start disclosure and not at the listener**, which §1 orders
    that way for a reason adversarial review found on its eleventh round:
    ``run_gateway`` "mints and discloses before it serves, so a disposition
    installed when the listener starts would leave a window in which the start
    disclosure has already named a process id and a signal the gateway would still
    die of".

    **Ignoring is the first fallback because the default action is to terminate.**
    "A gateway that cannot install it **starts anyway** rather than refusing to
    serve" — but it "sets ``SIGUSR1`` to **ignored** if it can, because the signal's
    default action is to terminate, and a process holding live sessions may not be
    left killable by the one signal its own disclosure names". Where even that
    fails, §1 has the gateway report the signal unsafe and "name the act in no
    disclosure", which is what returning ``None`` makes true of every disclosure
    that follows.

    **``add_signal_handler`` fails for reasons that are not about the platform**,
    "a loop composed off the main thread being the ordinary one", which is why the
    fallbacks are reached by ordinary exceptions rather than by a platform test.
    ``AttributeError`` is in both tuples for the narrower case of a platform with no
    such signal at all — one this system runs no hub on (§1), reported under the
    same note because a signal that cannot be delivered is not one to send either.

    Args:
        gateway: The gateway the act mints at.
        disclose: How a minted value reaches the owner.
        report: How an unavailable act reaches them, at start.

    Returns:
        The act to name in every disclosure, or ``None`` where there is none to
        name.
    """
    act = MintAct(signal=_MINT_SIGNAL, pid=os.getpid())
    handler = partial(_mint_on_the_act, gateway, disclose, report, act)
    try:
        asyncio.get_running_loop().add_signal_handler(signal.SIGUSR1, handler)
    except AttributeError, NotImplementedError, OSError, RuntimeError, ValueError:
        pass
    else:
        return act
    try:
        signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    except AttributeError, OSError, ValueError:
        report(Note.MINT_ACT_UNSAFE)
    else:
        report(Note.MINT_ACT_IGNORED)
    return None


def _release_the_mint_act(act: MintAct | None) -> None:
    """Drop the disposition once the listener is down (ADR-0182 §1).

    §1 has the gateway hold it "until its listener is shut down", so it is released
    here rather than left to the process exit — and only where one was installed,
    since restoring the default on the degraded path would re-arm the very
    termination the ignore was there to prevent.

    Args:
        act: What :func:`_install_the_mint_act` returned.
    """
    if act is None:
        return
    with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
        asyncio.get_running_loop().remove_signal_handler(signal.SIGUSR1)


async def run_gateway(
    *,
    settings: Settings,
    engine: AssistantEngine,
    disclose: Callable[[Disclosure], None],
    report: Callable[[Note], None],
    now: Callable[[], datetime] = utcnow,
) -> None:
    """Install the act, mint, disclose, then serve — the order ADR-0182 §1 fixes.

    "A gateway that cannot disclose its bootstrap value does not start, and
    reports why", so the disclosure happens **before** the listener is bound: a
    gateway that bound first and then failed to print would be answering a port
    with a value nobody can present.

    **The mint act's disposition is installed before that disclosure**, because
    ADR-0182 §1 orders it against the disclosure rather than against the listener:
    every disclosure of a gateway that can perform the act names the act and this
    process's id, and one named before the disposition exists is an instruction to
    send a signal whose default action would end the process.

    **Every origin is disclosed, not just the loopback one** (ADR-0174). The owner
    reads the value off this terminal and carries it to another device, and the
    address to type there is the overlay one — a disclosure naming only
    ``127.0.0.1`` would hand them a value and no door to spend it at. On a gateway
    with no remote listener this is the single origin it has always printed.

    **The agent is built only where a remote listener needs one**, from
    ``client_overlay_agent_socket`` — the field ADR-0174 §8 widens rather than
    duplicating: "a gateway may dial its hub over loopback and still serve browsers
    over the overlay, so the condition widens to cover a set
    ``gateway_remote_address``. No eleventh agent-socket field is owed, and the
    custody conditions ``wire/overlay.py`` enforces on that socket are applied
    unchanged." Those conditions are enforced by :func:`local_agent` itself, which
    refuses a configured path an untrusted user could answer on.

    Args:
        settings: The loaded configuration.
        engine: The hub, as the promoted ``AssistantEngine``. Built by whoever
            composes this process — the gateway builds no engine (ADR-0168 §1).
        disclose: How a bootstrap value and everything beside it reach the owner.
            Raising from it is what stops the gateway starting — and, at a later
            mint act, what ADR-0182 §1 has the gateway report and keep serving
            through.
        report: How the conditions of ADR-0182 §1 that carry no value reach the
            owner: an unavailable mint act at start, and a later mint that could
            not be disclosed.
        now: The clock. It decides sessions and records; ADR-0182 §3's bound is on
            the deferral seam's monotonic time and reads nothing from here.

    Raises:
        AssistantError: If the bootstrap value cannot be disclosed, if the overlay
            agent's configured socket fails its custody conditions, or if the remote
            browser listener is configured in a way that could never serve.
    """
    gateway = Gateway(
        settings=settings,
        engine=engine,
        now=now,
        defer=default_defer(),
        bundle=packaged_bundle(),
        agent=_agent_for(settings),
    )
    act = _install_the_mint_act(gateway=gateway, disclose=disclose, report=report)
    try:
        gateway.mint_bootstrap(disclose, act=act)
        await gateway.serve()
    finally:
        _release_the_mint_act(act)


def _agent_for(settings: Settings) -> OverlayAgent | None:
    """This machine's overlay agent, where a remote browser listener needs one.

    Args:
        settings: The loaded configuration.

    Returns:
        The agent, or ``None`` where no remote listener is configured and none is
        read. Building one eagerly would put a configured socket's custody check on
        the path of every gateway, including the loopback-only one ADR-0168 §2 rules
        and which never asks the agent anything.

    Raises:
        ConfigurationError: If a configured socket path fails the custody conditions
            ``wire/overlay.py`` holds both ends of ADR-0124 §4's hop to.
    """
    if settings.gateway_remote_address is None:
        return None
    return local_agent(settings.client_overlay_agent_socket, terms=CLIENT_AGENT_SOCKET)
