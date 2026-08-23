"""The gateway's own admission record for one browser, and the value that buys one.

ADR-0168 §4, §5 and §6 rule the session; ADR-0182 rules the bootstrap value beside
it — one outstanding at a time, ceasing on four events and no fifth.

A **web session** is "the gateway's own admission record for one browser… not an
enrolment (ADR-0124 §5), not a grant (ADR-0097), not a principal (ADR-0099 §1),
and no surface may present it as any of the three" (ADR-0168 §4). It is two
values — a cookie half and a header half — because a cookie is scoped to a host
and not to a port, so one value alone "would be presented to any other local
service on `127.0.0.1`" (ADR-0168 §6).

Everything here is process memory. ADR-0168 §4 forbids a session, a session value
or a verifier reaching "any database this system opens, any file, any log record,
any audit record, or into any error message or diagnostic the gateway emits", and
ADR-0172 §6 makes obeying that a **condition** of the ADR-0004 §3 exemption this
milestone runs under: an implementation that persists a session table does not
have the exemption and is in breach of ADR-0004 §3 as written.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Final, NewType, Protocol

#: What the table calls one live session, for a caller that must associate
#: something with it and end that thing when it does (ADR-0175 §7: "the gateway
#: ends every stream a session held at the moment that session ends").
#:
#: **It is not a session value and not a verifier** — it is an internal table key,
#: minted from :func:`secrets.token_hex` and never disclosed to a browser — so
#: handing one to a caller inside this process is not the disclosure ADR-0168 §4
#: forbids. It is still process memory that dies with the process, and nothing puts
#: one in a record: ADR-0168 §6's enumeration of what a record may carry does not
#: name it, and ``records.py`` is handed no session fact at all.
SessionHandle = NewType("SessionHandle", str)

#: How many random bytes each half and the bootstrap value carry. ADR-0168 §4 and
#: §5 require "at least 128 bits drawn from the operating system's cryptographic
#: random source"; 32 bytes is 256, and `secrets` is that source.
_ENTROPY_BYTES: Final = 32


class Cancellable(Protocol):
    """A scheduled callback that has not fired yet and can be called off."""

    def cancel(self) -> None:
        """Call the callback off."""


#: How the table defers a session's death. ADR-0168 §4 requires expired sessions
#: destroyed "continuously rather than at a checkpoint or on the next request that
#: happens to arrive", so a session's end is a scheduled act rather than a
#: condition someone notices — and it is injected rather than reached for, so a
#: test drives it instead of waiting out twelve hours.
Defer = Callable[[float, Callable[[], None]], Cancellable]


class Admission(StrEnum):
    """What the table made of the two values a request presented.

    The three are distinct because ADR-0168 §6 requires them to be: a header half
    verifying against a live session beside a cookie half that does not is
    "refused with a **distinct** fault — reported to the owner as its own
    condition, and never flattened into an expiry, a ceiling refusal or an
    ordinary absent session".
    """

    ADMITTED = "admitted"
    """Both halves verified against one live session."""

    NO_LIVE_SESSION = "no-live-session"
    """No live session verifies the header half presented, or none was presented."""

    COOKIE_HALF_MISMATCH = "cookie-half-mismatch"
    """A live session's header half arrived beside a cookie half that is not its
    own, or beside more than one cookie of the gateway's own name."""


@dataclass(frozen=True)
class SessionValues:
    """The two values a mint discloses to the browser, once (ADR-0168 §5, §6).

    Attributes:
        cookie_half: Set as an ``HttpOnly`` cookie and never read by script.
        header_half: Held in the origin's own browser storage and sent as a
            request header the front end sets.
    """

    cookie_half: str
    header_half: str


@dataclass
class _Session:
    """One live session: two verifiers, two clocks, and the timer that ends it.

    The values themselves are not here, and that is the whole point of the
    class. ADR-0124 §6 rules that retaining "only a verifier from which the
    credential cannot be recovered" means the retaining process "holds no
    device's Tier 0 secret at rest"; ADR-0168 §4 takes that verbatim for the
    gateway, and ADR-0172 §1 confirms a verifier is not itself in the credential
    class.
    """

    cookie_verifier: bytes
    header_verifier: bytes
    expires_at: datetime
    last_used_at: datetime
    timer: Cancellable | None = None


