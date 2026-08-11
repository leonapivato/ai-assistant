"""The composition root wires the production subsystems (ADR-0042 §2).

These are real integration tests: they open the actual connection-owning SQLite
stores (in a temp directory) and assemble the real subsystems. They do not call
the model — construction wires the provider but never invokes it — so no network
or API key is needed.
"""

from __future__ import annotations

import ast
import os
import stat
import sys
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import pytest

import ai_assistant
from ai_assistant.app import (
    Composition,
    build_composition,
    build_engine,
    build_measure_reader,
    build_reembedder,
    ensure_model_credentials,
)
from ai_assistant.app import composition as composition_module
from ai_assistant.context import AssemblingContextProvider, CalendarContextSource
from ai_assistant.core.config import EmbedderKind, Settings, load_settings
from ai_assistant.core.errors import (
    AssistantError,
    ConfigurationError,
    DeferralStoreError,
    ModelError,
    ReaderError,
    SourceNotGrantedError,
    TraceStoreError,
)
from ai_assistant.core.types import (
    BeliefBand,
    DataTier,
    GrantScope,
    MemoryKind,
    MemorySearchResult,
    MemorySource,
    MemoryUpdateProposal,
    NotificationCandidate,
    NotificationReach,
    Provenance,
    Reversibility,
    RiskLevel,
    SemanticMemory,
    TraceKind,
)
from ai_assistant.evaluation import SqliteTraceStore
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.memory import (
    DefaultMemoryPolicy,
    DefaultNotificationPolicy,
    MemoryIngestor,
    SqliteDeferralStore,
    SqliteMemoryStore,
)
from ai_assistant.memory import deferral_store as deferral_store_module
from ai_assistant.models import BoundedEmbedder, HashingEmbedder
from ai_assistant.orchestration import Engine
from ai_assistant.orchestration.conversations import BELIEF_KINDS
from ai_assistant.orchestration.retrieval import assemble_by_band
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.readers import CALENDAR_READER_NAME
from ai_assistant.testing import FakeMemoryStore, FakeTraceSink, evaluation_trace
from ai_assistant.tools import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence


class _CloudKind(StrEnum):
    """A stand-in for the cloud ``EmbedderKind`` ADR-0104 §4 rules about in advance.

    None exists yet — that is the point of deciding the rule while the case is
    hypothetical — so the refusal is exercised against a member the allow-list
    cannot contain.
    """

    CLOUD = "somebody-elses-cloud"


async def test_build_engine_returns_a_ready_engine(tmp_path: Path) -> None:
    """The builder assembles a real ``Engine`` and opens its stores."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert isinstance(engine, Engine)
        # The connection-owning stores were opened on disk.
        assert (tmp_path / "memory.db").exists()
        assert (tmp_path / "audit.db").exists()
        # The production plan store is now the durable SqlitePlanStore (#318), so a
        # parked execution survives a restart.
        assert (tmp_path / "plans.db").exists()
    finally:
        await engine.aclose()


async def test_build_engine_wires_the_durable_plan_store_as_one_shared_instance(
    tmp_path: Path,
) -> None:
    """The default is a durable ``SqlitePlanStore``, one instance shared everywhere (#318).

    The single-instance obligation ADR-0042 §2 documents: the *same* plan store
    object is injected into the runner, the executor behind it, and the façade, so
    the façade drives and resumes the execution the runner started. The audit trail
    is likewise the one instance the façade and the runner share (ADR-0052 §1).
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        plans = engine._plans
        assert isinstance(plans, SqlitePlanStore)
        assert engine._runner._plans is plans
        assert engine._runner._executor._plans is plans
        # The façade and the runner read the very same audit trail.
        assert engine._trail is engine._runner._trail
    finally:
        await engine.aclose()


async def test_build_engine_wires_one_memory_store_into_both_the_loop_and_the_writer(
    tmp_path: Path,
) -> None:
    """The store the loop retrieves from is the store the writer persists to (ADR-0028 §4).

    ``MemoryWriter``'s Protocol states this obligation in prose and says outright
    that it is "unenforceable here precisely because no store is on this seam" —
    so the composition root is the only place it can be checked, and identity is
    the only way to check it. Split the two and the learning loop is silently
    open: what the assistant learns is written somewhere nothing ever reads.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)
        writer = engine._loop._writes._writer
        assert isinstance(writer, MemoryIngestor)  # narrows the Protocol-typed seam
        assert writer._store is memory
    finally:
        await engine.aclose()


async def test_build_engine_wires_the_on_device_embedder_by_default(tmp_path: Path) -> None:
    """The default settings wire the vendored on-device embedder (ADR-0006 §2, roadmap leg 2).

    ADR-0006 §2's firm decision is that on-device embedding is the *default* — so an
    unconfigured deployment must get semantic recall, not the non-semantic
    ``HashingEmbedder`` the composition root wired unconditionally before this. The
    store the loop retrieves from must therefore carry a :class:`FastEmbedEmbedder`
    at its 384-dim embedding space (ADR-0024).

    Constructing that embedder is offline and cheap — it resolves its dimensions and
    embedding-space identity from the packaged artifact's metadata and defers loading
    the ONNX model to the first ``embed``, which ``build_engine`` never triggers — so
    this asserts the wired *type* and dimension without ever running the model. The
    vendored artifact is a build input present wherever the gate runs (ADR-0024), the
    same assumption the model-layer embedder tests already make.

    Since ADR-0118 §2 the store receives that embedder **wrapped in a bounded one**,
    so the assertion reaches through the wrapper. Its ``dimensions`` is checked on
    the wrapper rather than on the inner embedder, because delegating that unchanged
    is exactly what §2 requires of it.
    """
    from ai_assistant.models.fastembed_embedder import (  # noqa: PLC0415 — local so only this test imports fastembed
        FastEmbedEmbedder,
    )

    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)  # narrows the Protocol-typed seam
        assert isinstance(memory._embedder, BoundedEmbedder)
        assert isinstance(memory._embedder._inner, FastEmbedEmbedder)
        assert memory._embedder.dimensions == 384  # BAAI/bge-small-en-v1.5, ADR-0024
    finally:
        await engine.aclose()


async def test_build_engine_wires_the_hashing_embedder_when_selected(tmp_path: Path) -> None:
    """The ``hashing`` knob wires the deterministic ``HashingEmbedder`` instead (ADR-0006 §2).

    The escape hatch for tests, offline use, and CI: selecting it avoids the vendored
    model (and its ONNX runtime) entirely, at the cost of non-semantic retrieval. It
    is bounded too (ADR-0118 §2): the deadline is inert over an embedder that reaches
    no await, and wrapping both modes is what keeps the guarantee a property of the
    *seam* rather than of one branch.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)  # narrows the Protocol-typed seam
        assert isinstance(memory._embedder, BoundedEmbedder)
        assert isinstance(memory._embedder._inner, HashingEmbedder)
    finally:
        await engine.aclose()


@pytest.mark.parametrize("kind", list(EmbedderKind))
async def test_no_unbounded_embedder_reaches_the_memory_store(
    kind: EmbedderKind, tmp_path: Path
) -> None:
    """ADR-0118 §2's second clause, over every member rather than the two named above.

    "The composition root wires no unbounded ``Embedder`` into anything the hub can
    reach … ``_build_embedder`` returns the wrapped embedder for **every**
    ``EmbedderKind``." Parametrised over the enum rather than over a list written
    here, so a member added later fails this until it is wrapped too — the same
    fail-closed shape ``_build_embedder``'s own ``assert_never`` has.
    """
    engine = build_engine(Settings(embedder=kind), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)  # narrows the Protocol-typed seam
        assert isinstance(memory._embedder, BoundedEmbedder)
    finally:
        await engine.aclose()


