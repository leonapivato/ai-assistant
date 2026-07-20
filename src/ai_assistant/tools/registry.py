"""An in-memory :class:`~ai_assistant.core.protocols.ToolRegistry` (ADR-0016).

The registry holds declarations, answers questions about them, and ranks
nothing. Population is deliberately *not* on the Protocol — :meth:`register`
and :meth:`deregister` are this class's own API, because nothing outside
`tools` has business owning the registration lifecycle, and because binding a
callable at registration later must not become a breaking contract change
(ADR-0016 §5).

In-memory only, rebuilt from scratch each run. A ``ToolDefinition`` is Tier 2
configuration declared by code, not personal data, so there is no export or
delete obligation here as there is for ``MemoryStore`` and ``PlanStore``
(ADR-0016 §6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_assistant.core.errors import ToolRegistrationError
from ai_assistant.core.types import ToolDefinition

if TYPE_CHECKING:
    from collections.abc import Iterable


def _revalidated(tool: ToolDefinition) -> ToolDefinition:
    """Rebuild ``tool`` through validation, detached from the caller's instance.

    A definition can reach here in a state the type would refuse to construct,
    because ``frozen=True`` does not stop ``__dict__`` writes. Copying would
    preserve that state; round-tripping rejects it.

    **This is validation, not authentication.** It answers "could this have been
    constructed?", never "is this what the author declared?" — so a definition
    tampered into a *still-valid* state passes. See the class docstring.

    Raises:
        ValidationError: If the incoming definition violates the type's rules.
    """
    return ToolDefinition.model_validate(tool.model_dump())


class InMemoryToolRegistry:
    """A tool registry backed by a dict, structurally a ``ToolRegistry``.

    Ids are **spent on first use**: once an id has been registered it is bound
    to that definition for the life of this registry, and deregistering does not
    free it. See :meth:`register`.

    Definitions are **re-validated** on the way in and copied on the way out.
    That is not redundant with ``frozen=True``, for the reason ADR-0014 gives
    about stored plans: freezing refuses ``tool.risk_level = ...`` but not
    ``tool.__dict__["risk_level"] = ...``. Since that bypass is part of the
    threat model here — tool metadata is a security control — it has to be
    closed on both sides. Copying alone would preserve whatever state the object
    arrived in, so a definition mutated *before* registration (say
    ``side_effecting`` flipped to ``False`` while ``discloses`` stays non-empty)
    would be stored as authoritative despite being one the type would refuse to
    construct. Round-tripping through validation rebuilds it under the same
    rules, as ``FakePlanStore`` does for a step transition. Re-validation is the
    current strategy for ADR-0018 §4's postcondition — *what is stored is valid
    and detached* — rather than the postcondition itself; a trusted minting
    factory would satisfy it too.

    **What this does not catch.** Re-validation only rejects definitions that
    could not have been constructed. A definition tampered into a still-valid
    state — ``risk_level`` moved from ``CRITICAL`` to ``LOW`` — rebuilds
    successfully, because ``LOW`` is valid and this registry holds no trusted
    original to compare against. Such a definition is refused only when its id
    is *already bound* to a different one, which is the conflict rule below, not
    this. **Under a fresh id it is accepted, and nothing here detects it.**
    Closing that needs a provenance boundary — a signature, a minting factory,
    or the pinned digest issue #54 proposes for the approval path — which this
    contract does not provide (ADR-0018 §4).

    **Not thread-safe, by design.** The system composes on one event loop
    (CONTRIBUTING, "Async for all I/O"), and :meth:`register`/:meth:`deregister`
    are synchronous with no ``await`` inside, so they cannot interleave with the
    async queries on that loop. Registration from several OS threads would race
    the spent-id check against the write; a host that wants that must serialise
    it, and a lock here would otherwise be cost with no reader.
    """

    def __init__(self, tools: Iterable[ToolDefinition] = ()) -> None:
        """Create a registry, optionally registering ``tools`` in order.

        Args:
            tools: Definitions to register immediately, as a convenience for
                composition roots that know the full set up front.

        Raises:
            ToolRegistrationError: If ``tools`` contains two definitions sharing
                an id.
        """
        self._live: dict[str, ToolDefinition] = {}
        self._spent: dict[str, ToolDefinition] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        """Bind ``tool`` to its id, permanently.

        Re-registering the *same* definition under a live id is idempotent, so
        a composition root may run twice without special-casing. Anything else
        is refused:

        - a **different** definition under a used id would silently rewrite a
          security control — swapping ``risk_level=CRITICAL`` for ``LOW`` under
          an id a policy already trusts;
        - **any** registration under a *deregistered* id is refused too, even an
          identical one. Deregistration is revocation, not renaming. Were an id
          reusable, it could be rebound between a permission decision and the
          step that executes it: the user approves a ``REVERSIBLE`` send, an
          ``IRREVERSIBLE`` definition takes the name, and both the
          ``approval_ref`` and the ``bound_tool`` id still read as consistent.

        Raises:
            ToolRegistrationError: If the id is already bound to a different
                definition, or has been deregistered.
            ValidationError: If the definition violates the type's own rules,
                which a ``__dict__`` write can leave it doing.
        """
        validated = _revalidated(tool)

        previous = self._spent.get(validated.id)
        if previous is None:
            self._live[validated.id] = validated
            self._spent[validated.id] = validated
            return

        if validated.id not in self._live:
            msg = (
                f"tool id {validated.id!r} was deregistered and cannot be reused: "
                "deregistration is revocation, so a definition rebound to a spent id "
                "could be substituted for the one a permission decision approved"
            )
            raise ToolRegistrationError(msg)

        if previous != validated:
            msg = (
                f"tool id {validated.id!r} is already registered with a different definition; "
                "tool metadata is a security control, so it cannot be overwritten in place"
            )
            raise ToolRegistrationError(msg)

    def deregister(self, tool_id: str) -> bool:
        """Revoke a tool, spending its id for good.

        Returns:
            ``True`` if a live tool was removed, ``False`` if none had that id
            (including an id already deregistered).
        """
        return self._live.pop(tool_id, None) is not None

    async def get(self, tool_id: str) -> ToolDefinition | None:
        """Return the definition registered as ``tool_id``, or ``None``."""
        stored = self._live.get(tool_id)
        return None if stored is None else stored.model_copy(deep=True)

    async def find(self, capability: str) -> list[ToolDefinition]:
        """Return every live tool advertising ``capability``, ordered by id."""
        return [
            tool.model_copy(deep=True)
            for tool in sorted(self._live.values(), key=lambda tool: tool.id)
            if tool.capability == capability
        ]

    async def capabilities(self) -> tuple[str, ...]:
        """Return the advertised capability vocabulary, sorted and de-duplicated."""
        return tuple(sorted({tool.capability for tool in self._live.values()}))

    async def all_tools(self) -> list[ToolDefinition]:
        """Return every live definition, ordered by id."""
        return [
            tool.model_copy(deep=True)
            for tool in sorted(self._live.values(), key=lambda tool: tool.id)
        ]
