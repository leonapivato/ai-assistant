"""Transport-level suspension for ``PydanticAIProvider``'s input-observation case.

A direct provider suspends on its **transport**, not on an inner ``ModelProvider``
(ADR-0069 §3). ``PydanticAIProvider.complete``'s only ``await`` is
``self._agent.run``, and it renders the conversation into pydantic-ai's
``ModelMessage`` list on its first executed line — taking its one observation —
*before* that await. So the shared conformance case is served by stubbing the
agent's ``run`` to record the rendered conversation, suspend there at that first
await, and answer with :func:`~model_provider_contract.encode_conversation` of the
one observation it took, so the reply names the version it rests on.

Shared by the ``TestModel``-backed provider suite (``test_provider.py``) and the
real-vendor-stack suite (``test_provider_vendors.py``), which are both
``PydanticAIProvider`` bindings whose input observation is identical and
vendor-independent — it happens before the wire.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from model_provider_contract import encode_conversation

from ai_assistant.core.types import Role

if TYPE_CHECKING:
    from model_provider_contract import ConversationLog, FirstAwaitGate
    from pydantic_ai.messages import ModelMessage

    from ai_assistant.models import PydanticAIProvider

#: Which conversation role each rendered pydantic-ai part came from, so the
#: transport records the same (role, content, name) turn identity the wrapper
#: recorder does — a single direct-provider observation cannot tear across
#: attempts, but the log format must still match for the shared assertions.
_PART_ROLE = {
    "SystemPromptPart": Role.SYSTEM,
    "UserPromptPart": Role.USER,
    "TextPart": Role.ASSISTANT,
}


def _fingerprint_of(history: list[ModelMessage]) -> tuple[tuple[Role, str, str | None], ...]:
    """The turn identities ``PydanticAIProvider`` rendered its conversation into.

    Read back off the rendered ``ModelMessage`` history, mapping each part to the
    role it came from, so the transport records in the same (role, content, name)
    space the recorder-backed wrappers use. Name is unrepresented in the rendered
    parts and is ``None`` here, matching the wrapper turns the case builds.
    """
    return tuple(
        (_PART_ROLE[type(part).__name__], content, None)
        for message in history
        for part in message.parts
        if type(part).__name__ in _PART_ROLE
        and isinstance(content := getattr(part, "content", None), str)
    )


def suspend_the_transport(
    provider: PydanticAIProvider, log: ConversationLog, gate: FirstAwaitGate
) -> None:
    """Stub ``provider``'s agent so its next ``complete`` suspends at its first await.

    Records the rendered conversation into ``log``, holds at ``gate`` (the
    method's first and only suspension point), then answers with the encoded
    observation. The provider is expected to be discarded after the scenario, so
    nothing is restored.
    """

    async def suspending_run(
        *, message_history: list[ModelMessage], **_kwargs: object
    ) -> SimpleNamespace:
        observed = _fingerprint_of(message_history)
        log.record(observed)
        await gate.hold()
        return SimpleNamespace(output=encode_conversation(tuple(c for _r, c, _n in observed)))

    provider._agent.run = suspending_run  # type: ignore[assignment]
