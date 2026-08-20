"""The places the harness copies or mirrors something the package owns.

Each of them is a silent-staleness hazard: a literal that stops matching, a limit that
stops tracking the composition root, a refusal that stops being enforced, a read whose
shape drifts from the one the product performs. None is caught by a type check, so each
has a test.

**Since #1293 that includes the write path's argument list, and not only its numbers.**
The budgets, the routes and the observer's calendar were each pinned here — and
``build_harness`` still constructed ``MemoryIngestor`` without the ``reconciler`` the
composition root passes it, for two published pilots, because no test asserted anything
about *which arguments* the two calls carry. Pinning a chosen list would have the same
hole one argument further on, so the test below compares the calls themselves.
"""

from __future__ import annotations

import dataclasses
import hashlib
import urllib.request
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any
from unittest import mock
from zoneinfo import ZoneInfo

import pytest
from benchmarks.memory import answer, records, wiring
from benchmarks.memory.corpora import fetch as fetch_module
from benchmarks.memory.corpora.fetch import (
    CorpusFetchError,
    cached_path,
    digest_of,
    ensure_file,
)
from benchmarks.memory.corpora.provenance import CorpusFile
from benchmarks.memory.records import RunMode
from benchmarks.memory.run import (
    PREREGISTRATION_REFUSAL,
    check_credentials_for,
    refuse_ineligible_scored_run,
)
from benchmarks.memory.wiring import build_harness, build_reconciler, reconciler_spec

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType

from ai_assistant.app import composition
from ai_assistant.app.composition import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError
from ai_assistant.learning import ModelBackedObserver
from ai_assistant.memory import MemoryIngestor, ModelBackedReconciler
from ai_assistant.memory import traces as memory_traces
from ai_assistant.orchestration import loop as orchestration_loop
from ai_assistant.testing import FakeModelProvider, FakeObserver


def test_the_copied_trace_metric_keys_still_match_the_emitter() -> None:
    """`records.py` writes these as literals rather than importing a subsystem's
    module constants; this is what keeps the copy honest."""
    assert records.LIMIT_KEY == memory_traces.LIMIT
    assert records.FETCH_K_KEY == memory_traces.FETCH_K
    assert records.CANDIDATES_KEY == memory_traces.CANDIDATES
    assert records.BANDS_KEY == memory_traces.BANDS
    assert records.EXCLUSION_KEYS == (
        memory_traces.EXCLUDED_KIND,
        memory_traces.EXCLUDED_RETENTION,
        memory_traces.EXCLUDED_WINDOW,
        memory_traces.EXCLUDED_BAND,
    )


def test_the_trace_carries_no_capped_key_so_the_derivation_is_needed() -> None:
    """`ceiling_bound` is derived from `fetch_k < limit` precisely because the store
    emits no `capped` metric. If one ever appears, read it instead of deriving it."""
    assert not hasattr(memory_traces, "CAPPED")


def test_the_harness_retrieval_budget_is_the_composition_root_s(tmp_path: Path) -> None:
    """Imported, not copied — so a benchmark cannot measure a budget the product
    does not use."""
    harness = build_harness(
        Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING),
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
    )
    try:
        assert harness.retrieval_limit == composition.RETRIEVAL_LIMIT
    finally:
        harness.close()


def test_the_harness_episodic_budget_is_the_composition_root_s(tmp_path: Path) -> None:
    """ADR-0158 §3's supplement budget, imported like the belief budget beside it.

    The ceiling is asserted here as well as in the product, because it is the clause
    §3 puts the thesis in: whatever the numbers become, nobody can configure a system
    that asks for more transcript than belief — and a harness measuring one would
    publish it as this system's behaviour."""
    harness = build_harness(
        Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING),
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
    )
    try:
        assert harness.episodic_limit == composition.EPISODIC_SUPPLEMENT_LIMIT
        assert harness.episodic_limit <= harness.retrieval_limit
    finally:
        harness.close()


