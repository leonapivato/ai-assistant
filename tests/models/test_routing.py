"""Tests for the routing/fallback wrapper.

Everything here is offline and synchronous in effect: routes are backed by fakes
that either answer or raise a chosen ``ModelError``, so each test states exactly
one routing rule.
"""

from __future__ import annotations

import contextlib
import traceback
from typing import TYPE_CHECKING, Any, cast

import pytest
import structlog
from model_provider_contract import ModelProviderContract
from structlog.testing import capture_logs

from ai_assistant.core import errors
from ai_assistant.core.errors import (
    ConfigurationError,
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelUnavailableError,
)
from ai_assistant.core.types import Message, Role
from ai_assistant.models import RetryingProvider, Route, RoutingProvider
from ai_assistant.models.retry import RetryPolicy
from ai_assistant.models.routing import _classify
from ai_assistant.testing import FakeModelProvider

if TYPE_CHECKING:
    from collections.abc import Iterator, MutableMapping, Sequence

    from ai_assistant.core.protocols import ModelProvider

PROMPT = [Message(role=Role.USER, content="hi")]


async def _no_sleep(_delay: float) -> None:
    """Stand in for backoff, so composition tests never wait in real time."""


class AlwaysFailsProvider:
    """A ``ModelProvider`` that raises a fixed failure and counts its calls.

    Local rather than :class:`FakeModelProvider`: routing is driven by the
    *class* of the failure, and the canonical fake flattens every reply failure
    into a bare ``ModelError``, which is exactly the classification under test.
    """

    def __init__(self, error: ModelError) -> None:
        self._error = error
        self.calls = 0
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        self.models.append(model)
        raise self._error


class RecordingProvider:
    """A ``ModelProvider`` that always succeeds and records what it was asked."""

    def __init__(self, content: str = "ok") -> None:
        self._content = content
        self.calls = 0
        self.models: list[str | None] = []

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        self.models.append(model)
        return Message(role=Role.ASSISTANT, content=self._content)


class TestRoutingProviderContract(ModelProviderContract):
    """Runs RoutingProvider through the shared ModelProvider conformance suite.

    A router is substitutable for a single provider, so it owes the contract in
    its own right. Backed by the canonical fake, so the suite exercises the
    ordinary first-route-succeeds path.
    """

    @pytest.fixture
    def provider(self) -> ModelProvider:
        return RoutingProvider([Route(FakeModelProvider())])


def test_an_empty_route_list_is_rejected() -> None:
    # Failing at construction, not on the first call, keeps the error next to
    # the wiring mistake that caused it.
    with pytest.raises(ConfigurationError, match="at least one route"):
        RoutingProvider([])


async def test_the_first_route_wins_when_it_succeeds() -> None:
    primary, secondary = RecordingProvider("primary"), RecordingProvider("secondary")

    reply = await RoutingProvider([Route(primary), Route(secondary)]).complete(PROMPT)

    assert reply.content == "primary"
    # The fallback must not be warmed, called speculatively, or paid for.
    assert secondary.calls == 0


async def test_a_routable_failure_falls_through_to_the_next_route() -> None:
    down = AlwaysFailsProvider(ModelUnavailableError("503"))
    backup = RecordingProvider("backup")

    reply = await RoutingProvider([Route(down), Route(backup)]).complete(PROMPT)

    assert reply.content == "backup"
    assert down.calls == 1
    assert backup.calls == 1


async def test_a_non_routable_failure_stops_routing_immediately() -> None:
    refused = AlwaysFailsProvider(ModelContentFilterError("refused"))
    backup = RecordingProvider()

    with pytest.raises(ModelContentFilterError):
        await RoutingProvider([Route(refused), Route(backup)]).complete(PROMPT)

    # Shopping a refused prompt around until a provider accepts is not
    # resilience, and would widen who sees a prompt already flagged sensitive.
    assert backup.calls == 0


