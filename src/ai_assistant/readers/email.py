r"""The email reader: one local mbox file, read into attested envelope proposals.

Leg 11's second concrete :class:`~ai_assistant.core.protocols.Reader`, and the
second implementation ADR-0095 §3 said the shared conformance suite was waiting
for. It opens one file, resolves which of the messages that file holds arrived in
the window behind *now*, and proposes each one's **envelope** as an ``ATTESTED``
belief. It holds no store, writes nothing, keeps no cursor, and is never its own
caller.

**The arrangement is three parts and the file is the boundary between them**
(ADR-0140 §1). A co-located **fetcher** holds the account credential and writes a
local store; this reader opens that store and returns a ``SourceReading``. The two
share no process, no memory and no state but the file. The fetcher is a
*deployment component and not part of this system* — no Protocol describes it, no
``Settings`` field configures it, and nothing in ``src/`` starts, stops,
supervises or health-checks it. Everything this module says about it is confined
to the file boundary, and every such requirement is one a **deployment** meets and
this reader **cannot verify**.

**Nothing here opens a network connection, and no credential enters this
process** (§11). ``EmailReader`` speaks no IMAP, POP or SMTP, resolves no host,
and has no input but the store file and the clock. That is the whole reason the
arrangement is worth its awkwardness: ADR-0093 §11 rules that a networked source
"cannot be reached by changing a path to a URL" because it transmits a credential
and a request, and none of that is true of this system, because the process that
does it is not this system. What the hub does is open a file, which is what it
already does for a calendar. A later lane looking at ``secret_store/`` and at an
email source will see a natural home for an IMAP password; putting one there
would move the network into the hub by the shortest available path.

**A mailbox is out of ADR-0093 §5's scope and this source is not.** §5's clause
predicates on a source that *cannot be re-read in full within its bound* — and
what this reader opens is not the account, it is a file the fetcher replaces whole
containing the recent traffic. One ``open``, one bounded read, and every read gets
everything the file then holds. So there is **no cursor and no durable per-source
state** (ADR-0140 §3), and §5's own argument transfers clause for clause: the
window moves with the clock, so every run recomputes it from scratch. What that
costs is stated rather than assumed — it holds for as long as the fetcher's
retention exceeds this reader's window, and where it does not, messages are lost
to ingestion permanently. That is §5's already-accepted price arriving through the
fetcher rather than through the clock, and the operator's remedy is the same:
lengthen the retention or shorten the interval, knowingly.

**Envelopes only, and the argument is minimisation before it is injection**
(ADR-0140 §5). What leaves this reader is a sender string, a subject string and
two instants. No body span is ever interpreted, materialised, or put in a
proposal, a facet or any other value — which buys three bounds by construction
rather than by a rule someone must remember: ``sensitivity`` stays honestly
``PERSONAL`` (a mailbox's *bodies* hold everything from a newsletter to a
password-reset link, Tier 0 by ADR-0004's own classification, and no per-message
classifier could tell them apart); the byte cap becomes a bound rather than a
lottery (one 25 MiB attachment would exceed any figure a table could defend, and
ADR-0093 §5 makes a cap refuse rather than truncate, so one large message would
take the source offline until an operator intervened); and ADR-0140 §10's
narrowing is a shape rather than a discipline.

**Nothing the store says is authenticated, and no field of a message is an
identity** (§4). A sender address, a display name, a ``Message-ID`` or any other
field is *what the store says*, never a verified fact, and nothing in this system
may make a band, confidence, precedence, permission, grant, routing or ranking
decision on the strength of one. That clause is general because the reason is:
anyone who can send mail can already put any ``From:`` they like on a real
message, SMTP has never authenticated it, and the ``ATTESTED`` band is exactly
the right home for a belief whose whole standing is that somebody else said it.

**Two clocks, kept apart as two facts** (§5). ``Date:`` is the sender's claim,
which is precisely what :attr:`~ai_assistant.core.types.Attestation.reported_at`
means and precisely the thing an attacker controls — deciding window membership
on it would let a sender hold a message in every future window by writing a
future date, or drop out of every window by writing a past one. The **delivery
instant** is a different fact, written by the fetcher from what the server
recorded, and it is what membership is decided on. Neither is ever substituted
for the other.

**What is deliberately absent.** No coverage and no extent (§7): coverage is what
a read *exhausted*, and this read exhausts a file rather than a world — whether
the store holds every message that arrived in an interval is the fetcher's
property and unverifiable here, so declaring one would be a claim about the mail
account made on testimony, which ADR-0110 §2 forbids in its own words. The
demotion it would buy is not wanted either: the fetcher's retention guarantees
every message eventually leaves the store, so a coverage-declaring email reader
would retire the entire email half of memory on a disk-space setting's schedule.
No cursor, above. No lifecycle method (ADR-0093 §7): the only thing a ``close``
could do about a thread blocked in an uninterruptible syscall is wait for it. No
configurable identity: this reader is ``"email"``, never the account — ADR-0093
§7 uses exactly this source as its worked counter-example, and here the mistake
would be one keystroke away in a ``Settings`` field, which is why there is no
field.

**What the fetcher owes, and why none of it is checked here** (§1, §2, §5). It
must write header blocks and no bodies; exactly one
``X-Assistant-Delivered-At`` per message, in the closed subset
:func:`_delivery_instant` fixes, from the server's own record and after stripping
every copy the message carried; no header value containing a bare line break, and
the format's separator escaped; a store replaced whole by ``rename(2)`` on the
same filesystem, never appended to or edited in place; a retention exceeding this
reader's window; and a credential that never enters the hub. **The snapshot
property is bought by that ``rename(2)`` requirement and is not a property this
reader can establish from the bytes it reads** — where the requirement is
violated it may observe a store no complete version ever held, and nothing here
may be read as a guarantee that it cannot. What the reader does instead is skip
what it cannot interpret, and the clauses that bound a violated write are §4's,
which hold whatever the bytes turn out to be.

**Deploying the fetcher, and why it is a script rather than a mature daemon**
(§2). ADR-0095 rates co-located fetchers strongest because the pattern delegates
credential handling, network failure and protocol drift to mature tools — and
here that reason inverts halfway: ``offlineimap`` and ``mbsync`` are those tools
and both write **incrementally**, which is the one discipline §2 forbids. So the
delegation is kept where it is expensive and given up where it is cheap.
``imap-tools`` owns IMAP and TLS (#664's survey, kept entire except the word
*maildir*, §2); building a file and renaming it is a dozen lines, and it is the
dozen lines that let §7's descriptor check and the kernel's inode semantics do
the work three clauses would otherwise have to do badly. Install it on the hub
box as a *tool*, never as a dependency of this project — ``uv tool install
imap-tools`` — and give it a timer it owns (cron or a systemd timer). The shape
below is verified against ``imap-tools`` 1.15.0; its retries, its schedule and
its process model are its own and are governed nowhere here (§1)::

    import imaplib
    import os
    import ssl
    import tempfile
    import time
    from datetime import UTC, datetime, timedelta

    from imap_tools import A, MailBox

    KEEP = ("From", "Subject", "Date")
    SEPARATOR = "From assistant-fetcher Thu Jan  1 00:00:00 1970"


    # The one INTERNALDATE among a response's items, or None if it is not there.
    def delivered_at(items):
        for item in items:
            if isinstance(item, tuple):
                item = item[0]
            if isinstance(item, bytes) and b"INTERNALDATE" in item:
                local = imaplib.Internaldate2tuple(item)
                if local is not None:
                    return datetime.fromtimestamp(time.mktime(local), UTC)
        return None


    # Every message newer than `retention`, as one envelope-only mbox frame each.
    def frames(host, user, password, retention):
        # A day earlier than the edge: SINCE compares dates, not instants.
        since = (datetime.now(UTC) - retention - timedelta(days=1)).date()
        context = ssl.create_default_context()  # verified TLS; see below
        with MailBox(host, ssl_context=context).login(user, password) as box:
            box.folder.set("INBOX", readonly=True)
            for message in box.fetch(A(date_gte=since), headers_only=True, mark_seen=False):
                status, data = box.client.uid("FETCH", message.uid, "(INTERNALDATE)")
                if status != "OK":
                    continue
                delivered = delivered_at(data)
                if delivered is None:
                    continue
                stamp = format(delivered, "%Y-%m-%dT%H:%M:%SZ")
                lines = [SEPARATOR, "X-Assistant-Delivered-At: " + stamp]
                for name in KEEP:
                    for value in message.obj.get_all(name, []):
                        lines.append(name + ": " + " ".join(value.splitlines()))
                yield ("\n".join(lines) + "\n\n").encode()


    # Build the whole store beside its target, then move it into place.
    def publish(path, blocks):
        handle, staged = tempfile.mkstemp(dir=os.path.dirname(path))
        try:
            with os.fdopen(handle, "wb") as store:
                for block in blocks:
                    store.write(block)
                store.flush()
                os.fsync(store.fileno())
            os.replace(staged, path)
        except BaseException:
            os.unlink(staged)
            raise

**Six requirements, and every one of them is discharged by a specific line
above** — §13 states them as a list, and a list is what a deployment silently
half-implements.

- **Header blocks and no bodies** (§5). ``headers_only=True`` with
  ``mark_seen=False`` is what makes the IMAP command ``BODY.PEEK[HEADER]``: the
  first half leaves the body on the server, and the second is the ``.PEEK`` — with
  ``mark_seen`` left at its **default of ``True``** the same call is ``BODY[HEADER]``
  and sets ``\Seen`` on every message it touches. That is a *write* to the user's
  mailbox, from the network half of a seam that is read-only by construction
  (ADR-0093 §1), which is why ``readonly=True`` on the folder select is beside it
  rather than instead of it. Only ``KEEP``'s three fields are then emitted, so
  minimisation happens at the source rather than in the reader, which is what
  makes the reader's uniform ``PERSONAL`` tier honest.
- **Exactly one ``X-Assistant-Delivered-At``, and every copy the message carried
  stripped** (§5). Stripped **by construction**: the block is *built* from
  ``KEEP`` rather than filtered, so a header the sender wrote under our own name
  is never in a position to be forgotten. The value is the server's
  ``INTERNALDATE``, which is the only instant on our side of the file — ``Date``
  is the sender's clock and the thing an attacker controls (§5), and the search
  term is ``date_gte`` rather than a sent-date term for exactly that reason:
  ``imap-tools`` renders it as IMAP's ``SINCE``, which selects on
  ``INTERNALDATE`` too, so both ends of the arrangement are on one clock.
  **``SINCE`` is nonetheless a coarse filter and the extra day is not
  superstition**: RFC 3501 §6.4.4 selects on the internal date *"disregarding
  time and timezone"*, so the server compares calendar dates rendered in **its**
  zone against the date given. A server behind UTC therefore stamps a message
  delivered at ``2026-08-07T02:00Z`` with the local date ``06-Aug``, and a
  ``SINCE`` computed by truncating the retention edge to its UTC date would drop
  it while the reader's window — which is instants, and closed at the bottom —
  still contains it. §3 leaves no cursor to notice, so that message is lost
  permanently rather than late. Subtracting a day before truncating makes the
  search a **superset** of the retention edge in every zone; narrowing back to
  the window is the reader's job and it does it on the delivery instant.
- **In the closed subset and nothing wider** (§5, :data:`_DELIVERED_AT_VALUE`).
  The ``%Y-%m-%dT%H:%M:%SZ`` spelling lands inside it by construction.
  ``datetime.isoformat`` also lands inside it **when the value is UTC-aware** —
  it writes ``+00:00``, which the subset admits, and up to six fractional digits,
  which it also admits — and lands outside it the moment the value is **naive**,
  because there is then no offset at all and the message is silently skipped
  rather than dated. That is the failure mode to expect from a fetcher that
  reaches for the obvious call.
- **No header value carrying a bare line break, and the separator escaped**
  (§13). ``" ".join(value.splitlines())`` puts each value on one physical line,
  which discharges both: a value that cannot break the line cannot smuggle a
  ``From `` at one, and with every emitted line either the separator or
  ``Name: value``, no other line can begin the framing sequence. A fetcher that
  keeps bodies loses that argument and owes the ``>``-prefix escape instead — one
  more reason not to keep them.
- **Replaced whole by ``rename(2)`` on the same filesystem** (§2).
  ``mkstemp(dir=...)`` stages the replacement in the target's **own directory**,
  which is what makes it the same filesystem, and ``os.replace`` is ``rename(2)``.
  A read already in flight keeps the old inode and completes against bytes that
  were whole. Staging in ``/tmp`` and moving across is the one substitution that
  looks equivalent and is not: a cross-device move is a copy, and a copy is
  visible half-written.
- **A retention exceeding the reader's window, and a credential that never
  enters the hub** (§13, §11). ``retention`` is the fetcher's and must exceed
  ``ASSISTANT_EMAIL_WINDOW_PAST`` below, because §3 leaves no cursor: a message
  that leaves the store before a read sees it is lost to ingestion permanently.
  It must also stay inside ``ASSISTANT_EMAIL_MAX_MESSAGES``, which refuses rather
  than truncates — a retention that outgrows the cap takes the source offline
  rather than reading the recent tail (§12). The credential is the fetcher's
  process and the operator's secret store; nothing puts it in this one, and
  ``secret_store/`` is exactly where a later lane will be tempted to (§11).

**Two things in that recipe are load-bearing and look like boilerplate**, which
is the combination worth spelling out in the one document an operator copies
from.

- **``ssl_context=ssl.create_default_context()`` is not decoration.**
  ``MailBox(host)`` with no context reaches ``imaplib.IMAP4_SSL``, which builds
  ``ssl._create_stdlib_context()`` when none is passed — a context with
  ``check_hostname=False`` and ``verify_mode=CERT_NONE``. That is *encrypted and
  unauthenticated*: any certificate is accepted, so an attacker positioned on the
  network receives the account password and then chooses what the store says.
  ``ssl.create_default_context()`` is the same two knobs at ``True`` and
  ``CERT_REQUIRED``. §11 keeps the credential out of the hub precisely because
  it is the sensitive thing in this arrangement — handing it to an unverified
  peer at the other end gives back everything that buys. Note what the second
  half would defeat and what it would not: forged envelopes are still bounded by
  §4, which holds whatever the bytes turn out to be, because nothing the store
  says is authenticated *anyway*.
- **The ``INTERNALDATE`` is selected from the response rather than indexed out
  of it.** IMAP may interleave untagged and unsolicited responses, so
  ``data[0]`` is not reliably the item asked for;
  ``imaplib.Internaldate2tuple`` returns ``None`` rather than raising when its
  pattern does not match, and ``time.mktime(None)`` then raises ``TypeError``
  out of the generator — aborting the whole run *before* ``publish``, so the
  previous store stays in place. The reader cannot tell that store from a
  current one (§1, §7), which turns one odd response into a silent staleness
  rather than a loud failure. Selecting the item and skipping the message when
  there is none keeps the failure per-message, which is the same shape §5 gives
  the reader for a header it cannot use.

**Arming the read** is two settings, and the hub reads nothing on the strength of
them::

    ASSISTANT_EMAIL_SOURCE_PATH=/home/you/.mail/assistant.mbox
    ASSISTANT_EMAIL_READER_INTERVAL=PT15M

The path must be absolute — a relative one is refused at load, since it would
resolve against each process's working directory — and ``~`` is expanded. The two
are a matrix ``Settings`` refuses to leave incoherent: an interval with no path
fails at load, while a **path with no interval is coherent and deliberately
allowed**, being the facet-only state where a request-path assembly may read the
store while nothing ingests from it on a schedule (§12). The five remaining
fields — ``ASSISTANT_EMAIL_WINDOW_PAST`` (7 days), ``ASSISTANT_EMAIL_MAX_MESSAGES``
(2,000), ``ASSISTANT_EMAIL_MAX_BYTES`` (8 MiB), ``ASSISTANT_EMAIL_READ_TIMEOUT``
(10 s) and ``ASSISTANT_EMAIL_MAX_CONTENT_BYTES`` (4 MiB) — carry §12's defaults
and are what an operator changes only against a measured store.

**Every duration setting here takes either an ISO-8601 duration or a two-digit
``HH:MM:SS`` clock string**: ``PT15M``, ``PT30S``, ``00:15:00`` and ``P7D`` all
load. Two spellings are worth knowing before they cost an afternoon. A bare
number of seconds is **refused** — ``900`` fails at load with a parse error
naming a ``"day"`` identifier nobody typed, which is pydantic's message and the
same for every duration setting in this project (#981). And ``15:00`` **loads**,
as *fifteen hours* rather than fifteen minutes, while ``5:00`` is refused
outright because the hours field is two digits — so the wrong-by-a-factor form is
the one that starts cleanly.

**The grant is a separate act, and configuration is not consent** (§9, ADR-0097
§5). Until the user grants the source through a client the store is not
resolved, not opened and not parsed, and the scheduler's job fails every tick
with ``SourceNotGrantedError`` rather than reading::

    assistant sources                                 # what is offered, and from where
    assistant grant email --scope facet --scope ingest
    assistant amend email --scope ingest              # narrow or widen; two acts, both recorded
    assistant revoke email                            # prospective (ADR-0097 §6)

The source is **positional**; there is no ``--source`` option. A source holds one
grant at a time, so changing what one covers is ``assistant amend``, which is a
withdrawal followed by a fresh grant and says how each half went — or the same
two acts run by hand. ``--scope notify`` is accepted and buys nothing yet: §9
mints no producer for this source, so nothing reads that member until one exists.
§13 makes the composition-root registration its own deliverable — with
``email_source_path`` set the source is offered under the declared identity
``email`` and its consumers are wired on **separate** ``EmailReader`` instances;
with it unset, none of them is registered at all, because a source with nothing
to read is I/O on personal data in exchange for nothing.

**What revoking does not do, and it is not the calendar's situation** (§9). It
stops this system's read. It does not stop, start, describe or bear on the
fetcher: a process the operator launched holds a credential and pulls mail onto
the box whether or not any grant exists, so "your email is no longer being read"
is true and "we are no longer collecting your email" is false. No surface may say
the second. Nor does revoking remove the store from disk, and nothing here
retires what is already believed — ``assistant beliefs`` and ``assistant forget``
are that remedy.

**And a fetcher that stops running is invisible from here** (§1, §7). The reader
cannot tell a stale store from a quiet week: it reads the same messages, proposes
the same beliefs and reports health. That blindness is accepted rather than
patched, and §7's refusal to declare coverage is what keeps it from becoming a
*wrong* belief instead of merely a stale one — the fetcher is monitored where the
operator monitors processes, never through this system's surfaces.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from email.parser import BytesParser
from email.policy import compat32
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Final, final
from uuid import uuid4

from ai_assistant.core.clock import checked_clock
from ai_assistant.core.errors import ReaderError
from ai_assistant.core.types import (
    Attestation,
    DataTier,
    EmailFacet,
    MemorySource,
    MemoryUpdateProposal,
    Provenance,
    SemanticMemory,
    SourceReading,
)

# `saturating_add` and the two representable bounds are general instant
# arithmetic that happens to live beside the `.ics` semantics, and they are
# **shared rather than copied** on purpose: ADR-0093 §7b and ADR-0140 §3 state the
# same saturation rule for two readers, and two implementations of one clamp are
# two chances to disagree about where the bound is.
from ai_assistant.readers._occurrences import UTC_MAX, UTC_MIN, saturating_add
from ai_assistant.readers._source import OneWorker, acquire

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from email.message import Message

    from ai_assistant.core.clock import Clock

#: This reader's declared identity (ADR-0093 §7, ADR-0140 §9). **Declared, never
#: configured, and never the account**: it lands on the reading, on every belief
#: the gate then stores, in every export and in every log line, and a declared
#: constant cannot carry personal data at all — which is a property rather than a
#: rule. ``Reader.name``'s own docstring uses this exact source as the worked
#: counter-example: a reader names *itself*, never the data it holds.
EMAIL_READER_NAME: Final = "email"

#: The one header the reader decides window membership on (ADR-0140 §5). Written
#: by the **fetcher** from what the server recorded, which is what makes it the
#: only instant in a message whose author is on our side of the file: the
#: Unix-``From `` line is reachable by §4's splitting hazard and its timestamp has
#: never had one syntax, ``Received`` is a chain of hops whose earliest entries
#: are written by machines the sender may control, and ``Date`` is the sender's
#: own.
DELIVERED_AT_HEADER: Final = "X-Assistant-Delivered-At"

#: ADR-0140 §12's figures. The *dimensions* are the decision and the numbers are
#: revisable; each is named here rather than left to this module so that two
#: conforming implementations cannot diverge while each believes it conforms
#: (ADR-0074 §9.3, applied by ADR-0093 §5).
#:
#: They are repeated in ``core/config.py`` rather than imported from it, because
#: `core` depends on nothing else in ``ai_assistant`` (golden rule 2) and the
#: dependency can only point this way. ``tests/readers/test_email_settings.py``
#: pins the two to each other.
DEFAULT_EMAIL_WINDOW_PAST: Final = timedelta(days=7)
DEFAULT_EMAIL_MAX_MESSAGES: Final = 2_000
DEFAULT_EMAIL_MAX_BYTES: Final = 8 * 1024 * 1024
DEFAULT_EMAIL_READ_TIMEOUT: Final = timedelta(seconds=10)
DEFAULT_EMAIL_MAX_CONTENT_BYTES: Final = 4 * 1024 * 1024

#: The ceiling on the window's one arm (ADR-0140 §12). ``> 0`` alone admits
#: ``timedelta.max``, for which ``read_at - email_window_past`` is not a
#: representable instant — so a figure that passed a load-time range check would
#: produce an ``OverflowError`` on the first run, escaping ADR-0093 §8's two
#: outcomes entirely. It makes the overflow unreachable **from configuration
#: alone**; the case a clock can still reach is what :func:`saturating_add`
#: covers, which is why ADR-0140 §3 states a saturation clause of its own rather
#: than leaning on this number.
MAX_EMAIL_WINDOW: Final = timedelta(days=3650)

#: The upper bound ADR-0140 §12 puts on the message cap, for ADR-0093 §7a's
#: reason: a value outside ``[1, 2**63)`` is a ``ValueError`` wherever it is
#: eventually used, and a setting the runtime would refuse must fail at load
#: rather than at the first read.
MAX_EMAIL_COUNT: Final = 2**63

#: What a connected source's report is worth — the calendar reader's figure
#: unchanged, and for its reason: nothing forces a value below 1.0 in the
#: ``ATTESTED`` band, but a third party's claim about the user is not the user's
#: own word.
_ATTESTED_CONFIDENCE: Final = 0.9

#: A flat allowance for the fixed scaffolding of one rendered proposal — the
#: quoting, the date, the zone name — charged against ``email_max_content_bytes``
#: alongside the envelope's own text. Generous rather than exact: the budget
#: exists to stop a multiplicative blow-up, and a rendering that measured itself
#: precisely would have to be materialised first, which is the ordering ADR-0093
#: §7a forbids.
_RENDER_OVERHEAD_BYTES: Final = 256

#: Where one framed message begins. **CPython's own ``mailbox.mbox`` rule, matched
#: rather than approximated**: ``_generate_toc`` reads the store line by line and
#: starts a message at every line that ``startswith(b"From ")``, with no
#: precondition on what came before it. ``readline`` splits on ``\n`` alone, which
#: is exactly what ``(?m)^`` matches after, so this expression frames a store
#: identically to the stdlib — including the hostile shapes, which is the half
#: that matters (ADR-0140 §2, §4).
_MESSAGE_START: Final = re.compile(rb"(?m)^From ")

#: ADR-0140 §5's closed subset of RFC 3339, **stated as the admissible set rather
#: than as a list of exclusions**, because the list did not stay closed: three
#: separate literals sit inside RFC 3339's own grammar and each was found one at a
#: time, the second only after the first had been excluded. A fourth found later is
#: already excluded here rather than owing a fourth exclusion.
#:
#: What the shape buys, clause by clause. The separator is an upper-case ``T`` and
#: the zone spelling an upper-case ``Z``, because RFC 3339 §5.6 permits both in
#: lower case by name while ``datetime.fromisoformat`` raises on them — so the
#: message would be present in one lane's reading and absent from another's.
#: ``SS`` is ``00`` to ``59``, because §5.6 admits the leap second ``60``, which
#: Python's ``datetime`` cannot hold at all — leaving a lane whose parser accepts
#: the grammar to decide for itself whether to clamp or roll. And the fraction is
#: at most six digits, because every value this subset admits is one instant
#: ``UtcInstant`` holds exactly, so no conforming lane is ever left a
#: normalisation choice to make.
#:
#: ``-00:00`` is excluded by the guard in :func:`_delivery_instant` rather than by
#: this pattern, and the reason is not the one it looks like: RFC 3339 §4.3 makes
#: it a *determinate* UTC instant, so the value does establish a delivery time.
#: What it does not establish is agreement — ``datetime.fromisoformat`` reads it as
#: UTC while ``email.utils.parsedate_to_datetime`` treats the equivalent ``-0000``
#: as carrying no usable zone at all, so two conforming lanes admit and exclude the
#: same message at a window edge.
_DELIVERED_AT_VALUE: Final = re.compile(
    r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"T(?P<hour>[01]\d|2[0-3]):(?P<minute>[0-5]\d):(?P<second>[0-5]\d)"
    r"(?:\.(?P<fraction>\d{1,6}))?"
    r"(?:Z|(?P<sign>[+-])(?P<offset_hour>[01]\d|2[0-3]):(?P<offset_minute>[0-5]\d))"
)


class TooManyMessagesError(Exception):
    """The store framed more messages than ``email_max_messages`` (ADR-0140 §12).

    Refused, never truncated (ADR-0093 §5). **Counted at the framing**, which is
    the cap's ordering rather than its figure and is the property every other
    check passes while breached: deciding whether a message is *in the window*
    means reading its delivery header, which is the very step ADR-0140 §5's skip
    rule turns on — so a store of ``cap + 1`` messages none of which carries a
    valid ``X-Assistant-Delivered-At`` would be skipped message by message and
    returned as a **successful empty reading**. A busted cap wearing the clothes
    of a quiet week is exactly what the refuse-don't-truncate rule exists to
    prevent.

    The cost is that a reader pointed at a large archive refuses rather than
    reading the recent tail of it. That is the loud direction, and the operator's
    remedy is to shorten the fetcher's retention or raise the cap, knowingly.
    """


class ContentBudgetExhaustedError(Exception):
    """``email_max_content_bytes`` would be exceeded (ADR-0140 §12).

    It bounds the **output**, which none of the other caps do. A ``Subject`` may
    be folded across many lines, and two thousand of them inside the byte cap and
    the message cap alike can still materialise more content than any consumer
    wants. A single accumulator across the read, checked *before* each proposal is
    materialised.
    """


@dataclass(frozen=True)
class _Envelope:
    """One message's interpretable envelope: what a proposal is built from.

    Attributes:
        sender: ``From`` as the store gives it, or ``""``.
        subject: ``Subject`` as the store gives it, or ``""``.
        delivered_at: The fetcher's delivery instant, in UTC. What window
            membership is decided on, and never a report time.
        reported_at: The message's own ``Date``, in UTC. The sender's clock,
            which is what a report time is (ADR-0092 §3), and never a delivery
            instant.
        text_bytes: What this envelope's own text will cost the content budget,
            measured before anything is rendered (ADR-0093 §7a).
    """

    sender: str
    subject: str
    delivered_at: datetime
    reported_at: datetime
    text_bytes: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


@final
class EmailReader:
    """Reads one mbox file and proposes the envelopes that arrived in its window.

    Structurally implements :class:`~ai_assistant.core.protocols.Reader`.
    """

    def __init__(  # noqa: PLR0913 — one source, one clock and ADR-0140 §12's five figures; each is one knob a deployment sets
        self,
        path: Path,
        *,
        now: Clock = _utcnow,
        window_past: timedelta = DEFAULT_EMAIL_WINDOW_PAST,
        max_messages: int = DEFAULT_EMAIL_MAX_MESSAGES,
        max_bytes: int = DEFAULT_EMAIL_MAX_BYTES,
        read_timeout: timedelta = DEFAULT_EMAIL_READ_TIMEOUT,
        max_content_bytes: int = DEFAULT_EMAIL_MAX_CONTENT_BYTES,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        """Create a reader over one configured store.

        Every bound is refused **here**, not at the first read. ADR-0093 §10 names
        this as a clause the shared conformance suite cannot reach — "``Reader``
        specifies no constructor and no configuration surface … so a generic suite
        has nothing to over-supply. It is a concrete reader's test and a
        ``Settings`` test" — and this is the concrete reader's half of it.

        **No timezone parameter, unlike the calendar's**, and the absence is a
        consequence rather than an omission: every instant this reader reads is
        already an instant. The delivery header carries a determinate offset by
        ADR-0140 §5's grammar and ``Date`` is skipped unless it resolves to one,
        so there is no floating wall time for a zone to localise.

        Args:
            path: The store. **Absolute**, which is the *shape* validated at load;
                its existence and readability are properties of the world at an
                instant and are checked at run time, where they degrade under
                ADR-0093 §8 rather than refusing to start.
            now: The clock, read **exactly once per read, at the instant the
                store's bytes are acquired** (ADR-0093 §7b). Guarded by
                :func:`~ai_assistant.core.clock.checked_clock`.
            window_past: How far back the clock-relative arrival window reaches.
                May **not** be zero: a window of zero width is a reader that reads
                nothing while reporting health.
            max_messages: Framed messages the store may yield. Counted as they are
                framed, before any header is interpreted; exceeding it raises.
            max_bytes: The store read **before** parsing. Separate from
                ``max_messages`` and the one that must exist: a message cap can
                only be applied after parsing, so a cap on messages alone lets a
                2 GiB store be fully parsed before anything refuses it.
            read_timeout: This reader's deadline on its own read.
            max_content_bytes: Proposal content materialised across the whole read.
            id_factory: Mints the id of every record proposed. ``None`` mints a
                ``uuid4``. Injectable so tests assert exact ids; it is guarded at
                its output, which is the discipline ADR-0092 §6 owes a minted id.

        Raises:
            ValueError: If ``path`` is not absolute or any figure is outside
                ADR-0140 §12's range.
        """
        source = _checked_path(path)
        _check_window("email_window_past", window_past)
        _check_count("email_max_messages", max_messages)
        _check_positive_int("email_max_bytes", max_bytes)
        _check_positive_int("email_max_content_bytes", max_content_bytes)
        _check_duration("email_read_timeout", read_timeout)

        self._path = source
        self._now = checked_clock(now, owner="EmailReader")
        self._window_past = window_past
        self._max_messages = max_messages
        self._max_bytes = max_bytes
        self._read_timeout = read_timeout
        self._max_content_bytes = max_content_bytes
        self._id_factory = id_factory
        self._worker = OneWorker(thread_name=f"{EMAIL_READER_NAME}-reader")

    @property
    def name(self) -> str:
        """This reader's declared identity — stable, Tier 2, and never the account."""
        return EMAIL_READER_NAME

    async def read(self) -> SourceReading:
        """Read the store once, within this reader's own bound, and report it.

        Returns:
            The reading. An empty ``proposals`` tuple is a **success** and means
            the store had nothing to propose within the bound (ADR-0093 §8) — a
            quiet week, or a fetcher that stopped running, and **nothing here can
            tell the difference** (ADR-0140 §1). That blindness is named rather
            than papered over: the fetcher is monitored where the operator
            monitors processes, and §7's refusal to declare a coverage is what
            keeps it from becoming a *wrong* belief rather than a stale one.

        Raises:
            ReaderError: If the read cannot complete — a missing, unreadable,
                non-regular or oversized store, a store framing more messages than
                the cap, proposals past the content budget, a deadline expiry, or
                a worker from an earlier read still outstanding. The underlying
                failure is preserved as ``__cause__``; the **message** carries
                only this reader's identity and the failure's class.
            CancelledError: Delivered onward unchanged. A cancellation from
                outside is **excepted** from the wrapping rule above, and the
                carve-out matters because the wording it qualifies invites the
                mistake: a cancelled read has, in plain English, "not completed",
                and a reader wrapping everything it catches would convert it (§8).
        """
        try:
            return await self._worker.run(
                self._read_source, seconds=self._read_timeout.total_seconds()
            )
        except asyncio.CancelledError:
            # Explicit, though `except Exception` below would not catch it:
            # this is the one clause a conforming-looking reader gets wrong.
            raise
        except Exception as exc:
            raise ReaderError(self._failure(exc)) from exc

    def _failure(self, exc: BaseException) -> str:
        """A payload-free message: this reader's identity and the failure's class.

        ``raise ReaderError(str(exc)) from exc`` satisfies every word of ADR-0093
        §8's wrapping rule and, for a missing ``/home/alice/mail/inbox.mbox``,
        produces a message that **is** that path — which the scheduler then writes
        to a log under ADR-0083 §7. That is Tier 1 data in an operational log,
        which ADR-0004 §5 forbids outright, and a mail store's path is if anything
        worse than a calendar's: a directory names the user and a filename can
        name the account.

        The cause's class is included alongside this reader's own because it is
        the useful half and it is Tier 2 — ``PermissionError`` and
        ``FileNotFoundError`` tell an operator which action to take, and the
        operator already knows the path, because they configured it. Only the
        **class**, never ``str(cause)``, which for an ``OSError`` is the path.
        """
        cause = exc.__cause__
        if cause is None:
            return f"{self.name}: {type(exc).__name__}"
        return f"{self.name}: {type(exc).__name__} ({type(cause).__name__})"

    def _read_source(self) -> SourceReading:
        """The whole read, on the worker thread (ADR-0093 §7).

        **Every step is here and none of it is on the loop** — resolving the path,
        opening it, reading it, framing it, parsing header blocks and building the
        proposals alike. Run on the loop after the worker returned, that CPU work
        starves ADR-0083 §7's deliberately serial scheduler exactly as a blocked
        syscall does, and worse for the deadline: the timer callback cannot fire
        while the loop is occupied, so ``read()`` would overrun its timeout and
        then *return successfully*. A deadline that cannot be observed is not a
        deadline.
        """
        raw = acquire(self._path, max_bytes=self._max_bytes)
        # **Here, and exactly once** (ADR-0093 §7b). It is the moment the bytes
        # this reading describes came into our hands, and every membership test
        # below is evaluated against this one instant — which is what §7b's
        # truthfulness argument requires and what a directory walk could not have
        # supplied (ADR-0140 §2).
        read_at = self._now()
        window_start = saturating_add(read_at, -self._window_past)
        blocks = self._frame(raw)
        proposals = self._propose(blocks, window_start, read_at)
        return SourceReading(
            source=self.name,
            read_at=read_at,
            # **Never filled.** An mbox declares no reading-level as-of: the
            # format's report times are per message, and the file's mtime is a
            # fact about our filesystem rather than a claim the source made
            # (ADR-0093 §10, ADR-0092 §3).
            as_of=None,
            proposals=proposals,
            # **None, always** (ADR-0140 §7). A coverage is what a read
            # *exhausted*, and this read exhausts a file rather than a world:
            # whether the store holds every message that arrived in any interval
            # is the fetcher's property and there is no way to check it, so a
            # coverage declared here would be a claim about the mail account made
            # on testimony — the one thing ADR-0110 §2 forbids in its own words.
            # No belief this reader proposes is absence-demotable, and no extent
            # is declared for the same section's reason.
            coverage=None,
            facet=EmailFacet(
                source=self.name,
                read_at=read_at,
                as_of=None,
                # **What this read proposed from**, which is ADR-0140 §6's own
                # wording and is deliberately *not* the calendar's rule. That
                # facet counts occurrences its proposals skip, because it makes no
                # attestation and owes no report time; this one is specified as a
                # count of what was proposed from, so a skipped message is absent
                # from both halves. Either is legitimate — ADR-0093 §3 rules that
                # the two halves describing unequal sets is the design — and which
                # one holds here is the ADR's ruling rather than this module's.
                arrived_in_window=len(proposals),
                covers_from=window_start,
            ),
        )

    def _frame(self, raw: bytes) -> list[bytes]:
        """Split the store into per-message **header blocks**, and count as we go.

        Two acts, and ADR-0140 §5 turns on the difference between them: acquiring
        and traversing bytes is unrestricted and is what ADR-0093 §7's cap already
        governs, while *interpreting* them is what §5 confines to a header block.
        An in-band-delimited store cannot be traversed at all without scanning
        past bodies to reach the next delimiter, so a clause written over the
        bytes would be one the reader must breach to function — which is worse
        than no clause, because a later lane reads it as a guarantee somebody
        checked. What is returned here is the header block alone: the body is
        traversed and **discarded**, never parsed for meaning and never
        materialised into any value that leaves this reader.

        **Whether the framing is honest is the fetcher's and is not assumed.**
        Where §5's envelopes-only requirement is met there is no body for an
        unescaped ``From `` line to hide in; where it is not, text a message's
        author wrote may present itself here as another message's envelope. §4 is
        what bounds that — no authority, no identity, nothing authenticated — and
        nothing in this module may be read as a guarantee that it cannot happen.

        Returns:
            One header block per framed message, in the store's order. Bytes
            before the first ``From `` line frame no message and are discarded,
            exactly as ``mailbox.mbox`` discards them.

        Raises:
            TooManyMessagesError: As soon as the store frames more than
                ``email_max_messages``, before any header is interpreted.
        """
        starts: list[int] = []
        for match in _MESSAGE_START.finditer(raw):
            starts.append(match.start())
            if len(starts) > self._max_messages:
                msg = f"the store frames more than the {self._max_messages}-message cap"
                raise TooManyMessagesError(msg)
        if not starts:
            # An empty store, and a store of bytes that frame no message, are the
            # same answer: nothing was framed. Both are successful empty readings
            # (ADR-0093 §8) rather than faults — an mbox has no document-level
            # structure for arbitrary bytes to violate.
            return []
        bounds = [*starts[1:], len(raw)]
        return [_header_block(raw[start:end]) for start, end in zip(starts, bounds, strict=True)]

    def _propose(
        self, blocks: Sequence[bytes], window_start: datetime, read_at: datetime
    ) -> tuple[MemoryUpdateProposal, ...]:
        """Turn the in-window messages into attested proposals, within the budget.

        **The window is half-open and closed at the bottom** —
        ``window_start <= delivered_at < read_at`` — which ADR-0140 §3 states
        once. The lower edge is the direction that matters: a reader admitting
        only ``window_start < delivered_at`` loses the edge message
        **permanently** rather than late, because by the next run the window has
        moved past it and §3 leaves no cursor to notice.

        **A message the reader cannot interpret is skipped, and a skip raises
        nothing** (ADR-0140 §5). It is an entry the source holds that the read
        cannot account for, and ``CalendarReader`` skips exactly this shape for
        exactly this reason — ADR-0092 §3 permits no substitute for a report time
        the source did not make. That reader withholds its coverage on the
        strength of it; this one withholds nothing, because §7 gives it no
        coverage to withhold.

        Raises:
            ContentBudgetExhaustedError: Before materialising a proposal that
                would take the read past ``email_max_content_bytes``.
        """
        spent = 0
        proposals: list[MemoryUpdateProposal] = []
        for block in blocks:
            envelope = _interpret(block)
            if envelope is None:
                continue
            if not window_start <= envelope.delivered_at < read_at:
                continue
            spent += envelope.text_bytes + _RENDER_OVERHEAD_BYTES
            if spent > self._max_content_bytes:
                msg = (
                    f"the proposals would exceed the {self._max_content_bytes}-byte content budget"
                )
                raise ContentBudgetExhaustedError(msg)
            proposals.append(self._proposal(envelope, read_at))
        return tuple(proposals)

    def _proposal(self, envelope: _Envelope, read_at: datetime) -> MemoryUpdateProposal:
        """One attested belief about one message's envelope.

        **``reported_at`` lands in two fields for two different reasons**
        (ADR-0109 §4). In the ``Attestation`` it records who said what and when
        they said it — a disclosure obligation (ADR-0073 §4). As
        ``last_confirmed_at`` it records when the *world* last confirmed the
        belief, which for the ``ATTESTED`` band is the reporting source's report
        and never our ingestion of it (ADR-0103 §9).

        **No extent, and it is a ruling rather than an omission** (ADR-0140 §7).
        A message's position in the source's world is an instant, not a span, and
        ``ReportedExtent`` refuses a zero-width interval for a reason of its own:
        it would be contained by *every* coverage and would make the record
        demotable by any reading at all. ADR-0117 §6 met that shape in the
        zero-duration occurrence and ruled that the proposal simply declares none
        and is never absence-demotable. The same answer arrives here, and it costs
        nothing §7's first clause has not already declined.

        Args:
            envelope: What the store says about one message.
            read_at: Our own clock, at acquisition.
        """
        content = _render(envelope)
        return MemoryUpdateProposal(
            proposed=SemanticMemory(
                id=_mint(self._id_factory),
                content=content,
                fact=content,
                provenance=Provenance(
                    source=MemorySource.EXTERNAL,
                    confidence=_ATTESTED_CONFIDENCE,
                    # Ours: when *we* last revised the belief (ADR-0045 §3).
                    last_updated=read_at,
                    attestation=Attestation(
                        reported_by=self.name,
                        # Theirs, and never reconciled with ours — the sender's
                        # own `Date`, never the delivery instant beside it
                        # (ADR-0140 §5). A `reported_at` earlier than
                        # `last_updated` is the normal case rather than an
                        # anomaly.
                        reported_at=envelope.reported_at,
                        extent=None,
                    ),
                    # The band's confirming event, written as it stands: a
                    # `reported_at` in our future is stored unchanged rather than
                    # dropped or clamped (ADR-0092 §3). Never `read_at` — that
                    # would be transaction time, and a months-old message
                    # ingested this morning would read as perfectly fresh
                    # (ADR-0103 §9).
                    last_confirmed_at=envelope.reported_at,
                ),
            ),
            rationale=f"the {self.name} source reported this message",
            # Stated, never defaulted (ADR-0093 §4). `PERSONAL` is the honest
            # tier *because* the store holds envelopes: a mailbox's bodies hold
            # everything from a newsletter to a password-reset link, and no
            # per-message classifier could tell them apart — #659 records that a
            # `SECRET`-tier ruling made on the ingestion path reaches no surface,
            # so a wrong classification would also be an invisible one. An
            # envelope is `PERSONAL` and is uniformly `PERSONAL` (ADR-0140 §5).
            sensitivity=DataTier.PERSONAL,
        )