def test_build_engine_reports_a_missing_on_device_artifact_as_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuinely missing vendored model is a ConfigurationError, above disk (#372/#403).

    This is the *real* missing-artifact path, not a stubbed exception:
    ``packaged_artifact_dir`` is redirected to an absent directory, so the presence
    check in ``_build_embedder`` sees the manifest files missing. That check exists
    precisely because ``FastEmbedEmbedder`` construction would **not** notice — it
    reads only offline metadata and defers the artifact to its backend's first
    ``embed`` — so without it a missing model would surface far below disk as a
    ``MemoryStoreError`` after the stores were opened. ``build_engine`` runs the
    check in the same above-disk block as the model seam and the context provider,
    so it must fail as a ``ConfigurationError`` and leave the filesystem untouched:
    no data directory, no SQLite files. Mirrors the no-disk assertions #372/#403
    added for the other two pure-config steps.

    Redirecting to an absent directory means the check short-circuits before
    ``fastembed`` is even imported, so this stays offline and never loads ONNX.
    """
    from ai_assistant.models import embedding_artifact  # noqa: PLC0415

    monkeypatch.setattr(embedding_artifact, "packaged_artifact_dir", lambda: tmp_path / "no-model")

    absent = tmp_path / "state"
    assert not absent.exists()

    # Default settings select the on-device embedder (ADR-0006 §2).
    with pytest.raises(ConfigurationError, match="vendored model artifact is missing"):
        build_engine(Settings(), data_dir=absent)

    # The build failed above disk, before the data directory was ever created.
    assert not absent.exists()


def test_build_engine_reports_a_malformed_on_device_embedder_as_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A present-but-unbuildable model (malformed metadata) is also a ConfigurationError (#372).

    The second on-device failure branch: the artifact is present (the presence check
    passes), but ``FastEmbedEmbedder`` construction raises ``ModelError`` because its
    metadata cannot be resolved. ``_build_embedder`` re-raises that as a
    ``ConfigurationError`` — the same operator-facing install fault — above disk, so
    the filesystem is again left untouched. Forced by stubbing the constructor so the
    test neither depends on corrupting the vendored files nor loads the ONNX model.
    """
    from ai_assistant.models import fastembed_embedder  # noqa: PLC0415

    def _explode(*_args: object, **_kwargs: object) -> object:
        msg = "fastembed reported a non-integer dimension"
        raise ModelError(msg)

    monkeypatch.setattr(fastembed_embedder, "FastEmbedEmbedder", _explode)

    absent = tmp_path / "state"
    assert not absent.exists()

    with pytest.raises(ConfigurationError, match="could not construct the on-device embedder"):
        build_engine(Settings(), data_dir=absent)

    assert not absent.exists()


def test_build_engine_reports_an_unimportable_on_device_runtime_as_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing/unloadable fastembed/ONNX runtime is a ConfigurationError, above disk.

    The third on-device failure branch: the artifact is present, but importing the
    ``fastembed`` runtime fails — a dependency-pruned install (``ImportError``) or an
    unloadable ONNX native library (``OSError``). ``_build_embedder`` wraps that as a
    ``ConfigurationError`` so it does not escape the composition root as a raw import
    error outside the ``AssistantError`` hierarchy, and — being above disk — leaves
    the filesystem untouched.

    Simulated by removing the ``FastEmbedEmbedder`` name from its module so the lazy
    ``from ... import FastEmbedEmbedder`` raises ``ImportError`` (cannot import name),
    which needs neither uninstalling fastembed nor loading ONNX.

    This covers the ``ImportError`` half of the handler only; its ``OSError`` half is
    a separate arm with its own case below, because a handler narrowed to one of them
    still passes the other's test.
    """
    from ai_assistant.models import fastembed_embedder  # noqa: PLC0415

    monkeypatch.delattr(fastembed_embedder, "FastEmbedEmbedder")

    absent = tmp_path / "state"
    assert not absent.exists()

    with pytest.raises(ConfigurationError, match="on-device embedding runtime"):
        build_engine(Settings(), data_dir=absent)

    assert not absent.exists()


def test_build_engine_reports_an_unloadable_on_device_runtime_as_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``OSError`` half of that same handler: a native library that will not load.

    ``_build_embedder`` catches ``(ImportError, OSError)``, and the two are disjoint
    types — ``ImportError`` does not inherit from ``OSError`` — so the sibling case
    above cannot reach this arm. Dropping ``OSError`` from the handler leaves that
    case green while the raw ``OSError`` escapes the composition root, outside the
    ``AssistantError`` hierarchy an adapter's boundary catches. This is the case that
    goes red for it.

    The realistic fault is a present-but-unloadable ONNX shared object: the import
    machinery reaches the module and the *dynamic loader* fails, which surfaces as an
    ``OSError`` rather than an ``ImportError``. Reproduced deterministically by
    standing a stub module in ``sys.modules`` whose attribute access raises
    ``OSError``, so the lazy ``from ... import FastEmbedEmbedder`` raises one — no
    uninstall, no ONNX load, and the real module is left untouched (``monkeypatch``
    restores the entry).

    The dunder guard matters: the import machinery probes ``__spec__``/``__path__``
    on the way through, and those probes must answer normally so the ``OSError``
    arises where a loader failure really would — on the name being imported.
    """

    class _UnloadableRuntime(ModuleType):
        """A module whose one public name cannot be loaded."""

        def __getattr__(self, name: str) -> object:
            if name.startswith("__"):
                raise AttributeError(name)
            msg = "libonnxruntime_providers_shared.so: cannot open shared object file"
            raise OSError(msg)

    module_name = "ai_assistant.models.fastembed_embedder"
    monkeypatch.setitem(sys.modules, module_name, _UnloadableRuntime(module_name))

    absent = tmp_path / "state"
    assert not absent.exists()

    with pytest.raises(ConfigurationError, match="on-device embedding runtime") as raised:
        build_engine(Settings(), data_dir=absent)

    # Pins the arm rather than just the message: an ``ImportError`` cause would mean
    # the sibling case was re-run under a new name. ``ImportError`` is not an
    # ``OSError``, so this one assertion separates them.
    assert isinstance(raised.value.__cause__, OSError)

    # Above disk, like the other two on-device failures (#372/#403).
    assert not absent.exists()


async def test_build_engine_wires_one_registry_object_as_both_registry_and_invoker(
    tmp_path: Path,
) -> None:
    """Selection and execution act on one tool object, everywhere (ADR-0029 §8).

    The second prose-only wiring obligation: ``ToolRegistry`` and ``ToolInvoker``
    are separate seams that "no Protocol can close" onto one instance. If the
    runner selected from one registry while the executor invoked against another,
    a gated step could execute a tool the permission check never saw.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        tools = engine._runner._registry
        assert isinstance(tools, InMemoryToolRegistry)
        assert engine._runner._executor._registry is tools
        assert engine._runner._executor._invoker is tools
    finally:
        await engine.aclose()


async def test_build_engine_passes_the_configured_confirmation_ttl_to_the_runner(
    tmp_path: Path,
) -> None:
    """A configured lifetime reaches the runner that enforces it end to end (#310)."""
    ttl = timedelta(hours=1)
    engine = build_engine(
        Settings(confirmation_ttl=ttl, embedder=EmbedderKind.HASHING), data_dir=tmp_path
    )
    try:
        assert engine._runner._confirmation_ttl == ttl
    finally:
        await engine.aclose()


async def test_build_engine_defaults_the_runner_to_no_confirmation_lifetime(
    tmp_path: Path,
) -> None:
    """With no ``confirmation_ttl`` set, the runner keeps the pre-#243 default of None (#310)."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert engine._runner._confirmation_ttl is None
    finally:
        await engine.aclose()


def _spy_on_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, object]]:
    """Capture the kwargs ``build_engine`` constructs the policy with.

    Returns a list the builder appends one call's kwargs to, so a test asserts on
    exactly what reached ``ThresholdActionPolicy`` — which settings field mapped
    to which constructor parameter — without depending on the policy's private,
    deliberately opaque rule table.
    """
    calls: list[dict[str, object]] = []

    def factory(**kwargs: object) -> ThresholdActionPolicy:
        calls.append(kwargs)
        return ThresholdActionPolicy(**kwargs)  # type: ignore[arg-type]  # forwarded kwargs

    monkeypatch.setattr(composition_module, "ThresholdActionPolicy", factory)
    return calls


async def test_build_engine_passes_the_configured_thresholds_to_the_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each Settings threshold reaches its own policy parameter, unswapped (#239)."""
    calls = _spy_on_policy(monkeypatch)
    settings = Settings(
        confirm_at_risk=RiskLevel.HIGH,
        confirm_at_reversibility=Reversibility.RECOVERABLE,
        deny_at_risk=RiskLevel.CRITICAL,
        deny_at_reversibility=Reversibility.IRREVERSIBLE,
        embedder=EmbedderKind.HASHING,
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert calls == [
            {
                "confirm_at_risk": RiskLevel.HIGH,
                "confirm_at_reversibility": Reversibility.RECOVERABLE,
                "deny_at_risk": RiskLevel.CRITICAL,
                "deny_at_reversibility": Reversibility.IRREVERSIBLE,
            }
        ]
    finally:
        await engine.aclose()


async def test_build_engine_defaults_the_policy_to_todays_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With nothing configured, the policy is built with the pre-#239 defaults (#239)."""
    calls = _spy_on_policy(monkeypatch)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert calls == [
            {
                "confirm_at_risk": RiskLevel.MEDIUM,
                "confirm_at_reversibility": Reversibility.IRREVERSIBLE,
                "deny_at_risk": None,
                "deny_at_reversibility": None,
            }
        ]
    finally:
        await engine.aclose()


async def test_the_engine_closes_its_owned_resources(tmp_path: Path) -> None:
    """``aclose`` releases the connections the builder handed the façade (§2)."""
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    await engine.aclose()
    # Idempotent: a second close does nothing and does not raise.
    await engine.aclose()


async def test_build_engine_creates_a_missing_data_dir(tmp_path: Path) -> None:
    """A data directory that does not exist yet is created (§2 owns its resources)."""
    nested = tmp_path / "state" / "assistant"
    assert not nested.exists()
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=nested)
    try:
        assert nested.is_dir()
    finally:
        await engine.aclose()


# --- `data_dir` as a setting (ADR-0083 §2) -----------------------------


async def test_build_engine_reads_the_data_dir_from_settings(tmp_path: Path) -> None:
    """The field the hub's exclusivity, its lock and its socket are all keyed to.

    Before ADR-0083 §2 the data directory existed only as this function's keyword,
    resolved by a private helper — so nothing but a caller passing a path could
    move it, and a resident process had no configuration surface for the one item
    it needs most.
    """
    configured = tmp_path / "configured"
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING, data_dir=configured))
    try:
        assert (configured / "memory.db").exists()
    finally:
        await engine.aclose()


async def test_the_keyword_overrides_the_setting(tmp_path: Path) -> None:
    """§2 keeps the keyword, and keeps it winning.

    It is the injection seam every existing test uses, and it is how the hub hands
    over the directory it resolved and locked in startup's step 2 rather than
    letting this function resolve the same setting a second time.
    """
    configured = tmp_path / "configured"
    passed = tmp_path / "passed"
    engine = build_engine(
        Settings(embedder=EmbedderKind.HASHING, data_dir=configured), data_dir=passed
    )
    try:
        assert (passed / "memory.db").exists()
        assert not configured.exists()
    finally:
        await engine.aclose()


def test_the_data_dir_default_is_the_directory_this_module_used_to_resolve() -> None:
    """Purely additive: an unconfigured deployment's data does not move.

    The default moved from a private helper here to a field factory in
    ``core.config``, and the *value* has to be identical — a field that resolved
    anywhere else would silently strand every existing installation's memory.
    """
    assert Settings().data_dir == Path.home() / ".ai-assistant"