async def test_an_auth_failure_routes_even_though_it_is_not_retryable() -> None:
    # The case that motivates a second flag: retrying the same expired key is
    # pointless, but another provider authenticates with a different credential.
    expired = AlwaysFailsProvider(ModelAuthError("401"))
    backup = RecordingProvider("backup")

    assert ModelAuthError.retryable is False

    reply = await RoutingProvider([Route(expired), Route(backup)]).complete(PROMPT)

    assert reply.content == "backup"


async def test_routes_are_tried_in_order() -> None:
    first = AlwaysFailsProvider(ModelUnavailableError("first down"))
    second = AlwaysFailsProvider(ModelUnavailableError("second down"))
    third = RecordingProvider("third")

    await RoutingProvider([Route(first), Route(second), Route(third)]).complete(PROMPT)

    assert (first.calls, second.calls, third.calls) == (1, 1, 1)


async def test_exhausting_every_route_reports_all_of_them() -> None:
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(AlwaysFailsProvider(ModelRateLimitError("429"))),
    ]

    with capture_logs() as logs, pytest.raises(ModelError):
        await RoutingProvider(routes).complete(PROMPT)

    # Naming each candidate beats re-reading the wiring, but it is logged rather
    # than attached to the exception, which the router does not own.
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["routes"] == 2
    assert event["failures"] == [
        {"route": "route[1]", "error": "ModelUnavailableError"},
        {"route": "route[2]", "error": "ModelRateLimitError"},
    ]


async def test_a_survived_failure_is_still_logged() -> None:
    # A failure a later route papers over is invisible otherwise: the call
    # succeeds, so nothing surfaces, and a silently degrading primary is exactly
    # what an operator needs to see *before* the fallback also fails.
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(RecordingProvider("backup")),
    ]

    with capture_logs() as logs:
        reply = await RoutingProvider(routes).complete(PROMPT)

    assert reply.content == "backup"
    [event] = [e for e in logs if e["event"] == "route failed; trying the next one"]
    assert event["route"] == "route[1]"
    assert event["error"] == "ModelUnavailableError"


async def test_a_survived_failure_does_not_log_the_message_either() -> None:
    sensitive = "PATIENT SSN 123-45-6789"
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError(sensitive))),
        Route(RecordingProvider("backup")),
    ]

    with capture_logs() as logs:
        await RoutingProvider(routes).complete(PROMPT)

    # The same Tier 2 constraint applies on the path that succeeds.
    assert sensitive not in repr(logs)


async def test_exception_messages_never_reach_the_log() -> None:
    # ADR-0004 §5: logs are Tier 2 and must never carry Tier 0/1 data. Provider
    # errors routinely quote the offending request, so str(exc) is vendor- and
    # attacker-controlled text that can carry the prompt. Only the failure's
    # class is logged — fail-closed by construction rather than by redaction,
    # which matters because no redaction processor is configured yet.
    sensitive = "PATIENT SSN 123-45-6789"
    routes = [Route(AlwaysFailsProvider(ModelUnavailableError(sensitive)))]

    with capture_logs() as logs, pytest.raises(ModelUnavailableError):
        await RoutingProvider(routes).complete(PROMPT)

    assert sensitive not in repr(logs)
    # ...while the caller still gets the full message on the exception.
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "route[1]", "error": "ModelUnavailableError"}]


async def test_exhaustion_reraises_the_last_failure_untouched() -> None:
    last = ModelRateLimitError("429")
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(AlwaysFailsProvider(last)),
    ]

    with pytest.raises(ModelRateLimitError) as caught:
        await RoutingProvider(routes).complete(PROMPT)

    # Classification must survive routing: a caller that backs off on a rate
    # limit still sees one, rather than a flattened generic failure. The very
    # object comes back, with its own message and nothing bolted on.
    #
    # Note this does not claim the traceback is untouched — propagating through
    # the router appends frames to it, as it would through any intermediate
    # call. What is guaranteed is the identity, type, message and __cause__.
    assert caught.value is last
    assert str(caught.value) == "429"
    assert getattr(caught.value, "__notes__", []) == []