def _header_block(region: bytes) -> bytes:
    r"""The header block of one framed message: its separator line and body dropped.

    The block ends at the first **blank** line, which is RFC 5322's own boundary.
    A line of whitespace is not blank and stays in the block as a continuation,
    which is what makes a folded ``Subject`` survive framing intact.

    Split on ``\\n`` alone rather than with ``bytes.splitlines``, which also
    breaks on a bare ``\\r``: ``mailbox.mbox`` frames with ``readline``, so a
    lone ``\\r`` inside a header value is *not* a line boundary there and must
    not become one here. Matching the stdlib exactly is the point of the whole
    function (ADR-0140 §2).
    """
    _, _, rest = region.partition(b"\n")
    lines: list[bytes] = []
    for line in rest.split(b"\n"):
        if line in (b"", b"\r"):
            break
        lines.append(line)
    return b"\n".join(lines)


def _interpret(block: bytes) -> _Envelope | None:
    """One header block as an envelope, or ``None`` where it cannot be one.

    Every ``None`` here is ADR-0140 §5's **skip**, and a skip raises nothing.
    Nothing is substituted for a fact the source did not make: no fallback dates
    the message, and no field is filled from another.

    **The two instants are read under one rule and the two strings under
    another**, which §5 states in as many words. ``X-Assistant-Delivered-At`` and
    ``Date`` each carry an instant, so each must be present exactly once and
    resolve determinately or the message is skipped. The sender and the subject
    carry no instant and are never on their own a reason to skip: absent or
    duplicated, they are **empty**, with no selection made among the candidates.
    That last part is the case a lane breaches while passing the absent one,
    because ``email.message.Message``'s own mapping returns the *first* occurrence
    of a repeated header and says nothing — which is exactly the selection §5
    forbids, reaching the opposite outcome from the duplicate ``Date`` beside it.
    A message that legitimately carries no subject is ordinary mail rather than a
    fault.

    **Parsed under ``compat32``, which is what "as the store gives it" requires.**
    ``email.policy.default`` looks like the better choice and is not: it *rewrites*
    what it parses, turning ``From: <<<<>>>>`` into ``<>`` and an unterminated
    quoted display name into its contents. §5 carries the sender and subject as
    the store gives them, and §4 rules that nothing about them is authenticated
    anyway — so a normalising pass would put this reader's own interpretation on a
    value whose whole standing is that the store said it. What is done to the raw
    value is unfolding and nothing else.
    """
    message = BytesParser(policy=compat32).parsebytes(block, headersonly=True)

    delivered = _sole_header(message, DELIVERED_AT_HEADER)
    if delivered is None:
        return None
    delivered_at = _delivery_instant(delivered)
    if delivered_at is None:
        return None

    reported = _sole_header(message, "Date")
    if reported is None:
        return None
    reported_at = _reported_instant(reported)
    if reported_at is None:
        return None

    sender = _optional_header(message, "From")
    subject = _optional_header(message, "Subject")
    return _Envelope(
        sender=sender,
        subject=subject,
        delivered_at=delivered_at,
        reported_at=reported_at,
        text_bytes=len(sender.encode()) + len(subject.encode()),
    )


