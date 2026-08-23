"""The web session and the value that buys one (ADR-0168 §4, §6; ADR-0182 §1, §2, §3)."""

from __future__ import annotations

import base64
import secrets
from datetime import timedelta
from itertools import count

import pytest
from gateway_timing import Clock, Timers

from ai_assistant.interfaces.gateway.sessions import (
    Admission,
    BootstrapMint,
    SessionTable,
    mint_value,
    verifier,
)

_TTL = timedelta(hours=12)


@pytest.fixture
def clock() -> Clock:
    """A wall clock this module's tests move by hand."""
    return Clock()


@pytest.fixture
def timers() -> Timers:
    """Every callback the subject deferred, fired by hand."""
    return Timers()


_IDLE = timedelta(hours=1)


def _table(clock: Clock, timers: Timers, *, max_sessions: int = 8) -> SessionTable:
    """A table on ADR-0168 §8's own figures, with the clock and timer a test drives."""
    values = (f"value-{index}" for index in count())
    return SessionTable(
        max_sessions=max_sessions,
        ttl=_TTL,
        idle_timeout=_IDLE,
        now=clock,
        defer=timers,
        mint_value=lambda: next(values),
    )


def test_a_mint_discloses_two_values_and_they_differ(clock: Clock, timers: Timers) -> None:
    """ "A session is admitted only on **two** values presented together" (ADR-0168 §6)."""
    table = _table(clock, timers)

    values = table.mint()

    assert values is not None
    assert values.cookie_half != values.header_half


def test_neither_half_admits_a_request_alone(clock: Clock, timers: Timers) -> None:
    """ "Neither admits a request alone" — and one without the other is refused as neither is."""
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    assert table.admit(header_half=values.header_half, cookie_halves=()) is not Admission.ADMITTED
    assert table.admit(header_half=None, cookie_halves=(values.cookie_half,)) is (
        Admission.NO_LIVE_SESSION
    )


def test_both_halves_together_admit(clock: Clock, timers: Timers) -> None:
    """The whole point of the pair: presented together, they admit."""
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    outcome = table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))

    assert outcome is Admission.ADMITTED


def test_a_replaced_cookie_is_its_own_condition_and_not_an_absent_session(
    clock: Clock, timers: Timers
) -> None:
    """ADR-0168 §6's distinct fault, and the reason it exists.

    "Another local port cannot only *receive* the cookie half; it can *set* one of
    the same name for the same host" — a denial rather than a disclosure, and the
    owner has to read "something replaced their cookie" rather than "their session
    mysteriously ended". Flattening it into an absent session is precisely what §6
    forbids.
    """
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    outcome = table.admit(header_half=values.header_half, cookie_halves=("someone-elses",))

    assert outcome is Admission.COOKIE_HALF_MISMATCH


def test_more_than_one_cookie_of_the_gateways_name_is_the_same_condition(
    clock: Clock, timers: Timers
) -> None:
    """ "…or more than one cookie of the gateway's own name" — even where one is right.

    A second cookie with a narrower path makes the browser present both, and a
    door that picked the good one would silently prefer whichever the attacker
    arranged to be first.
    """
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    outcome = table.admit(
        header_half=values.header_half, cookie_halves=(values.cookie_half, "the-replacement")
    )

    assert outcome is Admission.COOKIE_HALF_MISMATCH


def test_the_ceiling_refuses_a_mint_rather_than_evicting(clock: Clock, timers: Timers) -> None:
    """ADR-0131 §2's direction, applied at ADR-0168 §4's ceiling.

    Evicting "hands any local caller a silent lever to log the owner out", and the
    eviction is indistinguishable from an ordinary expiry — so the incumbent
    survives and the newcomer is refused.
    """
    table = _table(clock, timers, max_sessions=1)
    first = table.mint()
    assert first is not None

    assert table.mint() is None
    assert (
        table.admit(header_half=first.header_half, cookie_halves=(first.cookie_half,))
        is Admission.ADMITTED
    )


def test_a_session_ends_at_its_idle_bound_when_it_is_the_earlier(
    clock: Clock, timers: Timers
) -> None:
    """ "A session ends at the earlier of its absolute lifetime and its idle timeout"."""
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None
    assert timers.armed[0].delay == pytest.approx(_IDLE.total_seconds())

    timers.fire_all()

    assert len(table) == 0
    assert (
        table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))
        is Admission.NO_LIVE_SESSION
    )


def test_a_session_is_destroyed_by_its_own_timer_and_not_by_the_next_request(
    clock: Clock, timers: Timers
) -> None:
    """ "…destroys expired sessions continuously rather than at a checkpoint or on the
    next request that happens to arrive" (ADR-0168 §4).

    The clock passing the bound is not what removes it — nothing has asked the
    table anything — so the check is that the table is empty with no request made.
    """
    table = _table(clock, timers)
    table.mint()

    clock.advance(_IDLE * 2)
    timers.fire_all()

    assert len(table) == 0


