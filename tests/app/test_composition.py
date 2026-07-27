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
from ai_assistant.core.config import Settings
from ai_assistant.core.errors import AssistantError, ConfigurationError
from ai_assistant.core.types import Reversibility, RiskLevel
from ai_assistant.memory import MemoryIngestor, SqliteMemoryStore
from ai_assistant.orchestration import Engine
from ai_assistant.permissions import ThresholdActionPolicy
from ai_assistant.planning import SqlitePlanStore
from ai_assistant.tools import InMemoryToolRegistry

if TYPE_CHECKING:
    from pathlib import Path


async def test_build_engine_returns_a_ready_engine(tmp_path: Path) -> None:
    """The builder assembles a real ``Engine`` and opens its stores."""
    engine = build_engine(Settings(), data_dir=tmp_path)
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
    engine = build_engine(Settings(), data_dir=tmp_path)
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
    engine = build_engine(Settings(), data_dir=tmp_path)
    try:
        memory = engine._loop._memory
        assert isinstance(memory, SqliteMemoryStore)
        writer = engine._loop._writer
        assert isinstance(writer, MemoryIngestor)  # narrows the Protocol-typed seam
        assert writer._store is memory
    finally:
        await engine.aclose()


async def test_build_engine_wires_one_registry_object_as_both_registry_and_invoker(
    tmp_path: Path,
) -> None:
    """Selection and execution act on one tool object, everywhere (ADR-0029 §8).

    The second prose-only wiring obligation: ``ToolRegistry`` and ``ToolInvoker``
    are separate seams that "no Protocol can close" onto one instance. If the
    runner selected from one registry while the executor invoked against another,
    a gated step could execute a tool the permission check never saw.
    """
    engine = build_engine(Settings(), data_dir=tmp_path)
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
    engine = build_engine(Settings(confirmation_ttl=ttl), data_dir=tmp_path)
    try:
        assert engine._runner._confirmation_ttl == ttl
    finally:
        await engine.aclose()


async def test_build_engine_defaults_the_runner_to_no_confirmation_lifetime(
    tmp_path: Path,
) -> None:
    """With no ``confirmation_ttl`` set, the runner keeps the pre-#243 default of None (#310)."""
    engine = build_engine(Settings(), data_dir=tmp_path)
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
    engine = build_engine(Settings(), data_dir=tmp_path)
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
    engine = build_engine(Settings(), data_dir=tmp_path)
    await engine.aclose()
    # Idempotent: a second close does nothing and does not raise.
    await engine.aclose()


async def test_build_engine_creates_a_missing_data_dir(tmp_path: Path) -> None:
    """A data directory that does not exist yet is created (§2 owns its resources)."""
    nested = tmp_path / "state" / "assistant"
    assert not nested.exists()
    engine = build_engine(Settings(), data_dir=nested)
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
        build_engine(Settings(), data_dir=tmp_path)

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
        build_engine(Settings(), data_dir=blocker / "sub")


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