def _sole_header(message: Message, name: str) -> str | None:
    """``name``'s single value, or ``None`` where the message carries zero or many.

    **Skipping a duplicate rather than picking one is fail-closed and is the whole
    point** for the delivery header (ADR-0140 §5). The fetcher strips every copy
    the message carried and writes its own; where that strip has failed, taking
    the first occurrence would make forgery *work*, because the attacker writes
    theirs above the fetcher's and ordering decides membership. Skipping costs an
    attacker their own message and costs an honest deployment nothing.

    ``Date`` is read under the same rule because it is the other field carrying an
    instant, and there the alternative is a reader **selecting** among several
    report times — which is the same defect wearing a more reasonable face.
    """
    values = message.get_all(name)
    if values is None or len(values) != 1:
        return None
    return _unfolded(values[0])


def _optional_header(message: Message, name: str) -> str:
    """``name``'s single value, or ``""`` where the message carries zero or many.

    The other half of :func:`_sole_header`'s rule, for the two fields that carry
    no instant (ADR-0140 §5): the message is still proposed, with the field empty
    and **no selection made** among the candidates.
    """
    values = message.get_all(name)
    if values is None or len(values) != 1:
        return ""
    return _unfolded(values[0])


def _unfolded(value: object) -> str:
    """One raw header value as a single-line ``str``.

    Two coercions, and each closes something a header can actually do.

    ``compat32`` returns a plain ``str`` for a value it could decode as ASCII and
    an :class:`email.header.Header` for one carrying bytes it could not — so a
    value's *type* here depends on the store's content, and a lane that assumed
    ``str`` would carry an object into a proposal. ``str`` on the ``Header``
    substitutes the replacement character for what it could not decode, which is
    also what keeps a lone surrogate out of a value that must survive UTF-8
    encoding.

    Unfolding removes the line breaks and keeps the whitespace, which is RFC
    5322's own rule and is why a folded ``Subject`` arrives as one line. The
    break-only removal matters beyond tidiness: a header value carrying a bare
    line break is a fetcher fault §4 names, and one reaching a rendered belief
    would put a newline inside a quoted span.
    """
    text = value if isinstance(value, str) else str(value)
    return text.replace("\r", "").replace("\n", "")