def verifier(value: str) -> bytes:
    """A digest of ``value`` from which ``value`` cannot be recovered.

    A plain SHA-256 rather than a password hash, and deliberately: every value it
    is given is 256 bits from the operating system's own random source
    (:data:`_ENTROPY_BYTES`), so there is no guessable input for a work factor to
    slow down, and a constant-time comparison is what the threat here actually
    needs.

    Args:
        value: The disclosed half, as the browser presents it.

    Returns:
        The digest the table retains in its place.
    """
    return hashlib.sha256(value.encode("utf-8")).digest()


def _saturating(moment: datetime, delta: timedelta) -> datetime:
    """``moment + delta``, or the end of representable time where that overflows.

    **A saturation clause rather than a ceiling on the setting**, and the choice is
    ADR-0140 §3's rather than ADR-0093 §7a's. ``gateway_session_ttl`` carries
    ``gt=timedelta(0)``, which admits ``timedelta.max``; a bound above the
    representable range is a session that never ends by lifetime, which is what
    saturating says, and it says it without adding a refusal ADR-0168 §8 does not
    state. The idle bound still binds, because a session ends "at the earlier" of
    the two — so a lifetime past the end of time is not a session without bounds.

    Args:
        moment: The reading to add to.
        delta: The bound being applied.

    Returns:
        The instant the bound falls on, or the latest representable one.
    """
    try:
        return moment + delta
    except OverflowError:
        return datetime.max.replace(tzinfo=moment.tzinfo)


def mint_value() -> str:
    """One value of at least 128 bits from the OS cryptographic random source."""
    return secrets.token_urlsafe(_ENTROPY_BYTES)


