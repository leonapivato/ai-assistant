"""The load-time vendor check that closes ADR-0062 §2's gap.

A sibling of ``test_provider.py`` rather than part of it, because the subject is
different in kind: everything there is about a *completion*, and this is about
what can be known before one is ever attempted.

What is on test is a promise about *when* a mistake surfaces. Before this, a spec
naming a vendor whose extra was never installed built an engine perfectly happily
and failed on the first user request — as a bare ``ModelError`` that
``RoutingProvider`` treats as non-routable, so the configured fallbacks behind it
were never tried either (ADR-0062 §2). The two tests that matter most here are
therefore the negative ones: that no credential and no socket is needed to find
out, since a check that quietly required either would take every wiring path
offline-hostile and would be the reason ADR-0062 rejected the alternatives.
"""

from __future__ import annotations

import importlib.util

import pytest
from network_guard import network_denied
from pydantic_ai.models import known_model_names, parse_model_id

from ai_assistant.core.errors import ConfigurationError, ModelError
from ai_assistant.models import ensure_vendor_available

#: A vendor pydantic-ai knows and whose optional package this project does not
#: install. ADR-0061 §1 installs exactly two extras — ``anthropic`` and
#: ``openai`` — so any third one stands in for "the operator named a vendor they
#: never installed". Groq is picked rather than detected so the test says plainly
#: what it assumes; :func:`test_the_uninstalled_vendor_is_really_uninstalled`
#: fails loudly and specifically if that assumption ever stops holding.
UNINSTALLED_SPEC = "groq:llama-3.3-70b-versatile"
UNINSTALLED_PACKAGE = "groq"

#: An installed one, from the two extras ADR-0061 §1 does pull in.
INSTALLED_SPEC = "anthropic:claude-opus-4-8"


def test_the_uninstalled_vendor_is_really_uninstalled() -> None:
    """Guard the precondition every negative test below rests on.

    Without this, installing the ``groq`` extra would turn the tests that expect a
    rejection into silent passes of a different assertion — or into confusing
    failures whose cause is the environment rather than the code.
    """
    assert importlib.util.find_spec(UNINSTALLED_PACKAGE) is None, (
        f"{UNINSTALLED_PACKAGE!r} is installed, so it no longer stands in for an "
        f"uninstalled vendor; pick another one pydantic-ai knows"
    )


def test_an_installed_vendor_is_accepted() -> None:
    ensure_vendor_available(INSTALLED_SPEC)


