"""The judge is an instrument, so its route is a choice a run records.

``build_grader`` pinned the judge to ``settings.default_model``, which made the judge
and the system under test the same model by construction. Nothing said so: the manifest
recorded ``answer_route`` and ``judge`` separately and they simply always agreed, so a
reader could not tell a deliberate self-judgement from a default nobody had considered.
Pilot 4 grades on a different model, and these pin the three properties that makes
safe — the default does not move, the route reaches the manifest through the grader
that graded, and the credential check follows the route rather than the default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from benchmarks.memory.grade import MODEL_JUDGE_PREFIX, ExactGrader, ModelGrader
from benchmarks.memory.run import build_grader, check_credentials_for

from ai_assistant.core.config import EmbedderKind, Settings
from ai_assistant.core.errors import ConfigurationError

if TYPE_CHECKING:
    from pathlib import Path

DEFAULT_ROUTE = "anthropic:claude-answering-x"
JUDGE_ROUTE = "anthropic:claude-judging-y"


def _settings(tmp_path: Path) -> Settings:
    """Settings naming a distinguishable answering route.

    Args:
        tmp_path: The test's directory.

    Returns:
        The settings.
    """
    return Settings(data_dir=tmp_path, embedder=EmbedderKind.HASHING, default_model=DEFAULT_ROUTE)


def test_the_judge_route_defaults_to_the_answering_route(tmp_path: Path) -> None:
    """The behaviour before the option existed, kept exactly.

    Asserted because the option's whole safety argument is that omitting it changes
    nothing: pilot 4 is a re-run under a new registration, and a default that moved
    would make every earlier manifest incomparable for a reason nobody chose.
    """
    judge = build_grader(_settings(tmp_path), kind="model")

    assert isinstance(judge, ModelGrader)
    assert judge.name == f"{MODEL_JUDGE_PREFIX}{DEFAULT_ROUTE}"


def test_an_explicit_judge_route_is_the_one_recorded(tmp_path: Path) -> None:
    """`Grader.name` is what the manifest's `judge` field takes, so this *is* the record.

    The assertion is on the name rather than on a private attribute deliberately: the
    manifest reads exactly this, so a route that were held but not reported would pass
    a test on the attribute and still leave the artifacts wrong.
    """
    judge = build_grader(_settings(tmp_path), kind="model", route=JUDGE_ROUTE)

    assert isinstance(judge, ModelGrader)
    assert judge.name == f"{MODEL_JUDGE_PREFIX}{JUDGE_ROUTE}"
    assert DEFAULT_ROUTE not in judge.name


def test_the_exact_grader_ignores_a_judge_route(tmp_path: Path) -> None:
    """It makes no model call, so a route is not a thing it could be wrong about."""
    judge = build_grader(_settings(tmp_path), kind="exact", route=JUDGE_ROUTE)

    assert isinstance(judge, ExactGrader)
    assert judge.name == "exact"


def test_an_unknown_grader_kind_is_still_refused(tmp_path: Path) -> None:
    """The new parameter did not widen what `kind` accepts."""
    with pytest.raises(ValueError, match="unknown grader"):
        build_grader(_settings(tmp_path), kind="llm", route=JUDGE_ROUTE)


def test_the_credential_check_follows_the_judge_route(tmp_path: Path) -> None:
    """The check ran on `default_model` for the judge, which a chosen route makes wrong.

    An unresolvable vendor is the cheapest failure to provoke and the one this check
    exists for: it fires before a store is opened or a corpus is fetched, so a judge
    route naming a vendor nobody installed stops the run in a second rather than at the
    first graded answer of a paid one. The answering route is left resolvable so the
    failure can only have come from the judge's.
    """
    settings = Settings(
        data_dir=tmp_path, embedder=EmbedderKind.HASHING, default_model=DEFAULT_ROUTE
    )

    with pytest.raises(ConfigurationError):
        check_credentials_for(
            settings,
            answering=False,
            distillation=False,
            judging=True,
            judge_route="nosuchvendor:model-z",
        )