async def test_exhaustion_survives_a_subclass_with_a_richer_constructor() -> None:
    # Regression (adversarial review): rebuilding the failure as
    # `type(last)(msg)` assumed every ModelError takes one message argument.
    # A route may be any ModelProvider, so a subclass carrying extra state used
    # to raise TypeError here — which `except ModelError` does not even catch,
    # destroying the provider's real failure.
    class ProviderQuotaError(ModelError):
        """A routable failure that carries more than a message."""

        routable = True

        def __init__(self, limit: int, message: str) -> None:
            super().__init__(message)
            self.limit = limit

    routes = [
        Route(AlwaysFailsProvider(ProviderQuotaError(100, "quota exhausted"))),
        Route(AlwaysFailsProvider(ProviderQuotaError(50, "quota exhausted"))),
    ]

    with pytest.raises(ProviderQuotaError) as caught:
        await RoutingProvider(routes).complete(PROMPT)

    assert caught.value.limit == 50


async def test_reusing_one_exception_object_does_not_accumulate_state() -> None:
    # Regression (adversarial review): the first fix attached a PEP 678 note to
    # the caught exception. A provider that raises a cached instance — which
    # AlwaysFailsProvider does — then grew a note per call, and concurrent
    # routers sharing that object would leak each other's route labels into it.
    shared = ModelUnavailableError("503")
    router = RoutingProvider([Route(AlwaysFailsProvider(shared))])

    for _ in range(3):
        with pytest.raises(ModelUnavailableError) as caught:
            await router.complete(PROMPT)
        assert caught.value is shared

    # The router owns no state on someone else's exception, so repetition is
    # idempotent no matter how many times it is re-raised.
    assert getattr(shared, "__notes__", []) == []
    assert str(shared) == "503"

    # Its traceback *does* grow across calls, but that is Python's behaviour for
    # re-raising one cached exception instance — a plain function re-raising it
    # accumulates frames identically — not something the router adds or can
    # prevent. Caching an exception instance is the anti-pattern; this asserts
    # the router does not make it materially worse.
    baseline = ModelUnavailableError("503")

    def reraise_baseline() -> None:
        try:
            raise baseline
        except ModelUnavailableError:
            raise

    for _ in range(3):
        with pytest.raises(ModelUnavailableError):
            reraise_baseline()

    assert len(traceback.extract_tb(shared.__traceback__)) <= 2 * len(
        traceback.extract_tb(baseline.__traceback__)
    )


async def test_a_route_model_override_is_passed_to_its_provider() -> None:
    # One provider can appear as several routes — a cheap model first, a
    # stronger one behind it — which is what the per-route override is for.
    shared = RecordingProvider()
    routes = [Route(shared, model="anthropic:claude-haiku-4-5"), Route(shared)]

    await RoutingProvider(routes).complete(PROMPT)

    assert shared.models == ["anthropic:claude-haiku-4-5"]


async def test_a_caller_supplied_override_disables_routing() -> None:
    primary = RecordingProvider("primary")
    backup = RecordingProvider("backup")

    reply = await RoutingProvider([Route(primary), Route(backup)]).complete(
        PROMPT, model="anthropic:claude-opus-4-8"
    )

    assert reply.content == "primary"
    assert primary.models == ["anthropic:claude-opus-4-8"]
    assert backup.calls == 0


async def test_a_caller_supplied_override_does_not_fall_back() -> None:
    down = AlwaysFailsProvider(ModelUnavailableError("503"))
    backup = RecordingProvider()

    # The caller named a model. Answering from a different one would be a worse
    # surprise than the failure, so the failure propagates.
    with pytest.raises(ModelUnavailableError):
        await RoutingProvider([Route(down), Route(backup)]).complete(PROMPT, model="prov:model")

    assert backup.calls == 0


async def test_a_single_route_degenerates_to_pass_through() -> None:
    only = RecordingProvider("only")

    assert (await RoutingProvider([Route(only)]).complete(PROMPT)).content == "only"