def _delivery_instant(value: str) -> datetime | None:
    """The fetcher's delivery instant, or ``None`` where the value is not one.

    **The spelling is checked against ADR-0140 §5's closed subset itself, and
    acceptance is never delegated to a more permissive parser** — a parser
    accepting a value is not this clause's test. So the instant is *constructed*
    from :data:`_DELIVERED_AT_VALUE`'s own groups rather than handed to
    ``datetime.fromisoformat``, which accepts five things the subset excludes: a
    space separator, a comma fractional separator, an offset carrying seconds, an
    omitted ``SS``, and a ``+0000`` written without its colon. A reader delegating
    to it passes every test written against the *unparseable* direction and still
    admits what §5 excludes.

    **Nothing is normalised onto the subset** either: no leap second is rolled to
    the following instant, no separator is case-folded, and no precision is
    dropped to make a value acceptable. A value RFC 3339 admits but the subset
    does not is skipped whether or not it is well-formed.

    Surrounding whitespace is not part of a header field's value — every parser
    strips the space after the colon already — so it is stripped here too rather
    than skipping an honest fetcher's message over a trailing space. What is
    *inside* the value must be the timestamp and nothing else.

    Returns:
        The instant in UTC, saturated at the representable bounds, or ``None``.
    """
    match = _DELIVERED_AT_VALUE.fullmatch(value.strip())
    if match is None:
        return None
    sign, offset_hour, offset_minute = (
        match["sign"],
        match["offset_hour"],
        match["offset_minute"],
    )
    if sign is None:
        zone = UTC
    else:
        offset = timedelta(hours=int(offset_hour), minutes=int(offset_minute))
        if sign == "-":
            # Excluded here rather than in the pattern, because the value is
            # otherwise a determinate UTC instant and the reason it goes is
            # disagreement rather than ambiguity (see `_DELIVERED_AT_VALUE`).
            if not offset:
                return None
            offset = -offset
        zone = timezone(offset)
    fraction = match["fraction"]
    try:
        return _in_utc(
            datetime(
                year=int(match["year"]),
                month=int(match["month"]),
                day=int(match["day"]),
                hour=int(match["hour"]),
                minute=int(match["minute"]),
                second=int(match["second"]),
                microsecond=int(fraction.ljust(6, "0")) if fraction else 0,
                tzinfo=zone,
            )
        )
    except ValueError:
        # A date the grammar admits and the calendar does not — `2026-02-30`,
        # `2026-13-01`. Skipped like every other value that is not a timestamp.
        return None


