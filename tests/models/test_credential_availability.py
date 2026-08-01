"""The startup credential check that closes #530.

A sibling of ``test_vendor_availability.py``, and the two are deliberately
separate because they answer adjacent questions with different costs. That one
asks whether the vendor's *package* is importable and is emphatically key-free;
this one asks whether a credential is present, which is the very thing that check
was shaped to avoid demanding.

**What is on test here is a boundary, twice over.** Upward: the probe must reach
far enough to notice a missing key, because a resident hub that starts without one
signals ready, looks healthy to every supervisor, and fails hours later on a
user's first real request (ADR-0083 §3, §5, §6). Downward: it must not reach
*past* that into a live call, because ADR-0083 §3 forbids startup blocking on a
network and ADR-0004's residency posture forbids paying egress on every boot. So
the two most load-bearing tests below are the negative ones — that no socket is
touched, and that a present-but-worthless key is accepted here rather than
adjudicated.
"""

from __future__ import annotations

import pytest
from network_guard import network_denied

from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.models import ensure_credential_available

#: An installed vendor, from the two extras ADR-0061 §1 pulls in.
INSTALLED_SPEC = "anthropic:claude-opus-4-8"

#: Every variable that could satisfy a probe of the specs used here, so a
#: developer's real environment cannot turn a negative test into a silent pass.
_CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "PYDANTIC_AI_GATEWAY_API_KEY",
)


@pytest.fixture
def no_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every credential the specs under test could read."""
    for variable in _CREDENTIAL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set a syntactically plausible but entirely fictional key.

    Fictional on purpose: the check must pass on a key it has no way of
    validating, because validating one is exactly what it declines to do.
    """
    for variable in _CREDENTIAL_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")


@pytest.mark.usefixtures("a_credential")
def test_a_present_credential_is_accepted() -> None:
    ensure_credential_available(INSTALLED_SPEC)


@pytest.mark.usefixtures("no_credentials")
def test_a_missing_credential_is_a_configuration_error() -> None:
    """The gap #530 reported, closed at the layer that can see it.

    The message quotes pydantic-ai's own diagnostic rather than paraphrasing it,
    for the same reason the vendor check does: that diagnostic names the exact
    variable to set, which is the one thing an operator needs and the one thing a
    restatement would eventually get wrong as vendors are added.
    """
    with pytest.raises(ConfigurationError) as caught:
        ensure_credential_available(INSTALLED_SPEC)

    message = str(caught.value)
    assert INSTALLED_SPEC in message
    assert "no credential" in message
    # pydantic-ai's own remedy, carried through verbatim.
    assert "ANTHROPIC_API_KEY" in message


@pytest.mark.usefixtures("no_credentials")
def test_a_missing_credential_is_not_a_model_error() -> None:
    """A startup misconfiguration must not arrive wearing a routing disposition.

    Same reasoning as the vendor check's: ``ModelError`` tells a caller whether
    another attempt (``retryable``) or another route (``routable``) could succeed,
    and an unset variable answers "no" to both until a human acts. Raising
    ``ConfigurationError`` is also what lets the hub map this to a stay-down exit
    with one type check rather than a growing list (ADR-0083 §5).
    """
    with pytest.raises(ConfigurationError) as caught:
        ensure_credential_available(INSTALLED_SPEC)

    assert not isinstance(caught.value, ModelError)


@pytest.mark.usefixtures("no_credentials")
def test_the_original_user_error_is_chained_but_does_not_escape() -> None:
    """pydantic-ai's exception stays reachable and stays behind the boundary."""
    with pytest.raises(ConfigurationError) as caught:
        ensure_credential_available(INSTALLED_SPEC)

    assert caught.value.__cause__ is not None
    assert type(caught.value.__cause__).__name__ == "UserError"


@pytest.mark.usefixtures("a_credential")
def test_the_check_touches_no_socket() -> None:
    """The clause this check could most easily have broken (ADR-0083 §3).

    "Nothing in startup may block indefinitely on a network. Every step is
    local-only by construction today, and keeping it so is what makes a
    supervisor's start timeout meaningful." A probe that validated the key by
    calling the vendor would satisfy #530's headline and break that clause, put
    egress on every boot against ADR-0004's residency posture, and make the hub's
    ability to start depend on a third party being reachable.

    Both branches are exercised inside the guard, because a lazy client that only
    connects on failure would pass a happy-path-only assertion.
    """
    with network_denied():
        ensure_credential_available(INSTALLED_SPEC)


@pytest.mark.usefixtures("no_credentials")
def test_the_failing_check_touches_no_socket() -> None:
    """The other branch of :func:`test_the_check_touches_no_socket`."""
    with network_denied(), pytest.raises(ConfigurationError):
        ensure_credential_available(INSTALLED_SPEC)


@pytest.mark.usefixtures("a_credential")
def test_validity_is_deliberately_not_checked() -> None:
    """Presence, never validity — and the boundary is stated rather than implied.

    ``a_credential`` sets a key that cannot possibly work. The check accepts it,
    and that is the decision: a revoked, wrong or throttled key is knowable only
    from a live call, so it stays a request-time failure classified as the model
    error it is. Asserting the acceptance is what stops a later change from
    quietly widening this into a validity check with egress attached.
    """
    ensure_credential_available(INSTALLED_SPEC)


@pytest.mark.usefixtures("no_credentials")
def test_a_spec_with_no_provider_half_is_refused() -> None:
    """The same malformed-spec guard its sibling carries, for the same reason."""
    with pytest.raises(ConfigurationError, match="names no provider"):
        ensure_credential_available("not-a-spec")
