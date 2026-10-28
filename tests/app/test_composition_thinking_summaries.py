"""ADR-0355 §2:3-§2:5, §8:2: which routes the root builds to keep a thinking summary.

The routed provider understanding and the digest reach through, and the observer's scout
and commit routes, keep a structured call's summary exactly where the record is on;
consolidation's route, which the matters pass and the tidy-up ride, and the reconciler's
keep none either way, because none of those consumers writes a returned entry.

None of these calls a model: ``PydanticAIProvider`` defers model resolution to the
first completion. The reach-ins are this directory's deliberate idiom (see
``test_composition_provider.py``): the obligation is about which object ends up where,
and no public surface exposes that.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ai_assistant.app import build_engine
from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.memory import MemoryIngestor, ModelBackedReconciler
from ai_assistant.models import PydanticAIProvider, RetryingProvider, RoutingProvider

if TYPE_CHECKING:
    from pathlib import Path

    from ai_assistant.orchestration import Engine


def _inner(route: object) -> PydanticAIProvider:
    """The one provider a single-route retrying wrapper is built over."""
    assert isinstance(route, RetryingProvider)
    inner = route._inner
    assert type(inner) is PydanticAIProvider
    return inner


def _routes(routed: object) -> list[PydanticAIProvider]:
    """Every route's provider behind the router, in preference order."""
    assert isinstance(routed, RoutingProvider)
    return [_inner(one.provider) for one in routed._routes]


def _keeps(engine: Engine) -> dict[str, list[bool]]:
    """Whether each consumer's providers keep a structured call's summary, by consumer."""
    understanding = engine._understanding
    phases = engine._phases
    observer = engine._observer
    matters_pass = engine._matters_pass
    assert understanding is not None
    assert phases is not None
    assert observer is not None
    assert matters_pass is not None
    story_calls = phases._story_calls
    assert story_calls is not None
    assert story_calls._tidy_up is not None
    writer = observer._writer._writes._writer
    assert isinstance(writer, MemoryIngestor)
    reconciler = writer._reconciler
    assert isinstance(reconciler, ModelBackedReconciler)
    held = {
        "understanding": _routes(understanding._model),
        "digesting": _routes(phases._digesting._provider),
        "observer.scout": [_inner(observer._scout)],
        "observer.commit": [_inner(observer._commit)],
        "matters_pass": [_inner(matters_pass._model)],
        "story_tidy_up": [_inner(story_calls._tidy_up._model)],
        "reconciler": [_inner(reconciler._completer)],
    }
    return {name: [one._thinking_summaries for one in built] for name, built in held.items()}


#: The consumers that write a returned entry for every structured call (ADR-0355 §6).
_WRITING = frozenset(
    {"understanding", "digesting", "observer.scout", "observer.commit"},
)


@pytest.mark.parametrize("record", [True, False], ids=["record-on", "record-off"])
async def test_only_the_routes_whose_consumers_write_entries_keep_a_summary_where_the_record_is_on(
    tmp_path: Path, record: bool
) -> None:
    """§2:3, §2:4, §8:2: on with the record, every route of the four; off for the rest."""
    settings = Settings(
        embedder=EmbedderKind.HASHING,
        diagnostic_record=record,
        default_model="anthropic:claude-x",
        fallback_models=("openai:gpt-5",),
        consolidation_model="anthropic:claude-consolidation",
        reconciler_model="anthropic:claude-reconciler",
        observer_scout_model="anthropic:claude-scout",
        observer_commit_model="anthropic:claude-commit",
    )
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        keeps = _keeps(engine)
    finally:
        await engine.aclose()

    assert keeps == {
        "understanding": [record, record],
        "digesting": [record, record],
        "observer.scout": [record],
        "observer.commit": [record],
        "matters_pass": [False],
        "story_tidy_up": [False],
        "reconciler": [False],
    }


async def test_no_consumer_writing_no_entry_is_handed_a_route_that_keeps_one(
    tmp_path: Path,
) -> None:
    """§2:5: with every spec left to ``default_model``, the routes are still apart.

    Consolidation's, the reconciler's and the observer's routes all name the default model
    when unset, so a root that shared one provider object between them would hand a
    summaries-on route to the matters pass, the tidy-up or the reconciler.
    """
    settings = Settings(embedder=EmbedderKind.HASHING, diagnostic_record=True)
    engine = build_engine(settings, data_dir=tmp_path)
    try:
        keeps = _keeps(engine)
    finally:
        await engine.aclose()

    on = {name for name, built in keeps.items() if any(built)}
    assert on == _WRITING
    assert all(all(built) for name, built in keeps.items() if name in _WRITING)
