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
unadmitted request and a refused one each return before :meth:`Gateway._assistant`,
the one method through which this class reaches the engine.

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

**A browser reaches a closed enumeration of operations** (ADR-0177 §1,
superseding ADR-0175 §6's first clause and its figure of five; ADR-0285 §6 took
``observe`` out of it, ADR-0293 §11 retires ``converse_streaming``, and ADR-0309
§5:4 and ADR-0313 §3:4 retire ``converse`` and ``converse_spoken`` with the Ask panel
and push-to-talk; this gateway serves none of the three). Among those served here:
``recent_conversations``, ``conversation`` and ``forget_conversation``, together
with the grant surface — ``grantable_sources``, ``grant``, ``revoke``,
``recent_grants``, ``standing_grants`` — the belief surface — ``beliefs``,
``belief``, ``forget``, and ADR-0329 §18:2's ``pending_candidates``, which the belief
panel calls — the notification *review* surface — ``notifications``,
``dismiss_notification``, ``forget_notification``, ``notification_preferences``,
``set_notification_preferences`` — and the connection surface —
``connect_account``, ``reprovision_account``, ``disconnect_account``,
``connected_accounts``, ``recent_connection_acts``. ADR-0296's record on ADR-0177
§1:1 adds the chat space's acts in the medium and its change read (ADR-0293 §11:2) —
``start_conversation``, ``my_devices``, ``set_my_devices``,
``set_conversation_devices``, ``write_message``, ``delete_message``,
``delete_conversation``, ``transcript`` and ``chat_changes`` — and its record on §1:5
the one value the gateway supplies of its own for them: the browser's device.
ADR-0332 §5:9 adds ``composing`` to those acts in the medium, "an act in the medium
that writes nothing into it", and §5:10 has this gateway serve it.
``next_notification`` remains the gateway's **own** poll and is none of them,
because no browser request resolves to it — :class:`.delivery.DeliveryFanOut`
originates it, no browser request names it, and no browser argument reaches it
(ADR-0175 §6's second clause, bound unchanged by ADR-0177 §1).

**What is left out is named, and the enumeration is no weaker for it.** The
confirmation, question, goal and authorization operations — ``pending_confirmations``,
``resume``, ``cancel_read``, ``questions``, ``interrupted_questions``, ``answer``,
``forget_question``, ``goals``, ``withdraw_clarification``, ``abandon_goal``,
``standing_authorizations`` and ``revoke_authorization`` — retire with their panels
(ADR-0309 §5); ``learn`` is admitted by nothing and stays unreached until its own
ratified decision (§11). The form is what ADR-0168 §6 chose it for — "naming what
may appear is the only form that stays right when a later lane adds a request shape
nobody has thought of yet".

**Two of them are narrower than the rest, and the narrowing is about
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

**A third listener serves the hosted owner through the sign-in edge, and it too is off
unless it is configured on** (ADR-0327). The edge — our own sign-in service, a program
outside this repository — holds a person's sign-in on the box behind the door's HTTPS,
and forwards each of their requests to this listener over the box's loopback with an
assertion it signs. That hop is the fifth egress boundary (§3:1). The listener binds
where only the box reaches it (§5), speaks plain HTTP to the edge (§5:6), and admits a
request on two facts: the edge's assertion, which :mod:`.edge` checks against keys
configured at setup and nothing fetched, and a live web session (§7:5). Its session is
minted by an exchange of the assertion with nothing typed (§8), it serves no bootstrap
exchange, and every browser it admits is the one hosted browser device the operator
named (§10). Its refusals on the assertion, the `Host` and the `Origin` are one refusal
(§7:6); its session refusals are ADR-0168's, unchanged.

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
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import partial
from importlib import resources
from typing import TYPE_CHECKING, Any, Final

import structlog
from pydantic import SecretStr, ValidationError

from ai_assistant.core.device_context import acting_for, current_acting_for
from ai_assistant.core.errors import (
    AssistantError,
    ConfigurationError,
    ConnectionStoreError,
    DeviceRefusedError,
    DisplacedProvisioningError,
    IncompleteProvisioningError,
    PersonModelOffError,
    ProvisioningOutcomeUnknownError,
    ResidualCredentialError,
    UnknownConnectionError,
    UnknownConversationError,
    UnusableIdentityError,
)
from ai_assistant.core.streams import closing_stream
from ai_assistant.core.types import (
    CHAT_DEVICES_MAX,
    DEFAULT_PAGE_SIZE,
    OWNER_PERSON_ID,
    TRANSCRIPT_MESSAGE_MAX_CHARS,
    ApprovalChoice,
    Attestation,
    Belief,
    BeliefBand,
    BeliefSummary,
    ChatChanges,
    ChatDevice,
    ChatStreamChunk,
    ChatStreamEnd,
    ClassReach,
    ConnectedAccount,
    ConnectionAct,
    ConversationDeletedChange,
    ConversationDigest,
    ConversationStartedChange,
    ConversationState,
    ConversationSummary,
    DeletedMessage,
    DeviceAccess,
    DevicesChangedChange,
    GrantableSource,
    GrantScope,
    HeldNotification,
    HolderKind,
    MemoryKind,
    MessageAddedChange,
    MessageDeletedChange,
    MessageReceipt,
    NotificationPreferences,
    NotificationReach,
    PendingCandidate,
    PersonModelList,
    ProfileField,
    QuietWindow,
    SourceGrant,
    SupportHolder,
    SupportView,
    TranscriptMessage,
    TranscriptPage,
    UserMessage,
    secret_value,
)
from ai_assistant.interfaces.devices import this_device
from ai_assistant.interfaces.gateway import approval_views, person_views, streams
from ai_assistant.interfaces.gateway.change_stream import paced
from ai_assistant.interfaces.gateway.delivery import DeliveryFanOut, DeliveryStream, write_stream
from ai_assistant.interfaces.gateway.edge import (
    ASSERTION_HEADER,
    AssertionFault,
    check_assertion,
    edge_terms,
)
from ai_assistant.interfaces.gateway.exits import ClearableRefusalError
from ai_assistant.interfaces.gateway.http import (
    NO_STORE,
    NO_STORE_NO_TRANSFORM,
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
from ai_assistant.interfaces.gateway.refusals import REFUSAL_FAULTS, refusal_detail
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
from ai_assistant.wire.envelope import checked_acting_for
from ai_assistant.wire.errors import OverlayIdentityUnavailableError, TransportError
from ai_assistant.wire.overlay import (
    CLIENT_AGENT_SOCKET,
    MAX_OVERLAY_IDENTITY_BYTES,
    local_agent,
)

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Awaitable, Callable, Iterator, Mapping

    from ai_assistant.core.config import Settings
    from ai_assistant.core.protocols import AssistantEngine
    from ai_assistant.core.types import (
        ChatChange,
    )
    from ai_assistant.interfaces.gateway.edge import EdgeTerms
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

#: The scheme of the hosted listener's **origin**, which is not the scheme it speaks.
#: The listener speaks plain HTTP to the edge, on the box (ADR-0327 §5:6); the page's
#: origin is the door's, which the box serves over HTTPS on port 443 (§4:1, §4:6), so
#: the `Origin` §7:3 admits is ``https://`` followed by ``gateway_hosted_host_name``.
_HOSTED_SCHEME: Final = "https"


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

#: The exchange that takes the bootstrap value's place on the hosted listener
#: (ADR-0327 §8): a ``POST`` with no body, admitted on the edge's assertion alone. A
#: path of its own rather than :data:`_SESSION_PATH` with a second meaning, so "the
#: hosted listener serves no bootstrap exchange" (§8:3) is a fact about routing: no
#: request on that listener reaches the code that reads a bootstrap value, and no
#: request on another listener reaches this one.
_EDGE_EXCHANGE_PATH: Final = "/session/edge"

#: ADR-0175 §4's delivery stream. ``GET`` because it carries no argument: the poll
#: is the gateway's own and takes none from a browser.
_DELIVERIES_PATH: Final = "/deliveries"

#: ADR-0175 §6's three conversation operations. "Resume" in milestone 14's own line
#: is resuming a *conversation* — reading it and continuing it — which is these two
#: plus the chat's own acts (ADR-0293) since the Ask panel retired (ADR-0309 §5:4).
#: ``AssistantEngine.resume`` resumed a parked **turn**, a different thing, and its
#: route retired with the confirmations panel (ADR-0309 §5).
_CONVERSATIONS_PATH: Final = "/conversations"
_CONVERSATION_PATH: Final = "/conversation"
_FORGET_CONVERSATION_PATH: Final = "/conversation/forget"

#: ADR-0293 §11:2's acts in the medium and the read of the changes after a cursor,
#: which ADR-0296's record on ADR-0177 §1:1 adds to the browser's enumeration ("§1:1's
#: enumeration, which gains the acts in the medium (ADR-0293 §11:2) and the change
#: stream"). :data:`_CHAT_CHANGES_PATH` is the read of every change after a cursor
#: (ADR-0293 §5:11), and :data:`_CHAT_FOLLOW_PATH` below the change stream itself.
#:
#: One path per operation, the verb last: the path names the thing acted on and then
#: the act, so a later act on the same thing cannot be reached by guessing. The
#: listing and the digest are not repeated here: ``recent_conversations`` and
#: ``conversation`` "remain reads" (ADR-0293 §11:3) and keep their paths above, the
#: digest gaining the current state and the devices.
_CHAT_START_PATH: Final = "/chat/start"
_CHAT_DEVICES_PATH: Final = "/chat/devices"
_CHAT_SET_DEVICES_PATH: Final = "/chat/devices/set"
_CHAT_CONVERSATION_DEVICES_PATH: Final = "/chat/conversation/devices/set"
_CHAT_WRITE_PATH: Final = "/chat/message/write"
#: ADR-0332 §5:10's composing signal: "The gateway serves it at ``POST /chat/composing``,
#: naming the conversation in its body, as it serves ``write_message`` at
#: ``/chat/message/write``." The path is the ADR's own, so it does not take the
#: thing-then-verb form above.
_CHAT_COMPOSING_PATH: Final = "/chat/composing"
_CHAT_DELETE_MESSAGE_PATH: Final = "/chat/message/delete"
_CHAT_DELETE_CONVERSATION_PATH: Final = "/chat/conversation/delete"
_CHAT_TRANSCRIPT_PATH: Final = "/chat/transcript"
_CHAT_CHANGES_PATH: Final = "/chat/changes"

#: ADR-0296 §4's change stream, relayed to a browser (ADR-0298 §7). The page follows
#: the chat on it in place of reading :data:`_CHAT_CHANGES_PATH` on a clock; that
#: read stays on the surface, and the page still makes it once to learn the cursor
#: it opens this stream from. ``POST`` because it carries one argument, the cursor,
#: and every argument here travels in a body (:data:`_SESSION_PATH`'s note).
#:
#: **ADR-0177 §1:1's enumeration gains ``follow_chat`` by ADR-0296's record on it**
#: ("§1:1's enumeration, which gains the acts in the medium … and the change
#: stream"), which no header line of ADR-0177 yet records for this route by name.
_CHAT_FOLLOW_PATH: Final = "/chat/follow"

#: ADR-0297 §5's stop command, reached by the chat's stop control beside "working…"
#: (ADR-0295 §1:2), which §6:4 lands last with ``assistant stop``.
#:
#: **ADR-0177 §1's closed enumeration is widened by this and ADR-0297's own
#: ``- Status:`` line does not record it** (issue #2714; #2274 and #2394 are the same
#: shape). ADR-0297 §6:4 rules that "the command line and the gateway's stop control
#: land last", and its Consequences give the interfaces lane "the gateway's stop control
#: beside 'working…', built on the current state's id" — so the route follows the
#: governing decision, as the cancel-read and authorization routes did before the
#: cutover retired them (ADR-0309 §5), and the reciprocal header record on ADR-0177 is
#: ADR-0297's to make.
#:
#: **Not under** ``/chat/``: the act names an activation, not a conversation, and the
#: answer says nothing about any conversation — a conversation's devices learn how it
#: ended from its current state (ADR-0293 §8), which the page already reads. The verb
#: comes last, for the chat paths' reason above.
_STOP_ACTIVATION_PATH: Final = "/activation/stop"

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

#: ADR-0329 §18:1-§18:2's read for the same panel: the candidates the observer has not
#: yet processed, which the page shows each by its fact and marks pending. A path of its
#: own rather than a member of the listing's answer, because a candidate is no memory —
#: it has no band, standing or support, and ``forget`` names nothing by it.
_PENDING_CANDIDATES_PATH: Final = "/candidates/pending"

#: ADR-0338 §8:2's About you panel, and the pin and unpin the belief panel gains: one
#: path per ``AssistantEngine`` member §8:1 adds, two reads and six writes. A read and a
#: write never share a path, for the reason the notification surface's write has its
#: own: the door classifies "from its method and path alone" (ADR-0168 §6).
#:
#: **ADR-0177 §1's closed enumeration is widened by these and ADR-0338's own
#: ``- Status:`` line does not record it**, the shape of #2714 and of
#: :data:`_PENDING_CANDIDATES_PATH`: §8:2 rules that "the web page gains an About you
#: panel" and that "the beliefs panel gains pin and unpin on each current memory", and
#: the page reaches the hub through this gateway alone, so the routes follow the
#: governing decision and the reciprocal header record on ADR-0177 is ADR-0338's to
#: make.
#:
#: **Who may see a person's model is not decided here** (§8:3). Each member sits in the
#: hub's route table's command row, so a request from a device without the role of
#: source of commands and queries is refused at the hub before dispatch (ADR-0298 §5:6),
#: and this gateway relays that refusal as every other (:meth:`Gateway._device_refused`).
#: A second rule here could only differ from that one.
_PERSON_MODEL_PATH: Final = "/person"
_PROFILE_CHANGES_PATH: Final = "/person/changes"
_SET_PROFILE_FIELD_PATH: Final = "/person/field/set"
_PIN_MEMORY_PATH: Final = "/person/pin"
_UNPIN_MEMORY_PATH: Final = "/person/unpin"
_REMOVE_STYLE_MARK_PATH: Final = "/person/style-mark/remove"
_ACCEPT_SUGGESTION_PATH: Final = "/person/suggestion/accept"
_DISMISS_SUGGESTION_PATH: Final = "/person/suggestion/dismiss"

#: ADR-0361 §4:6-§4:9's approvals panel: its query and its tap, one path per
#: ``AssistantEngine`` member §8:4 adds. A read and a write never share a path, for the
#: reason the person model's do not: the door classifies "from its method and path
#: alone" (ADR-0168 §6). ADR-0177 §1:1's enumeration gains both by ADR-0361 §11's record.
#:
#: **Neither carries a person**: the panel and its tap are the person's own, established
#: by the device being admitted under ADR-0124 (§4:8), so the page names no one and the
#: gateway supplies no one. **Who may tap is not decided here either**: both sit in the
#: hub's route table's command row, so a device without the command role is refused at
#: the hub before dispatch, and this gateway relays that refusal as every other.
_APPROVALS_PATH: Final = "/approvals"
_TAP_APPROVAL_PATH: Final = "/approval/tap"

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
    ("GET", _DELIVERIES_PATH): "delivery-stream",
    ("POST", _CONVERSATIONS_PATH): "recent_conversations",
    ("POST", _CONVERSATION_PATH): "conversation",
    ("POST", _FORGET_CONVERSATION_PATH): "forget_conversation",
    ("POST", _CHAT_START_PATH): "start_conversation",
    ("POST", _CHAT_DEVICES_PATH): "my_devices",
    ("POST", _CHAT_SET_DEVICES_PATH): "set_my_devices",
    ("POST", _CHAT_CONVERSATION_DEVICES_PATH): "set_conversation_devices",
    ("POST", _CHAT_WRITE_PATH): "write_message",
    ("POST", _CHAT_COMPOSING_PATH): "composing",
    ("POST", _CHAT_DELETE_MESSAGE_PATH): "delete_message",
    ("POST", _CHAT_DELETE_CONVERSATION_PATH): "delete_conversation",
    ("POST", _CHAT_TRANSCRIPT_PATH): "transcript",
    ("POST", _CHAT_CHANGES_PATH): "chat_changes",
    ("POST", _CHAT_FOLLOW_PATH): "follow_chat",
    ("POST", _STOP_ACTIVATION_PATH): "stop_activation",
    ("POST", _SOURCES_PATH): "grantable_sources",
    ("POST", _GRANT_PATH): "grant",
    ("POST", _REVOKE_PATH): "revoke",
    ("POST", _RECENT_GRANTS_PATH): "recent_grants",
    ("POST", _STANDING_PATH): "standing_grants",
    ("POST", _BELIEFS_PATH): "beliefs",
    ("POST", _BELIEF_PATH): "belief",
    ("POST", _FORGET_BELIEF_PATH): "forget",
    ("POST", _PENDING_CANDIDATES_PATH): "pending_candidates",
    ("POST", _PERSON_MODEL_PATH): "person_model",
    ("POST", _PROFILE_CHANGES_PATH): "profile_changes",
    ("POST", _SET_PROFILE_FIELD_PATH): "set_profile_field",
    ("POST", _PIN_MEMORY_PATH): "pin_memory",
    ("POST", _UNPIN_MEMORY_PATH): "unpin_memory",
    ("POST", _REMOVE_STYLE_MARK_PATH): "remove_style_mark",
    ("POST", _ACCEPT_SUGGESTION_PATH): "accept_person_suggestion",
    ("POST", _DISMISS_SUGGESTION_PATH): "dismiss_person_suggestion",
    ("POST", _APPROVALS_PATH): "approvals",
    ("POST", _TAP_APPROVAL_PATH): "tap_approval",
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

#: The shapes that answer on a stream (ADR-0175 §1): the delivery stream, and since
#: ADR-0298 §7 the change stream. They are held apart from the rest because only they
#: outlive the request that established them, so only they need the handle of the
#: session that admitted them (§7).
_STREAMED_SHAPES: Final = frozenset({("GET", _DELIVERIES_PATH), ("POST", _CHAT_FOLLOW_PATH)})

#: The cookie the gateway sets, and the header the front end sends. Two values
#: rather than one because "a cookie is not scoped to a port" (ADR-0168 §6).
_COOKIE_NAME: Final = "assistant_session"
_SESSION_HEADER: Final = "x-assistant-session"

#: The cookie half's name on the hosted listener (ADR-0327 §8:5): ``__Host-`` before
#: the same name, which a browser accepts only beside ``Secure``, ``Path=/`` and no
#: ``Domain`` — so a cookie of that name on the door's origin cannot have been set by
#: any other host, and every attribute §6:2 of ADR-0168 requires is held to it by the
#: browser as well as written by the gateway.
_HOSTED_COOKIE_NAME: Final = f"__Host-{_COOKIE_NAME}"

#: The policy every response carries (ADR-0168 §6): scripts, styles, fonts,
#: images, media and connections from the gateway's own origin alone, and no
#: inline script. `default-src 'none'` is what makes the enumeration exhaustive
#: rather than a list someone has to keep abreast of.
_POLICY: Final = (
    "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self'; media-src 'self'; connect-src 'self'; base-uri 'none'; "
    "form-action 'none'; frame-ancestors 'none'"
)


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
    # ADR-0327 §7:6: one refusal for the hosted listener's assertion, `Host` and
    # `Origin` alike. `403` rather than `401`, so it never reads as the absent session
    # §7:7 keeps distinct, and the page tells them apart by the `fault` member (§11).
    RefusalCondition.DOOR_REFUSED: (403, "Forbidden"),
    # Recorded and never written back: each is answered as `DOOR_REFUSED`. In the
    # table for the reason `SESSION_CEILING` is — a condition missing from it would be
    # a `KeyError` in the one place a gateway must not raise.
    RefusalCondition.ASSERTION_ABSENT: (403, "Forbidden"),
    RefusalCondition.ASSERTION_MALFORMED: (403, "Forbidden"),
    RefusalCondition.ASSERTION_SIGNATURE: (403, "Forbidden"),
    RefusalCondition.ASSERTION_ISSUER: (403, "Forbidden"),
    RefusalCondition.ASSERTION_AUDIENCE: (403, "Forbidden"),
    RefusalCondition.ASSERTION_SUBJECT: (403, "Forbidden"),
    RefusalCondition.ASSERTION_TIMES: (403, "Forbidden"),
}

#: How many parts a peer address must have before its host and port can be read.
#: An IPv6 ``peername`` is a four-tuple, so this is a floor rather than a length.
_ADDRESS_PARTS: Final = 2

#: The bundle's paths and media types (ADR-0168 §10). The gateway "serves only
#: assets that shipped in the installed distribution", so the map is fixed here
#: and the files are package data — nothing is fetched, listed or resolved from a
#: path a request supplies.
#:
#: The faces the stylesheet names are in it for the same clause's other half: the
#: page "loads no asset, font, style, script or datum from any origin but the
#: gateway's own", so a web font is one the gateway serves or one the page does
#: without. Each is listed by name rather than by a directory, so the licence texts
#: beside them ship in the distribution and are served by nothing.
_BUNDLE: Final[Mapping[str, tuple[str, str]]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/door.js": ("door.js", "text/javascript; charset=utf-8"),
    **{
        f"/fonts/{face}.woff2": (f"fonts/{face}.woff2", "font/woff2")
        for face in (
            "cormorant-garamond-latin-500-normal",
            "cormorant-garamond-latin-600-normal",
            "manrope-latin-400-normal",
            "manrope-latin-500-normal",
            "manrope-latin-600-normal",
            "jetbrains-mono-latin-400-normal",
        )
    },
}


#: The served path whose file differs on the hosted listener, and the file it serves
#: there (ADR-0327 §11). One path, one file, both shipped in the distribution: the
#: hosted bundle is the same bundle with this one substitution, so the page that
#: listener serves is this repository's page (§3:1, §4:7) and learns which door it
#: came through without asking the gateway anything before a session exists (§7:4).
_DOOR_PATH: Final = "/door.js"
_HOSTED_DOOR: Final = "door-hosted.js"

#: Whether the call being relayed came through the hosted listener (ADR-0327 §10), set
#: around the call beside the browser device's name (:meth:`Gateway._relaying_for`). Read
#: by one place, which words what the hub refused for the person who will read it
#: (:meth:`Gateway._device_refused`): through the sign-in door that is a person on their
#: phone, and anywhere else the owner at a machine of their own.
_THROUGH_THE_DOOR: Final[ContextVar[bool]] = ContextVar("gateway_through_the_door", default=False)


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


def _cookie(half: str, *, remote: bool, hosted: bool = False) -> str:
    """The `Set-Cookie` value for one minted session (ADR-0168 §6, ADR-0202 §7, ADR-0327 §8:5).

    One function rather than an interpolation at the call site, so the attribute set
    is one thing to read against the ADRs that decide it — and so a second mint path
    could never grow a different set.

    Args:
        half: The cookie half the session table minted.
        remote: Whether the exchange arrived on the remote browser listener.
        hosted: Whether it arrived on the hosted listener. With ``remote``, the only
            things that decide `Secure` and the name.

    Returns:
        The header value, with every attribute ADR-0168 §6 requires; `Secure` on the
        remote listener (ADR-0202 §7) and on the hosted one, which also takes the
        ``__Host-`` name (ADR-0327 §8:5).
    """
    attributes = "HttpOnly; SameSite=Strict; Path=/"
    if remote or hosted:
        attributes = f"{attributes}; Secure"
    name = _HOSTED_COOKIE_NAME if hosted else _COOKIE_NAME
    return f"{name}={half}; {attributes}"


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


def _refuse_a_hosted_address_this_machine_does_not_hold(address: str) -> None:
    """Refuse a hosted address no interface of this machine holds (ADR-0327 §5:4).

    The kernel is asked by a bind on an ephemeral port, for the reason
    :func:`_refuse_an_address_this_machine_does_not_hold` gives: the real bind turns
    ``EADDRNOTAVAIL`` into an ``OSError`` with no errno. A loopback address is always
    held; a private-use one is held inside the container whose own address it is,
    and a gateway configured with another machine's or container's address is a
    setup fault worth a sentence.

    Args:
        address: The address the hosted listener is about to bind.

    Raises:
        ConfigurationError: If the address is not one this machine holds.
        OSError: If the probe fails for any other reason.
    """
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    try:
        with socket.socket(family, socket.SOCK_STREAM) as probe:
            probe.bind((address, 0))
    except OSError as exc:
        if exc.errno != errno.EADDRNOTAVAIL:
            raise
        msg = (
            f"the hosted listener is configured to bind {address}, which is not an "
            f"address of this machine ({exc}). ADR-0327 §5:4 configures a private-use "
            f"address only for a gateway in a network namespace of its own, where that "
            f"address is its own; set ASSISTANT_GATEWAY_HOSTED_ADDRESS to 127.0.0.1 on "
            f"a gateway that shares the box's network"
        )
        raise ConfigurationError(msg) from exc


def _check_the_hosted_listener_can_serve(settings: Settings) -> EdgeTerms | None:
    """Refuse a hosted listener that could never relay a request (ADR-0327 §10:3).

    ``Settings`` refused what it could decide without importing a subsystem; the
    hosted device is held here to the whole of ADR-0298 §1:3 by the very check the
    wire client runs on every ``acting_for`` it writes, byte bound included. A name
    failing it would be refused before any frame was written, so every request the
    hosted owner made would fail with nothing at setup saying why.

    Args:
        settings: The loaded configuration.

    Returns:
        The terms the edge's assertions are held to, or ``None`` where the hosted
        listener is off.

    Raises:
        ConfigurationError: If the device cannot be named on the wire, or a key
            cannot be loaded.
    """
    terms = edge_terms(settings)
    device = settings.gateway_hosted_device
    if terms is None or device is None:
        return None
    try:
        checked_acting_for(device)
    except ValueError as exc:
        msg = (
            f"gateway_hosted_device cannot be named on the wire ({exc}), so the hub "
            f"could never be told which device the hosted owner's browsers are "
            f"(ADR-0327 §10:2, ADR-0298 §1:3); choose a shorter plain name"
        )
        raise ConfigurationError(msg) from exc
    return terms


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


def packaged_bundle(*, hosted: bool = False) -> Mapping[str, tuple[bytes, str]]:
    """Read the front end out of the installed distribution (ADR-0168 §10).

    Read once, at start, rather than per request: the bundle ships with the
    package and cannot change under a running process, and a gateway that read a
    file per request would have a filesystem in its request path for no gain.

    Args:
        hosted: Whether this is the bundle the hosted listener serves, which differs
            in :data:`_DOOR_PATH` alone (ADR-0327 §11).

    Returns:
        Each served path's bytes and media type.
    """
    root = resources.files(__package__) / "assets"
    files = {**_BUNDLE}
    if hosted:
        files[_DOOR_PATH] = (_HOSTED_DOOR, _BUNDLE[_DOOR_PATH][1])
    return {
        path: (root.joinpath(*name.split("/")).read_bytes(), media_type)
        for path, (name, media_type) in files.items()
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
            a loopback or hosted connection, which has no such fact — and a remote
            connection never reaches a request with it still ``None``, because §3
            refuses and closes one whose identity could not be obtained.
        hosted: Whether it arrived on the hosted listener (ADR-0327), which selects
            that ADR's admission on two facts — the edge's assertion and a live
            session. Never ``True`` beside ``remote``.
    """

    admitted: bool = False
    remote: bool = False
    device: str | None = None
    hosted: bool = False


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


@dataclass
class _Ending:
    """Whether a terminal value has been written on one stream (ADR-0175 §2).

    §2 partitions a stream's endings — "the gateway wrote a **terminal** value, or
    the body ended without one" — and §3 gives an answer stream exactly one of the
    first kind: "one value per ``ReplyChunk``, then one terminal value carrying the
    ``TurnOutcome``, or one terminal value carrying the fault the exchange ended in".
    A second terminal value appended to a stream that already has one is neither
    ending: a conforming reader stops at the first and never sees it, so it is a byte
    on the wire that no clause here describes and no reader is told how to treat.

    **It is set at framing time and not after the write**, which is the whole of why
    it is reliable. ``StreamWriter.write`` is synchronous and the ``drain`` that
    follows it is the suspension point, so a session ending during that drain finds
    this already true — where a flag set after the drain would find it false and
    append a second terminal to a stream whose browser is merely slow.

    One record per stream, built where the stream is decided and read where it is
    ended, so the body and :class:`_OpenStream` cannot hold two answers to one
    question.
    """

    named: bool = False
    outstanding: bool = False

    def framing(self, value: Mapping[str, Any]) -> bytes:
        """Frame one value for this stream, recording what it is as it goes.

        Framing is the synchronous step immediately before the write, and the drain
        after that write is the suspension point — so both facts recorded here are
        true from before a session's ending can observe them.

        Args:
            value: The value, already carrying its ``kind``.

        Returns:
            The bytes to write, framed as a chunk of the chunked body.
        """
        if value.get("kind") in streams.TERMINAL_KINDS:
            self.named = True
        self.outstanding = True
        return _frame(value)

    def wrote(self) -> None:
        """Record that the write begun by the last framing has completed."""
        self.outstanding = False


@dataclass(eq=False)
class _OpenStream:
    """One stream a session admitted, and how the gateway ends it (ADR-0175 §7).

    "A stream ends no later than the session that admitted it, and the gateway ends
    every stream a session held at the moment that session ends." A held-open stream
    sends no further request, so the gateway would otherwise learn of the session's
    death only from a request that never comes.

    Ending it is closing the connection the response body is being written on, which
    *is* the stream (§1) — but not *only* that, because ADR-0175 §2 makes the two
    endings a reader can meet a partition, and a close on its own puts this one on
    the wrong side of it. The ending is **named** first and closed second (#2498).

    A delivery stream is abandoned before either, so its writer stops waiting on a
    browser rather than on a socket that is about to go.

    Compared by identity, because two streams in the same state are not one stream.
    """

    writer: asyncio.StreamWriter
    ending: _Ending
    delivery: DeliveryStream | None = None
    driver: asyncio.Task[Any] | None = None

    def end(self) -> None:
        """End this stream now, tolerating a connection that is already gone.

        **Closing the writer is not enough on its own, and the case that shows it is
        a stream waiting on its next value.** A delivery poll may be waiting on the hub
        when the session expires; a closed socket does not interrupt an ``async for``,
        so the iteration — and with it the hub connection ADR-0175 §7
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

        **And the bytes are a terminal value before they are a closed socket**
        (#2498). ADR-0175 §2 gives a reader exactly two endings to tell apart —
        "the gateway wrote a **terminal** value, or the body ended without one" —
        and rules that the second "has a transport failure and the front end reports
        it as one". A session ending is not a transport failure: the gateway is
        listening, holds its hub connection, and answers the very next request. Ended
        by a close alone, §7's fourth clause reached a real browser as
        ``net::ERR_INCOMPLETE_CHUNKED_ENCODING`` and the owner was told the gateway
        "may have stopped" and to start it — an instruction to do something to a
        healthy process, and the one condition ``app.js`` has written words for and
        could never say, because no gateway in this tree wrote the value its
        ``IDLE_WHILE_WATCHING`` branch is conditioned on. Naming it is what puts this
        ending on §2's first side, and ``no-live-session`` is the condition itself:
        the same name :class:`.RefusalCondition` gives the request-side refusal, so
        the page describes a stream's ending with the words it already has for a
        response's, which is ADR-0168 §9's distinction surviving to what is read.

        **The name is true on all three routes into here**, which is why it is not
        conditioned on which one was taken: both of a session's bounds and
        :meth:`Gateway.close` on the way down each leave no live session. A process on
        its way down may not flush before it goes, and a browser that misses the flush
        sees exactly what it sees today — a body without a terminal value, which is
        §2's other ending and legible as one — so the shutdown route can lose this
        value but cannot be misled by it.

        Written after the cancellation rather than before it, so no value the driver
        was mid-body can follow the terminal one: a cancelled task resumes at its next
        suspension point, and by then this has written the zero-length chunk and closed
        the writer. ``close()`` flushes what is buffered, so the ordering costs no
        drain — which this cannot await, being the synchronous callback
        :class:`.SessionTable` announces an ending through.

        **And two streams are ended without a value at all, because writing one would
        breach a clause it was meant to serve** — adversarial review, rounds 1-3,
        ``blocker``. :meth:`_name_the_ending` has both and the reading behind the
        second.
        """
        self._name_the_ending()
        if self.delivery is not None:
            self.delivery.abandon()
        if self.driver is not None and self.driver is not asyncio.current_task():
            self.driver.cancel()
        with contextlib.suppress(ConnectionError, OSError):
            self.writer.close()

    def _name_the_ending(self) -> None:
        """Write the terminal fault this ending is, where the stream can carry one.

        **A stream that already carries a terminal value gets no second one** (§2,
        §3). The window is real rather than theoretical: a body writes its terminal
        value and then awaits the drain, and a session expiring inside that drain would
        find the value written and the response not yet complete. A conforming reader
        stops at the first terminal and never sees a second — so the harm is not what
        an owner reads but what the stream *is*, and §3 gives an answer stream exactly
        one. :class:`_Ending` is set at framing time, before the write that precedes
        that drain, so this reads the state as it is rather than as it was.

        **A delivery stream with a write outstanding is abandoned and gets no value**
        (§4): "the gateway holds at most one value pending per stream and queues nothing
        behind one", and "a write that has not completed when the next value is due on
        that stream is abandoned and the stream is ended". A session's ending is the
        next value due, so it takes the same disposition
        :meth:`.DeliveryFanOut._end_all` takes for a poll that could not complete, and
        the browser is not left guessing: §2 makes a body that ended without a terminal
        value a transport failure, and §4 prices the remedy in the same breath — "a
        reconnect, which is free, because a session outlives its connections".

        **The reading is disclosed because there was one to make** (adversarial review,
        rounds 1-3). The clause can be read narrowly, as the *pending slot*
        :meth:`.DeliveryStream.offer` refuses on — which this path never touches, since
        the value goes to the socket rather than through the fan-out — and on that
        reading writing here breaches nothing: two synchronous writes and a close delay
        no other browser, which is the purpose the abandonment clause states in its own
        sentence. The broad reading, that a value put on the wire behind one the browser
        has not taken is queued behind it whatever holds it, is the one taken here: it
        is the conservative of the two, it is never worse for anyone than the ending this
        build already gives that browser, and the case it governs is not #2498's — a page
        watching an idle stream drained its last keep-alive a poll budget ago. #2505 has
        the question if it is ever worth settling.

        **An answer stream is not guarded on this**, which is §4 in terms: "an answer
        stream has one reader and nothing to protect from it, and this clause does not
        reach one".
        """
        if self.ending.named:
            return
        if self.delivery is not None and self.ending.outstanding:
            return
        with contextlib.suppress(ConnectionError, OSError):
            self.writer.write(
                self.ending.framing(streams.fault(RefusalCondition.NO_LIVE_SESSION.value))
            )
            self.writer.write(render_stream_end())


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
        ending: What has been written on this stream and whether it has left. The body
            frames every value through it and reports each write's completion to it,
            and :meth:`_OpenStream._name_the_ending` reads it — so the two facts a
            session's ending turns on are held in one place rather than in two the
            body and the ending could disagree about.
        ends_when_the_peer_leaves: Whether the body is ended the moment the browser
            closes the connection, rather than at the next write that finds it gone.
            The change stream's: it holds a hub stream and a hub connection for the
            browser, and a page that lets it go — hidden, or following stopped — gives
            both back at once rather than a keep-alive cadence later.
    """

    handle: SessionHandle
    head: StreamHead
    body: Callable[[asyncio.StreamWriter], Awaitable[None]]
    release: Callable[[], None]
    ending: _Ending
    delivery: DeliveryStream | None = None
    ends_when_the_peer_leaves: bool = False


class Gateway:
    """Serves one device's browsers, and reaches the hub as any spoke does."""

    def __init__(  # noqa: PLR0913 — one keyword per injected seam: config, hub, clock, timer, bundles, agent, entropy
        self,
        *,
        settings: Settings,
        engine: AssistantEngine,
        now: Callable[[], datetime],
        defer: Defer,
        bundle: Mapping[str, tuple[bytes, str]],
        agent: OverlayAgent | None = None,
        mint_value: Callable[[], str] = mint_value,
        hosted_bundle: Mapping[str, tuple[bytes, str]] | None = None,
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
                ``gateway_remote_address`` is set. Where the hub is on another
                machine it is also asked, once at :meth:`start`, which node this
                machine is — the device a loopback browser writes from (ADR-0296
                §1:7). :func:`run_gateway` builds the real one where either needs it,
                and a test supplies a fake.
            mint_value: The entropy source for the bootstrap value and both
                session halves.
            hosted_bundle: The front end the hosted listener serves, or ``None`` to
                serve ``bundle`` there too. :func:`packaged_bundle` builds the real
                one, which differs in one file (ADR-0327 §11).

        Raises:
            ConfigurationError: If the remote browser listener is configured on with
                no agent to satisfy ADR-0174 §3, if a listed device's identity is
                over the byte bound the wire seam holds every overlay identity to, or
                if its TLS material fails any condition ADR-0202 §§2, 3, 6 and 8 put
                at start. Each is a stay-down deployment fault (ADR-0083 §5): a
                gateway that bound the door anyway would refuse every connection on
                it, refuse the owner's own named device at every exchange with
                nothing saying why, or serve a certificate no browser accepts. Also
                if the hosted listener's device cannot be named on the wire or an
                edge key cannot be loaded (ADR-0327 §6:4, §10:3). The one that is
                not stay-down is a certificate not yet in force, which the clock
                clears and which is raised as :class:`~.exits.ClearableRefusalError`.
        """
        _check_the_remote_listener_can_serve(settings, agent=agent)
        #: What the edge's assertions are held to (ADR-0327 §6), read once and never
        #: re-read: "No request on any listener may add to, remove from or replace
        #: the set" (§6:5). ``None`` exactly where the hosted listener is off.
        self._edge: EdgeTerms | None = _check_the_hosted_listener_can_serve(settings)
        tls = remote_tls(settings, now=now)
        self._settings = settings
        self._engine = engine
        self._now = now
        self._defer = defer
        self._bundle = bundle
        self._hosted_bundle = bundle if hosted_bundle is None else hosted_bundle
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
            own_device=lambda: self._own_device,
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
        #: This machine's device, for a browser on the loopback listener (ADR-0296
        #: §1:7), named once at :meth:`start` (:meth:`_name_own_device`) and ``None``
        #: until then — or for good, where the hub is on another machine and this
        #: machine's overlay agent would not say which node it is
        #: (:meth:`_browser_device`).
        self._own_device: str | None = None
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
        #: What a `Host` may name on the hosted listener (ADR-0327 §7:2): the door's
        #: own hostname and nothing else, compared literally and never resolved. Empty
        #: where the listener is off, so nothing is admitted by it.
        self._hosted_authorities = frozenset(
            name for name in (settings.gateway_hosted_host_name,) if name is not None
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
            _CONVERSATIONS_PATH: self._recent_conversations,
            _CONVERSATION_PATH: self._conversation,
            _FORGET_CONVERSATION_PATH: self._forget_conversation,
            _CHAT_START_PATH: self._start_conversation,
            _CHAT_SET_DEVICES_PATH: self._set_my_devices,
            _CHAT_CONVERSATION_DEVICES_PATH: self._set_conversation_devices,
            _CHAT_COMPOSING_PATH: self._composing,
            _CHAT_DELETE_MESSAGE_PATH: self._delete_message,
            _CHAT_DELETE_CONVERSATION_PATH: self._delete_conversation,
            _CHAT_TRANSCRIPT_PATH: self._transcript,
            _CHAT_CHANGES_PATH: self._chat_changes,
            _STOP_ACTIVATION_PATH: self._stop_activation,
            _SOURCES_PATH: self._grantable_sources,
            _GRANT_PATH: self._grant,
            _REVOKE_PATH: self._revoke,
            _RECENT_GRANTS_PATH: self._recent_grants,
            _STANDING_PATH: self._standing_grants,
            _BELIEFS_PATH: self._beliefs,
            _BELIEF_PATH: self._belief,
            _FORGET_BELIEF_PATH: self._forget_belief,
            _PENDING_CANDIDATES_PATH: self._pending_candidates,
            _PERSON_MODEL_PATH: self._person_model,
            _PROFILE_CHANGES_PATH: self._profile_changes,
            _SET_PROFILE_FIELD_PATH: self._set_profile_field,
            _PIN_MEMORY_PATH: self._pin_memory,
            _UNPIN_MEMORY_PATH: self._unpin_memory,
            _REMOVE_STYLE_MARK_PATH: self._remove_style_mark,
            _ACCEPT_SUGGESTION_PATH: self._accept_person_suggestion,
            _DISMISS_SUGGESTION_PATH: self._dismiss_person_suggestion,
            _APPROVALS_PATH: self._approvals,
            _TAP_APPROVAL_PATH: self._tap_approval,
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
        #: The two shapes that need the name of the browser device the request comes
        #: from, which ADR-0296's record on ADR-0177 §1:5 adds to the closed class of
        #: what the gateway supplies of its own. Kept apart from :attr:`_unary` so the
        #: name reaches these two handlers and no other: writing a message carries it
        #: as ``UserMessage.device_id`` (ADR-0293 §4:1), and reading "my devices" tells
        #: the page which device it is, so it can offer to add itself (§3:1). Nothing
        #: else of the browser's connection reaches a handler.
        self._named: Mapping[str, Callable[[Request, str | None], Awaitable[Response]]] = {
            _CHAT_DEVICES_PATH: self._my_devices,
            _CHAT_WRITE_PATH: self._write_message,
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

    @property
    def hosted_origin(self) -> str | None:
        """The door's origin, which the hosted listener admits, or ``None`` where it is off.

        **Not one of :attr:`origins`**, because those are where a bootstrap value is
        spent and every disclosure lists them beside one: "The hosted listener serves
        no bootstrap exchange" (ADR-0327 §8:3), so naming its origin beside a value
        would hand the owner a door the value does not open.

        Returns:
            ``https://`` followed by ``gateway_hosted_host_name`` (§7:3), or ``None``.
        """
        name = self._settings.gateway_hosted_host_name
        return None if self._edge is None or name is None else f"{_HOSTED_SCHEME}://{name}"

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

        **This machine's device is named first** (:meth:`_name_own_device`), so no
        request on the listener is ever answered before it has been: a browser there
        writes as that device, and a write answered in the gap would be refused as
        unnamed for no reason a later request would share.

        Returns:
            The bound server, whose lifetime the caller owns.
        """
        if self._own_device is None:
            self._own_device = await self._name_own_device()
        server = await asyncio.start_server(
            partial(self._handle, remote=False), host=_LOOPBACK, port=self._settings.gateway_port
        )
        _log.info("gateway.listening", origin=self._origin, served_paths=sorted(self._bundle))
        return server

    async def _name_own_device(self) -> str | None:
        """Name this machine's device, once, by the rule the command line uses (ADR-0296 §1).

        :func:`~ai_assistant.interfaces.devices.this_device` with nothing ``named``:
        ``hub`` where the hub is on this machine, and otherwise this machine's overlay
        identity as its own agent reports it. An agent that will not say leaves the
        device unnamed rather than stopping the gateway: ADR-0168 §9 binds the loopback
        listener whether or not the hub is reachable, and an agent that cannot answer
        is no better reason to stay down — an unnamed device costs only its writes,
        each refused as its own condition (:meth:`_write_message`).

        Returns:
            The device's id, or ``None`` where it cannot be named.
        """
        try:
            return await this_device(self._settings, named=None, agent=self._agent)
        except ConfigurationError as exc:
            _log.warning(
                "gateway.own_device_unnamed",
                detail=(
                    "a browser on the loopback listener has no device, so its writes "
                    "into a conversation are refused"
                ),
                reason=str(exc),
            )
            return None

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
                change is the configuration, the overlay, or the certificate — except
                an agent that would not answer, and a certificate a clock that moved
                back has put before its validity, which are
                :class:`~.exits.ClearableRefusalError` (#3167).
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

    async def start_hosted(self) -> asyncio.Server | None:
        """Bind the hosted listener, if the operator configured one (ADR-0327 §5).

        > The hosted listener is **off unless it is configured on**, by
        > ``gateway_hosted_address``. (§5:1)

        **Where it binds is decided before this, and what reaches it after.**
        ``Settings`` admits only a literal loopback or private-use address (§5:3), and
        this asks the kernel that the address is this machine's own. A loopback
        address is reached from the box alone; a private-use one is configured only
        inside a network namespace of its own whose hosted port is published to the
        host's loopback and to nothing else (§5:4), which the setup holds (#3142).
        The gateway cannot see that publication and does not claim to.

        **Plain HTTP, and no certificate** (§5:6): TLS is the door's, terminated on
        the box in front of the edge (§4:1). No request reaches this listener
        except one the edge forwarded, and the gateway checks every one (§7:1).

        **The device it names is not this machine's own**, which is checked here
        because only here is this machine's device known (:meth:`start`): a hosted
        owner's browsers acting as the gateway's own device would take its roles,
        which §10:2 forbids.

        **The keep-alive it relies on** (§5:9). Both streams write at least once per
        ``gateway_notification_budget``, twenty seconds by default (ADR-0175 §4,
        ADR-0298 §7), and the hosted listener adds no cadence of its own; this
        assumes every hop between the gateway and the browser, the edge among them,
        holds an idle stream for at least sixty seconds, three cadences at the
        default.

        Returns:
            The bound server, or ``None`` where the listener is off.

        Raises:
            ConfigurationError: If the address is not one this machine holds, or the
                hosted device is this machine's own.
            OSError: If the bind fails for any other reason, left raw for the reason
                :meth:`start_remote` leaves it.
        """
        address = self._settings.gateway_hosted_address
        device = self._settings.gateway_hosted_device
        if address is None or self._edge is None:
            return None
        if self._own_device is not None and device == self._own_device:
            msg = (
                "gateway_hosted_device names this gateway's own machine, so the hosted "
                "owner's browsers would act with its roles (ADR-0327 §10:2, ADR-0298 "
                "§8:1); give them a name of their own"
            )
            raise ConfigurationError(msg)
        _refuse_a_hosted_address_this_machine_does_not_hold(address)
        server = await asyncio.start_server(
            partial(self._handle, remote=False, hosted=True),
            host=address,
            port=self._settings.gateway_hosted_port,
        )
        # Tier 2 facts about the listener and nothing of the edge's terms: no key, no
        # issuer or audience, and never the subject, which §7:8 keeps out of every
        # record. ``origin`` rather than a key with ``auth`` in it, for the reason
        # :meth:`start_remote` gives about ``core.logging``'s mask.
        _log.info(
            "gateway.hosted_listening",
            origin=self.hosted_origin,
            bound=_authority(address, self._settings.gateway_hosted_port),
            edge_verifiers=len(self._edge.keys),
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
            ClearableRefusalError: If the agent places no node there, or will not
                say. A ``1`` rather than a ``78`` (#3167): the one error carries both
                "this address is not on the overlay" and "the agent timed out" or "is
                not running yet", and the second clears without anyone acting, so
                ADR-0083 §5's tie-break decides — "a spurious restart is recoverable
                and a spurious ``78`` is an outage".
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
            raise ClearableRefusalError(msg) from exc

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
            # The hosted listener is bound beside both and torn down with them, under
            # the same reasoning: a gateway asked to serve the door and unable to is
            # not left serving the other listeners as though it were (ADR-0327 §5:7).
            hosted = await self.start_hosted()
            if hosted is not None:
                bound.append(await stack.enter_async_context(hosted))
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
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        *,
        remote: bool,
        hosted: bool = False,
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
            hosted: Whether this is the hosted listener's (ADR-0327). It has no
                identity step and no handshake: the peer is the edge, on the box, and
                every request is admitted on the edge's assertion (§7:1).
        """
        connection = _Connection(remote=remote, hosted=hosted)
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
        # ADR-0327 §4:9: every response on the hosted listener asks the edge and the
        # browser to neither store nor transform it. Decided by the listener, once.
        cache = NO_STORE_NO_TRANSFORM if connection.hosted else NO_STORE
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
                if not await self._write_stream(
                    reader, writer, answer, closing=closing, cache=cache
                ):
                    return
            else:
                try:
                    writer.write(
                        render(replace(answer, close=closing), policy=_POLICY, cache=cache)
                    )
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
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        answer: _Streamed,
        *,
        closing: bool,
        cache: str = NO_STORE,
    ) -> bool:
        """Write one streamed response whole (ADR-0175 §1).

        The head, then whatever the body writes, then the zero-length chunk that
        ends a chunked body. A body that stops without that marker and without a
        terminal value is what ADR-0175 §2 makes a **transport failure** the front
        end reports as one, so a connection that dies mid-stream is legible at the
        browser rather than looking like a stream that finished with nothing to say.

        Args:
            reader: The connection's reader, watched for the browser leaving where
                ``answer`` asks for that (:attr:`_Streamed.ends_when_the_peer_leaves`).
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.
            cache: The head's ``Cache-Control`` (ADR-0327 §4:9).

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
            reader: The connection's reader.
            writer: The connection's writer.
            answer: What to stream.
            closing: Whether the connection is closed once this completes.
            cache: The head's ``Cache-Control`` (ADR-0327 §4:9).

        Returns:
            Whether the connection survived. ``False`` where the peer went away,
            which is an ordinary end for a stream and not a fault to report.
        """
        held = _OpenStream(
            writer=writer,
            ending=answer.ending,
            delivery=answer.delivery,
            driver=asyncio.current_task(),
        )
        self._register(answer.handle, held)
        try:
            writer.write(
                render_stream_head(replace(answer.head, close=closing), policy=_POLICY, cache=cache)
            )
            await writer.drain()
            if answer.ends_when_the_peer_leaves:
                if not await _while_the_peer_stays(answer.body(writer), reader):
                    return False
            else:
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
        if not connection.hosted:
            return await self._respond(request, connection)
        # ADR-0327 §9:2: "The gateway holds an assertion only while it checks the
        # request that carried it." The check is made here, and the request this frame
        # goes on holding — through the engine call and through a stream that may last
        # hours — is one the assertion has been taken out of. Rebinding the name is
        # what lets the original go: nothing else refers to it.
        request, verdict = self._take_the_assertion(request)
        return await self._respond(request, connection, verdict=verdict)

    def _take_the_assertion(self, request: Request) -> tuple[Request, AssertionFault | None]:
        """Check a hosted request's assertion, and hand back the request without it.

        The whole of the assertion's custody in this process (ADR-0327 §9:2, §9:7): it
        is read out of the request, checked (§6), and dropped with this frame. What
        survives is the verdict, a fixed value, and a request carrying every header
        but this one — so no frame that awaits anything afterwards, the engine call
        and a stream's body among them, holds a reference to it.

        Args:
            request: The request as read.

        Returns:
            The request without its ``Edge-Assertion`` header, and ``None`` where the
            assertion was accepted or the fault it failed on.
        """
        terms = self._edge
        verdict = (
            AssertionFault.ABSENT
            if terms is None
            else check_assertion(request.header(ASSERTION_HEADER), terms=terms, now=self._now())
        )
        kept = tuple((name, value) for name, value in request.headers if name != ASSERTION_HEADER)
        return replace(request, headers=kept), verdict

    async def _respond(
        self,
        request: Request,
        connection: _Connection,
        *,
        verdict: AssertionFault | None = AssertionFault.ABSENT,
    ) -> Response | _Streamed:
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

        **On the hosted listener the edge's assertion comes first** (ADR-0327 §7:1),
        "before ADR-0168 §7's ``Host`` and ``Origin`` checks and before any session is
        read" — the assets and the exchange included, since §7:4 serves them "once
        the checks above pass". A request failing the assertion, its `Host` or its
        `Origin` is recorded on the check it failed (§7:7) and answered with one
        refusal whichever it was (§7:6), so nothing a peer without the edge's key
        sends can learn which of the three it got wrong, or anything past them. The
        assertion itself was checked one frame up, by :meth:`_take_the_assertion`, and
        arrives here as ``verdict`` alone — whose default is a refusal, so a hosted
        request that reached here without the check is refused rather than admitted
        (§6:14). It is read on the hosted listener and on no other.
        """
        request_class = self._classify(request, hosted=connection.hosted)
        if connection.hosted and verdict is not None:
            return self._refuse(
                request_class,
                RefusalCondition(verdict.value),
                connection,
                answered_as=RefusalCondition.DOOR_REFUSED,
            )
        condition = self._check_door(request, connection)
        if condition is not None:
            answered = RefusalCondition.DOOR_REFUSED if connection.hosted else None
            return self._refuse(request_class, condition, connection, answered_as=answered)
        if request_class is RequestClass.ASSET:
            bundle = self._hosted_bundle if connection.hosted else self._bundle
            body, media_type = bundle[request.path]
            return Response(200, "OK", body=body, content_type=media_type, close=False)
        if connection.remote and connection.device not in self._listed_devices:
            return self._refuse(request_class, RefusalCondition.DEVICE_NOT_LISTED, connection)
        if request_class is RequestClass.BOOTSTRAP:
            exchange = self._edge_exchange if connection.hosted else self._exchange
            return exchange(request, connection)
        return await self._session_bound(request, connection, request_class)

    def _classify(self, request: Request, *, hosted: bool = False) -> RequestClass:
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
        # The exchange is in the bootstrap exchange's class (ADR-0327 §7:10), and each
        # listener has exactly one: the hosted listener serves no bootstrap exchange
        # (§8:3), and no other listener serves the edge's.
        exchange = _EDGE_EXCHANGE_PATH if hosted else _SESSION_PATH
        if request.method == "POST" and request.path == exchange:
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

        **On the hosted listener the set is one name, and the scheme is the door's**
        (ADR-0327 §7:2, §7:3): the `Host` must be ``gateway_hosted_host_name`` and an
        `Origin` must be ``https://`` followed by it, because the page's origin is the
        door's HTTPS one while this listener speaks plain HTTP to the edge.

        Args:
            request: The request as parsed.
            connection: The connection it arrived on, which decides which set of
                authorities its `Host` is judged against.

        Returns:
            The condition it fails, or ``None`` where it passes both.
        """
        if connection.hosted:
            admitted, scheme = self._hosted_authorities, _HOSTED_SCHEME
        elif connection.remote:
            admitted, scheme = self._remote_authorities, _REMOTE_SCHEME
        else:
            admitted, scheme = frozenset({self._authority}), _LOOPBACK_SCHEME
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

    def _edge_exchange(self, request: Request, connection: _Connection) -> Response:
        """The exchange that mints a session on the hosted listener (ADR-0327 §8).

        > On the hosted listener a session is minted by the **exchange**: a ``POST``
        > to the exchange path carrying a valid assertion, an ``Origin`` that §7
        > admits, and nothing else. A request to it with a body, or with no
        > ``Origin``, is refused. (§8:1)

        **The assertion and a present `Origin` were checked before this was reached**
        (:meth:`_respond`), so what is left is that the `Origin` is present at all —
        §7:3 refuses a wrong one and lets an absent one by, and an exchange is the one
        request §8:1 requires carry it — and that nothing else came with it. The body
        is refused unread: there is nothing in this exchange a browser could say.

        **A failed exchange discloses only that it failed** (§8:2), with ADR-0168
        §5:3's single answer, and the ceiling is recorded as itself and answered as
        that failure (ADR-0182 §4:2). The ceiling is reached only where no session
        minted here is live to end (§8:6): :meth:`.SessionTable.mint_hosted` ends this
        listener's oldest otherwise, and the record says so (§8:7).

        Args:
            request: The exchange as parsed.
            connection: The connection it arrived on.

        Returns:
            The two session values, or the refusal.
        """
        if request.header("origin") is None or request.body:
            return self._refuse(
                RequestClass.BOOTSTRAP, RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED, connection
            )
        minted = self._sessions.mint_hosted()
        if minted is None:
            return self._refuse(
                RequestClass.BOOTSTRAP,
                RefusalCondition.SESSION_CEILING,
                connection,
                answered_as=RefusalCondition.BOOTSTRAP_EXCHANGE_FAILED,
            )
        values, ended_oldest = minted
        self._records.session_minted(ended_oldest=ended_oldest)
        return Response(
            200,
            "OK",
            body=_json({"header_half": values.header_half}),
            content_type="application/json",
            set_cookie=_cookie(values.cookie_half, remote=False, hosted=True),
            close=True,
        )

    async def _session_bound(
        self, request: Request, connection: _Connection, request_class: RequestClass
    ) -> Response | _Streamed:
        """Everything ADR-0168 §3 serves only to an admitted browser.

        On the hosted listener this is the second of ADR-0327 §7:5's two facts — the
        assertion was the first — and its refusals are ADR-0168 §3:2's and §6:4's
        unchanged (§7:7), read off the ``__Host-`` cookie that listener sets (§8:5)
        and found only among the sessions it minted.
        """
        header_half = request.header(_SESSION_HEADER)
        cookie = _HOSTED_COOKIE_NAME if connection.hosted else _COOKIE_NAME
        outcome = self._sessions.admit(
            header_half=header_half,
            cookie_halves=request.cookies(cookie),
            hosted=connection.hosted,
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
            if shape in _STREAMED_SHAPES:
                return self._streamed(request, header_half, connection)
            with self._relaying_for(connection):
                if request.path in self._named:
                    return await self._named[request.path](
                        request, self._browser_device(connection)
                    )
                return await self._unary[request.path](request)
        except _Refused as refused:
            return refused.response

    def _streamed(
        self, request: Request, header_half: str | None, connection: _Connection
    ) -> Response | _Streamed:
        """Open one of :data:`_STREAMED_SHAPES`, held against its session (ADR-0175 §7).

        Raises:
            _Refused: If the change stream's cursor is malformed.
        """
        handle = None if header_half is None else self._sessions.handle(header_half)
        if handle is None:  # pragma: no cover — admitted means a session verified it
            return self._refuse(
                RequestClass.ASSISTANT, RefusalCondition.NO_LIVE_SESSION, connection
            )
        if request.path == _CHAT_FOLLOW_PATH:
            return self._change_stream(request, handle, connection)
        # **The delivery stream names nothing** (ADR-0298 §5): it is served from the
        # gateway's own poll, ``next_notification`` "is the connecting device's own",
        # and a poll carrying ``acting_for`` is refused. So it is opened outside
        # :meth:`_relaying_for`, and the poll's task, which copies the context it is
        # started in, never holds a browser's name.
        return self._delivery_stream(handle)

    def _acting_for(self, connection: _Connection) -> str | None:
        """The browser device a relayed call names to the hub, or ``None`` (ADR-0298 §1).

        **Read off :meth:`_browser_device`, so there is one source of truth.** The
        device a message names as ``UserMessage.device_id`` is the device the hub
        binds it to (§2:7), and the hub binds it to the requesting device: the one
        ``acting_for`` names, or the connecting device where it names none. Deriving
        both from the one method is what keeps them equal.

        * **On the remote listener**, the browser device ADR-0174 §3 obtained for the
          connection: the gateway names it on every request it relays for it
          (ADR-0296 §1:5).
        * **On the loopback listener**, nothing. That browser is the gateway's own
          machine (ADR-0296 §1:7), which is the connecting device, and ``acting_for``
          "is absent where the request is the connecting device's own" (ADR-0298
          §1:2).
        * **On the remote listener, where the browser is the gateway's own machine**,
          nothing either, for the same clause: a browser reaching this gateway over
          the overlay from the machine it runs on is still that machine.

        * **On the hosted listener**, the hosted browser device, on every request
          (ADR-0327 §10:2): "It relays no request from the hosted listener without
          it, so no such request acts with the gateway's own device's roles."

        Args:
            connection: The connection the request arrived on.

        Returns:
            The name, or ``None`` where the call is the connecting device's own.
        """
        if connection.hosted:
            return self._settings.gateway_hosted_device
        if not connection.remote:
            return None
        device = self._browser_device(connection)
        return None if device == self._own_device else device

    @contextlib.contextmanager
    def _relaying_for(self, connection: _Connection) -> Iterator[None]:
        """Name the browser device around one relayed call (ADR-0298 §1:5).

        The outbound context value is set around the handler, so the one
        ``AssistantEngine`` call each handler makes runs inside it and the wire client
        writes it into that call's frame. No handler takes the name as an argument and
        no engine method gains one. Whether the request came through the hosted
        listener is set beside it, for the same reason (:data:`_THROUGH_THE_DOOR`).

        Args:
            connection: The connection the request arrived on.

        Yields:
            Nothing; the handler runs inside both.
        """
        name = self._acting_for(connection)
        token = _THROUGH_THE_DOOR.set(connection.hosted)
        try:
            with contextlib.nullcontext() if name is None else acting_for(name):
                yield
        finally:
            _THROUGH_THE_DOOR.reset(token)

    def _browser_device(self, connection: _Connection) -> str | None:
        """The device a browser request comes from, as the gateway names it (ADR-0296 §1).

        A device is the machine, never a tab or a process (§1:6), and the gateway names
        it from facts of its own and never from anything the browser asserts:

        * **On the remote listener**, the overlay identity ADR-0174 §3 obtained for the
          connection from the gateway's own agent — the browser device of §1:1.
        * **On the loopback listener**, the gateway's own machine, which §1:7 makes
          that machine's hub device — named by the rule the command line names its
          machine by (:func:`~ai_assistant.interfaces.devices.this_device`): ``hub``
          where the hub is on this machine too, and otherwise this machine's overlay
          identity, read once from its own agent at :meth:`start`.

        **A loopback browser whose machine the agent would not name has no name
        here**, and ``None`` says so rather than inventing one. So a write from it is
        refused as its own condition (:meth:`_write_message`) instead of being
        recorded under an id the hub would not know the machine by.

        * **On the hosted listener**, the hosted browser device the operator named in
          ``gateway_hosted_device`` (ADR-0327 §10:1): every browser through the door
          is that one device, and none of them a machine.

        Args:
            connection: The connection the request arrived on.

        Returns:
            The device's id, or ``None`` where the gateway cannot name it.
        """
        if connection.hosted:
            return self._settings.gateway_hosted_device
        if connection.remote:
            return connection.device
        return self._own_device

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
        if connection.hosted and path in _CREDENTIAL_PATHS:
            # ADR-0327 §12:1, decided from the listener as ADR-0177 §3:4 and §3:5 rule.
            # The reason is not the remote listener's: the hosted page is HTTPS, and a
            # credential typed there would leave the person's device for the box and
            # pass the edge in the clear on it (§12's note).
            return _fault(
                403,
                "Forbidden",
                "credential-entry-loopback-only",
                detail=(
                    "Entering a credential is available on a loopback origin only. "
                    "Through the sign-in door a secret typed here would cross the box "
                    "in the clear on its way to the hub. Disconnecting and reading the "
                    "connections are available here."
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
        except DeviceRefusedError as exc:
            # Ahead of every caller's own naming: a refusal for the device is the same
            # condition whichever operation met it (ADR-0298 §6).
            raise _Refused(self._device_refused(exc)) from exc
        except (TransportError, AssistantError, ValueError) as exc:
            raise _Refused(named(exc)) from exc
        finally:
            self._give_hub_slot()

    def _device_refused(self, exc: DeviceRefusedError) -> Response:
        """One request the hub refused for its device, as the page reads it (ADR-0298 §6).

        The device is the one the request was made for, read back off the outbound
        name the call ran inside (:meth:`_relaying_for`) — the very value the frame
        carried — and otherwise the gateway's own, which is the connecting device the
        hub decided where the frame named none (§2:1).

        **The sentence is worded for whoever reads it** (:func:`.refusal_detail`): the
        person through the sign-in door, where the call came through the hosted
        listener (:data:`_THROUGH_THE_DOOR`), and the owner at a machine of their own
        anywhere else. The fault name is the same on both, so the reason stays
        machine-readable to the page (ADR-0298 §6:2).

        Args:
            exc: The refusal.

        Returns:
            The response: the reason's own fault name, and this gateway's sentence.
        """
        named = current_acting_for()
        return _fault(
            422,
            "Unprocessable Content",
            REFUSAL_FAULTS[exc.reason],
            detail=refusal_detail(
                exc.reason,
                device=self._own_device if named is None else named,
                gateway=self._own_device,
                hosted=_THROUGH_THE_DOOR.get(),
            ),
            close=False,
        )

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
        ending = _Ending()
        return _Streamed(
            handle=handle,
            head=StreamHead(
                content_type=streams.MEDIA_TYPE,
                headers=(streams.keep_alive_header(self._settings.gateway_notification_budget),),
            ),
            body=partial(write_stream, stream=opened, frame=ending.framing, wrote=ending.wrote),
            release=partial(self._deliveries.close, opened),
            ending=ending,
            delivery=opened,
        )

    def _change_stream(
        self, request: Request, handle: SessionHandle, connection: _Connection
    ) -> Response | _Streamed:
        """Open one browser's change stream, relayed from the hub's (ADR-0298 §7).

        **One hub stream per browser stream, relayed change for change.** Nothing is
        shared between two browsers or two tabs: each has its own cursor, and the hub
        filters each stream for the device it is followed for (§7:4, §7:5), so there is
        nothing a fan-out could hold in common. The stream holds one of
        ``gateway_max_hub_connections`` for its life, as a delivery poll does
        (ADR-0175 §7), and is refused with the ceiling where none is free.

        **The whole iteration runs inside the browser's name** (:meth:`_relaying_for`,
        ADR-0298 §1:5): the wire client writes ``acting_for`` into the request frame,
        and again into each one it reopens the stream with when the hub goes quiet
        (§7:13). Nothing is named for a loopback browser, which is the connecting
        device.

        **The head is written before the hub has answered**, so a refusal the hub
        makes on the first step — a device holding no role (ADR-0298 §5's "Reading
        many") — arrives as the stream's terminal ``fault``, carrying the same name
        and sentence a refused request would (:meth:`_device_refused`). Waiting for
        the first chunk instead would hold the head for as long as the chat space is
        quiet, since an engine followed in-process writes nothing until something
        changes.

        **The head states the cadence the gateway writes at**, the delivery stream's
        own figure (:meth:`_delivery_stream`): the gateway writes ``alive`` whenever
        that long passes with nothing else written, so the page can tell a quiet chat
        from a stream that has died.

        Args:
            request: The admitted request, carrying ``after``.
            handle: The session that admitted it (ADR-0175 §7).
            connection: The connection it arrived on, which names the browser.

        Returns:
            The stream, or a refusal: a malformed cursor, or the ceiling.

        Raises:
            _Refused: If the cursor is absent or out of range.
        """
        after = _required_cursor(_payload(request), "after")
        if not self._take_hub_slot():
            return _ceiling()
        ending = _Ending()
        budget = self._settings.gateway_notification_budget
        return _Streamed(
            handle=handle,
            head=StreamHead(
                content_type=streams.MEDIA_TYPE,
                headers=(streams.keep_alive_header(budget),),
            ),
            body=partial(
                self._follow_chat,
                after=after,
                connection=connection,
                every=budget,
                ending=ending,
            ),
            release=self._give_hub_slot,
            ending=ending,
            ends_when_the_peer_leaves=True,
        )

    async def _follow_chat(
        self,
        writer: asyncio.StreamWriter,
        *,
        after: int,
        connection: _Connection,
        every: timedelta,
        ending: _Ending,
    ) -> None:
        """Relay the hub's change stream onto one browser's, until either ends.

        Each chunk becomes one value (:func:`_stream_value`); the hub's heartbeat is
        relayed as ``alive``, and the gateway writes one of its own whenever ``every``
        passes with nothing written. The hub's ``ChatStreamEnd`` is relayed as the
        terminal ``end``; a failure the hub reports, or a hub that cannot be reached,
        as the terminal ``fault`` a refused request would name.

        **A browser that stops reading is let go.** A write that has not drained when
        the next keep-alive falls due ends the stream, as ADR-0175 §4 ends a delivery
        stream: the gateway holds nothing behind a browser that is not taking it, and
        stops asking the hub on its behalf. The page follows again from its cursor.

        Args:
            writer: The connection's writer, already carrying the stream's head.
            after: The browser's cursor.
            connection: The connection the stream was opened on, which names the
                browser device it is followed for (:meth:`_relaying_for`).
            every: The keep-alive cadence the head stated.
            ending: The stream's record of what it has written (:class:`_Ending`).

        Raises:
            ConnectionAbortedError: If a write did not drain within ``every``.
        """
        seconds = every.total_seconds()

        async def write(value: Mapping[str, Any]) -> None:
            writer.write(ending.framing(value))
            try:
                async with asyncio.timeout(seconds):
                    await writer.drain()
            except TimeoutError:
                writer.close()
                msg = "the browser stopped reading its change stream"
                raise ConnectionAbortedError(msg) from None
            ending.wrote()

        with self._relaying_for(connection):
            try:
                chunks = self._engine.follow_chat(after=after)
                async with closing_stream(paced(chunks, every=seconds)) as values:
                    async for chunk in values:
                        if isinstance(chunk, ChatStreamEnd):
                            await write(streams.end(chunk.next_after))
                            return
                        await write(streams.alive() if chunk is None else _stream_value(chunk))
            except DeviceRefusedError as exc:
                await write(_stream_fault(self._device_refused(exc)))
            except (TransportError, AssistantError, ValueError) as exc:
                await write(_stream_fault(_relay_fault(exc)))

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
        """Forget the episodes on one conversation's place (ADR-0175 §6, ADR-0293 §2:4).

        Memory-only since ADR-0293 §11:4: the conversation and its transcript stay,
        and ``destroyed`` answers whether an episode was forgotten.

        **This widens what a script on the gateway's own origin can spend, by less
        than what is already there**, and ADR-0175 §6 states the accounting rather
        than hiding it: ADR-0168 §6's residual — "script running on the gateway's own
        origin defeats both halves… it can simply issue requests the browser will
        authenticate" — covered ``converse`` from milestone 13 until it retired
        (ADR-0309 §5:4), and a turn could approve a tool, execute it and durably
        commit a non-idempotent effect. So this added a destructive operation to a
        surface that already carried a more destructive one, and no new class of
        residual.
        """
        named = _required_string(_payload(request), "conversation_id")
        destroyed = await self._relayed(partial(self._engine.forget_conversation, named))
        return _rendered({"destroyed": destroyed})

    # --- ADR-0293 §11: the chat space's acts in the medium and its reads ---
    #
    # One handler per operation, each one engine call (ADR-0168 §1). Every argument is
    # the browser's own but one: the device a message is written from, which is the
    # gateway's to name (ADR-0296's record on ADR-0177 §1:5) and which no body member
    # can supply. A conversation the hub says is gone is ``no-such-conversation``, the
    # condition :meth:`_conversation` already answers with, so the page treats a
    # conversation deleted elsewhere the same way whichever act met it.

    async def _start_conversation(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Start an empty conversation, shown on "my devices" (ADR-0293 §2:1)."""
        started = await self._relayed(self._engine.start_conversation)
        return _rendered({"conversation": _summary_view(started)})

    async def _my_devices(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_named`
        device: str | None,
    ) -> Response:
        """Read "my devices", and say which device this browser is (ADR-0293 §3:1).

        ``this_device`` is the gateway's naming of the browser's own machine
        (:meth:`_browser_device`), carried so the page can offer to add itself to the
        set rather than asking the owner to type an overlay identity. ``None`` where
        the gateway cannot name it.
        """
        held = await self._relayed(self._engine.my_devices)
        return _rendered({"devices": [_device_view(one) for one in held], "this_device": device})

    async def _set_my_devices(self, request: Request) -> Response:
        """Replace "my devices" with the set the browser sent (ADR-0293 §3:1, §3:2).

        The whole set travels, as the surface takes it: the page adds or removes a
        device by sending the set it now wants, so nothing here composes a change out
        of the set it last read.
        """
        devices = _chat_devices(_payload(request))
        changed = await self._relayed(partial(self._engine.set_my_devices, devices))
        return _rendered({"changed": changed})

    async def _set_conversation_devices(self, request: Request) -> Response:
        """Choose one conversation's devices, leaving "my devices" alone (ADR-0293 §3:3)."""
        payload = _payload(request)
        named = _required_string(payload, "conversation_id")
        devices = _chat_devices(payload)
        changed = await self._relayed(
            partial(self._engine.set_conversation_devices, named, devices=devices),
            fault=_chat_fault,
        )
        return _rendered({"changed": changed})

    async def _write_message(self, request: Request, device: str | None) -> Response:
        """Write the owner's message into a conversation, and answer *received* (§4).

        **The device is the gateway's naming and never the browser's**: no body member
        is read for it, so a page cannot write as another device. The message id is
        the browser's, chosen once per message and sent again with a repeat (§4:1,
        §4:2), so a send the page could not confirm is safe for the owner to press
        again.

        **Two refusals are answered before the hub is asked**, each as its own
        condition: a browser whose device the gateway cannot name
        (:meth:`_browser_device`), and a message over the size bound, which §4:7 has
        "refused, with the error on the send" — the bound is the type's, so the same
        figure the hub would refuse on. Everything else is the hub's answer, and a
        receipt with no position (``not_an_end``, ``no_such_reply``) is an answer, not
        a fault: the page says what it means.
        """
        payload = _payload(request)
        named = _required_string(payload, "conversation_id")
        message_id = _required_string(payload, "message_id")
        text = _required_string(payload, "text")
        replies_to = _optional_position(payload, "replies_to")
        if device is None:
            return _fault(
                422,
                "Unprocessable Content",
                "device-unnamed",
                detail=_DEVICE_UNNAMED,
                close=False,
            )
        if len(text) > TRANSCRIPT_MESSAGE_MAX_CHARS:
            return _fault(
                422,
                "Unprocessable Content",
                "message-too-long",
                detail=f"A message is at most {TRANSCRIPT_MESSAGE_MAX_CHARS} characters.",
                close=False,
            )
        try:
            message = UserMessage(
                device_id=device, message_id=message_id, text=text, replies_to=replies_to
            )
        except ValidationError:
            # Blank text or a blank message id: a value the browser owns and the type
            # refuses, answered as malformed without the rejected value in the body.
            raise _malformed() from None
        receipt = await self._relayed(
            partial(self._engine.write_message, named, message=message), fault=_chat_fault
        )
        return _rendered({"receipt": _receipt_view(receipt)})

    async def _composing(self, request: Request) -> Response:
        """Say the person is typing in a conversation, and answer nothing (ADR-0332 §5).

        **One relay and nothing else.** The conversation is the browser's own argument,
        relayed whole, and the signal is handed to ``AssistantEngine.composing`` (§5:9),
        which writes nothing into the medium, any store or any episode (§5:8). Nothing
        is held here either: the gateway keeps no note of who is typing, starts no wait,
        and answers no state.

        **Admission is the hub's** (ADR-0298 §5:6). ``composing`` is in the table's
        Writing row (ADR-0332 §5:11): the requesting device must be the named
        conversation's end for writing. That device is the one this gateway names for the
        request (:meth:`_relaying_for`), as it is for ``write_message``, so a browser
        device that only reads the conversation is refused by the hub, and the refusal
        reaches the page as its reason's own fault (:meth:`_relayed`). No device is
        checked here, and no body member is read for one.

        Args:
            request: The admitted request, carrying ``conversation_id``.

        Returns:
            An empty answer, because the signal answers nothing.
        """
        named = _required_string(_payload(request), "conversation_id")
        await self._relayed(partial(self._engine.composing, named), fault=_chat_fault)
        return _rendered({})

    async def _delete_message(self, request: Request) -> Response:
        """Delete one message of either author, leaving its marker (ADR-0293 §5:8, §5:9)."""
        payload = _payload(request)
        named = _required_string(payload, "conversation_id")
        position = _required_position(payload, "position")
        deleted = await self._relayed(
            partial(self._engine.delete_message, named, position=position), fault=_chat_fault
        )
        return _rendered({"deleted": deleted})

    async def _delete_conversation(self, request: Request) -> Response:
        """Delete a conversation and its transcript, forgetting nothing (ADR-0293 §2:3).

        The other act the page offers beside forgetting, never composed with it: no
        single operation both deletes and forgets (§2:7), so the page sends this or
        :data:`_FORGET_CONVERSATION_PATH`, and the gateway holds nothing between them.
        """
        named = _required_string(_payload(request), "conversation_id")
        deleted = await self._relayed(partial(self._engine.delete_conversation, named))
        return _rendered({"deleted": deleted})

    async def _transcript(self, request: Request) -> Response:
        """Read a conversation's recent messages, or the ones before a position (§5:13)."""
        payload = _payload(request)
        named = _required_string(payload, "conversation_id")
        before = _optional_position(payload, "before")
        limit = _page(payload, "limit", DEFAULT_PAGE_SIZE)
        page = await self._relayed(
            partial(self._engine.transcript, named, before=before, limit=limit)
        )
        if page is None:
            return _fault(404, "Not Found", "no-such-conversation", close=False)
        return _rendered({"transcript": _transcript_view(page)})

    async def _stop_activation(self, request: Request) -> Response:
        """Stop one running activation, named by the browser (ADR-0297 §5, ADR-0295 §1).

        **The id is the browser's own argument and is relayed whole**: the page names
        an activation its conversation's current state named while it showed
        "working…" (ADR-0297 §5:7), and nothing here reads a state to choose one, so
        a page cannot be made to stop an activation it did not name. Where the state
        names several, the page sends one of these for each (ADR-0349 §4:3): every
        stop still names exactly one activation (ADR-0295 §1:1). Whether the id
        names a running activation, an ended one or nothing the hub knows is the hub's
        answer (§5:4-§5:6), relayed as its own value; none of the three is a fault.

        **No device role is checked here** (§5:7): which devices may send a command
        is decided where every command's sender is checked, not in an adapter.

        Args:
            request: The admitted request, carrying ``activation_id``.

        Returns:
            Which of :class:`~ai_assistant.core.types.ActivationStop`'s three answers
            the stop reached, as its own value.
        """
        stopped = await self._relayed(
            partial(
                self._engine.stop_activation,
                _required_string(_payload(request), "activation_id"),
            )
        )
        return _rendered({"stop": stopped.value})

    async def _chat_changes(self, request: Request) -> Response:
        """Read every change to the chat space after the browser's cursor (§5:11).

        One request, answered at once: following the changes as they happen is the
        change stream's (:meth:`_change_stream`, ADR-0296 §4). The page reads this once,
        for the cursor it opens the stream from. The cursor is the browser's own — "a
        device keeps one cursor for the chat space" — and this gateway holds none.
        """
        payload = _payload(request)
        after = _required_cursor(payload, "after")
        conversations = _optional_ids(payload, "conversation_ids")
        limit = _page(payload, "limit", DEFAULT_PAGE_SIZE)
        page = await self._relayed(
            partial(
                self._engine.chat_changes,
                after=after,
                conversation_ids=conversations,
                limit=limit,
            )
        )
        return _rendered(_changes_view(page))

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
        """List the memories held, band-scoped, as summaries (ADR-0073 §1, ADR-0328 §15:1).

        Memories by default: the engine's listing excludes episodes unless the
        request names the episodic kind (ADR-0328 §11:2, ADR-0074 §6, #3143). The page
        never names it.

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
        """Read one memory with its supports resolved (ADR-0328 §15:2).

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

    async def _pending_candidates(
        self,
        request: Request,  # noqa: ARG002 — one signature per entry in `_unary`
    ) -> Response:
        """Relay the candidates the observer has not yet processed (ADR-0329 §18:2).

        **It takes no argument and is not paged**, and this handler adds neither: the
        read is bounded by the hub, and an adapter that offered a page would be
        inventing a surface §18:2 does not have. Nothing is joined to it and nothing
        is dropped; a hub whose ``remember`` writes memories answers none, and that
        empty answer is relayed as it came.

        Args:
            request: The admitted request, which carries no argument.

        Returns:
            Each pending candidate by its episode and its fact, in the hub's order.
        """
        held = await self._relayed(self._engine.pending_candidates)
        return _rendered({"candidates": [_pending_candidate_view(one) for one in held]})

    # --- ADR-0338 §8:1-§8:3: the person model, for the panels -------------
    #
    # Each handler is one engine call with the browser's own arguments, the person's id
    # among them: the page names the person whose model it shows, as every caller of the
    # promoted surface does, and the gateway supplies no person of its own (ADR-0177
    # §1:5). Where the hub keeps no person model, every one of the eight answers `off`
    # (:func:`_person_model_fault`).

    async def _person_model(self, request: Request) -> Response:
        """Read one page of a person's model (ADR-0338 §8:1-§8:2).

        Args:
            request: The admitted request, carrying ``person_id`` and an optional
                ``lists``, ``limit`` and ``offset``. An absent ``lists`` fills every
                list and an empty one fills none, as the contract says.

        Returns:
            The model, ``null`` where the hub holds no such person, or ``off``.
        """
        payload = _payload(request)
        held = await self._relayed(
            partial(
                self._engine.person_model,
                _required_string(payload, "person_id"),
                lists=_members(payload, "lists", PersonModelList),
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            ),
            fault=_person_model_fault,
        )
        return _rendered(
            {"person_model": None if held is None else person_views.person_model_view(held)}
        )

    async def _profile_changes(self, request: Request) -> Response:
        """Read one page of a person's change log, the most recent first (ADR-0338 §3:5).

        Args:
            request: The admitted request, carrying ``person_id`` and an optional
                ``limit`` and ``offset``.

        Returns:
            The page, or ``off``.
        """
        payload = _payload(request)
        page = await self._relayed(
            partial(
                self._engine.profile_changes,
                _required_string(payload, "person_id"),
                limit=_page(payload, "limit", DEFAULT_PAGE_SIZE),
                offset=_page(payload, "offset", 0),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"changes": [person_views.profile_change_view(one) for one in page]})

    async def _set_profile_field(self, request: Request) -> Response:
        """Set one of a person's five fields, or clear it (ADR-0338 §3, §8:2).

        **A clear is an absent or ``null`` value**, and nothing else is: the contract
        clears on ``None``, and a value of any other type is refused here rather than
        read as a clear, so a page that sent a number cannot empty a field. Validation
        of the value itself is the store's (§3:2), and its refusal crosses in the edit.

        Args:
            request: The admitted request, carrying ``person_id``, ``field`` and an
                optional ``value``.

        Returns:
            What the write did, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.set_profile_field,
                _required_string(payload, "person_id"),
                field=_member(payload, "field", ProfileField),
                value=_optional_string(payload, "value"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    async def _pin_memory(self, request: Request) -> Response:
        """Pin a memory, which confirms its wording (ADR-0338 §4:2-§4:3, §6:3).

        Args:
            request: The admitted request, carrying ``person_id`` and ``memory_id``.

        Returns:
            What the pin did, a refusal before any write among them, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.pin_memory,
                _required_string(payload, "person_id"),
                memory_id=_required_string(payload, "memory_id"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    async def _unpin_memory(self, request: Request) -> Response:
        """Unpin a memory, erasing nothing (ADR-0338 §4:7).

        Args:
            request: The admitted request, carrying ``person_id`` and ``memory_id``.

        Returns:
            What the unpin did, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.unpin_memory,
                _required_string(payload, "person_id"),
                memory_id=_required_string(payload, "memory_id"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    async def _remove_style_mark(self, request: Request) -> Response:
        """Remove a style mark, so its memory is not marked again (ADR-0338 §5:3).

        Args:
            request: The admitted request, carrying ``person_id`` and ``mark_id``.

        Returns:
            What the removal did, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.remove_style_mark,
                _required_string(payload, "person_id"),
                mark_id=_required_string(payload, "mark_id"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    async def _accept_person_suggestion(self, request: Request) -> Response:
        """Accept a pending suggestion (ADR-0338 §8:2, §8:8).

        Args:
            request: The admitted request, carrying ``person_id`` and ``suggestion_id``.

        Returns:
            What accepting it did, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.accept_person_suggestion,
                _required_string(payload, "person_id"),
                suggestion_id=_required_string(payload, "suggestion_id"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    async def _dismiss_person_suggestion(self, request: Request) -> Response:
        """Dismiss a pending suggestion, so an equal one is not recorded again (§9:2).

        Args:
            request: The admitted request, carrying ``person_id`` and ``suggestion_id``.

        Returns:
            What dismissing it did, or ``off``.
        """
        payload = _payload(request)
        edit = await self._relayed(
            partial(
                self._engine.dismiss_person_suggestion,
                _required_string(payload, "person_id"),
                suggestion_id=_required_string(payload, "suggestion_id"),
            ),
            fault=_person_model_fault,
        )
        return _rendered({"edit": person_views.edit_view(edit)})

    # --- ADR-0361 §4:6-§4:9: the approvals panel ------------------------------
    #
    # Each handler is one engine call with the browser's own arguments, none of them a
    # person: the panel is the person's own, whom the admitted device establishes
    # (§4:8). A tap is a command, never perceived (§4:7), and what it came to is the
    # hub's store's to say; the gateway relays it.

    async def _approvals(self, request: Request) -> Response:
        """Read the person's requests, as the approvals panel shows them (ADR-0361 §4:6).

        Args:
            request: The admitted request, carrying an optional ``limit``.

        Returns:
            The pending requests and the most recently ended, each as its card shows it.
        """
        payload = _payload(request)
        panel = await self._relayed(
            partial(self._engine.approvals, limit=_page(payload, "limit", DEFAULT_PAGE_SIZE))
        )
        return _rendered({"approvals": approval_views.panel_view(panel)})

    async def _tap_approval(self, request: Request) -> Response:
        """Tap Approve or Deny on one of the person's requests (ADR-0361 §4:7-§4:9).

        Args:
            request: The admitted request, carrying ``request_id`` and ``choice``.

        Returns:
            What the tap came to, and the request as the panel now shows it.
        """
        payload = _payload(request)
        tapped = await self._relayed(
            partial(
                self._engine.tap_approval,
                _required_string(payload, "request_id"),
                choice=_member(payload, "choice", ApprovalChoice),
            )
        )
        return _rendered({"tap": approval_views.tap_view(tapped)})

    # --- ADR-0078 §8: the deferred-question surface -----------------------

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


def _required_cursor(payload: Mapping[str, Any], name: str) -> int:
    """The change stream's cursor, which must be there: ``0`` for none (ADR-0293 §5:11).

    Required rather than defaulted, because ``chat_changes`` declares no default for
    it and ADR-0177 §1 has the gateway default no argument the surface leaves to its
    caller. Its range is the surface's own, ``[0, 2**63)``.

    Raises:
        _Refused: If the member is absent or is not an integer in that range.
    """
    if name not in payload:
        raise _malformed()
    return _page(payload, name, 0)


def _optional_position(payload: Mapping[str, Any], name: str) -> int | None:
    """A transcript position that may be absent or null: ``None``, or an integer ≥ 1.

    Raises:
        _Refused: If the member is present, not null, and not an integer in
            ``[1, 2**63)``.
    """
    if name not in payload or payload[name] is None:
        return None
    return _required_position(payload, name)


def _required_position(payload: Mapping[str, Any], name: str) -> int:
    """A transcript position that must be there, an integer in ``[1, 2**63)`` (§4:4).

    Raises:
        _Refused: If the member is absent or is not such an integer.
    """
    if name not in payload:
        raise _malformed()
    value = _integer(payload, name, 0)
    if value is None or not 1 <= value < _PAGE_CEILING:
        raise _malformed()
    return value


def _optional_ids(payload: Mapping[str, Any], name: str) -> tuple[str, ...] | None:
    """A list of conversation ids that may be absent or null, meaning every one.

    The bound and the blank check are the surface's own (``chat_conversation_ids``),
    and are left to it: what is refused here is only a shape that is not a list of
    strings, since nothing downstream could tell what it meant.

    Raises:
        _Refused: If the member is present, not null, and not a list of strings.
    """
    if name not in payload or payload[name] is None:
        return None
    value = payload[name]
    if not isinstance(value, list) or not all(isinstance(one, str) for one in value):
        raise _malformed()
    return tuple(value)


def _chat_devices(payload: Mapping[str, Any]) -> tuple[ChatDevice, ...]:
    """The ``devices`` member: a whole set of devices, each ``{device_id, access}``.

    Each entry is read as ADR-0293 §3 shapes it and nothing more: the device's id and
    whether it is an end for reading, writing or both (§3:5). Whether the set names a
    device twice is the surface's to refuse, and it does (``checked_chat_devices``),
    as a relay fault the page renders.

    Raises:
        _Refused: If the member is absent, is not a list, holds more than
            ``CHAT_DEVICES_MAX`` entries, or holds an entry that is not an object of
            exactly those two members with a known access.
    """
    value = payload.get("devices")
    if not isinstance(value, list) or len(value) > CHAT_DEVICES_MAX:
        raise _malformed()
    held: list[ChatDevice] = []
    for one in value:
        if not isinstance(one, dict) or set(one) != {"device_id", "access"}:
            raise _malformed()
        device_id, access = one["device_id"], one["access"]
        if not isinstance(device_id, str) or not isinstance(access, str):
            raise _malformed()
        if access not in _ACCESSES:
            raise _malformed()
        try:
            held.append(ChatDevice(device_id=device_id, access=DeviceAccess(access)))
        except ValidationError:
            raise _malformed() from None
    return tuple(held)


#: The three ways a device may be one of a conversation's ends (ADR-0293 §3:5), as
#: their wire values, so a browser value is matched against the enumeration rather
#: than handed to its constructor.
_ACCESSES: Final = frozenset(one.value for one in DeviceAccess)

#: What the page is told where the gateway cannot name the browser's device
#: (:meth:`Gateway._browser_device`). The owner's words, and the remedy is where to go.
_DEVICE_UNNAMED: Final = (
    "This gateway cannot name this browser's device, so it cannot write a message from "
    "here: its hub is on another machine, and a browser on the gateway's own machine is "
    "that machine's device, whose overlay identity this machine's overlay agent did not "
    "give the gateway when it started. Start the overlay agent and restart the gateway, "
    "or write from a browser on the hub's own machine, or from another device through "
    "the gateway's remote listener."
)


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


def _optional_string(payload: Mapping[str, Any], name: str) -> str | None:
    """One optional string member: absent or ``null`` is ``None``, anything else refused.

    Not :func:`_string`, which reads a member of the wrong type as absent: here absent
    *means* something — ``set_profile_field`` clears a field on ``None`` — so a value of
    another type is refused rather than taken for a clear. Relayed verbatim, as
    :func:`_required_string` relays.

    Args:
        payload: The request's JSON object.
        name: The member to read.

    Returns:
        The value, or ``None`` where it is absent or ``null``.

    Raises:
        _Refused: If the member is present and is neither a string nor ``null``.
    """
    value = payload.get(name)
    if value is None or isinstance(value, str):
        return value
    raise _malformed()


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


def _chat_fault(exc: Exception) -> Response:
    """One failed act on a named conversation: gone is its own condition, the rest relayed.

    An act in the medium raises ``UnknownConversationError`` where "the id names no
    conversation, or one deleted" (ADR-0293 §2:2), and the page meets the same fact on
    a read as ``no-such-conversation`` (:meth:`Gateway._conversation`). Answering it
    here under that name, rather than as :func:`_relay_fault`'s ``assistant-declined``,
    is what lets the page drop a conversation deleted on another device whichever act
    found it out. Everything else is ADR-0168 §9's three conditions, unchanged.
    """
    if isinstance(exc, UnknownConversationError):
        return _fault(404, "Not Found", "no-such-conversation", close=False)
    return _relay_fault(exc)


def _person_model_fault(exc: Exception) -> Response:
    """One person-model act on a hub that keeps no person model, answered as that state.

    :class:`~ai_assistant.core.errors.PersonModelOffError` is "not a fault and not a
    refused write" in its own words: the hub keeps no person model to read or write,
    "so a client shows 'not switched on' rather than an empty profile". So it crosses as
    an answer that says so, ``{"off": true}``, and never as a refusal the page would
    render in its fault surface. It stays distinguishable from every answer the hub
    gives a person model, each of which carries its own member and never ``off``.
    Everything else is ADR-0168 §9's three conditions, unchanged.
    """
    if isinstance(exc, PersonModelOffError):
        return _rendered({"off": True})
    return _relay_fault(exc)


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


def _summary_view(summary: ConversationSummary) -> dict[str, Any]:
    """One conversation, as a person choosing which to continue reads it (ADR-0074 §2).

    An enumeration for ADR-0168 §6's reason: what may appear on the page is
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
        "state": _state_view(digest.state),
        "devices": [_device_view(one) for one in digest.devices],
    }


def _state_view(state: ConversationState) -> dict[str, Any]:
    """What a conversation's devices are shown about the assistant (ADR-0293 §8).

    Relayed and never derived: "working…" while an activation started from the
    conversation runs (§8:2), and how the last one ended (§8:3, with ADR-0295 §3:4's
    *stopped*). The page renders it beside the transcript and never into it (§8:1).

    **Every running activation the state names crosses, in the state's order**, as
    ``activation_ids``, and the page's stop control sends a stop for each (ADR-0349
    §4:3, §10:3). The one ``activation_id`` this view carried before is not kept beside
    it: the page is its only reader, and this gateway serves the page with ``no-store``,
    so every load pairs the page with this view. A page left open across an upgrade
    finds no id under the old key and offers no stop until it is loaded again, which is
    safer than a key that would let it stop one activation of several.
    """
    return {
        "working": state.working,
        "activation_ids": list(state.activation_ids),
        "last_ended": None if state.last_ended is None else state.last_ended.value,
    }


def _device_view(device: ChatDevice) -> dict[str, Any]:
    """One device of a set, "my devices" or a conversation's (ADR-0293 §3)."""
    return {"device_id": device.device_id, "access": device.access.value}


def _receipt_view(receipt: MessageReceipt) -> dict[str, Any]:
    """The answer to a send: the outcome, and the position that is *received* (§4:4)."""
    return {
        "conversation_id": receipt.conversation_id,
        "outcome": receipt.outcome.value,
        "position": receipt.position,
    }


def _entry_view(entry: TranscriptMessage | DeletedMessage) -> dict[str, Any]:
    """One transcript entry: a message with ADR-0293 §5:2's properties, or its marker.

    **A deleted message crosses as its marker alone** — its position and that it was
    deleted, with no text (§5:12) — so a reply naming it is shown as naming a deleted
    message (§5:8). An enumeration for ADR-0168 §6's reason: what may reach
    the page is decided here and not by whatever the type later carries.
    """
    if isinstance(entry, DeletedMessage):
        return {"position": entry.position, "deleted": True}
    return {
        "position": entry.position,
        "deleted": False,
        "written_at": entry.written_at.isoformat(),
        "author": entry.author.value,
        "text": entry.text,
        "replies_to": entry.replies_to,
        "options": list(entry.options),
        "cut_off": entry.cut_off,
        "device_id": entry.device_id,
        "message_id": entry.message_id,
    }


def _transcript_view(page: TranscriptPage) -> dict[str, Any]:
    """Part of a conversation's transcript, and the cursor it was read at (§5:13)."""
    return {
        "conversation_id": page.conversation_id,
        "entries": [_entry_view(one) for one in page.entries],
        "as_of": page.as_of,
    }


def _change_view(change: ChatChange) -> dict[str, Any]:
    """One change to the chat space, told apart by its ``kind`` (ADR-0293 §5:10).

    Each kind carries the conversation it is about (``None`` for "my devices") beside
    its sequence number, so the page applies it without a lookup.
    """
    head: dict[str, Any] = {"kind": change.kind, "seq": change.seq}
    match change:
        case MessageAddedChange():
            return {
                **head,
                "conversation_id": change.conversation_id,
                "message": _entry_view(change.message),
            }
        case MessageDeletedChange():
            return {
                **head,
                "conversation_id": change.conversation_id,
                "position": change.marker.position,
            }
        case ConversationStartedChange():
            return {
                **head,
                "conversation_id": change.conversation_id,
                "devices": [_device_view(one) for one in change.devices],
            }
        case ConversationDeletedChange():
            return {**head, "conversation_id": change.conversation_id}
        case DevicesChangedChange():
            return {
                **head,
                "conversation_id": change.conversation_id,
                "devices": [_device_view(one) for one in change.devices],
            }


def _changes_view(page: ChatChanges) -> dict[str, Any]:
    """The changes after a cursor, and the cursor to ask from next (§5:10, §5:11)."""
    return {"changes": [_change_view(one) for one in page.changes], "next_after": page.next_after}


def _stream_value(chunk: ChatStreamChunk) -> dict[str, Any]:
    """One chunk of the hub's change stream, as the browser's stream carries it.

    Exactly one of four, as the chunk holds exactly one (ADR-0298 §7:3), each under its
    own ``kind`` (ADR-0175 §2):

    * ``change`` — the change as :func:`_change_view` renders it in a page of
      ``chat_changes``, and ``snapshot``: the conversation's entries as
      :func:`_entry_view` renders a transcript's, on the change that makes the device
      a reader (§7:6), and ``null`` on every other. One shape, so the page reads one
      member rather than testing for one;
    * ``state`` — a conversation's current state, as :func:`_state_view` renders the
      digest's (ADR-0296 §4:9);
    * ``roles`` — the device's own roles (§7:9);
    * the hub's heartbeat — relayed as ``alive``, which is what it is to the page.
    """
    if chunk.change is not None:
        snapshot = chunk.change.snapshot
        return {
            "kind": streams.ValueKind.CHANGE.value,
            "change": _change_view(chunk.change.change),
            "snapshot": None if snapshot is None else [_entry_view(one) for one in snapshot],
        }
    if chunk.state is not None:
        return {
            "kind": streams.ValueKind.STATE.value,
            "conversation_id": chunk.state.conversation_id,
            "state": _state_view(chunk.state.state),
        }
    if chunk.roles is not None:
        return {
            "kind": streams.ValueKind.ROLES.value,
            "roles": [one.value for one in chunk.roles],
        }
    return streams.alive()


async def _while_the_peer_stays(body: Awaitable[None], reader: asyncio.StreamReader) -> bool:
    """Run a stream's body until it ends or the browser leaves, whichever is first.

    A browser sends nothing on a connection whose response it is still reading, so
    anything the reader returns — the end of the stream above all — is the browser
    having gone: a page that aborts its ``fetch`` closes the connection. Leaving it to
    the next write to find that out holds what the body holds for as long as the body
    writes nothing.

    Args:
        body: The stream's body, not yet started.
        reader: The connection's reader.

    Returns:
        Whether the body ran to its end. ``False`` where the browser left first, and the
        body was cancelled.

    Raises:
        ConnectionError: Whatever the body raised, as it raised it.
        OSError: Likewise.
    """
    running = asyncio.ensure_future(body)
    leaving = asyncio.ensure_future(reader.read(1))
    try:
        await asyncio.wait({running, leaving}, return_when=asyncio.FIRST_COMPLETED)
        if running.done():
            await running
            return True
        return False
    finally:
        for pending in (running, leaving):
            pending.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending


def _stream_fault(refused: Response) -> dict[str, Any]:
    """A refusal a request would have been answered with, as a stream's terminal value.

    The same ``fault`` name and the same sentence, read back off the body the request
    path builds, so a refusal reaches the page in the same words whichever of the two
    shapes met it — and no second table of names can drift from the first.
    """
    body = json.loads(refused.body)
    detail = body.get("detail")
    return streams.fault(body["fault"], detail=detail if isinstance(detail, str) else None)


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
    """What ADR-0328 §15:1 has **both** memory views carry, as the record holds it.

    The id, the wording, the standing and its band, the status, the validity end, as
    of, learned, the evidence summary, the reading certainty, the track record's counts
    and last use, and whether it is legacy, unbacked, rests on outside content, or has
    lost every episode its supports point into (§15:7). **No confidence, presented
    confidence or elision count crosses** (§15:3): a memory carries none.

    Nothing here computes a value: each is the engine's projection's, so the page and
    the CLI cannot quote different standings for one memory (ADR-0189 §1).
    """
    evidence = belief.evidence
    track = belief.track_record
    return {
        "id": belief.id,
        "kind": belief.kind,
        "band": belief.band.value,
        "standing": None if belief.standing is None else belief.standing.value,
        "status": None if belief.status is None else belief.status.value,
        "content": belief.content,
        "valid_until": _instant(belief.valid_until),
        "as_of": _instant(belief.as_of),
        "learned": _instant(belief.learned),
        "evidence": {
            "supporting": evidence.supporting,
            "against": evidence.against,
            "episodes": evidence.episodes,
            "latest": _instant(evidence.latest),
        },
        "reading_certainty": (
            None if belief.reading_certainty is None else belief.reading_certainty.value
        ),
        "track_record": {
            "relied_on": track.relied_on,
            "held_up": track.held_up,
            "let_down": track.let_down,
            "last_used": _instant(track.last_used),
        },
        "legacy": belief.legacy,
        "unbacked": belief.unbacked,
        "rests_on_outside_content": belief.rests_on_outside_content,
        "supports_gone": belief.supports_gone,
        # What reported it and when, on that source's clock (ADR-0189 §1): an episode's
        # provenance attestation, or the source details a memory's standing rests on
        # (ADR-0328 §2:6); null otherwise.
        "attestation": _attestation_view(belief.attestation),
        # ADR-0345 §12:1: whose belief it is, whom it is about, what it is for, and the
        # marks; and, for a memory marked as the assistant's statement, where and when
        # it was said (§12:4).
        "holders": [_holder_view(one) for one in belief.holders],
        "partial_supporters": [_holder_view(one) for one in belief.partial_supporters],
        "subjects": None if belief.subjects is None else list(belief.subjects),
        "involved": None if belief.involved is None else list(belief.involved),
        "labels": [label.text for label in belief.labels],
        "marks": [mark.value for mark in belief.marks],
        "statements": [
            {"episode": one.episode, "when": _instant(one.when)} for one in belief.statements
        ],
    }


def _holder_view(holder: SupportHolder | None) -> dict[str, Any] | None:
    """Whose belief a support records, and whether that is the owner (ADR-0345 §12).

    ``owner`` is computed here, against the identifier that names the owner (§2:5), so
    the page says "you" without knowing that identifier.
    """
    if holder is None:
        return None
    return {
        "kind": holder.kind.value,
        "identifier": holder.identifier,
        "claimed": holder.claimed,
        "owner": holder.kind is HolderKind.PERSON and holder.identifier == OWNER_PERSON_ID,
    }


def _instant(instant: datetime | None) -> str | None:
    """An instant as the wire carries one, or ``null`` where it is unknown."""
    return None if instant is None else instant.isoformat()


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


def _belief_summary_view(summary: BeliefSummary) -> dict[str, Any]:
    """One row of the listing, which ships the computed values and **not** the supports.

    The split is the type's rather than this function's (ADR-0085 §4a): a
    :class:`~ai_assistant.core.types.BeliefSummary` has nowhere to put a support.
    """
    return _belief_fields(summary)


def _pending_candidate_view(candidate: PendingCandidate) -> dict[str, Any]:
    """One pending candidate: its episode and its fact, and nothing more (ADR-0329 §18:3)."""
    return {"episode_id": candidate.episode_id, "fact": candidate.fact}


def _belief_view(belief: Belief) -> dict[str, Any]:
    """The single-memory view: the same fields, plus every support (ADR-0328 §15:2).

    A support whose part no longer resolves crosses with ``content`` ``null`` — shown
    as gone, never as evidence, and never as a bare id (§15:7, ADR-0073 §4's floor).
    :class:`~ai_assistant.core.types.SupportView` carries no id at all.
    """
    return _belief_fields(belief) | {"supports": [_support_view(one) for one in belief.supports]}


def _support_view(support: SupportView) -> dict[str, Any]:
    """One support: its part resolved or gone, and what the record holds of it."""
    return {
        "part": support.part,
        "content": support.content,
        "origin": support.origin.value,
        "direction": support.direction.value,
        "note": support.note,
        "how_sure": None if support.how_sure is None else support.how_sure.value,
        "when": _instant(support.when),
        "about_when": _instant(support.about_when),
        "source_details": _attestation_view(support.source_details),
        "counts": support.counts,
        "holder": _holder_view(support.holder),
    }


def _notification_view(record: HeldNotification, *, now: datetime) -> dict[str, Any]:
    """One held notification, as a person deciding what to do with it reads it.

    An enumeration for ADR-0168 §6's reason, and a **different** one from
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

    **The agent is built only where a remote listener or this machine's device needs
    one** (:func:`_agent_for`), from ``client_overlay_agent_socket`` — the field
    ADR-0174 §8 widens rather than duplicating: "a gateway may dial its hub over
    loopback and still serve browsers over the overlay, so the condition widens to
    cover a set ``gateway_remote_address``. No eleventh agent-socket field is owed, and the
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
        hosted_bundle=packaged_bundle(hosted=True),
    )
    act = _install_the_mint_act(gateway=gateway, disclose=disclose, report=report)
    try:
        gateway.mint_bootstrap(disclose, act=act)
        await gateway.serve()
    finally:
        _release_the_mint_act(act)


def _agent_for(settings: Settings) -> OverlayAgent | None:
    """This machine's overlay agent, where a remote browser listener needs one.

    **Also where the hub is on another machine**, because this machine's device is
    then its overlay identity and the agent is what says it (ADR-0296 §1:7,
    :meth:`Gateway._name_own_device`). Such a gateway already reaches its hub through
    an agent built from this same setting, under these same custody conditions, so
    building one here puts no new check on its path.

    Args:
        settings: The loaded configuration.

    Returns:
        The agent, or ``None`` where no remote listener is configured, the hub is on
        this machine, and none is read. Building one eagerly would put a configured
        socket's custody check on the path of every gateway, including the
        loopback-only one ADR-0168 §2 rules and which never asks the agent anything.

    Raises:
        ConfigurationError: If a configured socket path fails the custody conditions
            ``wire/overlay.py`` holds both ends of ADR-0124 §4's hop to.
    """
    if settings.gateway_remote_address is None and settings.remote_hub_address is None:
        return None
    return local_agent(settings.client_overlay_agent_socket, terms=CLIENT_AGENT_SOCKET)