def _reported_instant(value: str) -> datetime | None:
    """The message's own ``Date`` as an instant, or ``None`` where it resolves to none.

    ADR-0140 §5 skips a ``Date`` "the reader cannot resolve to a determinate
    instant — RFC 5322's ``-0000`` and an absent zone alike", and the predicate is
    what is implemented rather than the two values offered to illustrate it.
    ``parsedate_to_datetime`` reaches the whole of it in one shape: it **raises**
    on a value that does not parse at all, and returns a **naive** datetime for
    exactly the two that parse and then resolve to nothing usable — RFC 5322
    defines ``-0000`` as "no usable zone", and an absent zone is the same fact
    spelled differently. So the test is awareness, and the arms are not a list
    somebody has to keep complete.

    A lane handling only the illustrations reaches either a fallback or an
    escaping parser error, and the second breaches §5's rule that a skip raises
    nothing while every other test still passes.

    Unlike the delivery header this **is** delegated to a parser, and the
    asymmetry is deliberate: §5 fixes the delivery header's grammar itself
    because the fetcher writes it, while ``Date`` is RFC 5322's field as senders
    write it and the corpus has one answer for reading those.
    """
    try:
        parsed = parsedate_to_datetime(value)
    except ValueError, TypeError:
        return None
    if parsed.utcoffset() is None:
        return None
    return _in_utc(parsed)


