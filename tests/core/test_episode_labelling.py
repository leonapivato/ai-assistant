"""ADR-0239's `core` surface: the labelling value, and what an outcome refuses.

§9 fixes the change exactly — `core/types.py` gains
:class:`~ai_assistant.core.types.EpisodeLabelling`, and
:class:`~ai_assistant.core.types.ObservationOutcome` gains ``labellings``
together with §2's per-episode uniqueness validator — so what is pinned here is
that surface and its edges: the canonical form on **both** axes, the empty
default that §6 reads as "no label was recorded", the additive member that leaves
every existing outcome constructible, the duplicate an outcome refuses at
construction, and the two things this type deliberately does **not** check.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_assistant.core import protocols
from ai_assistant.core.types import (
    MAX_TOPIC_LABEL_LENGTH,
    MAX_TOPICS_PER_PROPOSAL,
    EpisodeLabelling,
    ObservationOutcome,
)

# --- the labelling itself (ADR-0239 §2, §4) ---------------------------------


def test_a_labelling_defaults_to_no_label_on_either_axis() -> None:
    """Empty is the ordinary state and states that nothing was recorded (§6).

    Neither axis says the episode is about nothing or involved nobody, and neither
    says it is about everything or involved everyone — which is why the default is
    the empty tuple and not a sentinel a consumer could read either way.
    """
    labelling = EpisodeLabelling(episode_id="conv:c1:1")

    assert labelling.topics == ()
    assert labelling.participants == ()


def test_a_labelling_carries_both_axes_independently() -> None:
    """An episode may carry either, both or neither, and one is no evidence about the other.

    ADR-0213 §14's third clause read across to the second axis: the two are never
    read for each other, so a labelling admissible on one and empty on the other is
    an ordinary value rather than a half-formed one (§5).
    """
    topics_only = EpisodeLabelling(episode_id="conv:c1:1", topics=("house renovation",))
    people_only = EpisodeLabelling(episode_id="conv:c1:2", participants=("alex",))

    assert topics_only.topics == ("house renovation",)
    assert topics_only.participants == ()
    assert people_only.topics == ()
    assert people_only.participants == ("alex",)


def test_a_labelling_is_frozen() -> None:
    """It reports what a pass proposed, so it must not be editable after the fact."""
    labelling = EpisodeLabelling(episode_id="conv:c1:1", topics=("health",))

    with pytest.raises(ValidationError):
        labelling.topics = ("money",)


@pytest.mark.parametrize(
    "label",
    [
        "Alex",
        " alex",
        "alex ",
        "alex  chen",
        "alex\tchen",
        # U+00A0: whitespace that survives ``casefold()`` and is not U+0020, so a
        # form checked against a remembered list of characters would admit it.
        "alex\u00a0chen",
        "",
        "a" * (MAX_TOPIC_LABEL_LENGTH + 1),
    ],
)
def test_a_participant_label_takes_the_same_canonical_form_as_a_topic(label: str) -> None:
    """§4's second clause: the participant axis is ADR-0213 §3's form, exactly.

    Refused rather than folded, and refused on the *participant* axis specifically,
    because that is the clause this decision adds. "Alex" is the representative
    input §10 names: the value is judged as it stands, and nothing case-folds,
    strips or otherwise repairs it on the way to a label. A second canonical form
    would have been a second rule to keep in step, and this is the assertion that
    there is only one.
    """
    with pytest.raises(ValidationError):
        EpisodeLabelling(episode_id="conv:c1:1", participants=(label,))

    with pytest.raises(ValidationError):
        EpisodeLabelling(episode_id="conv:c1:1", topics=(label,))


def test_a_labelling_does_not_bound_an_axis_or_order_it() -> None:
    """§4's bound and code-point order are the producer's judgement, not this type's.

    §5 rules that an axis breaking either is **ignored** — no labels on that axis,
    the other standing, no counter moving — which is a decision made before a
    labelling exists. A bound here would turn a producer's own miss into a
    ``ValidationError`` its caller cannot act on, and would put the belief-trading
    ADR-0213 §4 refuses one seam further out. The check lives in the producer
    (``learning.observer._topics``) and in the canonical fake's script, and both
    are pinned there.

    This is the same placement ADR-0213 §1 gives ``MAX_TOPICS_PER_RECORD``, for a
    different reason: there the bound is off the type because a later ADR will
    raise it and a stored record would stop decoding; here it is off the type
    because the rule that reads it is "ignore", not "refuse".
    """
    over_bound = EpisodeLabelling(
        episode_id="conv:c1:1",
        topics=tuple(f"topic {index}" for index in range(MAX_TOPICS_PER_PROPOSAL + 1)),
    )
    unordered = EpisodeLabelling(episode_id="conv:c1:2", participants=("bob", "alex"))

    assert len(over_bound.topics) == MAX_TOPICS_PER_PROPOSAL + 1
    assert unordered.participants == ("bob", "alex")


# --- the outcome's new member (ADR-0239 §2, §9) ------------------------------


def test_an_outcome_carries_no_labelling_by_default() -> None:
    """The member is additive, so every outcome written before ADR-0239 still holds.

    A response carrying no labelling key at all is a **normal** outcome (§5): it
    leaves the episodes unlabelled, is not an error and is not reported as
    degradation.
    """
    assert ObservationOutcome().labellings == ()


def test_an_outcome_refuses_two_labellings_for_one_episode() -> None:
    """§2's validator: no seam value names one episode twice.

    Without it a conforming outcome could carry the ambiguity all the way to the
    writing stage, which would then have to choose between an atomic batch holding
    duplicate ids and a sequence whose result depends on response order — two
    undefined behaviours where the decision needs one. The message names the
    episode so the producer can see which entry it emitted twice.
    """
    first = EpisodeLabelling(episode_id="conv:c1:1", topics=("health",))
    second = EpisodeLabelling(episode_id="conv:c1:1", topics=("money",))

    with pytest.raises(ValidationError, match=r"at most one labelling per episode"):
        ObservationOutcome(labellings=(first, second))


def test_an_outcome_carries_one_labelling_per_distinct_episode() -> None:
    """The uniqueness rule is about equal ids and constrains nothing else.

    Two episodes filed under the very same words are two ordinary labellings: the
    axes are not a key, and equality of labels relates nothing (ADR-0213 §3,
    ADR-0239 §4).
    """
    outcome = ObservationOutcome(
        labellings=(
            EpisodeLabelling(episode_id="conv:c1:1", topics=("health",)),
            EpisodeLabelling(episode_id="conv:c1:2", topics=("health",)),
        )
    )

    assert [labelling.episode_id for labelling in outcome.labellings] == [
        "conv:c1:1",
        "conv:c1:2",
    ]


def test_no_counter_moves_for_a_labelling() -> None:
    """§2's counts are untouched and no third counter is added (§5).

    A labelling is not an entry of the proposal population, an ignored labelling is
    not a discard, and a labelling the caller declines to write is not one either —
    so ``len(proposals) + discarded_unusable + discarded_over_limit`` keeps exactly
    the meaning ADR-0077 §4 gives it. Asserted over the *fields* rather than over
    one instance's values, because what would break the invariant is a member
    someone adds later.
    """
    outcome = ObservationOutcome(
        labellings=(EpisodeLabelling(episode_id="conv:c1:1", topics=("health",)),)
    )

    assert outcome.discarded_unusable == 0
    assert outcome.discarded_over_limit == 0
    assert set(ObservationOutcome.model_fields) == {
        "proposals",
        "discarded_unusable",
        "discarded_over_limit",
        "labellings",
    }


# --- the surface this decision does not touch (ADR-0239 §9) ------------------


def test_the_contract_surface_is_the_outcome_alone() -> None:
    """`core/protocols.py` gains nothing and changes nothing (§9).

    The labelling reaches its caller through the value ``observe`` already
    returns, so ``Observer.observe``'s signature is untouched, no ``MemoryStore``
    member is added or widened, and no other Protocol is touched. Pinned as the
    absence of a name rather than as a diff, because the failure this guards
    against is a lane adding a member here and calling it ADR-0239's.
    """
    assert not hasattr(protocols, "EpisodeLabelling")
    assert "labelling" not in protocols.Observer.observe.__doc__.lower()  # type: ignore[union-attr]
