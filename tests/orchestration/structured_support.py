"""The structured seam for suites that script a stage's replies as text (ADR-0354 §9:1).

The digest, the observer, the matters pass and the tidy-up each ask for their reply as a
shape through a ``StructuredCompleter``. A suite that scripts the reply's text through a
:class:`~ai_assistant.testing.FakeModelProvider` hands the stage that provider seen as
the seam (:class:`~understanding_support.TextAsStructured`): each call is the provider's
completion, its reply read by ``core``'s one rule with the shape, so the suite reads what
the stage sent from the provider. A suite of the seam's own returned failures uses the
canonical :class:`~ai_assistant.testing.FakeStructuredCompleter` instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from understanding_support import TextAsStructured

from ai_assistant.core.protocols import StructuredCompleter

if TYPE_CHECKING:
    from ai_assistant.core.protocols import ModelProvider


def structured(model: ModelProvider | StructuredCompleter) -> StructuredCompleter:
    """``model`` as the structured seam: itself where it is one, else its completions."""
    if isinstance(model, StructuredCompleter):
        return model
    return TextAsStructured(model)