@pytest.mark.parametrize(
    ("bound", "error"),
    [
        pytest.param(composition.RETRIEVAL_LIMIT + 1, ValueError, id="above-the-belief-budget"),
        pytest.param(-1, ValueError, id="negative"),
        # `True` is the case the annotation cannot hold: `bool` is an `int` subclass,
        # so this type-checks and would run the supplement at a bound of one.
        pytest.param(True, TypeError, id="a-flag-is-not-a-count"),
        pytest.param(1.5, TypeError, id="non-integral"),
    ],
)
def test_a_harness_may_not_carry_an_episodic_bound_the_product_would_refuse(
    tmp_path: Path, bound: object, error: type[Exception]
) -> None:
    """ADR-0158 §3's ceiling and the loop's own tuning check, held by construction.

    The bound `build_harness` sets is always the composition root's, so none of this
    is reachable from a run — but a harness derived with `dataclasses.replace`, which
    is how a test varies the bound, would otherwise measure a configuration
    `LearningLoop.__init__` refuses to start under. Zero is *not* in this list because
    zero is legal and disables the supplement.
    """
    harness = build_harness(
        Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING),
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
    )
    try:
        with pytest.raises(error, match="episodic_limit"):
            dataclasses.replace(harness, episodic_limit=bound)  # type: ignore[arg-type]
    finally:
        harness.close()


def test_a_harness_may_not_carry_a_belief_budget_the_product_would_refuse(
    tmp_path: Path,
) -> None:
    """The same check on the budget beside it, which `LearningLoop` requires positive."""
    harness = build_harness(
        Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING),
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
    )
    try:
        with pytest.raises(ValueError, match="retrieval_limit"):
            dataclasses.replace(harness, retrieval_limit=0, episodic_limit=0)
    finally:
        harness.close()


def test_the_supplement_reads_the_kinds_and_bands_the_loop_reads() -> None:
    """The equivalence guard on ADR-0158's read, and the reason it is a test.

    ``answer.py`` mirrors ``LearningLoop._supplement`` by hand — the harness must not
    run the engine — and the loop's two constants are *private*, so they are copied
    rather than imported: a benchmark does not get to widen a subsystem's public
    surface for its own convenience. This is what makes the copy honest. Widening
    either side alone is the failure it exists for, and both are the kind of edit that
    looks harmless: `EPISODIC` joining the belief kinds is exactly what §2 forbids,
    and a `None` band is the flat read §3 refuses by name.
    """
    assert answer.SUPPLEMENT_KINDS == orchestration_loop._SUPPLEMENT_KINDS
    assert answer.SUPPLEMENT_BANDS == orchestration_loop._SUPPLEMENT_BANDS


@contextmanager
def _recorded_ingestor(module: ModuleType) -> Iterator[dict[str, Any]]:
    """Capture the keyword arguments ``module`` constructs its ``MemoryIngestor`` with.

    The real class is still constructed and handed back, so the composition under test
    goes on working — this observes the call rather than replacing the object.

    Args:
        module: The composition root to watch. It must bind ``MemoryIngestor`` as a
            module attribute, which both roots do.

    Yields:
        The mapping, empty until the build inside the block runs.
    """
    captured: dict[str, Any] = {}

    def _record(**kwargs: Any) -> MemoryIngestor:
        if captured:
            pytest.fail(f"{module.__name__} built more than one MemoryIngestor")
        captured.update(kwargs)
        return MemoryIngestor(**kwargs)

    with mock.patch.object(module, "MemoryIngestor", _record):
        yield captured