async def test_routes_are_not_mutated_by_a_later_caller() -> None:
    routes = [Route(RecordingProvider("primary"))]
    provider = RoutingProvider(routes)

    routes.append(Route(AlwaysFailsProvider(ModelUnavailableError("boom"))))

    # The router snapshots its routes, so mutating the caller's list after
    # construction cannot silently re-wire it.
    assert (await provider.complete(PROMPT)).content == "primary"


class FlakyProvider:
    """Fails with a routable+retryable error N times, then succeeds."""

    def __init__(self, failures: int, content: str) -> None:
        self._remaining = failures
        self._content = content
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        model: str | None = None,
    ) -> Message:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise ModelUnavailableError("503")
        return Message(role=Role.ASSISTANT, content=self._content)


async def test_retrying_inside_routing_exhausts_a_provider_before_falling_back() -> None:
    # The composition ADR-0011 promised and ADR-0013 recommends. Cheap retries
    # against the primary come first; only a provider that stays down costs a
    # re-send elsewhere.
    primary = FlakyProvider(failures=99, content="primary")
    backup = RecordingProvider("backup")
    policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0.001, backoff_max_seconds=0.001)

    router = RoutingProvider(
        [
            Route(RetryingProvider(primary, policy=policy, sleep=_no_sleep)),
            Route(backup),
        ]
    )

    reply = await router.complete(PROMPT)

    assert reply.content == "backup"
    # Three attempts against the primary, then one fallback — not one attempt
    # each, and not three fallbacks.
    assert primary.calls == 3
    assert backup.calls == 1


async def test_a_route_that_recovers_within_its_retries_never_falls_back() -> None:
    primary = FlakyProvider(failures=1, content="primary")
    backup = RecordingProvider("backup")
    policy = RetryPolicy(max_attempts=3, backoff_base_seconds=0.001, backoff_max_seconds=0.001)

    router = RoutingProvider(
        [
            Route(RetryingProvider(primary, policy=policy, sleep=_no_sleep)),
            Route(backup),
        ]
    )

    assert (await router.complete(PROMPT)).content == "primary"
    assert primary.calls == 2
    assert backup.calls == 0


def _exploding_processor(
    _logger: Any, _name: str, _event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """A structlog processor that fails, standing in for a broken sink."""
    msg = "sink is down"
    raise RuntimeError(msg)


async def test_a_broken_logger_does_not_abort_the_fallback() -> None:
    # Regression (CI adversarial review): the diagnostic warning was emitted
    # inline, so an application-installed processor that raises took the whole
    # router down with it — the backup route was never even tried. Routing
    # exists to survive a failing dependency, and the logger is a dependency.
    backup = RecordingProvider("backup")
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(backup),
    ]

    structlog.configure(processors=[_exploding_processor])
    try:
        reply = await RoutingProvider(routes).complete(PROMPT)
    finally:
        structlog.reset_defaults()

    assert reply.content == "backup"
    assert backup.calls == 1


async def test_a_class_claiming_our_module_is_not_trusted() -> None:
    # Regression (CI adversarial review): membership was decided by comparing
    # `cls.__module__` to this project's errors module — and __module__ is a
    # writable attribute, so a class can simply claim it. Membership is now by
    # object identity against a set frozen at import, which is not forgeable.
    spoofed = type(
        "PATIENT_SSN_123_45_6789",
        (ModelRateLimitError,),
        {"__module__": "ai_assistant.core.errors"},
    )

    routes = [Route(AlwaysFailsProvider(spoofed("failure")))]

    with capture_logs() as logs, pytest.raises(ModelRateLimitError):
        await RoutingProvider(routes).complete(PROMPT)

    assert "PATIENT_SSN" not in repr(logs)
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "route[1]", "error": "ModelRateLimitError"}]