def test_a_session_past_a_bound_is_not_admitted_by_a_late_timer(
    clock: Clock, timers: Timers
) -> None:
    """The bound ends the session, not the promptness of the callback.

    The timer is armed and has not run — a busy loop, a suspended machine, or a
    request landing on the same turn as an overdue callback. ADR-0168 §4 says a
    session "ends at the earlier of its absolute lifetime and its idle timeout",
    and admitting one past that would be worse than late: the re-arm on admission
    would cancel the very callback about to end it, so the session could outlive
    both of its bounds indefinitely.
    """
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    clock.advance(_IDLE)
    outcome = table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))

    assert outcome is Admission.NO_LIVE_SESSION
    assert len(table) == 0
    assert timers.armed == []


def test_a_session_past_its_absolute_lifetime_is_not_admitted_either(
    clock: Clock, timers: Timers
) -> None:
    """The other of the two bounds, kept in use the whole way so the idle one
    never binds — which is what makes the absolute one the subject."""
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None
    for _ in range(23):
        clock.advance(timedelta(minutes=30))
        table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))

    clock.advance(timedelta(minutes=30))
    outcome = table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))

    assert outcome is Admission.NO_LIVE_SESSION


def test_use_restarts_the_idle_clock_but_never_the_absolute_one(
    clock: Clock, timers: Timers
) -> None:
    """The two bounds are kept apart: an idle timeout that measured age would be
    the absolute lifetime under another name.

    Used every half hour, the session never goes idle — so after eleven and a half
    hours it is still live, and what is left is half an hour of *lifetime*. A
    re-arm to a fresh idle hour there would push the death past
    ``gateway_session_ttl``, which is the bound that may not move.
    """
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    for _ in range(23):
        clock.advance(timedelta(minutes=30))
        assert (
            table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))
            is Admission.ADMITTED
        )

    assert timers.armed[-1].delay == pytest.approx(timedelta(minutes=30).total_seconds())


def test_a_lifetime_past_the_end_of_representable_time_still_mints(
    clock: Clock, timers: Timers
) -> None:
    """``gt=timedelta(0)`` admits ``timedelta.max``, and a mint must not fail on it.

    ADR-0168 §8 refuses ``gateway_session_ttl`` "unless it is strictly positive"
    and names no ceiling, so a deployment can set one whose sum with any ordinary
    clock reading is not a representable instant. The bound saturates rather than
    raising — and the idle bound still binds, because a session ends "at the
    earlier" of the two, so a lifetime past the end of time is not a session
    without bounds.
    """
    table = SessionTable(
        max_sessions=1,
        ttl=timedelta.max,
        idle_timeout=_IDLE,
        now=clock,
        defer=timers,
        mint_value=lambda: secrets.token_urlsafe(8),
    )

    values = table.mint()

    assert values is not None
    assert timers.armed[0].delay == pytest.approx(_IDLE.total_seconds())
    clock.advance(_IDLE)
    assert (
        table.admit(header_half=values.header_half, cookie_halves=(values.cookie_half,))
        is Admission.NO_LIVE_SESSION
    )


def test_clearing_the_table_ends_every_session_and_disarms_every_timer(
    clock: Clock, timers: Timers
) -> None:
    """ "Every session ends when the gateway process ends" (ADR-0168 §4)."""
    table = _table(clock, timers, max_sessions=3)
    table.mint()
    table.mint()

    table.clear()

    assert len(table) == 0
    assert timers.armed == []


def test_the_table_retains_verifiers_and_not_the_values(clock: Clock, timers: Timers) -> None:
    """ADR-0124 §6's design applied to a smaller secret (ADR-0168 §4).

    Retaining "only a verifier from which the credential cannot be recovered"
    means the gateway "holds no device's Tier 0 secret at rest". Read from the
    outside: no attribute reachable from the table holds either disclosed value.
    """
    table = _table(clock, timers)
    values = table.mint()
    assert values is not None

    held = repr(vars(table))

    assert values.cookie_half not in held
    assert values.header_half not in held


def test_a_verifier_does_not_yield_the_value_it_verifies() -> None:
    """The verifier is a digest, which is what "cannot be recovered" means here."""
    value = "the-header-half"

    digest = verifier(value)

    assert value.encode() not in digest
    assert digest == verifier(value)
    assert digest != verifier(value + "!")


def test_a_minted_value_carries_at_least_128_bits() -> None:
    """ "At least 128 bits drawn from the operating system's cryptographic random
    source" (ADR-0168 §4, §5).

    Measured on the decoded value rather than on the text, because the text is a
    URL-safe encoding and its length is not the entropy.
    """
    value = mint_value()

    padded = value + "=" * (-len(value) % 4)
    assert len(base64.urlsafe_b64decode(padded)) * 8 >= 128