async def test_the_harness_ingestor_is_built_from_the_composition_root_s_arguments(
    tmp_path: Path,
) -> None:
    """The write path's equivalence guard, in the shape #1181 forced for the read path.

    **This is the test #1293 did not have.** The budgets, the routes and the observer's
    calendar were each pinned above, and none of them could see that ``build_harness``
    passed no ``reconciler`` while the composition root passed one: the hole was in the
    *argument list*, which nothing compared. So this compares the calls rather than a
    chosen list of their contents — a keyword added to one root and not the other fails
    here whatever it is called and whatever it carries.

    ``now`` is the one permitted difference, and it is the module's first documented
    deviation: the harness runs on the corpus's clock (``BenchmarkClock``) where the
    product runs on the wall clock, which is a difference the benchmark exists to have.
    It is asserted as an exact set rather than skipped, so a *second* harness-only
    argument cannot slip in beside it.

    The settings deliberately name a reconciler route and a bound that are not the
    defaults, so the two roots agreeing is a fact about what they read rather than about
    what they both left alone.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-answers",
        reconciler_model="anthropic:claude-reconciles",
        reconciler_max_conflicts=7,
    )

    with _recorded_ingestor(composition) as product:
        engine = build_engine(settings, data_dir=tmp_path / "product")
        await engine.aclose()
    with _recorded_ingestor(wiring) as harness_arguments:
        harness = build_harness(
            settings,
            data_dir=tmp_path / "harness",
            model=FakeModelProvider(),
            observer=FakeObserver(),
        )
        harness.close()

    assert set(product) - set(harness_arguments) == set()
    assert set(harness_arguments) - set(product) == {"now"}
    # The collaborators are distinct instances over distinct directories, so the
    # comparison is of *shape*: the harness must not quietly substitute another store,
    # another policy or another trace sink for the one the product wires.
    for name in ("store", "policy", "traces_sink", "reconciler"):
        assert type(harness_arguments[name]) is type(product[name]), name
    assert harness_arguments["conflict_limit"] == product["conflict_limit"]


async def test_the_harness_reconciler_labels_where_the_product_s_would(
    tmp_path: Path,
) -> None:
    """ADR-0159 §3's two configured facts, on the same settings, from both roots.

    Equal *classes* would be satisfied by a reconciler pointed at another model under
    another bound, which is a different mechanism wearing the right type. The provider
    is compared by shape for the same reason the objects above are: §3 requires one
    route with retry and no routing, and a harness that wrapped a router here would
    measure a fallback the product does not have on this seam.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-answers",
        reconciler_model="anthropic:claude-reconciles",
        reconciler_max_conflicts=7,
    )

    with _recorded_ingestor(composition) as product:
        engine = build_engine(settings, data_dir=tmp_path / "product")
        await engine.aclose()
    with _recorded_ingestor(wiring) as harness_arguments:
        harness = build_harness(
            settings,
            data_dir=tmp_path / "harness",
            model=FakeModelProvider(),
            observer=FakeObserver(),
        )
        harness.close()

    theirs, ours = product["reconciler"], harness_arguments["reconciler"]
    assert isinstance(theirs, ModelBackedReconciler)
    assert isinstance(ours, ModelBackedReconciler)
    assert ours._route == theirs._route == "anthropic:claude-reconciles"
    assert ours._max_conflicts == theirs._max_conflicts == 7
    assert type(ours._model) is type(theirs._model)


def test_the_harness_resolves_the_reconciler_route_the_composition_root_resolves(
    tmp_path: Path,
) -> None:
    """``_reconciler_spec`` is private, so the harness spells it; this keeps the copy
    honest, in the shape the copied trace keys above are kept honest.

    Both branches are exercised, because the fallback is the one that carries ADR-0159
    §3's property: an unset ``reconciler_model`` names no provider the operator did not
    already configure, so leaving it alone cannot breach ADR-0004 §2.
    """
    unset = Settings(
        data_dir=tmp_path,
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-answers",
    )
    named = unset.model_copy(update={"reconciler_model": "openai:gpt-reconciles"})

    for settings in (unset, named):
        assert reconciler_spec(settings) == composition._reconciler_spec(settings)
    # And not vacuously equal on both sides of the branch.
    assert reconciler_spec(unset) == "anthropic:claude-answers"
    assert reconciler_spec(named) == "openai:gpt-reconciles"


