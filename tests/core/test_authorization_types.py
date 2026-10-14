"""What of ADR-0254's `core` vocabulary outlives the goal authorizations.

ADR-0309 §5 deletes the old path, and with it the goal-authorization Protocols, their
contract suites and their canonical fakes. The row family those Protocols stored —
``Authorization``, ``CoverageMember``, ``AuthorizationBasis``, ``ValueResolution`` and
their vocabularies — left ``core`` with them, and so did the bound a user could state
(``BoundKind``, ``ValueBound``) and the request's ``goal``, which nothing held once the
family went.

What stays is pinned here, each value built locally rather than from a fake that no
longer exists: the tool declaration's own refusal (``system_supplied``), the one
canonical encoding, and ``Settings``' absence of any authorization field.
"""

from __future__ import annotations

from typing import Final

import pytest
from pydantic import ValidationError

from ai_assistant.core.config import Settings
from ai_assistant.core.types import (
    CapabilityEffect,
    CapabilityResult,
    CostBasis,
    DataTier,
    Idempotency,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    canonical_json_bytes,
)

#: A declaration that classifies nothing system-supplied and declares no bounded
#: argument, so a case about either field raises it on a copy of this.
TOOL: Final = ToolDefinition(
    id="book_site",
    capability="book_site",
    description="Book a pitch at a campsite through the connected account.",
    risk_level=RiskLevel.LOW,
    reversibility=Reversibility.REVERSIBLE,
    side_effecting=True,
    reads=(),
    writes=(),
    discloses=(DataTier.PERSONAL,),
    cost=ToolCost(basis=CostBasis.FREE),
    idempotency=Idempotency.NONE,
    effect=CapabilityEffect.WORLD,
    leaves_hub=True,
    result=CapabilityResult.NO_OUTSIDE_TEXT,
    outcome_can_be_unknown=True,
    safe_to_repeat=False,
)


# --- §3, §7: what the declaration carries -------------------------------------


def test_a_declaration_classifies_nothing_system_supplied_by_default() -> None:
    """§3: the empty tuple makes the **opposite** claim to the one ADR-0016 §1 refuses.

    An unclassified argument is **user-facing**, so a declaration that says nothing
    needs coverage for every argument and asks where it has none: *"It costs a
    question and can never authorise a call"*.
    """
    assert TOOL.system_supplied == ()
    assert ToolDefinition.model_fields["system_supplied"].default == ()


def test_a_declaration_classifies_each_key_system_supplied_once() -> None:
    """§3: duplicate-free — *"a duplicate is a second spelling of one classification"*."""
    with pytest.raises(ValidationError, match="each key system-supplied once"):
        ToolDefinition.model_validate(
            {**TOOL.model_dump(), "system_supplied": ("locale", "locale")}
        )


# --- §3: one canonical encoding, and it is the digest's ----------------------


def test_the_fixed_value_comparison_reads_the_encoding_the_digest_is_taken_over() -> None:
    """§3: *"there is one canonical form in this system and not a second"* (arm 7).

    ``==`` on the values will not do, and this is why: Python compares ``1`` equal
    to ``1.0`` and ``True`` equal to ``1``, while their canonical encodings differ —
    so a comparison over ``==`` would cover a call the user's act did not.
    """
    one: object = 1
    assert one == 1.0
    assert canonical_json_bytes(1) != canonical_json_bytes(1.0)
    assert one == True  # noqa: E712 — the loose comparison is the point
    assert canonical_json_bytes(True) != canonical_json_bytes(1)
    assert canonical_json_bytes("60") != canonical_json_bytes(60)


# --- §12, ADR-0256 §2: Settings gains nothing --------------------------------


def test_settings_carries_no_authorization_field_at_all() -> None:
    """§12 and ADR-0256 §2, arm 69's ``Settings`` limb, in ADR-0178 §10's shape.

    *"No field is added, no default about an authorization is minted, no ceiling is
    placed on rung 1 or rung 2, and there is **no sentinel, no 'forever' spelling
    and no disable spelling**."* ADR-0254 §20's *"no ``Settings`` field at all"*
    binds every implementing lane unchanged.

    The one deployment value ADR-0256 §1's rung 3 reads is ``episode_retention``,
    which ADR-0074 §7 already owns — it is read by ``orchestration`` at the write
    and by no store, no policy and no trail.
    """
    named = {
        name
        for name in Settings.model_fields
        if any(word in name for word in ("authoriz", "authoris"))
    }
    assert named == set(), named
    assert "episode_retention" in Settings.model_fields