def test_the_data_dir_binds_to_the_prefixed_variable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``ASSISTANT_DATA_DIR``, and **not** ``AI_ASSISTANT_DATA_DIR`` (#535).

    ADR-0083 §2's prose printed the second name and was wrong when written; its
    own amendment note and ADR-0084 §9 carry the correction. This is pinned rather
    than trusted because the failure the wrong name causes is **silent**:
    ``Settings`` sets ``extra="ignore"``, so an operator who followed that sentence
    gets no error at all and lands on the default directory — while the hub's
    exclusivity, its instance lock and (under ADR-0084) its socket path are all
    keyed to the directory they think they configured.
    """
    monkeypatch.setenv("AI_ASSISTANT_DATA_DIR", str(tmp_path / "wrong"))
    assert Settings().data_dir == Path.home() / ".ai-assistant"

    monkeypatch.setenv("ASSISTANT_DATA_DIR", str(tmp_path / "right"))
    assert Settings().data_dir == tmp_path / "right"


def test_a_relative_data_dir_is_refused_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0084 §1: the value must mean one directory, and a relative one does not.

    "A hub started at boot with a working directory of ``/`` and a setting of
    ``state`` binds ``/state/hub.sock``, while a CLI run from a project directory
    looks for ``<project>/state/hub.sock`` and truthfully reports the hub down.
    Both read the same setting and disagree." Refusing at load is what makes the
    one-setting-locates-both property §9 rests on hold by construction, rather
    than surfacing later as a missing socket that names nothing about its cause.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", "state")

    with pytest.raises(ConfigurationError, match="must be an absolute path"):
        load_settings()


def test_the_data_dir_is_canonicalised_at_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Canonicalised **once**, where both readers pick it up already resolved.

    Two readers that each resolve are two chances to resolve differently, and the
    composition root and the hub are exactly those two readers. Doing it in the
    field is what makes "the same field" mean the same directory (ADR-0084 §1),
    rather than making it a rule each caller has to remember.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("ASSISTANT_DATA_DIR", f"{link}/./nested/..")

    assert Settings().data_dir == real


def test_a_tilde_data_dir_is_expanded_rather_than_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``~/.ai-assistant`` and the default name one directory, so both are accepted.

    ``Path`` performs no expansion, so a bare ``is_absolute()`` test would reject
    the very directory the default factory produces — a distinction with no
    justification an operator could anticipate.
    """
    monkeypatch.setenv("ASSISTANT_DATA_DIR", "~/.ai-assistant")

    assert Settings().data_dir == Path(os.path.realpath(Path.home() / ".ai-assistant"))


# --- the shutdown budget reaches the façade (ADR-0083 §4) --------------


async def test_build_engine_hands_the_facade_the_configured_drain_budget(
    tmp_path: Path,
) -> None:
    """Every production engine gets phase A's bound, hub and CLI alike.

    It is set here rather than as an ``Engine`` default because it is a deployment
    value and this is the layer that reads deployment values — an ``Engine`` a test
    builds directly keeps the unbounded drain it always had.
    """
    settings = Settings(embedder=EmbedderKind.HASHING, shutdown_drain_seconds=timedelta(seconds=7))
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._drain_timeout == timedelta(seconds=7)
    finally:
        await engine.aclose()


# --- the hub's credential preflight (#530) -----------------------------


def test_the_credential_preflight_covers_every_configured_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The router's whole preference order *and* the observer's own route.

    The observer's route never falls back (ADR-0077 §3), so a credential it lacks
    disables observation rather than being covered by a sibling — which is exactly
    the silent, hours-later failure #530 is about, in the one place nothing is
    waiting to notice it.
    """
    asked: list[str] = []
    monkeypatch.setattr(composition_module, "ensure_vendor_available", lambda spec: None)
    monkeypatch.setattr(composition_module, "ensure_credential_available", asked.append)

    ensure_model_credentials(
        Settings(
            default_model="anthropic:one",
            fallback_models=("openai:two",),
            observer_model="anthropic:three",
        )
    )

    assert asked == ["anthropic:one", "openai:two", "anthropic:three"]


def test_the_credential_preflight_asks_once_per_distinct_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The observer's spec defaults to ``default_model``; repeating only repeats the message."""
    asked: list[str] = []
    monkeypatch.setattr(composition_module, "ensure_vendor_available", lambda spec: None)
    monkeypatch.setattr(composition_module, "ensure_credential_available", asked.append)

    ensure_model_credentials(Settings(default_model="anthropic:one"))

    assert asked == ["anthropic:one"]


def test_the_vendor_check_runs_before_the_credential_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordering, because the two failures have very different messages.

    The vendor check names the extra to install; the credential probe presumes the
    vendor resolved and would report an uninstalled package as a bare
    ``ImportError``. Asking in the wrong order would replace a good diagnostic with
    a worse one at the exact moment an operator needs the good one.
    """
    order: list[str] = []
    monkeypatch.setattr(
        composition_module, "ensure_vendor_available", lambda spec: order.append("vendor")
    )
    monkeypatch.setattr(
        composition_module, "ensure_credential_available", lambda spec: order.append("credential")
    )

    ensure_model_credentials(Settings(default_model="anthropic:one"))

    assert order == ["vendor", "credential"]


async def test_build_engine_does_not_check_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The decision at the heart of #530's fix, pinned so it cannot drift.

    #530 records that the shipped CLI's behaviour is correct: the failure lands on
    the command that needed a credential, and ``beliefs``, ``learn``, ``questions``,
    ``answer`` and ``forget`` — none of which touch a model — are not blocked by
    its absence. Folding the check into the composition root would make every one
    of them start failing without a key: a regression introduced by a fix, for a
    defect the CLI does not have. Only the hub asks.
    """
    asked: list[str] = []
    monkeypatch.setattr(composition_module, "ensure_credential_available", asked.append)

    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert asked == []
    finally:
        await engine.aclose()


class _SpyStore:
    """A stand-in for a connection-owning store that records its close call."""

    instances: list[_SpyStore] = []  # noqa: RUF012 — a test-local registry, not a model field

    def __init__(self, **_kwargs: object) -> None:
        self.closed = False
        _SpyStore.instances.append(self)

    def close(self) -> None:
        self.closed = True


async def test_build_engine_closes_opened_stores_when_a_later_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If construction fails after a store is opened, that store is closed (§2).

    The builder must return no half-built façade with an orphaned connection.
    """
    _SpyStore.instances.clear()
    monkeypatch.setattr(composition_module, "SqliteMemoryStore", _SpyStore)
    monkeypatch.setattr(composition_module, "SqliteAuditTrail", _SpyStore)

    def _boom(*_args: object, **_kwargs: object) -> object:
        msg = "planner construction failed"
        raise RuntimeError(msg)

    # ModelBackedPlanner is built *after* both stores are opened.
    monkeypatch.setattr(composition_module, "ModelBackedPlanner", _boom)

    with pytest.raises(RuntimeError, match="planner construction failed"):
        build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)

    assert _SpyStore.instances, "both stores should have been opened before the failure"
    assert all(store.closed for store in _SpyStore.instances)  # every opened store was closed


async def test_build_engine_converts_a_data_dir_failure_to_an_assistant_error(
    tmp_path: Path,
) -> None:
    """A directory that cannot be created is an AssistantError, not a raw OSError."""
    # A file occupies the path where a directory is needed, so mkdir fails.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    with pytest.raises(AssistantError, match="data directory"):
        build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=blocker / "sub")


def test_build_engine_touches_no_disk_when_config_validation_fails(tmp_path: Path) -> None:
    """A pure-config failure leaves the filesystem untouched — no dir, no files (#372).

    The resource-free validation (the model seam's vendor check, ADR-0062 §2) runs
    before ``build_engine`` opens a store, so a bad configuration fails before any
    disk is touched: the data directory is never created and none of the three
    SQLite files (``memory.db``, ``audit.db``, ``plans.db``) is written for a build
    that was never going to return an engine. Before #372 the stores were opened
    first, so this exact failure left the directory and three empty-schema files
    behind.

    The failure is forced through the config path, not by a package being absent:
    ``nosuchvendor`` is a vendor pydantic-ai cannot know however the environment is
    provisioned, so ``ensure_vendor_available`` raises ``ConfigurationError``
    deterministically. The spec is well-formed (``provider:model``), so it reaches
    that check rather than being rejected earlier by ``Settings``.
    """
    absent = tmp_path / "state"
    assert not absent.exists()

    settings = Settings(default_model="nosuchvendor:whatever")
    with pytest.raises(ConfigurationError, match="nosuchvendor"):
        build_engine(settings, data_dir=absent)

    # The build failed before touching disk: no data directory, and therefore none
    # of the connection-owning stores' files.
    assert not absent.exists()


@pytest.mark.parametrize(
    ("bad_settings", "match"),
    [
        pytest.param(
            Settings.model_construct(timezone="Definitely/Not_A_Zone"),
            "unknown timezone",
            id="unknown-timezone",
        ),
        pytest.param(
            Settings.model_construct(working_hours_start=20, working_hours_end=8),
            "invalid working-hours window",
            id="invalid-working-hours",
        ),
    ],
)
def test_a_context_config_failure_touches_no_disk_either(
    tmp_path: Path, bad_settings: Settings, match: str
) -> None:
    """The *other* resource-free step — the context provider — also fails before disk (#403).

    #372 hoisted two pure-config steps above the data directory: the model seam's
    vendor check and the context provider's construction. The sibling test above
    covers the model-seam half; this covers the context half. Building the
    ``AssemblingContextProvider`` constructs a ``ClockContextSource``, which
    validates its locale at construction and raises ``ConfigurationError`` on an
    unknown timezone or an empty working-hours window
    (``ai_assistant.context.sources``). Because that step runs above the
    ``mkdir``/store-opening block, such a failure must leave the filesystem
    untouched — no data directory and none of the three SQLite files.

    ``Settings`` validates both fields at load, so a well-formed instance can never
    carry a bad one into ``build_engine`` — unlike the vendor check, there is no
    natural "load-valid but build-invalid" spec to exploit. ``model_construct``
    (pydantic's validation-bypassing constructor) hands ``build_engine`` the exact
    out-of-contract configuration that only its hoisted context step would catch,
    with every other field left at its default so the model seam ahead of it
    passes and the context step is genuinely the one that fails.
    """
    absent = tmp_path / "state"
    assert not absent.exists()

    with pytest.raises(ConfigurationError, match=match):
        build_engine(bad_settings, data_dir=absent)

    # The build failed at the context step, before touching disk: no data
    # directory, and therefore none of the connection-owning stores' files.
    assert not absent.exists()


async def test_build_engine_wires_the_observation_stage_over_the_one_memory_store(
    tmp_path: Path,
) -> None:
    """The stage selects from, and writes through, the store everything else uses.

    ADR-0028 §4's obligation applied to a second producer (ADR-0077 §8): a stage over
    a second store would select episodes the write path cannot cite, so every
    proposal would be refused for evidence that resolves perfectly well in the store
    the user reads — and the derived band would stay empty while the run reported
    health.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        stage = engine._observation
        assert stage._memory is memory
        assert stage._writes is engine._loop._writes
        # The same conversation index the capture stage appends turns to, or the
        # selection would look for a conversation nothing ever recorded.
        assert stage._conversations is engine._conversations._conversations
    finally:
        await engine.aclose()


async def test_build_engine_gives_the_stage_and_the_producer_one_batch_bound(
    tmp_path: Path,
) -> None:
    """One ``Settings`` value bounds both, which is what keeps them in step.

    ADR-0077 §1 puts the oversized-batch refusal on the producer because the
    Protocol is a cross-subsystem contract; §9.7 correspondingly has the stage select
    **at most** that many. Wired from two values, the producer's ``ValueError`` would
    stop being a guard on a contract and start being a routine failure.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING, observation_batch_size=7, observation_max_proposals=2
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        stage = engine._observation
        observer = stage._observer
        assert isinstance(observer, ModelBackedObserver)
        assert stage._batch_size == 7
        assert observer.max_batch_size == 7
        assert observer.max_proposals == 2
    finally:
        await engine.aclose()


async def test_build_engine_tells_the_stage_the_route_the_observer_reads_through(
    tmp_path: Path,
) -> None:
    """The route the report names is the one the provider was built from (ADR-0013 §6).

    No seam exposes it — an ``Observer`` holds its provider and shows nobody — so the
    label is supplied by the layer that built the provider, and a stage told anything
    else would report a read that did not happen.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-x",
        observer_model="openai:gpt-5",
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._observation._route == "openai:gpt-5"
    finally:
        await engine.aclose()


async def test_build_engine_opens_the_deferral_queue_under_the_data_dir(
    tmp_path: Path,
) -> None:
    """The deferred-question queue is a fourth Tier 1 store, wired here (ADR-0078 §10).

    Opened under the same data directory and with the same owner-only file mode as
    the others, because what it holds is the user's own words waiting on an answer
    (ADR-0004 §4). An unwired store would be dead code and a question would still
    have nowhere to wait — the gap ADR-0078 exists to close.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        path = tmp_path / "deferrals.db"
        assert path.exists()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    finally:
        await engine.aclose()


def _spy_on_deferrals(monkeypatch: pytest.MonkeyPatch) -> list[SqliteDeferralStore]:
    """Record every deferral store the builder constructs, still building real ones.

    A recording subclass rather than a stub, so the engine it is wired into is the
    real one and this assertion is about the *built* store rather than about a
    double standing where it would have been.
    """
    built: list[SqliteDeferralStore] = []

    class _Recorded(SqliteDeferralStore):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]  # the root's own keywords
            built.append(self)

    monkeypatch.setattr(composition_module, "SqliteDeferralStore", _Recorded)
    return built


async def test_build_engine_leaves_the_deferral_stores_token_source_at_its_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The composition-root assertion ADR-0078 §10 item 4 owes.

    "Unpredictable" is a property of the *source*, and injection alone would let this
    layer wire a counter and satisfy every word of "fresh" — while ``interrupted``
    publishes every claimed question's id to any caller, so a guessable token is one
    a reader can spend on someone else's claim. No type expresses that the default
    was kept, so this test does (the shape ADR-0028 §4 established for the same class
    of hazard).
    """
    built = _spy_on_deferrals(monkeypatch)

    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert len(built) == 1
        assert built[0]._new_claim_id is deferral_store_module._secret_claim_id
    finally:
        await engine.aclose()


async def test_build_engine_gives_the_deferral_queue_the_configured_tuning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both tunings are the user's configuration and both reach the constructor (§10).

    Read **once**, there, and stamped onto each question at admission — which is what
    keeps a later change to the setting from reaching back and shortening a question
    already asked (ADR-0078 §2).
    """
    built = _spy_on_deferrals(monkeypatch)
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        deferral_ttl=timedelta(days=3),
        deferral_queue_limit=7,
    )

    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert built[0]._retention == timedelta(days=3)
        assert built[0]._queue_limit == 7
    finally:
        await engine.aclose()


async def test_the_deferral_queue_joins_the_ordered_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store this layer opens is a resource this layer owns (ADR-0042 §2).

    One left out of the façade's shutdown path is a connection leaked on every
    session. Asserted by using the store after ``aclose``: a closed ``sqlite3``
    connection refuses, and this seam reports that as its own error.
    """
    built = _spy_on_deferrals(monkeypatch)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)

    await engine.aclose()

    with pytest.raises(DeferralStoreError):
        await built[0].export()


async def test_build_engine_gives_the_write_stage_and_the_answer_path_one_queue(
    tmp_path: Path,
) -> None:
    """ADR-0078 §3's **first** composition-root obligation, enforced rather than asked.

    "The ``DeferralStore`` the write stage enqueues into is the **same instance** the
    façade enumerates from. A second instance queues questions nobody can answer."
    No type expresses it — a ``DeferralStore`` exposes no identity and the two stages
    are wired independently — so identity here is the only way to check it, exactly as
    ADR-0028 §4's writer/store rule is checked.

    The observation stage is included because it is the *second* producer and reaches
    memory through the same stage: a second write stage over a second queue would park
    an observed question the question surface cannot show, which is the drop ADR-0078
    ends restored by a wiring mistake.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        writes = engine._loop._writes
        assert engine._observation._writes is writes, "one write stage, both producers"
        assert engine._questions._deferrals is writes._deferrals
        assert isinstance(writes._deferrals, SqliteDeferralStore)
    finally:
        await engine.aclose()


async def test_build_engine_gives_the_answer_path_the_writer_and_store_learn_uses(
    tmp_path: Path,
) -> None:
    """ADR-0078 §3's **second** obligation: ADR-0028 §4's rule at a second place.

    "The ``MemoryWriter`` an answer applies through writes to the **same**
    ``MemoryStore`` whose records the question's frozen conflict set names… applying a
    confirmed retirement against a different store would retire nothing while
    reporting success." The answer path also *reads* that store directly, to resolve
    what accepting would retire — so a second store would show the user conflicts the
    apply cannot reach.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert engine._questions._writer is engine._loop._writes._writer
        assert engine._questions._memory is memory
        writer = engine._questions._writer
        assert isinstance(writer, MemoryIngestor)  # narrows the Protocol-typed seam
        assert writer._store is memory
    finally:
        await engine.aclose()


def _one_event_calendar(directory: Path) -> Path:
    """A minimal ``.ics`` with one event an hour from now, and its path.

    Written against the *real* clock, because the composition root deliberately
    leaves the reader's clock at its default: nothing at this layer has a second
    clock to hand it, and inventing one would be the second timezone source
    ADR-0093 §7b refuses for the same reason. An hour ahead sits comfortably inside
    the seven-day default window (§7a), so the case does not depend on the wall
    clock beyond it being a clock.
    """
    begins = datetime.now(UTC) + timedelta(hours=1)
    ends = begins + timedelta(minutes=30)
    stamp = "%Y%m%dT%H%M%SZ"
    path = directory / "calendar.ics"
    path.write_bytes(
        (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant tests//EN\r\n"
            "BEGIN:VEVENT\r\nUID:e1\r\nDTSTAMP:20260101T000000Z\r\n"
            f"DTSTART:{begins.strftime(stamp)}\r\nDTEND:{ends.strftime(stamp)}\r\n"
            "SUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()
    )
    return path


def _calendar_sources(engine: Engine) -> list[CalendarContextSource]:
    """The calendar context sources the built provider actually composes.

    Reached through the loop's provider because that is where the assembled
    ``CurrentContext`` comes from: a source registered anywhere else would not
    contribute to a turn, so asserting on the list this layer built would be
    asserting on the wrong object.
    """
    provider = engine._loop._context
    assert isinstance(provider, AssemblingContextProvider)
    return [source for source in provider._sources if isinstance(source, CalendarContextSource)]


async def _grant_the_calendar(engine: Engine) -> None:
    """Grant the one source this tree has, through the surface a user uses.

    **Through the surface rather than through an injected fake**, which is the
    change ADR-0102 §7 makes possible and is the point of it: ``build_engine`` now
    opens the grant store itself, so a test no longer hands the drivers a
    ``SourceGrants`` nothing in production would have handed them. What is
    exercised below is therefore the path a person actually takes — enumerate,
    grant, then read — and leg 6's exit test becomes reachable by a user rather
    than by a fake (#684).

    ``CALENDAR_READER_NAME`` rather than a literal, because ADR-0097 §1 keys a
    grant to the reader's **declared** identity and a grant naming anything else
    covers nothing.
    """
    await engine.grant(CALENDAR_READER_NAME, scope=[GrantScope.FACET, GrantScope.INGEST])


async def test_build_engine_wires_both_drivers_on_a_configured_path(
    tmp_path: Path,
) -> None:
    """A configured source is now enough to *wire*, and never enough to *read*.

    Until ADR-0102 §7 this needed two conditions: a path, and a ``SourceGrants``
    the composition root was handed — which nothing in production ever handed it,
    so ``build_engine`` wired neither driver and no deployment read a calendar
    (#684). The store is opened here now, so the seam is always present and only
    the *grant* decides whether anything is read.

    Both halves are covered because the property that matters is that neither
    reads the file before the user says so: the stage exists and refuses, and the
    context source is registered and contributes nothing.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._ingestion is not None
        assert len(_calendar_sources(engine)) == 1
        # ADR-0097 §8: an installation that has been reading a source stops
        # reading it until the user grants. Nothing is minted from configuration.
        with pytest.raises(SourceNotGrantedError):
            await engine.ingest()
        assert (await engine._loop._context.assemble()).calendar is None
    finally:
        await engine.aclose()


async def test_build_engine_offers_the_configured_source_with_its_location(
    tmp_path: Path,
) -> None:
    """ADR-0102 §7's identities and locations, read off the readers this layer built.

    The identity comes from the reader object rather than from a setting (§7's
    clause), and the location is the configured path — carried by this response and
    by no durable record anywhere (§6, ADR-0097 §9a). The two ``CalendarReader``
    instances ADR-0096 §5 requires deduplicate to **one** entry, which is the other
    half of §7's rule.
    """
    source = _one_event_calendar(tmp_path)
    settings = Settings(embedder=EmbedderKind.HASHING, calendar_reader_path=source)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        offered = await engine.grantable_sources()

        assert [one.source for one in offered] == [CALENDAR_READER_NAME]
        assert offered[0].location == str(source)
        assert offered[0].live is None
    finally:
        await engine.aclose()


async def test_the_grant_store_is_the_sixth_database_in_the_data_directory(
    tmp_path: Path,
) -> None:
    """ADR-0102 §7 and §12: opened here, under ``Settings.data_dir``, owner-only.

    Asserted as a file on disk rather than through the object graph, because the
    claim ADR-0102 §12's normative clause makes is about the *directory* — the hub
    owns eight databases exclusively (ADR-0083 ruling 4), and the sixth obeys that
    ruling by living inside the directory the instance lock already covers.
    ADR-0130 §9's notification store is the eighth and obeys it for the same
    reason: inside the directory the instance lock already covers, opened by the
    same process, closed in the same ordered shutdown.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        # The directory listing is a synchronous read of a temporary directory this
        # test owns, not an I/O path the event loop can be starved by.
        databases = sorted(path.name for path in tmp_path.glob("*.db"))  # noqa: ASYNC240
        assert databases == [
            "audit.db",
            "conversations.db",
            "deferrals.db",
            "grants.db",
            "memory.db",
            "notifications.db",
            "plans.db",
            "traces.db",
        ]
        assert stat.S_IMODE((tmp_path / "grants.db").stat().st_mode) == 0o600
        # ADR-0004 §4 reaches the eighth exactly as it reaches the sixth: a
        # candidate carries free text a producer wrote to be shown to a person.
        assert stat.S_IMODE((tmp_path / "notifications.db").stat().st_mode) == 0o600
    finally:
        await engine.aclose()


# --- the notification chassis (ADR-0130 §3, §9) ----------------------------


def _a_candidate() -> NotificationCandidate:
    """One candidate, so a case can watch what a composed store stamps on it."""
    return NotificationCandidate(
        candidate_key="k1",
        producer="a-test",
        notification_class="calendar",
        summary="something you did not ask for",
        noticed_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        confidence=0.5,
        sensitivity=DataTier.PERSONAL,
    )


async def test_the_notification_surface_answers_instead_of_refusing(
    tmp_path: Path,
) -> None:
    """ADR-0130 §9's five methods work on a composed hub (#948).

    Until this wiring existed every one of them raised ``ConfigurationError`` in
    ``Engine.ingest``'s shape — and "no store is composed" and "nothing is held"
    are different facts, so answering an empty page would have reported the second
    while the first was true. The read, the preferences and the maintenance drain
    are asserted together because it is exactly the *pairing* the engine refuses
    to be built without: a store with no policy could hold records nothing rules.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert await engine.notifications() == ()
        # §6: an empty store is a working policy, so the tuning surface works on
        # the first day with no history — which the ruling on #879 makes a
        # precondition rather than a nicety.
        preferences = await engine.notification_preferences()
        assert preferences.reach_for("a-class-nobody-has-named") is NotificationReach.HOLD
        assert preferences.interruption_budget == 3
        assert preferences.quiet_windows == ()
        # The maintenance drain runs rather than refusing, and rules nothing:
        # with no producers there is nothing due (ADR-0130 §5).
        assert await engine.reconsider_notifications() == 0
    finally:
        await engine.aclose()


async def test_the_retention_purge_reaches_the_notification_store(
    tmp_path: Path,
) -> None:
    """ADR-0130 §7: "the retention purge job ADR-0083 §7 already runs calls this
    store's purge".

    ``PurgeReport.notifications`` is ``None`` while no store is wired, which is the
    honest report for a stage that did not run — so an integer here is the
    observable that the sweep now reaches the eighth database. No new job and no
    new interval, exactly as ADR-0119 §10 did for the trace store.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        report = await engine.purge_expired()

        assert report.notifications == 0
    finally:
        await engine.aclose()


async def test_the_store_takes_its_cap_and_retention_from_settings(
    tmp_path: Path,
) -> None:
    """ADR-0130 §7: both tunings are read **once**, at construction.

    Asserted through the published cap rather than through a private attribute,
    because §7 publishes it for exactly this reason — "a conformance suite cannot
    test a boundary nobody stated". The retention is asserted where it is
    observable: stamped onto a record at admission, never consulted from the
    setting afterwards.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        notification_queue_limit=7,
        notification_retention=timedelta(days=3),
    )
    composed = build_composition(settings, data_dir=tmp_path)
    try:
        store = composed.engine._notifications
        assert store is not None
        assert store.cap == 7

        ruling = await store.admit(
            _a_candidate(), policy=DefaultNotificationPolicy(timezone=settings.timezone)
        )
        assert ruling.notification_id is not None
        record = await store.get(ruling.notification_id)
        assert record is not None
        assert record.retention == timedelta(days=3)
    finally:
        await composed.engine.aclose()


async def test_the_policy_reads_quiet_windows_in_the_configured_timezone(
    tmp_path: Path,
) -> None:
    """ADR-0130 §6: quiet windows are read in ``Settings.timezone``.

    The same value ADR-0008 §5 gives the temporal context and ADR-0093 §7b binds
    the calendar reader to, with no second timezone source introduced — which is
    why the policy takes it at construction rather than per call: a caller free to
    vary it could move the user's night. A consequence ADR-0130 names is that
    ``Settings.timezone`` becomes load-bearing for a user-visible behaviour, so
    this asserts the wiring rather than trusting the comment.
    """
    settings = Settings(embedder=EmbedderKind.HASHING, timezone="Pacific/Kiritimati")
    composed = build_composition(settings, data_dir=tmp_path)
    try:
        policy = composed.engine._notification_policy
        assert isinstance(policy, DefaultNotificationPolicy)
        assert policy._zone == ZoneInfo("Pacific/Kiritimati")
    finally:
        await composed.engine.aclose()


def _spy_on_traces(monkeypatch: pytest.MonkeyPatch) -> list[SqliteTraceStore]:
    """Record every trace store the builder constructs, still building real ones.

    A recording subclass rather than a stub, for ``_spy_on_deferrals``' reason: the
    engine it is wired into is the real one, so the assertion is about the *built*
    store rather than about a double standing where it would have been.
    """
    built: list[SqliteTraceStore] = []

    class _Recorded(SqliteTraceStore):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)  # type: ignore[arg-type]  # the root's own keywords
            built.append(self)

    monkeypatch.setattr(composition_module, "SqliteTraceStore", _Recorded)
    return built


async def test_the_trace_store_is_the_seventh_database_in_the_data_directory(
    tmp_path: Path,
) -> None:
    """ADR-0119 §6, in the shape ADR-0102 §12's clause took for the sixth.

    Asserted as a file on disk rather than through the object graph, because the
    claim §6 makes is about the *directory*: ADR-0083 ruling 4's exclusivity needs
    nothing new for a seventh store that lives inside the directory the instance
    lock already covers, is opened by the same process, and is reached only
    through the API.

    Owner-only like the other six, and that is defence in depth rather than the
    guarantee it is elsewhere: this is the one **Tier 2** store here, so ADR-0004
    §4's mode is kept because a store that opted out of the family's posture is
    the one #506 would have to bring back in.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        traces = tmp_path / "traces.db"
        assert traces.exists()
        assert stat.S_IMODE(traces.stat().st_mode) == 0o600
    finally:
        await engine.aclose()


async def test_the_trace_store_joins_the_ordered_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A store this layer opens is a resource this layer owns (ADR-0042 §2).

    One left out of the façade's shutdown path is a connection leaked on every
    session — and this is the store most likely to be forgotten, because nothing
    in the pipeline holds it yet (ADR-0119 §13d puts the emitters in a later
    lane), so no consumer's test would notice.

    Asserted through ``walk`` rather than ``emit``: ``emit`` swallows every store
    fault by contract (§5), so a closed connection is invisible there. The read
    seam raises, which is what makes the closure observable at all.
    """
    built = _spy_on_traces(monkeypatch)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)

    await engine.aclose()

    assert len(built) == 1
    with pytest.raises(TraceStoreError):
        await built[0].walk(limit=1)


async def test_only_the_maintenance_operation_is_handed_the_trace_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0119 §7, at the one place a violation would be introduced.

    "No component of the request pipeline holds a seam carrying the walk, and none
    reads a trace back." ``lint-imports`` stops a subsystem *importing* the
    concrete; this stops the composition root *handing* one over — the route the
    contract cannot see, because the store arrives by injection precisely so that
    a subsystem never names it.

    **Four attributes of the engine are the permitted holders, and between them
    they are §7's two narrow seams**: "a ``TraceSink`` to every emitter, a
    ``TraceRetention`` to the ``Engine``'s maintenance operation, and the
    ``TraceStore`` itself to nothing in the pipeline". ``_traces`` is the purge
    (§10); the other three are §8's emitters — the engine boundary, ``memory``'s
    relevance read and ``memory``'s write path — each reaching the object through
    its own ``MemoryTraces``/``OperationTraces`` and each holding it under a
    ``TraceSink`` annotation. The narrowing is that annotation rather than anything
    done here, which is why the object identity is the same and the *reach* is not
    — the same arrangement ``SourceGrants``/``SourceGrantStore`` uses.

    **Neither can walk, which is the property the list is guarding.** §7 cuts the
    seam at the walk rather than at the store — "the pipeline may not read a trace
    back" — so a second holder is admissible exactly when it is a narrowed one, and
    this list grows by a reviewed line when an emitter lands rather than by a
    directory exclusion.

    Asserted by identity over the engine's reachable collaborators rather than by
    naming the ones that exist today, so a stage added later is covered without
    this test being edited. A stage handed the store would show up here as a third
    path even though it is the same object.
    """
    built = _spy_on_traces(monkeypatch)
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        holders = _holders_of(engine, built[0])
        assert sorted(holders) == [
            "engine._loop._memory._traces._sink",
            "engine._loop._writes._writer._traces._sink",
            "engine._operation_traces._sink",
            "engine._traces",
        ], f"the trace store is reachable from {holders}"
    finally:
        await engine.aclose()


async def test_the_engine_sweeps_the_configured_trace_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#852 end to end: a trace past the horizon is gone after the sweep runs.

    The whole of ADR-0119 §10 wired together over the *real* store — the horizon
    from ``Settings``, the instant from the engine's own clock, the deletion from
    the seventh database — because every piece of it was already present and
    nothing joined them: "a horizon an operator can set and nothing applies is
    exactly the shape that reads as working".

    Ages are far from the horizon on both sides, so the assertion is about the
    wiring and not about a boundary a wall clock could cross mid-test. The strict
    bound itself is pinned against the seam in ``tests/orchestration/test_engine.py``
    and by the shared ``TraceRetentionContract``.
    """
    built = _spy_on_traces(monkeypatch)
    settings = Settings(embedder=EmbedderKind.HASHING, trace_retention=timedelta(days=365))
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        store = built[0]
        now = datetime.now(UTC)
        await store.emit(evaluation_trace("stale", occurred_at=now - timedelta(days=400)))
        kept = evaluation_trace("fresh", occurred_at=now - timedelta(days=1))
        await store.emit(kept)

        report = await engine.purge_expired()

        assert report.traces == 1
        # The purge's *own* ``OPERATION`` trace lands in the store it just swept,
        # which ADR-0119 §10 states outright — "one instant after the sweep, and…
        # therefore never a candidate for it. Noted because it looks like a paradox
        # and is not." So the walk returns the kept trace and the record of the
        # sweep that kept it, and the seam names which is which.
        walked = (await store.walk(limit=10)).traces
        assert [trace.id for trace in walked] == [kept.id, walked[-1].id]
        assert (walked[-1].kind, walked[-1].seam) == (TraceKind.OPERATION, "purge_expired")
        assert walked[-1].metrics["traces"] == 1
    finally:
        await engine.aclose()


async def test_a_keep_forever_horizon_sweeps_no_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``None`` is the disable sentinel, and it reaches the sweep as "do not run".

    ADR-0119 §10 gives the horizon ``episode_retention``'s convention — ``None``
    means keep forever — so a deployment that set it has asked for a store nothing
    deletes from. A composition that quietly substituted the default would destroy
    exactly the unarmed baseline #829's natural experiment depends on, which is the
    same loss §10 refuses a count cap over.
    """
    built = _spy_on_traces(monkeypatch)
    settings = Settings(embedder=EmbedderKind.HASHING, trace_retention=None)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        store = built[0]
        ancient = evaluation_trace("stale", occurred_at=datetime(2001, 1, 1, tzinfo=UTC))
        await store.emit(ancient)

        report = await engine.purge_expired()

        assert report.traces is None
        # The sweep did not run, so the operation's own trace **omits** the
        # ``traces`` key rather than reporting zero: ADR-0119 §3's observation rule,
        # where "an absent key means *not observed* and never zero". A zero here
        # would say a store was swept clean by a sweep nobody ran.
        walked = (await store.walk(limit=10)).traces
        assert [trace.id for trace in walked] == [ancient.id, walked[-1].id]
        assert walked[-1].seam == "purge_expired"
        assert "traces" not in walked[-1].metrics
        assert walked[-1].metrics["records"] == 0
    finally:
        await engine.aclose()


def _holders_of(root: object, target: object, *, depth: int = 6) -> list[str]:
    """Every attribute path from ``root`` that reaches ``target``.

    Bounded in depth and cycle-guarded, because an engine's object graph is deep
    and partly cyclic. **Six levels rather than four** since ADR-0119 §8's memory
    emitters landed: the writer's sink sits at
    ``engine._loop._writes._writer._traces._sink``, one hop past where four
    stopped, so the walk would have reported one memory emitter and silently
    missed its twin. Eight finds nothing six does not, so six is a bound rather
    than a lucky number.
    """
    found: list[str] = []
    seen: set[int] = set()

    def visit(subject: object, path: str, remaining: int) -> None:
        if remaining == 0 or id(subject) in seen:
            return
        seen.add(id(subject))
        for name, value in vars(subject).items():
            if value is target:
                found.append(f"{path}.{name}")
            elif hasattr(value, "__dict__"):
                visit(value, f"{path}.{name}", remaining - 1)

    visit(root, "engine", depth)
    return found


async def test_the_drivers_and_the_grant_operations_share_one_store(
    tmp_path: Path,
) -> None:
    """ADR-0102 §7: the *same object*, passed twice.

    A second store would let a user grant a source the gate then reads a different
    answer about — the failure mode that looks like nothing at all, because both
    halves work and disagree. Structural typing is what makes one object serve
    both seams (ADR-0097 §3), and the narrowing is the annotation on the driver's
    constructor rather than anything the composition root does.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        stage = engine._ingestion
        assert stage is not None
        (facet_source,) = _calendar_sources(engine)
        assert stage._grants is engine._grants._store
        assert facet_source._grants is engine._grants._store
    finally:
        await engine.aclose()


async def test_a_granted_source_becomes_readable_and_a_revocation_stops_it(
    tmp_path: Path,
) -> None:
    """Leg 6's exit test, reachable by a user rather than by a fake (#684).

    The whole loop through the real surface: nothing is read, the user grants,
    ingestion runs, the user revokes, and ingestion stops. What ADR-0102 §7 buys is
    that every step here is one a person can take at a terminal.

    **Revoking retires nothing**, which is asserted rather than assumed: ADR-0097
    §6 makes revocation prospective, so the belief the granted read produced is
    still held afterwards. A test that only checked the refusal would pass against
    an implementation that deleted what it had ingested.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        with pytest.raises(SourceNotGrantedError):
            await engine.ingest()

        await _grant_the_calendar(engine)
        assert (await engine.ingest()).stored == 1

        assert await engine.revoke(CALENDAR_READER_NAME) is not None
        with pytest.raises(SourceNotGrantedError):
            await engine.ingest()
        assert len(await engine.beliefs()) == 1
    finally:
        await engine.aclose()


async def test_build_engine_registers_no_calendar_source_without_a_path(
    tmp_path: Path,
) -> None:
    """A source with nothing to read is I/O on personal data in exchange for nothing.

    ADR-0093 §7a's words about the state it reserved, and the reason the adapter is
    registered on the path rather than unconditionally.
    """
    settings = Settings(embedder=EmbedderKind.HASHING)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert not _calendar_sources(engine)
    finally:
        await engine.aclose()


def _in_progress_calendar(directory: Path) -> Path:
    """A source holding one entry that is happening **right now**.

    Anchored on the wall clock for :func:`_one_event_calendar`'s reason — this
    layer wires the reader's own default clock, and inventing a second one here
    would be the second timezone/clock source ADR-0093 §7b refuses. Half an hour
    either side of now, so the entry is unambiguously in progress at whatever
    instant the read lands on (#658 tracks the live-clock dependency this shares).
    """
    began = datetime.now(UTC) - timedelta(minutes=30)
    ends = began + timedelta(hours=1)
    stamp = "%Y%m%dT%H%M%SZ"
    path = directory / "in-progress.ics"
    path.write_bytes(
        (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//ai-assistant tests//EN\r\n"
            "BEGIN:VEVENT\r\nUID:e1\r\nDTSTAMP:20260101T000000Z\r\n"
            f"DTSTART:{began.strftime(stamp)}\r\nDTEND:{ends.strftime(stamp)}\r\n"
            "SUMMARY:Dentist\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        ).encode()
    )
    return path


async def test_a_granted_calendar_reaches_the_assembled_context_as_a_facet(
    tmp_path: Path,
) -> None:
    """The facet half, end to end over the concrete reader (ADR-0096 §8).

    The claim nothing below this layer can make: ``lint-imports`` forbids every
    subsystem to import ``ai_assistant.readers``, so this is the only place a real
    ``CalendarReader`` and a real provider meet. It is the counterpart to the
    ingestion end-to-end case — a file on disk becomes a *facet* rather than a
    belief — and it is what would fail if the reader stopped populating
    ``SourceReading.facet`` and the adapter went back to contributing ``{}`` for
    every deployment.

    **It asserts the stamp and the count and nothing about the entry**, because the
    facet carries no entry text at all: "Dentist" reaches memory through the
    proposals and must not reach the situational context by a second route with a
    different stamp (ADR-0096 §6).
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_in_progress_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        await _grant_the_calendar(engine)
        context = await engine._loop._context.assemble()

        assert context.calendar is not None
        assert context.calendar.source == CALENDAR_READER_NAME
        assert context.calendar.read_at <= context.calendar.covers_until
        assert context.calendar.entries_in_progress == 1
    finally:
        await engine.aclose()


async def test_an_ungranted_calendar_reaches_the_context_as_nothing_at_all(
    tmp_path: Path,
) -> None:
    """And the ungranted deployment is observationally identical to an unread one.

    ADR-0097 §5's last clause over the concrete reader: the file below holds an
    entry that is happening right now, and the assembled context says nothing
    about it and nothing about why. ``CurrentContext`` never reports a source's
    grant state, because a field that did would be a model being handed a script
    to ask for access.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_in_progress_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        context = await engine._loop._context.assemble()

        assert context.calendar is None
    finally:
        await engine.aclose()


async def test_the_two_consumers_hold_separate_reader_instances(
    tmp_path: Path,
) -> None:
    """ADR-0096 §5, decided there rather than left for this layer to pick by accident.

    ADR-0093 §7 bounds a reader at **one outstanding worker**, and that reservation
    is per instance. Share one and a scheduled ingestion read suppresses the
    request-path facet for as long as it runs — coupling a request cadence to a
    periodic job, in the direction that makes an advisory facet wait on it.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        stage = engine._ingestion
        assert stage is not None
        (facet_source,) = _calendar_sources(engine)
        assert stage._reader is not facet_source._reader
    finally:
        await engine.aclose()


async def test_build_engine_wires_no_reader_when_no_source_is_configured(
    tmp_path: Path,
) -> None:
    """The shipping default, and the refusal that keeps it honest (ADR-0093 §7).

    "Every reader ships **disabled by default**, and the reason is that nothing may
    read a user's personal files because a default said so." So the ordinary
    deployment builds no stage — and asking it to ingest is a wiring fault it
    refuses, rather than an empty report indistinguishable from a source that had
    nothing to say (§8).
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert engine._ingestion is None
        with pytest.raises(ConfigurationError):
            await engine.ingest()
    finally:
        await engine.aclose()


async def test_build_engine_wires_the_ingestion_stage_over_the_one_memory_store(
    tmp_path: Path,
) -> None:
    """ADR-0028 §4's obligation applied to a **third** producer (ADR-0093 §6).

    The stage writes through the *same* write stage the learn leg and the
    observation stage use, which is ADR-0078 §3's one wiring obligation: a producer
    holding a ``MemoryWriter`` of its own "gets the ratified policy and applier and
    silently loses the queue", and a reader's proposals reach nobody in the moment,
    so a lost question is one nobody is ever asked. Over a second store an ingested
    belief would be unreadable and unforgettable through the surfaces the user
    actually has.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        stage = engine._ingestion
        assert stage is not None
        assert stage._writes is engine._loop._writes
    finally:
        await engine.aclose()


async def test_an_ingested_belief_is_readable_through_the_surface_the_user_has(
    tmp_path: Path,
) -> None:
    """The whole path, end to end: a file on disk becomes an inspectable belief.

    This is the claim the wiring exists to support and the one nothing below the
    composition root can make — ``lint-imports`` forbids every subsystem to import
    ``ai_assistant.readers``, so this layer is the only place a concrete reader and
    a real store meet (ADR-0093 §2, ADR-0095 §3). It also pins the direction
    ADR-0093 §1 rules on: the reader proposed, and the gate disposed.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=_one_event_calendar(tmp_path),
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        await _grant_the_calendar(engine)
        report = await engine.ingest()

        assert report.source == "calendar"
        assert report.proposed == 1
        assert report.stored == 1
        beliefs = await engine.beliefs()
        assert len(beliefs) == 1
        assert "Dentist" in beliefs[0].content
    finally:
        await engine.aclose()


async def test_a_configured_but_missing_source_fails_at_run_time_and_not_at_build(
    tmp_path: Path,
) -> None:
    """The split ADR-0093 §7 draws, honoured by the layer that could break it.

    Shape is validated at load — the path must be absolute — while "existence and
    readability" are properties of the world at an instant and are checked at run
    time, "where it degrades under §6 rather than refusing to start". A hub that
    would not boot because a calendar file sat on an unmounted volume would turn an
    advisory source into a boot dependency, which is the coupling ADR-0008 §4
    declined for the whole context subsystem.
    """
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        calendar_reader_path=tmp_path / "nowhere.ics",
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        assert engine._ingestion is not None
        # Granted first, so the failure this reaches is the *read* rather than the
        # gate: ADR-0097 §5 refuses before the source is resolved, so an ungranted
        # engine would raise ``SourceNotGrantedError`` and prove nothing about a
        # missing file.
        await _grant_the_calendar(engine)
        with pytest.raises(ReaderError):
            await engine.ingest()
    finally:
        await engine.aclose()


#: Every place a sweep may be called from (ADR-0083 §11, ADR-0119 §10).
#:
#: A file *and a function*, not a file alone: the delegating call sites are the
#: body of ``Engine._purge_expired`` and nothing else, so a second sweeper added
#: further down the same module is caught exactly as one added in another package.
#: Line numbers are deliberately absent — they churn on every edit above and would
#: turn a real guard into a chore.
#:
#: **Three names, because there are three stores.** ADR-0119 §10 sends the trace
#: purge to this same operation — "the trace purge becomes the third call behind
#: that same operation" — on ADR-0078 §10 item 8's reasoning rather than a new
#: one, so ``purge_before`` is guarded exactly as the first two names are.
#:
#: The last two entries are the canonical fakes **implementing** the seam, not
#: scheduling a sweep: ``ai_assistant.testing`` is test-only and the composition
#: root never imports it, so neither is reachable from a deployment. They are
#: listed rather than excluded by directory, because an excluded directory is a
#: hole in a guard whose whole value is that it has none.
_SWEEP_HOME = frozenset(
    {
        ("orchestration/engine.py", "Engine._purge_expired", "purge_expired"),
        ("orchestration/engine.py", "Engine._purge_expired", "purge"),
        ("orchestration/engine.py", "Engine._purge_expired", "purge_before"),
        ("testing/traces.py", "FakeTraceRetention.purge_before", "purge_before"),
        ("testing/traces.py", "FakeTraceStore.purge_before", "purge_before"),
    }
)


#: The three sweep names, one per store the maintenance operation reaches.
_SWEEP_NAMES = frozenset({"purge", "purge_expired", "purge_before"})


class _SweepScan(ast.NodeVisitor):
    """Find every call to one of :data:`_SWEEP_NAMES` and the function it sits in.

    **Receiver-blind, exactly as the pre-inversion guard was**, and ADR-0083 §11
    says that blindness is a *feature* here: it is what makes a sweep added under a
    different name, or over a different store, still show up. The scan matches the
    bare attribute name and has no idea what it is called on.
    """

    def __init__(self, module: str) -> None:
        self._module = module
        self._scope: list[str] = []
        #: ``(module, enclosing qualname, attribute)`` for each call found.
        self.found: set[tuple[str, str, str]] = set()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in _SWEEP_NAMES:
            self.found.add((self._module, ".".join(self._scope) or "<module>", node.func.attr))
        self.generic_visit(node)


def _sweep_call_sites(root: Path) -> set[tuple[str, str, str]]:
    """Every sweep call under ``root``, as ``(module, enclosing qualname, name)``."""
    found: set[tuple[str, str, str]] = set()
    for path in sorted(root.rglob("*.py")):
        scan = _SweepScan(path.relative_to(root).as_posix())
        scan.visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        found |= scan.found
    return found


def test_only_the_scheduler_s_own_path_sweeps_either_store() -> None:
    """ADR-0083 §11's inversion: the guard moves its goalpost, it is not deleted.

    Before leg 5 this asserted ``swept == []`` — an *absence*, the only shape a "do
    not invent a mechanism" instruction could be pinned in while nothing was allowed
    to sweep. ADR-0078 §10 item 8: "this store's purge is wired wherever
    ``purge_expired`` is wired and inherits the same fate. Inventing a second
    sweeping mechanism for one store would be the thing that has to be undone at
    leg 5." Its own docstring recorded that it "fails the day someone adds the timer
    leg 5 would have to remove".

    Leg 5 added that timer, so the assertion becomes an *equality with one named
    place*: every sweep is called from ``Engine._purge_expired`` and nowhere else,
    which is the scheduler's own path — its ``retention_purge`` job is
    ``Engine.purge_expired`` bound, and this is where that method delegates. §11:
    "``swept`` equals *exactly* the scheduler's own path… so that a second bespoke
    sweeper added anywhere else still fails."

    ADR-0119 §10 put a **third** store behind that one operation on the same
    reasoning, so ``purge_before`` joined the scan with it. A trace sweep on a timer
    of its own would be the second mechanism ADR-0078 §10 item 8 forbids, arriving
    for the store whose horizon has no read-time enforcement to fall back on.

    **Deleting it was the wrong move**, and §11 says why: it is the only mechanical
    expression of ADR-0078 §10 item 8, and "an instruction not to build a second
    mechanism is worth exactly as much as the guard that notices one".

    It still has to be static. A runtime test could only prove that the handful of
    operations it happened to call do not sweep, which is not the claim; reading the
    source proves the claim.

    That the scan **discriminates** — that it would still fail for a sweeper added
    somewhere else — is not taken on trust: see the two tests below, which run this
    same scan over a tree that has one.
    """
    root = Path(ai_assistant.__file__).resolve().parent

    assert _sweep_call_sites(root) == _SWEEP_HOME, (
        "the set of production sweep call sites is no longer exactly the scheduler's "
        "own path. ADR-0078 §10 item 8 forbids a second sweeping mechanism, and "
        "ADR-0083 §11 puts the one permitted home in Engine._purge_expired: one job "
        "calling both stores. A new entry here is a second sweeper; a missing one is "
        "a sweep that stopped happening."
    )


def test_the_sweep_guard_still_catches_a_sweeper_added_somewhere_else(tmp_path: Path) -> None:
    """The inverted guard is only worth keeping if it still fires. Proven, not assumed.

    An equality assertion can be satisfied by a scan that finds the right two things
    and is blind to everything else, and that scan would look identical on the real
    tree while catching nothing. So the scan is run over a tree that *does* contain a
    second sweeper, and it must find it.

    Four decoys, one per way a second mechanism could arrive: a different package
    entirely, a *different function in the very module that is allowed to sweep*, a
    sweep of some other store under a name nobody enumerated, and a trace sweep on a
    timer of its own (ADR-0119 §10's own "no second sweeping mechanism"). The second
    is what a file-level allowlist would have missed, and the third is what
    receiver-blindness buys (ADR-0083 §11 calls that blindness a feature).
    """
    (tmp_path / "orchestration").mkdir()
    (tmp_path / "orchestration" / "engine.py").write_text(
        "class Engine:\n"
        "    async def _purge_expired(self):\n"
        "        await self._memory.purge_expired()\n"
        "        await self._deferrals.purge()\n"
        "    async def _tick(self):\n"
        "        await self._deferrals.purge()\n",  # a second sweeper, same module
        encoding="utf-8",
    )
    (tmp_path / "timer.py").write_text(
        "async def sweep(store):\n    await store.purge_expired()\n",  # another package
        encoding="utf-8",
    )
    (tmp_path / "other.py").write_text(
        "async def tidy(trail):\n    await trail.purge()\n",  # some other store
        encoding="utf-8",
    )
    (tmp_path / "instrument.py").write_text(
        # A trace sweep of its own, which is what ADR-0119 §10 forbids by name.
        "async def age_out(traces, horizon):\n    await traces.purge_before(horizon)\n",
        encoding="utf-8",
    )

    found = _sweep_call_sites(tmp_path)

    assert found != _SWEEP_HOME, "the guard passed a tree with four foreign sweepers"
    assert ("orchestration/engine.py", "Engine._tick", "purge") in found
    assert ("timer.py", "sweep", "purge_expired") in found
    assert ("other.py", "tidy", "purge") in found
    assert ("instrument.py", "age_out", "purge_before") in found


def test_the_sweep_guard_accepts_only_the_permitted_home(tmp_path: Path) -> None:
    """The other half of discrimination: it must *pass* for the shape it permits.

    A scan that reported everything would also "still fail for a foreign sweeper",
    and would be useless — the guard has to be able to say yes. This pins that the
    permitted set is reachable, and that the thing making it reachable is the
    enclosing function rather than the file: the same three calls moved into a
    sibling method of the same class do **not** satisfy it.

    The canonical fakes are written out too, because they are in the permitted set:
    a fake *implementing* ``purge_before`` by delegating to its own rows is the
    Protocol's behaviour, not a scheduled sweep, and ``ai_assistant.testing`` is
    reachable from no deployment.
    """
    (tmp_path / "orchestration").mkdir()
    (tmp_path / "testing").mkdir()
    permitted = (
        "class Engine:\n"
        "    async def _purge_expired(self):\n"
        "        await self._memory.purge_expired()\n"
        "        await self._deferrals.purge()\n"
        "        await self._traces.purge_before(self._clock())\n"
    )
    (tmp_path / "orchestration" / "engine.py").write_text(permitted, encoding="utf-8")
    (tmp_path / "testing" / "traces.py").write_text(
        "class FakeTraceRetention:\n"
        "    async def purge_before(self, instant):\n"
        "        return self._rows.purge_before(instant)\n"
        "class FakeTraceStore:\n"
        "    async def purge_before(self, instant):\n"
        "        return self._rows.purge_before(instant)\n",
        encoding="utf-8",
    )
    assert _sweep_call_sites(tmp_path) == _SWEEP_HOME

    (tmp_path / "orchestration" / "engine.py").write_text(
        permitted.replace("_purge_expired", "_sweep_everything"), encoding="utf-8"
    )
    assert _sweep_call_sites(tmp_path) != _SWEEP_HOME


class TestBuildReembedder:
    """The composition root's second function, and ADR-0104 §4's refusal (#425)."""

    def test_it_wires_the_configured_embedder_to_the_stores_migration(self, tmp_path: Path) -> None:
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        reembedder = build_reembedder(settings)

        assert reembedder.store == tmp_path / "memory.db"

    def test_the_migration_receives_the_bounded_embedder_too(self, tmp_path: Path) -> None:
        """ADR-0118 §2's second clause names this consumer explicitly.

        "every consumer it hands an embedder to — the memory store and
        ``build_reembedder`` alike — receives that one." The migration walks a whole
        store through ``Embedder.embed``, so an unbounded one here would leave the
        longest-running embedding path in the tree the only unbounded one — and
        ADR-0104 §6 keeps it outside the scheduler, so no clause of ADR-0111 would
        ever have reached it.
        """
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        reembedder = build_reembedder(settings)

        assert isinstance(reembedder._embedder, BoundedEmbedder)
        assert isinstance(reembedder._embedder._inner, HashingEmbedder)

    def test_the_data_dir_keyword_wins_over_the_setting(self, tmp_path: Path) -> None:
        configured = tmp_path / "configured"
        configured.mkdir()
        passed = tmp_path / "passed"
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=configured)

        reembedder = build_reembedder(settings, data_dir=passed)

        assert reembedder.store == passed / "memory.db"

    def test_every_embedder_this_build_offers_is_on_device(self) -> None:
        """The tripwire, and it is meant to fail loudly the day it stops being true.

        ADR-0104 §4 refuses by an **enumerated** allow-list rather than a predicate,
        so a cloud ``EmbedderKind`` added later is refused until somebody puts it in
        the list deliberately. This is the other half of that: a member added and
        *not* classified fails here, so the decision cannot be skipped by omission.
        """
        assert set(EmbedderKind) == composition_module._ON_DEVICE_EMBEDDERS

    def test_an_off_device_target_is_refused_and_the_refusal_names_the_act(
        self, tmp_path: Path
    ) -> None:
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)
        cloud = settings.model_copy(update={"embedder": _CloudKind.CLOUD})

        with pytest.raises(ConfigurationError) as caught:
            build_reembedder(cloud)

        message = str(caught.value)
        # The refusal path is also the disclosure path (ADR-0104 §4).
        assert "upload every record in the memory store" in message
        assert "somebody-elses-cloud" in message
        assert "--upload-entire-memory-store" in message

    def test_the_flag_lifts_the_refusal_and_lifts_nothing_else(self, tmp_path: Path) -> None:
        """Authorising the egress does not conjure an embedder that does not exist.

        Review round 4 pressed on this and was right to: with the refusal lifted,
        construction used to fall through to the vendored on-device model, so an
        authorised selection would have reported one recipient and used another.
        `_build_embedder` is exhaustive now, so an unimplemented member is refused
        instead — and, because both members are branched, adding a third without a
        branch is a `mypy` error at the gate rather than anything reachable here
        (#737).
        """
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)
        cloud = settings.model_copy(update={"embedder": _CloudKind.CLOUD})

        with pytest.raises(AssertionError, match="somebody-elses-cloud"):
            build_reembedder(cloud, upload_entire_memory_store=True)

    def test_an_on_device_selection_reaches_the_migration_as_that_target(
        self, tmp_path: Path
    ) -> None:
        """The other half: a selection that *is* implemented is the one wired.

        Read off the plan rather than the object, because the plan is what the
        tool discloses to the operator (ADR-0104 §4) — so this is the assertion
        that the disclosed recipient is the configured one.
        """
        SqliteMemoryStore(
            traces_sink=FakeTraceSink(),
            path=tmp_path / "memory.db",
            embedder=HashingEmbedder(dimensions=8),
        ).close()
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        plan = build_reembedder(settings).plan()

        assert plan.target_model == HashingEmbedder().model_id
        assert plan.source_model == "hashing-8"
        assert plan.required


# --- ADR-0119 §9's two effective search limits -------------------------------
# §9 records, for every cardinality control that can drive a traced read past
# §3's 256-id cap, "the **effective** ``search`` limit that control produces at
# the seam, which need not equal the control's own value". Neither control is a
# ``Settings`` field, so the figure has to come from here: "the figure to record
# is the one the composition root actually produced".
#
# The three tests below are one property in three places, and they need to be
# three: what this layer *reports*, what it *tuned the collaborators to*, and
# what those collaborators then *ask the store for*. A record that is right in
# the first two and wrong in the third is exactly §9's failure — "a diagnostic
# that is wrong two short of its own boundary is worse than none, because it is
# the record an operator reaches for when truncated traces appear and cannot see
# why".


class _LimitSpy(FakeMemoryStore):
    """A canonical store that also remembers what ``limit`` it was asked for.

    Subclassed rather than hand-rolled: the point is to observe the real call a
    real collaborator makes, so everything about the store's behaviour has to stay
    the canonical one and only the observation is added.
    """

    def __init__(self) -> None:
        """Create an empty store with an empty log of asked-for limits."""
        super().__init__()
        self.limits: list[int] = []

    async def search(
        self,
        query: str,
        *,
        limit: int = 10,
        kinds: Sequence[MemoryKind] | None = None,
        bands: Sequence[BeliefBand] | None = None,
    ) -> MemorySearchResult:
        """Record ``limit``, then answer exactly as the canonical store would.

        Args:
            query: The query text.
            limit: How many records the caller asked for; the observation.
            kinds: The kind filter, passed through.
            bands: The band filter, passed through.

        Returns:
            Whatever :class:`~ai_assistant.testing.FakeMemoryStore` returns.
        """
        self.limits.append(limit)
        return await super().search(query, limit=limit, kinds=kinds, bands=bands)


async def test_build_composition_reports_the_two_effective_search_limits(
    tmp_path: Path,
) -> None:
    """What ADR-0119 §9's startup stamp is handed, and where it comes from.

    The retrieval figure is the control's own value; the conflict figure is the
    control **plus two**, because ADR-0079 §1's probe over-asks its ceiling. §9
    requires the second and not the first: "a ``conflict_limit`` of 255 sits under
    the cap while the probe it drives asks for 257".
    """
    composed = build_composition(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        assert isinstance(composed, Composition)
        assert composed.retrieval_search_limit == composition_module.RETRIEVAL_LIMIT
        assert composed.conflict_search_limit == composition_module.CONFLICT_LIMIT + 2
        assert isinstance(composed.engine, Engine)
    finally:
        await composed.engine.aclose()


async def test_build_composition_tunes_the_collaborators_to_the_figures_it_reports(
    tmp_path: Path,
) -> None:
    """The report is not a second opinion about what was built.

    §9's whole reason for saying *effective* is that the number must be the one
    the machine is running on. If the root reported these figures while leaving
    either collaborator on a default it does not control, a later change to that
    default would silently make the operator's record wrong — which is the failure
    this lane exists to avoid rather than one it may reintroduce.
    """
    composed = build_composition(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        writer = composed.engine._loop._writes._writer
        assert isinstance(writer, MemoryIngestor)  # narrows the Protocol-typed seam
        assert composed.engine._loop._retrieval_limit == composed.retrieval_search_limit
        assert writer._conflict_limit + 2 == composed.conflict_search_limit
    finally:
        await composed.engine.aclose()


async def test_the_conflict_probe_asks_the_store_for_the_reported_figure() -> None:
    """The ``+ 2`` is pinned against the ingestor's behaviour, not against a comment.

    The arithmetic is duplicated in the composition root because `memory` exposes
    no effective-limit seam and golden rule 1 forbids importing its internals. A
    duplicate is only safe if something fails when it drifts, and this is that
    something: the ingestor tuned to the root's ceiling is asked what limit it
    actually reaches ``search`` with.
    """
    store = _LimitSpy()
    writer = MemoryIngestor(
        store=store,
        policy=DefaultMemoryPolicy(),
        traces_sink=FakeTraceSink(),
        conflict_limit=composition_module.CONFLICT_LIMIT,
    )

    await writer.ingest(
        MemoryUpdateProposal(
            proposed=SemanticMemory(
                id="record-1",
                content="the user drinks oat milk",
                fact="the user drinks oat milk",
                provenance=Provenance(
                    source=MemorySource.USER_ASSERTED,
                    confidence=1.0,
                    last_updated=datetime(2026, 8, 9, tzinfo=UTC),
                ),
            ),
            rationale="because",
        )
    )

    assert store.limits == [composition_module.CONFLICT_LIMIT + 2]


async def test_the_band_budget_never_asks_for_more_than_the_reported_figure() -> None:
    """The retrieval figure's "effective equals its own value", pinned the same way.

    ``orchestration/retrieval.py`` fills one budget of ``retrieval_limit`` band by
    band, so the first band asks for all of it and every later band asks for what
    is left. The largest ``limit`` reaching the store is therefore the control
    itself — which is what §9 asserts and what this checks rather than assumes.
    """
    store = _LimitSpy()

    await assemble_by_band(
        store, "oat milk", limit=composition_module.RETRIEVAL_LIMIT, kinds=BELIEF_KINDS
    )

    assert store.limits
    assert max(store.limits) == composition_module.RETRIEVAL_LIMIT


class TestBuildMeasureReader:
    """The composition root's third function (ADR-0120 §9).

    Thin by design: §9 gives the reporting tool nothing to be wired *to*, so what
    is on test is the one fact it may not go and get for itself — where the trace
    store is — and the property that asking does not create one.
    """

    def test_it_points_the_reader_at_the_trace_store(self, tmp_path: Path) -> None:
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        reader = build_measure_reader(settings)

        assert reader.store == tmp_path / "traces.db"

    def test_the_data_dir_keyword_wins_over_the_setting(self, tmp_path: Path) -> None:
        configured = tmp_path / "configured"
        configured.mkdir()
        passed = tmp_path / "passed"
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=configured)

        reader = build_measure_reader(settings, data_dir=passed)

        assert reader.store == passed / "traces.db"

    def test_building_a_reader_opens_no_database(self, tmp_path: Path) -> None:
        """ADR-0120 §8's answer to a stream with nothing in it is a sentence.

        A reader that opened the store on construction would create an empty
        seventh database as a side effect of a deployment that has never run the
        hub asking whether it has any traces — a write, by a tool that reads.
        """
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        build_measure_reader(settings)

        assert not (tmp_path / "traces.db").exists()

    async def test_the_reader_reports_the_empty_stream_over_a_store_with_nothing_in_it(
        self, tmp_path: Path
    ) -> None:
        """End to end against the durable store, through the walk and back."""
        SqliteTraceStore(path=tmp_path / "traces.db").close()
        settings = Settings(embedder=EmbedderKind.HASHING, data_dir=tmp_path)

        report = await build_measure_reader(settings).report(
            start=datetime(2026, 7, 1, tzinfo=UTC),
            end=datetime(2026, 8, 1, tzinfo=UTC),
            settling=timedelta(hours=1),
        )

        assert "empty" in report.render()