def test_a_harness_reports_the_reconciler_it_built(tmp_path: Path) -> None:
    """The manifest's field is read off this, so it has to name the object's own facts.

    Not the settings': #1293's whole failure was a provenance claim assembled from
    ``Settings`` while the ingestor held nothing, and a description that merely repeated
    its inputs would leave that possible one layer up.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-answers",
        reconciler_model="anthropic:claude-reconciles",
        reconciler_max_conflicts=7,
    )
    harness = build_harness(
        settings,
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
    )
    try:
        built = harness.reconciliation
        assert built.route == "anthropic:claude-reconciles"
        assert built.max_conflicts == 7
        assert built.name == (
            "ModelBackedReconciler(route=anthropic:claude-reconciles, max_conflicts=7)"
        )
    finally:
        harness.close()


def test_an_injected_reconciler_is_the_one_the_harness_reports(tmp_path: Path) -> None:
    """A run builds one reconciler and shares it, so the harness must report what it was
    handed rather than what the settings would have produced.

    This is the property that makes ``manifest.reconciler`` an account of an object:
    the settings here name a route the assertion below refuses to see, so a field
    rebuilt from them cannot pass.
    """
    settings = Settings(
        data_dir=tmp_path / "data",
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-answers",
        reconciler_model="anthropic:claude-configured",
    )
    injected = build_reconciler(settings.model_copy(update={"reconciler_model": None}))
    harness = build_harness(
        settings,
        data_dir=tmp_path / "case",
        model=FakeModelProvider(),
        observer=FakeObserver(),
        reconciler=injected,
    )
    try:
        assert harness.reconciliation is injected
        assert harness.reconciliation.route == "anthropic:claude-answers"
        assert "claude-configured" not in harness.reconciliation.name
    finally:
        harness.close()


def test_the_harness_reports_the_routes_the_settings_name(tmp_path: Path) -> None:
    """A pilot that changed one route without recording it is uninterpretable."""
    settings = Settings(
        data_dir=tmp_path,
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-x",
        observer_model="openai:gpt-y",
    )
    harness = build_harness(
        settings, data_dir=tmp_path / "case", model=FakeModelProvider(), observer=FakeObserver()
    )
    try:
        assert harness.model_route == "anthropic:claude-x"
        assert harness.observer_route == "openai:gpt-y"
    finally:
        harness.close()


def test_the_observer_route_falls_back_to_the_default_model(tmp_path: Path) -> None:
    """The same fallback `_observer_spec` applies, so an unset setting names no
    provider the operator did not already configure."""
    settings = Settings(
        data_dir=tmp_path, embedder=EmbedderKind.HASHING, default_model="anthropic:claude-x"
    )
    harness = build_harness(
        settings, data_dir=tmp_path / "case", model=FakeModelProvider(), observer=FakeObserver()
    )
    try:
        assert harness.observer_route == "anthropic:claude-x"
    finally:
        harness.close()


def test_the_harness_gives_the_observer_the_configured_timezone(tmp_path: Path) -> None:
    """The harness builds its own producer, so ADR-0156 §7's wiring line has to be
    made here too — and its omission is silent (#1171).

    ADR-0156 §3's second clause has a producer handed no calendar render no instants
    and resolve no relative expression at all. That is deliberate behaviour, not a
    fault, so nothing raises and nothing degrades: a harness taking the ``None``
    default would ingest a whole corpus with no event times in the observation prompt
    and report a healthy run, and a pilot's temporal categories would come back flat
    for a wiring reason rather than a measured one. This is the one argument in that
    constructor whose absence no other test could notice.

    The zone is read off the built producer because nothing exposes it — an
    ``Observer`` holds its calendar and shows nobody, exactly as it holds its
    provider — which is the same reading ``tests/app/test_composition.py`` takes of
    the composition root. A zone far from UTC is chosen so the default could not
    pass. The observer is deliberately **not** injected here: the injected seam is the
    one this test must not measure.
    """
    settings = Settings(
        data_dir=tmp_path, embedder=EmbedderKind.HASHING, timezone="Pacific/Kiritimati"
    )
    harness = build_harness(settings, data_dir=tmp_path / "case", model=FakeModelProvider())
    try:
        observer = harness.observation._observer
        assert isinstance(observer, ModelBackedObserver)
        assert observer._zone == ZoneInfo("Pacific/Kiritimati")
    finally:
        harness.close()


def test_a_smoke_run_is_refused_nothing() -> None:
    """Every condition below is a scored-run condition; a smoke run answers to none of
    them, which is what makes smoke the safe default."""
    refuse_ineligible_scored_run(
        RunMode.SMOKE,
        preregistration_final=False,
        max_sessions=2,
        embedder=EmbedderKind.HASHING,
        grader_kind="exact",
    )


def test_a_scored_run_is_refused_without_confirmation() -> None:
    """#1029's ground rule 1, made a refusal rather than an understanding."""
    with pytest.raises(PermissionError) as caught:
        refuse_ineligible_scored_run(RunMode.SCORED, preregistration_final=False)

    assert str(caught.value) == PREREGISTRATION_REFUSAL
    assert "#1029" in PREREGISTRATION_REFUSAL


def test_a_fully_eligible_scored_run_is_allowed() -> None:
    """`max_sessions=0` is stated, not omitted: the default is `None`, which says the
    selection recorded nothing and is refused."""
    refuse_ineligible_scored_run(
        RunMode.SCORED,
        preregistration_final=True,
        max_sessions=0,
        embedder=EmbedderKind.ON_DEVICE,
        grader_kind="model",
        injected_seams=(),
    )


def test_a_scored_run_under_the_hashing_embedder_is_refused() -> None:
    """Retrieval under it is non-semantic, so the run would not measure the pipeline
    #1029 predicts about."""
    with pytest.raises(ValueError, match="non-semantic"):
        refuse_ineligible_scored_run(
            RunMode.SCORED,
            preregistration_final=True,
            max_sessions=0,
            embedder=EmbedderKind.HASHING,
            grader_kind="model",
        )


def test_a_scored_run_with_the_exact_grader_is_refused() -> None:
    """Both benchmarks grade with an LLM judge; a substring match is comparable to no
    published number."""
    with pytest.raises(ValueError, match="LLM judge"):
        refuse_ineligible_scored_run(
            RunMode.SCORED,
            preregistration_final=True,
            max_sessions=0,
            embedder=EmbedderKind.ON_DEVICE,
            grader_kind="exact",
        )


def test_a_rejected_url_leaves_no_staging_file_behind(tmp_path: Path) -> None:
    """`mkstemp` creates the file before the download is even attempted, so every exit
    that is not a successful publish has to remove it — including the ones that raise
    before a byte is written."""
    file = CorpusFile(
        name="corpus.json", url="http://example.invalid/x", sha256="a" * 64, size_bytes=1
    )

    with pytest.raises(CorpusFetchError, match="non-https"):
        ensure_file(file, cache=tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.integration
def test_a_cached_file_with_the_wrong_bytes_is_refused_and_removed(tmp_path: Path) -> None:
    """A cache hit is re-verified rather than trusted: a truncated download from an
    interrupted run is exactly what a hit-means-done rule gets wrong. The refusal here
    comes from the re-download, which cannot reach the network in this test."""
    file = CorpusFile(
        name="corpus.json", url="https://example.invalid/x", sha256="a" * 64, size_bytes=1
    )
    target = cached_path(file, cache=tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("not the pinned bytes", encoding="utf-8")

    with pytest.raises(CorpusFetchError):
        ensure_file(file, cache=tmp_path)

    assert not target.exists()


@pytest.mark.integration
def test_a_cached_file_with_the_right_bytes_is_returned_without_a_download(
    tmp_path: Path,
) -> None:
    payload = "the pinned bytes"
    target = tmp_path / "corpus.json"
    target.write_text(payload, encoding="utf-8")
    file = CorpusFile(
        name="corpus.json",
        # A URL that would fail if it were reached, which is what makes this a test
        # that the cache short-circuits rather than a test that the network works.
        url="https://example.invalid/x",
        sha256=digest_of(target),
        size_bytes=len(payload),
    )

    assert ensure_file(file, cache=tmp_path) == target


def test_a_non_https_url_is_refused_before_anything_is_written(tmp_path: Path) -> None:
    """Everything downstream trusts these bytes, and a pin can be edited in the same
    diff that edits the URL."""
    file = CorpusFile(
        name="corpus.json", url="http://example.invalid/x", sha256="a" * 64, size_bytes=1
    )

    with pytest.raises(CorpusFetchError, match="non-https"):
        ensure_file(file, cache=tmp_path)

    assert not (tmp_path / "corpus.json").exists()


class _StalledResponse:
    """A peer that completed the handshake and then delivers nothing.

    `urlopen(timeout=…)` arms the socket, so a stall surfaces from the *read* as
    `TimeoutError` rather than from the connect — which is why this raises there and
    not from the constructor.
    """

    def __enter__(self) -> _StalledResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self, _size: int = -1) -> bytes:
        msg = "the read operation timed out"
        raise TimeoutError(msg)


def test_a_stalled_transfer_fails_instead_of_hanging(tmp_path: Path) -> None:
    """Without an explicit timeout `urlopen` inherits the global default of `None`, so
    a server that accepts and then sends nothing blocks `fetch` — and with it `run` —
    forever, with no output and no exception path ever reached."""
    file = CorpusFile(
        name="corpus.json", url="https://example.invalid/x", sha256="a" * 64, size_bytes=1
    )
    seen: dict[str, object] = {}

    def _fake_urlopen(request: object, *, timeout: float | None = None) -> _StalledResponse:
        seen["timeout"] = timeout
        return _StalledResponse()

    with (
        # Patched on `urllib.request` itself, which is where `_download` resolves the
        # name at call time.
        mock.patch.object(urllib.request, "urlopen", _fake_urlopen),
        pytest.raises(CorpusFetchError) as raised,
    ):
        ensure_file(file, cache=tmp_path)

    # The bound is passed and finite: a `None` here is exactly the defect, and it would
    # otherwise be invisible because the fake never blocks.
    assert isinstance(seen["timeout"], float)
    assert seen["timeout"] > 0
    # Surfaced as this module's error with the stall preserved, rather than escaping as
    # a bare `TimeoutError` from inside a download.
    assert isinstance(raised.value.__cause__, TimeoutError)
    assert not (tmp_path / "corpus.json").exists()


def test_a_scored_run_over_shortened_histories_is_refused() -> None:
    """A shortened history is a different memory, so its answers are about a
    conversation that did not happen — not something a frozen prediction is scored
    against."""
    with pytest.raises(ValueError, match="different memory"):
        refuse_ineligible_scored_run(
            RunMode.SCORED,
            preregistration_final=True,
            max_sessions=2,
            embedder=EmbedderKind.ON_DEVICE,
            grader_kind="model",
        )


def test_a_scored_run_whose_selection_recorded_nothing_is_refused() -> None:
    """An unrecorded bound is not a whole history (#1052). The bound now arrives from
    the plan's own selection, so `None` says the cases reached the gate carrying no
    account of what was done to them — and refusing that is what stops the truncation
    from being invisible rather than merely undeclared."""
    with pytest.raises(ValueError, match="no record of how"):
        refuse_ineligible_scored_run(
            RunMode.SCORED,
            preregistration_final=True,
            max_sessions=None,
            embedder=EmbedderKind.ON_DEVICE,
            grader_kind="model",
        )


@pytest.mark.integration
def test_two_fetches_of_one_corpus_do_not_share_a_staging_path(tmp_path: Path) -> None:
    """A shared `.partial` would have one process verify and publish the inode the
    other is still writing through — corrupting the cache *after* the digest check that
    is supposed to make it trustworthy. Each fetch stages under a name of its own, so
    the loser of the race only overwrites identical verified content."""
    staged: list[str] = []
    payload = b"the pinned bytes"
    file = CorpusFile(
        name="corpus.json",
        url="https://example.invalid/x",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )

    def _fake_download(url: str, target: Path) -> None:
        staged.append(target.name)
        target.write_bytes(payload)

    with mock.patch.object(fetch_module, "_download", _fake_download):
        first = ensure_file(file, cache=tmp_path)
        (tmp_path / "corpus.json").unlink()
        second = ensure_file(file, cache=tmp_path)

    assert first == second
    assert len(staged) == 2
    assert staged[0] != staged[1]
    assert not list(tmp_path.glob("*.partial"))


def test_a_configured_but_unreached_fallback_needs_no_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The harness builds one fixed route per seam and disables routing, so checking
    the router's whole preference order — as `app.ensure_model_credentials` does, and
    rightly, for the hub — would refuse a valid benchmark over a vendor it never
    constructs."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "present-for-the-route-that-is-used")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(
        data_dir=tmp_path,
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-opus-4-8",
        fallback_models=("openai:gpt-4o",),
    )

    check_credentials_for(
        settings, answering=True, distillation=True, judging=True, reconciling=True
    )


def test_the_observer_route_is_checked_even_when_it_repeats_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`observer_model` defaults to `default_model`, so a mapping keyed by spec would
    have one entry overwrite the other and check nothing."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        data_dir=tmp_path,
        embedder=EmbedderKind.HASHING,
        default_model="anthropic:claude-opus-4-8",
    )

    with pytest.raises(ConfigurationError):
        check_credentials_for(
            settings, answering=False, distillation=True, judging=False, reconciling=False
        )


def test_no_route_is_checked_when_every_seam_is_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fake needs no credential, which is what keeps this suite runnable with no key
    configured at all."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING)

    check_credentials_for(
        settings, answering=False, distillation=False, judging=False, reconciling=False
    )