def test_the_check_needs_no_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole reason the check has this shape (ADR-0062 §2).

    ``models.infer_model`` and ``defer_model_check=False`` both *construct* the
    vendor provider, which reads its API key — verified in ADR-0062 §2 as
    ``UserError: Set the ANTHROPIC_API_KEY …``. Either would make ``build_engine``
    demand live credentials of anything that merely wires the system up, and would
    take the whole composition suite offline-hostile. ``infer_provider_class``
    returns the provider *class*, so it imports and stops.
    """
    for variable in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PYDANTIC_AI_GATEWAY_API_KEY"):
        monkeypatch.delenv(variable, raising=False)

    ensure_vendor_available(INSTALLED_SPEC)
    ensure_vendor_available("gateway/anthropic:claude-opus-4-8")


def test_the_check_touches_no_socket() -> None:
    """Offline, as an assertion rather than an assumption.

    The check runs at composition time on every configured spec, so a hidden name
    lookup or connection in it would be paid on every startup — and would fail one
    on a machine without egress, for a question that is answered entirely by an
    import.
    """
    with network_denied():
        ensure_vendor_available(INSTALLED_SPEC)
        with pytest.raises(ConfigurationError):
            ensure_vendor_available(UNINSTALLED_SPEC)


def test_an_uninstalled_vendor_is_a_configuration_error() -> None:
    """The gap ADR-0062 §2 left open, closed.

    The message quotes pydantic-ai's own diagnostic rather than paraphrasing it,
    because that diagnostic names the extra to install — which is the one thing
    the operator needs and the one thing we would get wrong by restating.
    """
    with pytest.raises(ConfigurationError) as caught:
        ensure_vendor_available(UNINSTALLED_SPEC)

    message = str(caught.value)
    assert UNINSTALLED_SPEC in message
    assert "not installed" in message
    # pydantic-ai's own remedy, carried through verbatim.
    assert "pydantic-ai-slim[groq]" in message


def test_an_uninstalled_vendor_is_not_a_model_error() -> None:
    """A wiring failure must not arrive wearing a routing disposition.

    ``ModelError`` exists to tell a caller whether another attempt could succeed
    (``retryable``) and whether another route could (``routable``). A missing
    package answers "no" to both, permanently, so classifying it as one would
    invite a retry budget and a whole fallback order to be burned on a mistake
    that reproduces identically everywhere. It is a ``ConfigurationError``, which
    is what the three sibling spec mistakes already raise (ADR-0062 §§1, 3).
    """
    with pytest.raises(ConfigurationError) as caught:
        ensure_vendor_available(UNINSTALLED_SPEC)

    assert not isinstance(caught.value, ModelError)


def test_the_original_import_error_is_chained_but_does_not_escape() -> None:
    """The raw ``ImportError`` stays reachable, and stays behind the boundary.

    Same discipline as ``permissions/audit.py`` and ``planning/sqlite_store.py``:
    a foreign exception type is converted at the subsystem edge so callers depend
    on our taxonomy, and chained so nothing is lost for debugging.
    """
    with pytest.raises(ConfigurationError) as caught:
        ensure_vendor_available(UNINSTALLED_SPEC)

    assert isinstance(caught.value.__cause__, ImportError)


def test_an_unknown_provider_is_a_configuration_error() -> None:
    """The other half of "unresolvable" (ADR-0062 Context).

    A spec can be perfectly well formed — ``core.config``'s pattern accepts it —
    and still name a vendor pydantic-ai has never heard of. That fails at the
    first completion in exactly the same non-routable way as an uninstalled one,
    so it fails at load in exactly the same way too.
    """
    with pytest.raises(ConfigurationError, match="unknown provider"):
        ensure_vendor_available("nosuchvendor:some-model")


def test_an_unknown_provider_chains_the_value_error() -> None:
    with pytest.raises(ConfigurationError) as caught:
        ensure_vendor_available("nosuchvendor:some-model")

    assert isinstance(caught.value.__cause__, ValueError)


def test_a_spec_with_no_provider_half_is_a_configuration_error() -> None:
    """Including ``test``, pydantic-ai's colon-less in-memory dummy.

    ``core.config``'s pattern already refuses it and ADR-0062 §2 accepted losing
    it — ``PydanticAIProvider`` takes a pydantic-ai ``Model`` *instance* for the
    test path, which is what every test here uses. This keeps the two layers
    agreeing rather than leaving the function to guess at a colon-less string.
    """
    with pytest.raises(ConfigurationError, match="names no provider"):
        ensure_vendor_available("test")


def test_the_model_half_may_contain_colons() -> None:
    """Only the *first* colon separates, as ``parse_model_id`` splits.

    ``bedrock:us.anthropic.claude-3-5-sonnet-20240620-v1:0`` is a real name
    pydantic-ai ships (ADR-0062 §2 lists it), so a check that split on the last
    colon — or on every one — would reject a legitimate spec. Asserted over an
    *installed* vendor so a failure here means the split is wrong, not that
    something is missing.
    """
    ensure_vendor_available("anthropic:claude-3-5-sonnet-20240620-v1:0")


def test_a_gateway_prefixed_provider_is_accepted() -> None:
    """``gateway/anthropic:…`` resolves, and the slash is not mistaken for a split.

    ADR-0062 §1's pattern explicitly admits a slash in the provider half, so a
    check that could not resolve one would refuse a spec configuration accepts.
    pydantic-ai's ``infer_provider_class`` strips the prefix itself, which is
    precisely why this delegates rather than parsing.
    """
    ensure_vendor_available("gateway/anthropic:claude-opus-4-8")


def test_no_name_pydantic_ai_ships_is_reported_as_an_unknown_provider() -> None:
    """Refuse to over-reject, exhaustively — the shape ADR-0062's config test uses.

    The danger in a check like this is a false negative: refusing to start a
    deployment whose spec pydantic-ai would have resolved. Hand-picked examples
    cannot deliver that guarantee across an upgrade, so this is checked over the
    whole vocabulary an operator can legitimately draw from. Every colon-bearing
    name must be *either* accepted *or* rejected for a missing package — never as
    an unknown provider, which is the verdict that would mean this check and
    pydantic-ai's own resolution disagree about what exists.

    "Not installed" is an acceptable verdict for a name in this set precisely
    because it is the truth about this machine: ADR-0061 §1 installs two extras,
    and pydantic-ai ships names for twenty-odd vendors.
    """
    names = tuple(known_model_names())
    # `parse_model_id` returns `None` for a colon-less name (pydantic-ai's `test`
    # dummy); the filter drops those, and the walrus keeps mypy sure of it.
    prefixes = sorted({prefix for name in names if (prefix := parse_model_id(name)[0]) is not None})
    assert prefixes, "no colon-bearing model name was found, so this test proved nothing"

    disowned = []
    for prefix in prefixes:
        try:
            ensure_vendor_available(f"{prefix}:a-model")
        except ConfigurationError as exc:
            if not isinstance(exc.__cause__, ImportError):
                disowned.append(prefix)

    assert not disowned, (
        "these providers are in pydantic-ai's own vocabulary but this check calls "
        f"them unknown, so a legitimate deployment could not start: {disowned}"
    )