def _in_utc(instant: datetime) -> datetime:
    """An aware instant in UTC, clamping instead of raising (ADR-0140 §3).

    A value near a representable bound can carry an offset that pushes its UTC
    form past it — ``0001-01-01T00:00:00+05:00`` is the reachable case, and a
    store is written by a component this reader does not control. Unguarded that
    raises an ``OverflowError`` from inside ``astimezone``, which escapes ADR-0093
    §8's two outcomes entirely rather than arriving as a ``ReaderError``, and
    would do it on a store that parsed perfectly.

    Deliberately not a refusal, for ADR-0093 §7b's reason: saturation loses
    nothing here, because a clamped instant lands outside any window a real
    deployment configures and is simply not proposed, while a refusal would take
    the whole source offline over one message.
    """
    try:
        return instant.astimezone(UTC)
    except OverflowError, ValueError, OSError:
        # The direction is decided by the offset that overflowed: a positive one
        # subtracts toward the minimum, a negative one adds toward the maximum.
        offset = instant.utcoffset() or timedelta(0)
        return UTC_MIN if offset > timedelta(0) else UTC_MAX


def _mint(factory: Callable[[], str] | None) -> str:
    """Mint one opaque record id, guarded at its output (ADR-0092 §6, ADR-0045 §4).

    **Opaque, and never the source's key.** ADR-0092 §6 rules that an ``EXTERNAL``
    producer proposes each record at an id it mints, opaque to the source, and
    ADR-0140 §4's fourth clause states it for this source because the header is
    unusually inviting: a ``Message-ID`` is globally unique, stable and sitting
    right there. It may not be used as, or derived into, a record id. A derived id
    is an **address**, aimed at the same record on every re-read, and "minting
    removes the aim" — with it the ADR-0038 §2a resurrection where a re-read
    recomputes a retired record's id and erases its closed validity window.

    **Idempotency does not vanish; it moves.** An unchanged message re-read
    proposes the same content, and the gate folds it by *similarity* at the
    target's id (#631). Email is the friendlier case here — a delivered message is
    immutable, so #631's rewrite arm has no subject — but the guarantee relied on
    is the narrower one ADR-0093 §5 relies on: a re-read destroys nothing.

    Raises:
        ValueError: If the factory returns anything that is not a non-blank
            built-in ``str``, so a malformed mint fails loudly instead of
            becoming a key.
    """
    minted = factory() if factory is not None else f"email-{uuid4().hex}"
    # An **exact** `str` is required rather than an `isinstance` one: a hostile
    # subclass — one whose `strip` or `__hash__` raises — passes `isinstance` and
    # then leaks an arbitrary exception across the seam as a store key.
    if type(minted) is not str or not minted.strip():
        msg = (
            "the id factory did not return a non-blank built-in str; "
            "a malformed mint must not become a key (ADR-0092 §6)"
        )
        raise ValueError(msg)
    return minted


