"""The composition root wires the production subsystems (ADR-0042 §2).

These are real integration tests: they open the actual connection-owning SQLite
stores (in a temp directory) and assemble the real subsystems. They do not call
the model — construction wires the provider but never invokes it — so no network
or API key is needed.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.app import composition as composition_module
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import AssistantError, ConfigurationError, ModelError
from ai_assistant.core.types import Reversibility, RiskLevel
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.memory import MemoryIngestor, SqliteMemoryStore
from ai_assistant.models import HashingEmbedder
from ai_assistant.orchestration import Engine
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.tools import InMemoryToolRegistry

if TYPE_CHECKING:
    from pathlib import Path


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
        writer = engine._loop._writer
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
    """
    from ai_assistant.models.fastembed_embedder import (  # noqa: PLC0415 — local so only this test imports fastembed
        FastEmbedEmbedder,
    )

    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)  # narrows the Protocol-typed seam
        assert isinstance(memory._embedder, FastEmbedEmbedder)
        assert memory._embedder.dimensions == 384  # BAAI/bge-small-en-v1.5, ADR-0024
    finally:
        await engine.aclose()


async def test_build_engine_wires_the_hashing_embedder_when_selected(tmp_path: Path) -> None:
    """The ``hashing`` knob wires the deterministic ``HashingEmbedder`` instead (ADR-0006 §2).

    The escape hatch for tests, offline use, and CI: selecting it avoids the vendored
    model (and its ONNX runtime) entirely, at the cost of non-semantic retrieval.
    """
    engine = build_engine(Settings(embedder=EmbedderKind.HASHING), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)  # narrows the Protocol-typed seam
        assert isinstance(memory._embedder, HashingEmbedder)
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
    """
    from ai_assistant.models import fastembed_embedder  # noqa: PLC0415

    monkeypatch.delattr(fastembed_embedder, "FastEmbedEmbedder")

    absent = tmp_path / "state"
    assert not absent.exists()

    with pytest.raises(ConfigurationError, match="on-device embedding runtime"):
        build_engine(Settings(), data_dir=absent)

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
        assert stage._writer is engine._loop._writer
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
