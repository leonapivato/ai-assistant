"""The gateway's admission record — what it emits, and what it refuses to (ADR-0168 §6).

**The gateway records its own admission decisions and nothing else, and they are
two**: a session minted, and a request refused on a condition of ADR-0168 §3, §4,
§5, §6 or §7 — a refused mint included. "Nothing is recorded for a request a live
session admits, which is not an admission decision, and nothing for a refusal on
any other ground, §8's size bound included."

**A record carries only Tier 2 facts, enumerated.** ADR-0168 §6 states the
enumeration and forbids everything outside it: no session half, bootstrap value or
verifier; no request body; no path, query string or fragment; no header or cookie;
and nothing the hub or a model returned. That is ADR-0004 §5 applied — "logs are
Tier 2 only" — and §6 records that an earlier draft's *exclusion list* would have
leaked the utterance out of a refused `ask`. This module therefore builds each
record from a fixed set of fields and is handed nothing else to build one from.

**Refusal records are rate-bounded, and the count is why they are emitted at the
end of an interval rather than on arrival.** §6 requires each distinct **pair** of
request class and refusal condition emitted at most once per
`gateway_record_interval`, carrying "the number of times that class and that
condition occurred together in that interval" — a number no record written on the
first occurrence could state. So the interval's counters are held, one integer per
pair, and flushed as the interval closes. That is the whole of what the gateway
retains: "a fixed set of integers, reset each interval", and no history of what it
emitted (ADR-0172 §3 — the replacement reaches the record's *emission* and not its
retention).
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover — imported for typing alone
    from collections.abc import Callable
    from datetime import datetime, timedelta

    from ai_assistant.interfaces.gateway.sessions import Cancellable, Defer

_log = structlog.get_logger(__name__)

#: The event name every admission record carries, so the two decisions are one
#: stream a reader can select on.
_EVENT = "gateway.admission"


class RequestClass(StrEnum):
    """The four kinds of request the gateway can see (ADR-0168 §6).

    An enumeration "fixed in advance" and **total**: §6 records that a three-value
    list left "a refused request that asks the assistant for nothing" with no class
    to be recorded under, and that "the residual fourth class is what makes the
    enumeration total rather than merely long".
    """

    ASSET = "asset"
    """The front end's own static assets (ADR-0168 §10)."""

    BOOTSTRAP = "bootstrap-exchange"
    """The single bootstrap exchange of ADR-0168 §5."""

    ASSISTANT = "assistant-request"
    """A request that asks the assistant for something."""

    OTHER = "other"
    """Every other request — the residual that makes the four total."""


class RefusalCondition(StrEnum):
    """The conditions a recorded refusal is decided on (ADR-0168 §3 to §7).

    Total over the sections §6 names, and a refusal "is decided on exactly one
    condition — the first the gateway evaluates that the request fails". §8's own
    conditions are deliberately absent: a refusal on the size bound, a connection
    ceiling or the hub-connection ceiling closes the connection like any other and
    is **not** recorded.
    """

    HOST_NOT_BOUND = "host-not-bound"
    """§7 — the `Host` is not one of the loopback names the gateway bound."""

    ORIGIN_NOT_OWN = "origin-not-own"
    """§7 — the request carried an `Origin` that is not the gateway's own."""

    NO_LIVE_SESSION = "no-live-session"
    """§3 — the request arrived without a live session."""

    COOKIE_HALF_MISMATCH = "cookie-half-mismatch"
    """§6 — a live session's header half beside a cookie half that is not its
    own, or beside more than one cookie of the gateway's name. Its own condition,
    never flattened into an expiry or an absent session."""

    SESSION_CEILING = "session-ceiling"
    """§4 — a mint refused at ``gateway_max_sessions`` rather than evicting."""

    BOOTSTRAP_EXCHANGE_FAILED = "bootstrap-exchange-failed"
    """§5 — an exchange that did not yield a session. The condition says only
    that it failed, exactly as the response does."""


class AdmissionRecorder:
    """Emits the two admission decisions, and retains only the interval's counters."""

    def __init__(
        self,
        *,
        interval: timedelta,
        now: Callable[[], datetime],
        defer: Defer,
    ) -> None:
        """Build a recorder with no counts and no interval running.

        Args:
            interval: ``gateway_record_interval`` — the window each distinct pair
                of class and condition is emitted at most once within.
            now: The clock, injected. It stamps a mint and bounds a refusal
                interval, and a test drives it rather than waiting a minute.
            defer: How the interval's close is scheduled.
        """
        self._interval = interval
        self._now = now
        self._defer = defer
        self._counts: dict[tuple[RequestClass, RefusalCondition], int] = {}
        self._opened_at: datetime | None = None
        self._timer: Cancellable | None = None

    def session_minted(self) -> None:
        """Record that a session was minted (ADR-0168 §6).

        Not rate-bounded, and §6 says why it needs no bound: "§5 permits one mint
        per process life".
        """
        _log.info(
            _EVENT,
            instant=self._now().isoformat(),
            request_class=RequestClass.BOOTSTRAP.value,
            outcome="session-minted",
        )

    def refused(self, request_class: RequestClass, condition: RefusalCondition) -> None:
        """Count one refusal against the interval it falls in (ADR-0168 §6).

        Nothing is emitted here. The pair's record is written when the interval
        closes, because it carries the number of times that pair occurred and that
        number is not known until then.

        Args:
            request_class: Which of the four kinds the request was.
            condition: The single condition it was refused on.
        """
        if self._opened_at is None:
            self._open()
        pair = (request_class, condition)
        self._counts[pair] = self._counts.get(pair, 0) + 1

    def flush(self) -> None:
        """Close the current interval, emitting one record per pair that occurred.

        Called by the interval's own timer, and on the way down so a gateway that
        stops does not swallow the interval it was in the middle of.
        """
        opened_at = self._opened_at
        counts = self._counts
        self._counts = {}
        self._opened_at = None
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if opened_at is None:
            return
        closed_at = self._now()
        for (request_class, condition), count in counts.items():
            _log.info(
                _EVENT,
                interval_start=opened_at.isoformat(),
                interval_end=closed_at.isoformat(),
                request_class=request_class.value,
                outcome="refused",
                condition=condition.value,
                count=count,
            )

    def _open(self) -> None:
        """Start an interval and arm the timer that closes it."""
        self._opened_at = self._now()
        self._timer = self._defer(self._interval.total_seconds(), self.flush)