def _render(envelope: _Envelope) -> str:
    """One envelope as the belief's canonical text.

    The whole field set ADR-0140 §5 admits, and nothing else. What is deliberately
    left out: ``To:`` and ``Cc:``, which multiply Tier-1 addresses by every
    recipient of every mailing list and whose useful question — *was this
    addressed to me* — needs the user's own addresses, which this reader does not
    have and must not guess; ``Message-ID``, which is not carried into content at
    all; and threading headers, because reconstructing a conversation from
    ``References`` is an inference and ADR-0093 §2 rules that a reader infers
    nothing. And the body, which is not in the store to render.

    **The rendered spans are external content under ADR-0098 §1** — the sender,
    the display name, the address and the subject alike — and every clause of
    ADR-0098 binds a consumer of them unchanged. A lane rendering one of these
    into a prompt owes §2 and §9's marked test for its assembler's own container
    syntax; nothing here discharges any part of it.
    """
    sender = envelope.sender.strip() or "an unnamed sender"
    subject = envelope.subject.strip() or "no subject"
    return f'Email from "{sender}" with subject "{subject}", delivered {_when(envelope)}.'


def _when(envelope: _Envelope) -> str:
    """The delivery instant, rendered in UTC.

    UTC rather than a local zone, and the absence of a choice is the point: this
    reader takes no timezone, because there is no floating wall time in a message
    for one to localise. Rendering the instant in the zone it is held in states
    exactly what the store said and needs no second configuration nobody argued.
    """
    return f"{envelope.delivered_at:%Y-%m-%d %H:%M} (UTC)"