class SessionTable:
    """Every live web session, in process memory, dying with the process.

    The table holds no history: a session that ends is removed, and nothing
    records that it existed beyond the admission record ADR-0168 §6 requires,
    which the table does not write and does not keep.
    """

    def __init__(  # noqa: PLR0913 — one keyword per figure ADR-0168 §4 names, plus the two injected seams
        self,
        *,
        max_sessions: int,
        ttl: timedelta,
        idle_timeout: timedelta,
        now: Callable[[], datetime],
        defer: Defer,
        mint_value: Callable[[], str] = mint_value,
        on_ended: Callable[[SessionHandle], None] | None = None,
    ) -> None:
        """Build an empty table.

        Args:
            max_sessions: ``gateway_max_sessions`` — the ceiling a mint is refused
                at rather than evicting an incumbent (ADR-0168 §4).
            ttl: ``gateway_session_ttl``, a session's absolute lifetime.
            idle_timeout: ``gateway_session_idle_timeout``.
            now: The clock, injected so a test does not wait out a lifetime.
            defer: How a session's death is scheduled.
            mint_value: The entropy source, injected for the same reason as the
                clock. The default is the operating system's.
            on_ended: Called with a session's handle the moment that session ends,
                by whichever of its two bounds and on the way down alike. It is what
                ADR-0175 §7's "the gateway ends every stream a session held at the
                moment that session ends" hangs on: without a notification the
                gateway would learn of an ended session only on the next request
                that presented it, which a held-open stream never sends.
        """
        self._max_sessions = max_sessions
        self._ttl = ttl
        self._idle_timeout = idle_timeout
        self._now = now
        self._defer = defer
        self._mint_value = mint_value
        self._on_ended = on_ended
        self._sessions: dict[SessionHandle, _Session] = {}

    def __len__(self) -> int:
        """How many sessions are live."""
        return len(self._sessions)

    def mint(self) -> SessionValues | None:
        """Mint one session, or refuse at the ceiling (ADR-0168 §4).

        **Refusing rather than evicting is ADR-0131 §2's direction**, for its
        reason: evicting the oldest "hands any local caller a silent lever to log
        the owner out", and the eviction is indistinguishable from an ordinary
        expiry.

        Returns:
            The two values to disclose, or ``None`` where the ceiling is reached.
        """
        if len(self._sessions) >= self._max_sessions:
            return None
        values = SessionValues(cookie_half=self._mint_value(), header_half=self._mint_value())
        moment = self._now()
        key = SessionHandle(secrets.token_hex(8))
        session = _Session(
            cookie_verifier=verifier(values.cookie_half),
            header_verifier=verifier(values.header_half),
            expires_at=_saturating(moment, self._ttl),
            last_used_at=moment,
        )
        self._sessions[key] = session
        self._rearm(key, session)
        return values

    def admit(self, *, header_half: str | None, cookie_halves: tuple[str, ...]) -> Admission:
        """Decide one request's two values (ADR-0168 §6).

        The header half is what a session is *found* by, and the cookie half is
        what confirms it. That order is what makes the distinct fault decidable:
        without a session in hand there is nothing for a cookie to fail against,
        and a refusal that named the cookie anyway would be naming a condition it
        had not checked.

        Args:
            header_half: The value the front end sent as a header, or ``None``.
            cookie_halves: Every cookie presented under the gateway's own name —
                all of them, since more than one is itself the refusal.

        Returns:
            What the table made of them.
        """
        found = None if header_half is None else self._find(header_half)
        if found is None:
            return Admission.NO_LIVE_SESSION
        key, session = found
        # **The bound is what ends a session, not the scheduler's promptness.** The
        # timer below is the continuous destruction ADR-0168 §4 requires, and it is
        # still what removes an expired session with nobody asking; this is the
        # guard that keeps a *late* callback from admitting one past the bound it
        # has already crossed. Without it a busy loop, a suspended machine or a
        # request landing on the same turn as an overdue timer would be admitted —
        # and `_rearm` would then cancel the very callback that was about to end
        # it, so a session could outlive both of its bounds indefinitely.
        if self._expired(session):
            self._end(key)
            return Admission.NO_LIVE_SESSION
        if len(cookie_halves) != 1 or not hmac.compare_digest(
            verifier(cookie_halves[0]), session.cookie_verifier
        ):
            return Admission.COOKIE_HALF_MISMATCH
        # An admitted request is a use, so the idle clock restarts here rather than
        # in a second call a caller could forget: an idle timeout that measured age
        # would be the absolute lifetime under another name, and ADR-0168 §4 keeps
        # the two bounds separate on purpose.
        session.last_used_at = self._now()
        self._rearm(key, session)
        return Admission.ADMITTED

    def handle(self, header_half: str) -> SessionHandle | None:
        """The live session that header half names, for a caller that must hold it.

        A second lookup rather than a member on :meth:`admit`'s result, and the
        cost is bounded by ``gateway_max_sessions``: only the two stream shapes
        ADR-0175 §1 defines ever ask, because only they outlive the request that
        established them. Every ordinary request pays nothing.

        **It admits nothing.** The verdict is :meth:`admit`'s alone, and this
        neither refreshes the idle clock nor consults either bound — ADR-0175 §7:
        "``gateway_session_idle_timeout`` is refreshed by a request the gateway
        admits and by nothing else".

        Args:
            header_half: The value the front end sent as a header.

        Returns:
            The handle, or ``None`` where no live session verifies it.
        """
        found = self._find(header_half)
        return None if found is None else found[0]

    def clear(self) -> None:
        """End every session and cancel every timer (ADR-0168 §4).

        "Every session ends when the gateway process ends." This is what the
        gateway calls on the way down, so that a process shutting down leaves no
        timer armed and no verifier behind — and each handle is announced as it
        goes, so a stream the session held ends with it (ADR-0175 §7).
        """
        held = tuple(self._sessions)
        for session in self._sessions.values():
            if session.timer is not None:
                session.timer.cancel()
        self._sessions.clear()
        for key in held:
            self._announce(key)

    def _announce(self, key: SessionHandle) -> None:
        """Tell an observer one session has ended (ADR-0175 §7)."""
        if self._on_ended is not None:
            self._on_ended(key)

    def _find(self, header_half: str) -> tuple[SessionHandle, _Session] | None:
        """The live session whose header verifier matches, with its key."""
        for key, session in self._sessions.items():
            if self._matches(session, header_half):
                return key, session
        return None

    @staticmethod
    def _matches(session: _Session, header_half: str) -> bool:
        """Whether ``header_half`` verifies against ``session``, in constant time."""
        return hmac.compare_digest(verifier(header_half), session.header_verifier)

    def _rearm(self, key: SessionHandle, session: _Session) -> None:
        """Schedule this session's death at the earlier of its two bounds.

        A session "ends at the earlier of its absolute lifetime and its idle
        timeout" (ADR-0168 §4), so the timer is set to whichever comes first and
        reset whenever the idle clock moves. The delay is never negative: a
        session already past its bound is ended on the next tick rather than
        scheduled into the past.

        Args:
            key: The table key.
            session: The session to arm.
        """
        if session.timer is not None:
            session.timer.cancel()
        ends_at = min(session.expires_at, _saturating(session.last_used_at, self._idle_timeout))
        delay = max((ends_at - self._now()).total_seconds(), 0.0)
        session.timer = self._defer(delay, partial(self._end, key))

    def _expired(self, session: _Session) -> bool:
        """Whether either of ADR-0168 §4's two bounds has been reached.

        Read with ``>=`` so that the answer agrees with the timer, which is armed
        for exactly that instant: a session the timer would have ended is one this
        refuses to admit, whether or not the callback has run yet.
        """
        moment = self._now()
        return moment >= session.expires_at or moment >= _saturating(
            session.last_used_at, self._idle_timeout
        )

    def _end(self, key: SessionHandle) -> None:
        """Destroy one session, whichever of its two bounds arrived first.

        The observer is told **after** the session is gone, so a callback that
        looks the handle up finds nothing rather than a session in the act of
        ending — and only where there was one to end, so a timer that fires twice
        announces once.
        """
        session = self._sessions.pop(key, None)
        if session is None:
            return
        if session.timer is not None:
            session.timer.cancel()
        self._announce(key)


