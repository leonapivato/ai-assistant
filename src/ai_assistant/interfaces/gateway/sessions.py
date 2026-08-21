"""The gateway's own admission record for one browser (ADR-0168 §4, §5, §6).

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
from enum import StrEnum
from functools import partial
from typing import TYPE_CHECKING, Final, Protocol

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from datetime import datetime, timedelta

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
        """
        self._max_sessions = max_sessions
        self._ttl = ttl
        self._idle_timeout = idle_timeout
        self._now = now
        self._defer = defer
        self._mint_value = mint_value
        self._sessions: dict[str, _Session] = {}

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
        key = secrets.token_hex(8)
        session = _Session(
            cookie_verifier=verifier(values.cookie_half),
            header_verifier=verifier(values.header_half),
            expires_at=moment + self._ttl,
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

    def clear(self) -> None:
        """End every session and cancel every timer (ADR-0168 §4).

        "Every session ends when the gateway process ends." This is what the
        gateway calls on the way down, so that a process shutting down leaves no
        timer armed and no verifier behind.
        """
        for session in self._sessions.values():
            if session.timer is not None:
                session.timer.cancel()
        self._sessions.clear()

    def _find(self, header_half: str) -> tuple[str, _Session] | None:
        """The live session whose header verifier matches, with its key."""
        for key, session in self._sessions.items():
            if self._matches(session, header_half):
                return key, session
        return None

    @staticmethod
    def _matches(session: _Session, header_half: str) -> bool:
        """Whether ``header_half`` verifies against ``session``, in constant time."""
        return hmac.compare_digest(verifier(header_half), session.header_verifier)

    def _rearm(self, key: str, session: _Session) -> None:
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
        ends_at = min(session.expires_at, session.last_used_at + self._idle_timeout)
        delay = max((ends_at - self._now()).total_seconds(), 0.0)
        session.timer = self._defer(delay, partial(self._end, key))

    def _expired(self, session: _Session) -> bool:
        """Whether either of ADR-0168 §4's two bounds has been reached.

        Read with ``>=`` so that the answer agrees with the timer, which is armed
        for exactly that instant: a session the timer would have ended is one this
        refuses to admit, whether or not the callback has run yet.
        """
        moment = self._now()
        return moment >= session.expires_at or moment >= session.last_used_at + self._idle_timeout

    def _end(self, key: str) -> None:
        """Destroy one session, whichever of its two bounds arrived first."""
        session = self._sessions.pop(key, None)
        if session is not None and session.timer is not None:
            session.timer.cancel()