def _check_window(field: str, value: timedelta) -> None:
    # **May not be zero**, unlike `calendar_window_past` — a window of zero width
    # is a reader that reads nothing while reporting health, and the neighbouring
    # field's `>= 0` is exactly what a lane inherits by copying (ADR-0140 §12).
    _refuse_a_non_duration(field, value)
    if value <= timedelta(0) or value > MAX_EMAIL_WINDOW:
        msg = (
            f"{field} must be > 0 and <= {MAX_EMAIL_WINDOW}, got {value!r}; the ceiling "
            f"is what keeps `read_at - {field}` reachable from configuration alone "
            f"(ADR-0140 §12)"
        )
        raise ValueError(msg)


def _check_duration(field: str, value: timedelta) -> None:
    _refuse_a_non_duration(field, value)
    if value <= timedelta(0):
        msg = f"{field} must be > 0, got {value!r}"
        raise ValueError(msg)


def _checked_path(value: object) -> Path:
    """The configured store as an absolute ``Path``, or a refusal naming the field.

    **Typed before it is called into**, which is this constructor's rule for every
    argument rather than a guard bolted onto one: a ``str`` has no ``is_absolute``
    and ``None`` has no attributes at all, so an unguarded call turns a caller's
    mistake into an ``AttributeError`` naming a *method* instead of the
    ``ValueError`` naming the field this seam documents.

    Typed ``object`` and returning the narrowed value, for
    :func:`_refuse_a_non_duration`'s reason: a ``Path`` annotation would make the
    refusal statically unreachable, which is the reasoning that let the value
    through. ``type(value).__name__`` rather than ``repr`` — a hostile
    ``__repr__`` must not raise past a guard, which is the discipline
    :func:`_mint` already keeps.

    ``Settings`` refuses a non-path at load and ``mypy`` refuses one at a
    type-checked call site; what is left is the direct caller ADR-0093 §10 names —
    "a test or a second composition root" — for whom the refusal is the only
    description of the rule they broke.

    Raises:
        ValueError: If ``value`` is not a ``Path``, or is not absolute. Absoluteness
            is the *shape* checked here; existence is a property of the world at an
            instant and is checked at run time, where it degrades under ADR-0093 §8.
    """
    if not isinstance(value, Path):
        msg = f"the email source must be a Path, got {type(value).__name__}"
        raise ValueError(msg)
    if not value.is_absolute():
        msg = (
            f"the email source must be an absolute path, got {str(value)!r}; a "
            f"relative value resolves against each process's working directory "
            f"(ADR-0093 §7)"
        )
        raise ValueError(msg)
    return value


def _refuse_a_non_duration(field: str, value: object) -> None:
    """Refuse a value no ordering comparison below could survive.

    Typed ``object`` because the guard **disbelieves the annotation, which is the
    point** — the same reason :func:`~ai_assistant.core.clock.checked_clock`
    states for its own parameter. A ``timedelta`` annotation here would make the
    refusal statically unreachable, which is exactly the reasoning that let the
    value through in the first place.

    **The type check is the two integer guards' rule for the durations**, and
    without it this constructor is asymmetric with itself: ``_check_count``
    refuses anything that is not exactly an ``int`` while a duration reached a
    bare ``<=``, so ``window_past=None`` escaped as a ``TypeError`` from an
    operator rather than as the ``ValueError`` this constructor documents.

    The reason a duration needs one at all is not the reason an integer does.
    ``bool`` is an ``int`` by inheritance, so ``max_messages=True`` **passes**
    ``mypy`` and loads as a cap of one — a value silently accepted, which is
    #471's defect. Nothing is silently accepted here: every wrong type already
    fails, and what it fails as is the whole of what this fixes. A refusal at
    construction that names the field it refused is what ADR-0093 §10 asks the
    concrete reader's constructor for, and an operator's ``TypeError`` naming
    ``NoneType`` and ``datetime.timedelta`` names neither the field nor the rule.

    ``isinstance`` rather than an exact-type test, unlike the integer guards: they
    are exact in order to exclude ``bool`` specifically, and there is no
    ``timedelta`` subclass whose acceptance would be a mistake.
    """
    if not isinstance(value, timedelta):
        msg = f"{field} must be a timedelta, got {value!r}"
        raise ValueError(msg)


def _check_count(field: str, value: int) -> None:
    # `bool` is an `int` by inheritance and a flag is not a count — the rule the
    # layers under `Settings` already state, at the seam a direct caller reaches
    # (issue #471).
    if isinstance(value, bool) or type(value) is not int or not 1 <= value < MAX_EMAIL_COUNT:
        msg = f"{field} must be an int in [1, 2**63), got {value!r}"
        raise ValueError(msg)


def _check_positive_int(field: str, value: int) -> None:
    if isinstance(value, bool) or type(value) is not int or value <= 0:
        msg = f"{field} must be a positive int, got {value!r}"
        raise ValueError(msg)


__all__ = [
    "DEFAULT_EMAIL_MAX_BYTES",
    "DEFAULT_EMAIL_MAX_CONTENT_BYTES",
    "DEFAULT_EMAIL_MAX_MESSAGES",
    "DEFAULT_EMAIL_READ_TIMEOUT",
    "DEFAULT_EMAIL_WINDOW_PAST",
    "DELIVERED_AT_HEADER",
    "EMAIL_READER_NAME",
    "MAX_EMAIL_COUNT",
    "MAX_EMAIL_WINDOW",
    "ContentBudgetExhaustedError",
    "EmailReader",
    "TooManyMessagesError",
]