async def test_a_non_routable_failure_is_deliberately_not_logged() -> None:
    # The routable case is logged because a later route may paper over it,
    # leaving a degrading provider invisible behind a successful call. This one
    # is raised to the caller, so it is already visible and logging it would
    # only duplicate. Pinned because the changelog previously overclaimed that
    # *every* candidate failure was logged.
    routes = [
        Route(AlwaysFailsProvider(ModelContentFilterError("refused"))),
        Route(RecordingProvider("backup")),
    ]

    with capture_logs() as logs, pytest.raises(ModelContentFilterError):
        await RoutingProvider(routes).complete(PROMPT)

    assert logs == []


async def test_a_dropping_processor_does_not_abort_the_fallback() -> None:
    # A review argued that `structlog.DropEvent` — which is a BaseException, so
    # `suppress(Exception)` does not catch it — would escape `_warn` and kill
    # the fallback. It does not: structlog raises DropEvent as its own
    # control-flow signal for "drop this event" and handles it internally, so it
    # never reaches the caller's frame.
    #
    # Pinned rather than argued, because it is not obvious from the type
    # hierarchy, and because `core/logging.py`'s redaction processor raises
    # exactly this on its fail-closed path — so the two components do meet.
    def dropping(
        _logger: Any, _name: str, _event: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        raise structlog.DropEvent

    backup = RecordingProvider("backup")
    routes = [Route(AlwaysFailsProvider(ModelUnavailableError("503"))), Route(backup)]

    structlog.configure(processors=[dropping])
    try:
        reply = await RoutingProvider(routes).complete(PROMPT)
    finally:
        structlog.reset_defaults()

    assert reply.content == "backup"
    assert backup.calls == 1


async def test_a_broken_logger_does_not_replace_the_promised_failure() -> None:
    # On exhaustion the aggregate warning ran *before* `raise last`, so a
    # logging error reached the caller instead of the ModelError this class
    # documents — silently converting a handled failure into an unhandled one.
    routes = [
        Route(AlwaysFailsProvider(ModelUnavailableError("503"))),
        Route(AlwaysFailsProvider(ModelRateLimitError("429"))),
    ]

    structlog.configure(processors=[_exploding_processor])
    try:
        with pytest.raises(ModelRateLimitError, match="429"):
            await RoutingProvider(routes).complete(PROMPT)
    finally:
        structlog.reset_defaults()


def test_a_route_is_identified_by_position_only() -> None:
    # Regression (CI adversarial review, twice). The diagnostic identifier was
    # first the model id, then a charset-validated caller label; both leaked,
    # because `patient-SSN-123-45-6789`, `sk-live-abc` and `eu-west-1` are the
    # same shape. Any rule admitting *some* caller text has to say which, and
    # every such rule eventually meets a counterexample. A position carries no
    # data by construction, so the question does not arise.
    provider = RecordingProvider()

    assert Route(provider).describe(1) == "route[1]"
    assert Route(provider, model="anthropic:claude-haiku-4-5").describe(2) == "route[2]"


async def test_an_unlabelled_route_never_logs_its_model_id() -> None:
    # Regression (CI adversarial review). `model` used to be the label fallback,
    # so `model="patient-SSN-123-45-6789"` went straight into a Tier 2 log.
    #
    # Filtering it by charset was tried first and does not work: that string
    # passes exactly the same character check as `eu-west-1`, because they are
    # structurally identical. A charset test cannot tell a model id from a
    # record id, so the diagnostic identifier is a position — which carries no
    # data by construction — unless a caller opts in by setting a label.
    routes = [Route(AlwaysFailsProvider(ModelUnavailableError("503")), model="patient-SSN-123")]

    with capture_logs() as logs, pytest.raises(ModelUnavailableError):
        await RoutingProvider(routes).complete(PROMPT)

    assert "patient-SSN-123" not in repr(logs)
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "route[1]", "error": "ModelUnavailableError"}]