@dataclass(frozen=True)
class BootstrapCandidate:
    """A value the gateway has generated and not yet disclosed (ADR-0182 §1, §2).

    "An undisclosed **candidate** is not a value (§3), it admits nothing, and no
    exchange accepts one before the disclosure that promotes it." It exists as its
    own type because §1 fixes the order — mint, disclose, and only on a
    **successful** disclosure promote — so there is an interval in which the
    gateway holds a candidate beside a still-outstanding value, and giving the two
    different types is what stops that interval being two values standing.

    Attributes:
        value: The bytes to disclose, held in the clear because disclosing them is
            the only thing this object is for. It is dropped at the promotion,
            after which the mint retains a verifier alone.
    """

    value: str


class BootstrapMint:
    """The one bootstrap value that admits, and the four ways it ceases (ADR-0182 §2).

    "At most **one** unexchanged bootstrap value **admits** at a time", and it
    ceases "on the first of four events, and there is no fifth: its exchange
    (ADR-0168 §5's single use), ``gateway_bootstrap_ttl``'s expiry (§3), its
    replacement by a fresh mint, and the end of the gateway process (ADR-0168 §4)".
    Each of the four is one method here — :meth:`spend`, the timer :meth:`promote`
    arms, :meth:`promote` itself, and :meth:`clear` — and nothing else in this class
    clears the outstanding value, which is what makes "no fifth" a property of the
    code rather than a claim about it.

    **The clock is the deferral seam and nothing else, which is how §3's monotonic
    requirement is met.** §3 requires the bound "measured on a **monotonic**
    elapsed-time source — one the system clock being moved in either direction does
    not affect — and a value that has ceased… destroyed continuously, through the
    deferral seam ADR-0168 §4's own continuous destruction already uses". So this
    class reads no clock at all: the value's whole life is one scheduled callback,
    and the production seam schedules it on ``loop.call_later``, whose delays run on
    the event loop's monotonic time. There is deliberately no ``now`` beside it —
    a second source is what lets the two disagree, which is the divergence #1439
    records of :class:`SessionTable` and which §3 says in terms this figure does not
    inherit.
    """

    def __init__(
        self,
        *,
        ttl: timedelta,
        defer: Defer,
        mint_value: Callable[[], str] = mint_value,
    ) -> None:
        """Build a mint holding no candidate and no outstanding value.

        Args:
            ttl: ``gateway_bootstrap_ttl`` — how long a disclosed value admits,
                from the disclosure that promoted it (ADR-0182 §3).
            defer: How the value's death is scheduled. The same seam a session's is
                scheduled on, and here it is the *only* time source.
            mint_value: The entropy source, injected for the reason
                :class:`SessionTable`'s is. The default is the operating system's.
        """
        self._ttl = ttl
        self._defer = defer
        self._mint_value = mint_value
        self._candidate: BootstrapCandidate | None = None
        self._outstanding: bytes | None = None
        self._timer: Cancellable | None = None

    def mint(self) -> BootstrapCandidate:
        """Generate a candidate, which admits nothing until it is disclosed.

        "Nothing about a previously outstanding value changes before that point"
        (ADR-0182 §1), so this touches neither the outstanding value nor its clock.

        Returns:
            The candidate to disclose, and then to :meth:`promote` or
            :meth:`discard`.
        """
        self._candidate = BootstrapCandidate(value=self._mint_value())
        return self._candidate

    def promote(self, candidate: BootstrapCandidate) -> None:
        """The disclosure succeeded: this value admits, and the previous one ceases.

        Two of ADR-0182's clauses meet here and neither survives being separated.
        §2's third cessation event — "its replacement by a fresh mint" — is the
        previous value ending at this instant and not at the mint that preceded it.
        And §3's clock "runs from the **successful disclosure** that promotes a
        candidate… and from no other", because "the write is the act that can
        block, so a gateway whose standard output is back-pressured could generate a
        candidate, block for longer than the whole bound, and then promote a value
        already past its clock".

        Args:
            candidate: The candidate the caller has just disclosed.
        """
        self._candidate = None
        self._cease()
        self._outstanding = verifier(candidate.value)
        self._timer = self._defer(self._ttl.total_seconds(), self._expire)

    def discard(self, candidate: BootstrapCandidate) -> None:
        """The disclosure failed: destroy the candidate and touch nothing else.

        "A value the gateway cannot disclose is **not minted**: the gateway destroys
        the candidate, reports the failure, leaves any previously outstanding value
        exactly as it was — still outstanding, still on its own clock" (ADR-0182 §1).
        The outstanding value and its timer are therefore not named below.

        Args:
            candidate: The candidate that was not disclosed. A candidate that is no
                longer the held one has already been dropped, and dropping the held
                one in its place would destroy a value this call is not about.
        """
        if self._candidate is candidate:
            self._candidate = None

    def spend(self, presented: str) -> bool:
        """The exchange — ADR-0182 §2's first cessation event, and ADR-0168 §5's.

        **A match consumes the value here rather than at the session it produces**,
        which is ADR-0182 §4: an exchange refused at ``gateway_max_sessions`` has
        "the value the exchange carried… consumed exactly as a spent value is, so a
        refused exchange is not a value the caller may present again". A failure to
        match consumes nothing, because there was nothing this caller held to
        consume.

        Args:
            presented: The value the exchange carried.

        Returns:
            Whether an outstanding value verified it. What the caller then does
            with the session does not reach the value again.
        """
        held = self._outstanding
        if held is None or not hmac.compare_digest(verifier(presented), held):
            return False
        self._cease()
        return True

    def clear(self) -> None:
        """ADR-0182 §2's fourth cessation event: the gateway process is ending.

        ADR-0168 §4's "every session ends when the gateway process ends" applied to
        the value beside them, so a process on the way down leaves no timer armed
        and no verifier behind — and no candidate either, which is the one piece of
        state here that never became a value.
        """
        self._candidate = None
        self._cease()

    def _expire(self) -> None:
        """ADR-0182 §2's second cessation event: ``gateway_bootstrap_ttl`` elapsed.

        Reached only from the timer :meth:`promote` armed, which is what makes the
        destruction continuous — "rather than at a checkpoint or on the next
        exchange that happens to arrive" (§2).
        """
        self._outstanding = None
        self._timer = None

    def _cease(self) -> None:
        """Destroy the outstanding value and disarm the clock that would have."""
        self._outstanding = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
