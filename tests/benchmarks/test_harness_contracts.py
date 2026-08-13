"""The three places the harness copies or mirrors something the package owns.

Each of them is a silent-staleness hazard: a literal that stops matching, a limit that
stops tracking the composition root, a refusal that stops being enforced. None is
caught by a type check, so each has a test.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from benchmarks.memory import records
from benchmarks.memory.corpora.fetch import CorpusFetchError, cached_path, digest_of, ensure_file
from benchmarks.memory.corpora.provenance import CorpusFile
from benchmarks.memory.records import RunMode
from benchmarks.memory.run import PREREGISTRATION_REFUSAL, refuse_unconfirmed_scored_run
from benchmarks.memory.wiring import build_harness

if TYPE_CHECKING:
    from pathlib import Path

from ai_assistant.app import composition
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.memory import traces as memory_traces
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


def test_a_smoke_run_needs_no_confirmation() -> None:
    refuse_unconfirmed_scored_run(RunMode.SMOKE, preregistration_final=False)


def test_a_scored_run_is_refused_without_confirmation() -> None:
    """#1029's ground rule 1, made a refusal rather than an understanding."""
    with pytest.raises(PermissionError) as caught:
        refuse_unconfirmed_scored_run(RunMode.SCORED, preregistration_final=False)

    assert str(caught.value) == PREREGISTRATION_REFUSAL
    assert "#1029" in PREREGISTRATION_REFUSAL


def test_a_confirmed_scored_run_is_allowed() -> None:
    refuse_unconfirmed_scored_run(RunMode.SCORED, preregistration_final=True)


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