async def test_a_provider_defined_error_class_name_is_not_logged() -> None:
    # Regression (CI adversarial review): `type(exc).__name__` is
    # provider-controlled — a route may be any ModelProvider — and reached the
    # log under an `error` key the redactor treats as innocuous. The MRO is
    # walked for the nearest class we defined, so the emitted string can only
    # ever be one of ours, while a third-party subclass keeps its diagnostic
    # value by reporting its nearest known ancestor.
    leaky = type("PATIENT_SSN_123_45_6789", (ModelRateLimitError,), {})

    routes = [Route(AlwaysFailsProvider(leaky("failure")))]

    with capture_logs() as logs, pytest.raises(ModelRateLimitError):
        await RoutingProvider(routes).complete(PROMPT)

    assert "PATIENT_SSN" not in repr(logs)
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "route[1]", "error": "ModelRateLimitError"}]


@contextlib.contextmanager
def _renamed(cls: type, name: str) -> Iterator[None]:
    """Give ``cls`` a different ``__name__`` for the block, then put it back.

    Not ``monkeypatch.setattr``: a class's ``__name__`` lives on the metaclass,
    not in the class ``__dict__``, so monkeypatch reads it as previously-unset
    and undoes by *deleting* it — which raises ``TypeError`` and leaves the
    rename in place for every later test. An explicit restore is the tool that
    actually works here.
    """
    original = cls.__name__
    cls.__name__ = name
    try:
        yield
    finally:
        cls.__name__ = original


async def test_renaming_a_taxonomy_class_does_not_change_what_is_logged() -> None:
    # Regression (#181): identity membership settles *which* class matches, but
    # the emitted string used to be read live off that class — and `__name__` is
    # writable on our own classes too, so assigning to it put arbitrary text in
    # a Tier 2 log through a class the taxonomy trusts. The names are now
    # snapshotted at import, so a later assignment cannot reach the log.
    routes = [Route(AlwaysFailsProvider(ModelRateLimitError("429")))]

    with (
        _renamed(ModelRateLimitError, "PATIENT_SSN_123_45_6789"),
        capture_logs() as logs,
        pytest.raises(ModelRateLimitError),
    ):
        await RoutingProvider(routes).complete(PROMPT)

    assert "PATIENT_SSN" not in repr(logs)
    [event] = [e for e in logs if e["event"] == "all routes failed"]
    assert event["failures"] == [{"route": "route[1]", "error": "ModelRateLimitError"}]


def test_the_no_match_default_is_snapshotted_too() -> None:
    # The other half of #181: `_classify` ended in `return ModelError.__name__`,
    # the same live read on the path taken when nothing in the MRO is known.
    # Unreachable through `RoutingProvider` — it only ever classifies
    # `ModelError`s, and `ModelError` is itself in the taxonomy — so it is
    # pinned directly, on a failure deliberately outside the hierarchy.
    alien = type("ProviderQuotaError", (Exception,), {})

    with _renamed(ModelError, "PATIENT_SSN_123_45_6789"):
        assert _classify(cast("ModelError", alien("failure"))) == "ModelError"


def test_a_class_added_to_the_error_taxonomy_is_picked_up_without_editing_routing() -> None:
    # The property the `vars(errors)` scan exists for, and which snapshotting
    # the names had to preserve: every ModelError subclass the errors module
    # defines is classifiable, with no list in `routing.py` to keep in step. A
    # hand-written map would let a newly added class fall through to the
    # generic default instead.
    defined = {
        obj
        for obj in vars(errors).values()
        if isinstance(obj, type) and issubclass(obj, ModelError)
    }

    assert defined
    for cls in defined:
        assert _classify(cls("failure")) == cls.__name__


async def test_no_fallback_is_announced_when_there_is_nowhere_to_fall_back_to() -> None:
    # Regression (CI adversarial review): a single failing route logged "trying
    # the next one" and then immediately "all routes failed". That reads as a
    # fallback that was tried and also failed — a different incident from
    # having nowhere left to go.
    routes = [Route(AlwaysFailsProvider(ModelUnavailableError("503")))]

    with capture_logs() as logs, pytest.raises(ModelUnavailableError):
        await RoutingProvider(routes).complete(PROMPT)

    assert [e["event"] for e in logs] == ["all routes failed"]