def test_two_mints_do_not_repeat() -> None:
    """A source that repeated would make every session the same session."""
    assert mint_value() != mint_value()


# --- ADR-0182 §2: one outstanding value, and the four ways it ceases ---


_BOOTSTRAP_TTL = timedelta(minutes=10)


def _mint(timers: Timers) -> BootstrapMint:
    """A bootstrap mint on ADR-0182 §3's own figure, with the timer a test fires."""
    values = (f"bootstrap-{index}" for index in count())
    return BootstrapMint(ttl=_BOOTSTRAP_TTL, defer=timers, mint_value=lambda: next(values))


def _disclosed(mint: BootstrapMint) -> str:
    """Mint a candidate and promote it, as a successful disclosure does."""
    candidate = mint.mint()
    mint.promote(candidate)
    return candidate.value


def test_an_undisclosed_candidate_admits_nothing(timers: Timers) -> None:
    """§2: "An undisclosed **candidate** is not a value (§3), it admits nothing, and
    no exchange accepts one before the disclosure that promotes it".

    This is what makes §2's admission invariant true across the interval §1's order
    creates — the candidate and the still-outstanding value are both in the
    gateway's memory for the width of the write, and only one of them admits.
    """
    mint = _mint(timers)
    standing = _disclosed(mint)
    candidate = mint.mint()

    assert mint.spend(candidate.value) is False
    assert mint.spend(standing) is True


def test_a_value_ceases_on_its_exchange(timers: Timers) -> None:
    """§2's first event, which is ADR-0168 §5's single use."""
    mint = _mint(timers)
    value = _disclosed(mint)

    assert mint.spend(value) is True
    assert mint.spend(value) is False


def test_a_value_ceases_when_its_ttl_elapses_on_the_deferral_seam(timers: Timers) -> None:
    """§2's second event, and §3's monotonic clause pinned the way §10 asks.

    "It is measured on a **monotonic** elapsed-time source — one the system clock
    being moved in either direction does not affect — and a value that has ceased
    is destroyed continuously, through the deferral seam ADR-0168 §4's own
    continuous destruction already uses." So the bound is asserted by *firing* what
    the mint deferred, and no clock is moved: there is no clock here to move.
    """
    mint = _mint(timers)
    value = _disclosed(mint)
    armed = timers.armed[-1]

    assert armed.delay == _BOOTSTRAP_TTL.total_seconds()
    timers.fire_all()

    assert mint.spend(value) is False


def test_a_value_ceases_when_a_fresh_mint_replaces_it(timers: Timers) -> None:
    """§2's third event: "A **disclosed** mint (§1) replaces the outstanding value,
    which ceases to admit anything at that moment".

    The replaced value's timer goes with it, so a gateway does not hold a callback
    against a value nothing can spend.
    """
    mint = _mint(timers)
    first = _disclosed(mint)
    second = _disclosed(mint)

    assert first != second
    assert len(timers.armed) == 1
    assert mint.spend(first) is False
    assert mint.spend(second) is True


def test_a_value_ceases_when_the_gateway_process_ends(timers: Timers) -> None:
    """§2's fourth event: "the end of the gateway process (ADR-0168 §4)"."""
    mint = _mint(timers)
    value = _disclosed(mint)

    mint.clear()

    assert mint.spend(value) is False
    assert timers.armed == []


def test_a_candidate_that_was_not_disclosed_leaves_the_previous_value_alone(
    timers: Timers,
) -> None:
    """§1: such a value "is **not minted**".

    "The gateway destroys the candidate… leaves any previously outstanding value
    exactly as it was — still outstanding, still on its own clock." The clock half
    is what the armed timer below stands for: a replacement would have cancelled it
    and armed another.
    """
    mint = _mint(timers)
    standing = _disclosed(mint)
    armed = timers.armed[-1]
    candidate = mint.mint()

    mint.discard(candidate)

    assert mint.spend(candidate.value) is False
    assert timers.armed == [armed]
    assert mint.spend(standing) is True


def test_the_clock_starts_at_the_promotion_and_not_at_the_mint(timers: Timers) -> None:
    """§3: the clock "runs from the **successful disclosure** that promotes a
    candidate to the outstanding value (§1)… and from no other".

    "The write is the act that can block, so a gateway whose standard output is
    back-pressured could generate a candidate, block for longer than the whole
    bound, and then promote a value already past its clock" — so nothing is
    scheduled until the promotion, which is what the empty list below says.
    """
    mint = _mint(timers)

    candidate = mint.mint()
    assert timers.scheduled == []

    mint.promote(candidate)

    assert [one.delay for one in timers.armed] == [_BOOTSTRAP_TTL.total_seconds()]


def test_a_mint_holding_nothing_spends_nothing(timers: Timers) -> None:
    """Before the first disclosure there is no outstanding value, and a constant-time
    comparison against nothing is a refusal rather than an error."""
    assert _mint(timers).spend("anything") is False
