"""The shared conformance suite for ``EgressBinder`` (ADR-0152 §13).

Every implementation of :class:`~ai_assistant.core.protocols.EgressBinder` must
pass this suite. ADR-0152 §13 names what the implementing lane owes, clause by
clause; this module's cases are that list, and each docstring quotes the clause it
serves.

**Every refusal is exercised *directly*, against a subject handed inputs no runner
would produce** — which is ADR-0152 §10's clause in terms: "An implementation that
refuses only what the runner would already have refused does not satisfy this
contract." So the calls here bypass selection, the schema check and the request
entirely, exactly as a bypass would.

**The arrangement hooks exist because the face is narrow on purpose.**
``EgressBinder`` has no member that registers a tool, provisions an account or
writes a connection record — a seam that could would be the widening ADR-0152 §10
refuses — so the suite asks the *subject* to arrange those, which in production and
in the fake is the same object under a wider face.

Named ``*_contract`` (not ``test_*``) so pytest collects these only via a
``Test``-prefixed subclass, never the abstract base directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Final

import pytest

from ai_assistant.core.errors import ConnectionStoreError, EgressBindingError
from ai_assistant.core.protocols import EgressBinder
from ai_assistant.core.types import (
    BoundEgressCall,
    CarriedProvenance,
    CostBasis,
    DataTier,
    DiscloserProvenance,
    EgressBinding,
    EgressSpanLocator,
    Idempotency,
    ProvisioningState,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.testing.cancellation import held_at_its_first_await

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.testing.cancellation import SuspendedCall

__all__ = ["EgressBinderContract", "recipients", "tool_declaring"]

#: The connection reference and identity every case arranges unless it says
#: otherwise. The identity is a Tier 1 value and is asserted to appear in **no**
#: refusal message (ADR-0152 §11).
REFERENCE: Final = "conn-0001"
IDENTITY: Final = "work@example.com"
ENDPOINT: Final = "test://endpoint/one"


def recipients(*, tier: str = "personal", protocol: str = "smtp") -> dict[str, FrozenJson]:
    """A well-formed destination-bearing subschema: an array of strings."""
    return {
        "type": "array",
        "items": {"type": "string"},
        "x-egress-destination": protocol,
        "x-egress-tier": tier,
    }


def tool_declaring(
    properties: Mapping[str, FrozenJson], *, tool_id: str = "send_email@work"
) -> ToolDefinition:
    """A high-risk, disclosing tool whose schema statically names ``properties``.

    ``discloses`` is non-empty because ADR-0148 §8's second clause requires it of a
    tool registered at the seam — it makes ADR-0021 §5's floor bite so no send is
    auto-granted. Nothing here is registered anywhere: ``ai_assistant.tools.egress``
    stays approved and undesignated, and these definitions exist only to be bound.
    """
    return ToolDefinition(
        id=tool_id,
        capability="send_email",
        description="Send an email from a connected account to the named recipients.",
        risk_level=RiskLevel.HIGH,
        reversibility=Reversibility.IRREVERSIBLE,
        side_effecting=True,
        reads=(),
        writes=(),
        discloses=(DataTier.PERSONAL,),
        cost=ToolCost(basis=CostBasis.UNKNOWN),
        idempotency=Idempotency.NONE,
        parameters_schema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": dict(properties),
            "additionalProperties": False,
        },
    )


#: The shape every happy-path case binds: recipients, a subject and a body. The
#: two free-text arguments establish no tier, which is ADR-0146 §5's own worked
#: split — "a message body, a note, a subject line" establishes none.
SEND_EMAIL: Final = tool_declaring(
    {
        "to": recipients(),
        "subject": {"type": "string"},
        "body": {"type": "string"},
    }
)

#: A tool bound to no account and declaring neither keyword: ADR-0152 §8's ``None``.
NOT_EGRESS: Final = tool_declaring({"query": {"type": "string"}}, tool_id="recall_memory")


def _no_provenance() -> CarriedProvenance:
    """A carrier over an empty mapping, passed deliberately (ADR-0152 §1)."""
    return CarriedProvenance(spans={})


class EgressBinderContract(ABC):
    """What every ``EgressBinder`` must do (ADR-0152 §1, §3 to §11, §13)."""

    @pytest.fixture
    @abstractmethod
    def binder(self) -> EgressBinder:
        """The subject, holding no tool, no registration and no connection record."""

    # --- the hooks the narrow face cannot supply -----------------------------

    @abstractmethod
    def register(self, binder: EgressBinder, tool: ToolDefinition) -> None:
        """Hold ``tool`` as the registry's untampered original, bound to no account."""

    @abstractmethod
    def register_egress(  # noqa: PLR0913 — one parameter per fact a connection record carries
        self,
        binder: EgressBinder,
        tool: ToolDefinition,
        *,
        reference: str = REFERENCE,
        identity: str = IDENTITY,
        transport_endpoint: str = ENDPOINT,
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Register ``tool`` against a connected account, and record that account."""

    @abstractmethod
    def set_connection(
        self,
        binder: EgressBinder,
        reference: str,
        *,
        identity: str,
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Rewrite the record ``reference`` names, as a provisioning act would."""

    @abstractmethod
    def remove_connection(self, binder: EgressBinder, reference: str) -> None:
        """Drop the record, as a disconnection's removal entry does (ADR-0149 §5)."""

    @abstractmethod
    def fail_next_read(self, binder: EgressBinder) -> None:
        """Arm the subject's connection store to raise ``ConnectionStoreError`` next."""

    @abstractmethod
    def suspend_next_read(self, binder: EgressBinder) -> SuspendedCall:
        """Hold the subject's next connection-record read open (ADR-0152 §10's one await)."""

    @abstractmethod
    def reads(self, binder: EgressBinder) -> tuple[str, ...]:
        """Every connection reference the subject has read, in order."""

    @abstractmethod
    def canonicalising_nothing(self) -> EgressBinder:
        """A subject holding **no** canonicaliser for any protocol.

        ADR-0152 §13 obliges a case for "a ``DestinationProtocol`` the seam holds no
        canonicaliser for", and ADR-0150 §3 admits exactly one protocol today — so
        the case is reachable only against a subject whose canonicaliser set has
        been **narrowed**. Narrowing is not the second canonicaliser ADR-0148 §2's
        sixth clause forbids: nothing here supplies an alternative rule for a
        protocol the seam already canonicalises.
        """

    # --- ADR-0152 §1: the face itself ---------------------------------------

    def test_conforms_to_the_binder_protocol(self, binder: EgressBinder) -> None:
        """ADR-0152 §1: the decorator is stated as a decision, and this is why.

        Without ``@runtime_checkable`` this obligation would *error* rather than
        fail, because ``isinstance`` against a bare ``Protocol`` raises
        ``TypeError``; ``tests/core/test_protocol_triad.py`` reaches every
        Protocol's implementations that way, so the triad could not pass.
        """
        assert isinstance(binder, EgressBinder)

    # --- ADR-0152 §8: the non-egress path -----------------------------------

    async def test_a_non_egress_call_binds_to_none_and_reads_no_record(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §8 and §10: ``None``, and **no** connection record read.

        The whole answer for a call that is not an egress call: no binding, every
        §6 refusal inapplicable, and no reference to name a record with.
        """
        self.register(binder, NOT_EGRESS)

        bound = await binder.bind(
            NOT_EGRESS, parameters={"query": "when is my flight"}, provenance=_no_provenance()
        )

        assert bound is None
        assert self.reads(binder) == ()

    async def test_a_tool_declaring_egress_against_no_account_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §8: mis-registered, and answering ``None`` would discard the declaration.

        The other limb of §8's partition. Exactly one of the two applies to any
        tool with no egress registration whose arguments revalidated, and no tool
        is both returned ``None`` for and refused under that section.
        """
        self.register(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_the_partition_is_exclusive_over_one_unregistered_tool(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §8: no tool is both answered ``None`` and refused.

        Asserted over a *pair* rather than over one call, because the clause is
        about the partition and a case that only exercised one limb would leave the
        exclusivity unpinned.
        """
        self.register(binder, NOT_EGRESS)
        self.register(binder, SEND_EMAIL)

        answered = await binder.bind(
            NOT_EGRESS, parameters={"query": "q"}, provenance=_no_provenance()
        )
        with pytest.raises(EgressBindingError):
            await binder.bind(SEND_EMAIL, parameters={}, provenance=_no_provenance())

        assert answered is None

    # --- ADR-0152 §5: what the derivation produces --------------------------

    async def test_the_binding_covers_every_argument_and_carries_derived_destinations(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0150 §4 and ADR-0152 §5: one span per described value, occurrences computed here.

        The recipient array decomposes to one span per element, each carrying the
        canonical form this seam's own canonicaliser computed — which discharges
        ADR-0150 §11's correspondence check by construction rather than by a
        comparison, since a caller has no route by which to present one that
        disagrees.
        """
        self.register_egress(binder, SEND_EMAIL)

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={
                "to": ["Alice@Example.COM", "bob@example.com"],
                "subject": "s",
                "body": "b",
            },
            provenance=_no_provenance(),
        )

        assert bound is not None
        located = {(span.argument, span.index): span for span in bound.binding.spans}
        assert set(located) == {("body", None), ("subject", None), ("to", 0), ("to", 1)}
        first = located[("to", 0)]
        assert first.destination is not None
        assert first.destination.supplied == "Alice@Example.COM"
        assert first.destination.canonical == "Alice@example.com"
        assert first.tier is DataTier.PERSONAL
        assert located[("body", None)].destination is None
        assert located[("body", None)].tier is None
        assert bound.binding.account.identity == IDENTITY
        assert bound.binding.account.reference == REFERENCE
        assert bound.binding.transport_endpoint == ENDPOINT

    async def test_an_empty_recipient_array_carries_no_span(self, binder: EgressBinder) -> None:
        """ADR-0150 §4: an empty JSON array is described by no span.

        A span for it would have to state an extent and a provenance for a thing
        that does not exist, and ``SYSTEM_SELECTED`` would be a disclosure record
        for nothing disclosed. The binding is still produced: the call selects no
        onward recipient, which is ADR-0148 §2's third clause and not a defect.
        """
        self.register_egress(binder, SEND_EMAIL)

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={"to": [], "subject": "s", "body": "b"},
            provenance=_no_provenance(),
        )

        assert bound is not None
        assert {span.argument for span in bound.binding.spans} == {"subject", "body"}

    async def test_a_supplied_form_with_no_canonical_form_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0148 §1 and ADR-0152 §5: refused, never passed through as its own canonical form."""
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["not an address"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_a_structured_destination_value_naming_two_recipients_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0150 §12 and ADR-0152 §4, §13: the multi-recipient structured span case.

        Refused **rather than described by a binding carrying one of them** — which
        is how §12 states it, over the outcome rather than over which clause
        produced it. Exercised **at the seam**, against a tool whose declaration is
        flat and well-formed: that is the only place it is reachable, now that §4's
        declaration clause refuses the schema that would carry it and ADR-0145
        refuses the value against the schema that survives.
        """
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={
                    "to": {"to": ["alice@example.com", "mallory@example.com"]},
                    "subject": "s",
                    "body": "b",
                },
                provenance=_no_provenance(),
            )

    async def test_a_structured_destination_value_naming_one_recipient_is_also_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §4: the per-call clause is about the *shape*, not the count.

        ADR-0152 §13 says a test asserting that a structured value naming **one**
        recipient is accepted does not reach the case. It is refused too, and this
        is what says so.
        """
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": {"address": "alice@example.com"}, "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    # --- ADR-0152 §6: the undescribed key -----------------------------------

    async def test_an_undescribed_key_is_refused_and_never_rendered(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §6, §11, §13: the live failure path for the ``X-Secret`` shape.

        The test is **authorship, not validity**: a locator is persisted into the
        recorded decision, so it must be text the tool's author wrote. Built
        against a seam that otherwise supplies a binding, and asserting the message
        renders neither the key nor its value — a key is a string a model can write
        as freely as a value, and this seam runs before the request exists.
        """
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(
                SEND_EMAIL,
                parameters={
                    "to": ["alice@example.com"],
                    "subject": "s",
                    "body": "b",
                    "X-Secret": "sk-live-0001",
                },
                provenance=_no_provenance(),
            )

        assert "X-Secret" not in str(raised.value)
        assert "sk-live-0001" not in str(raised.value)

    async def test_a_key_admitted_only_by_additional_properties_is_still_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §6: an open-ended form does not statically name a key.

        ADR-0145 §11 records that a schema omitting ``additionalProperties``
        "permits keys it never described, and those keys travel in an authorised
        payload", so schema validation passes such a call by design. This clause is
        what detects it.
        """
        permissive = ToolDefinition.model_validate(
            SEND_EMAIL.model_dump()
            | {
                "parameters_schema": {
                    "type": "object",
                    "properties": {"to": recipients(), "body": {"type": "string"}},
                    "additionalProperties": {"type": "string"},
                }
            }
        )
        self.register_egress(binder, permissive)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                permissive,
                parameters={"to": ["alice@example.com"], "body": "b", "extra": "v"},
                provenance=_no_provenance(),
            )

    async def test_a_tool_with_no_properties_statically_names_nothing(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §6: it refuses a call carrying any parameter, and not one carrying none.

        Both limbs, because the clause is stated in both directions and a case
        asserting only the refusal would leave the empty call unpinned.
        """
        bare = ToolDefinition.model_validate(
            SEND_EMAIL.model_dump() | {"parameters_schema": {"type": "object"}}
        )
        self.register_egress(binder, bare)

        empty = await binder.bind(bare, parameters={}, provenance=_no_provenance())
        with pytest.raises(EgressBindingError):
            await binder.bind(bare, parameters={"anything": "v"}, provenance=_no_provenance())

        assert empty is not None
        assert empty.binding.spans == ()

    # --- ADR-0152 §3, §4: the declaration -----------------------------------

    @pytest.mark.parametrize(
        "properties",
        [
            pytest.param(
                {"to": {"type": "array", "items": recipients()}, "body": {"type": "string"}},
                id="nested-inside-items",
            ),
            pytest.param(
                {
                    "to": {"type": "string"},
                    "$defs": {"r": recipients()},
                    "body": {"type": "string"},
                },
                id="inside-defs",
            ),
            pytest.param(
                {
                    "to": {"type": "object", "additionalProperties": recipients()},
                    "body": {"type": "string"},
                },
                id="inside-additional-properties",
            ),
            pytest.param(
                {"to": {"anyOf": [recipients()]}, "body": {"type": "string"}},
                id="inside-an-applicator",
            ),
        ],
    )
    async def test_a_keyword_outside_a_top_level_property_is_refused(
        self, binder: EgressBinder, properties: Mapping[str, FrozenJson]
    ) -> None:
        """ADR-0152 §3, §13: refused rather than ignored, in each named position.

        Ignoring it would let an author believe they had declared a recipient
        argument while the seam described a body span — the mis-declaration
        ADR-0148 §2's third clause names, arriving through the mechanism meant to
        prevent it.
        """
        misdeclared = tool_declaring(properties)
        self.register_egress(binder, misdeclared)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                misdeclared,
                parameters={"to": "alice@example.com", "body": "b"},
                provenance=_no_provenance(),
            )

    @pytest.mark.parametrize(
        "properties",
        [
            pytest.param(
                {"to": recipients(protocol="carrier-pigeon")}, id="destination-names-no-member"
            ),
            pytest.param({"to": recipients(tier="platinum")}, id="tier-names-no-member"),
        ],
    )
    async def test_a_keyword_value_naming_no_enum_member_is_refused(
        self, binder: EgressBinder, properties: Mapping[str, FrozenJson]
    ) -> None:
        """ADR-0152 §3, §13: and no lane reads an unrecognised value as "no declaration"."""
        misdeclared = tool_declaring(properties)
        self.register_egress(binder, misdeclared)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                misdeclared, parameters={"to": ["a@example.com"]}, provenance=_no_provenance()
            )

    async def test_a_protocol_with_no_canonicaliser_is_refused(self) -> None:
        """ADR-0152 §3, §13: ADR-0148 §1's third clause, and not a pass-through.

        Against a subject whose canonicaliser set has been narrowed, because
        ADR-0150 §3 admits exactly one protocol and this repository canonicalises
        it — so the refusal is otherwise unreachable rather than absent.
        """
        binder = self.canonicalising_nothing()
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_a_destination_bearing_argument_stating_no_tier_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §3, §13: a description stating none for the destinations under-describes.

        The destinations are what ADR-0148 §8's fourth clause requires the
        confirmation to name, so a span the approver most needs would arrive
        stating nothing about its tier.
        """
        untiered = tool_declaring(
            {"to": {"type": "array", "items": {"type": "string"}, "x-egress-destination": "smtp"}}
        )
        self.register_egress(binder, untiered)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                untiered, parameters={"to": ["a@example.com"]}, provenance=_no_provenance()
            )

    @pytest.mark.parametrize(
        "subschema",
        [
            pytest.param(
                {"type": "object", "x-egress-destination": "smtp", "x-egress-tier": "personal"},
                id="an-object",
            ),
            pytest.param(
                {"x-egress-destination": "smtp", "x-egress-tier": "personal"}, id="no-type"
            ),
            pytest.param(
                {
                    "type": ["string", "null"],
                    "x-egress-destination": "smtp",
                    "x-egress-tier": "personal",
                },
                id="a-union-of-types",
            ),
            pytest.param(
                {
                    "$defs": {"r": {"type": "string"}},
                    "$ref": "#/properties/to/$defs/r",
                    "x-egress-destination": "smtp",
                    "x-egress-tier": "personal",
                },
                id="a-ref",
            ),
            pytest.param(
                {
                    "type": "array",
                    "items": {"type": "object"},
                    "x-egress-destination": "smtp",
                    "x-egress-tier": "personal",
                },
                id="an-array-of-objects",
            ),
        ],
    )
    async def test_a_non_flat_destination_bearing_declaration_is_refused(
        self, binder: EgressBinder, subschema: Mapping[str, FrozenJson]
    ) -> None:
        """ADR-0152 §4, §13: only a string, or an array whose items is a string.

        Refused when the declaration is read, before any call is made — which is
        why each case here binds a call that would otherwise succeed.
        """
        misshapen = tool_declaring({"to": subschema})
        self.register_egress(binder, misshapen)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                misshapen, parameters={"to": "a@example.com"}, provenance=_no_provenance()
            )

    async def test_a_flat_string_destination_argument_is_admitted(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §4: the *other* flat form, so the constraint is not "arrays only"."""
        single = tool_declaring({"to": {"type": "string", **_destination_keywords()}})
        self.register_egress(binder, single)

        bound = await binder.bind(
            single, parameters={"to": "Alice@Example.COM"}, provenance=_no_provenance()
        )

        assert bound is not None
        assert [span.index for span in bound.binding.spans] == [None]
        assert bound.binding.spans[0].destination is not None

    # --- ADR-0152 §6, §8, §10: connectability -------------------------------

    async def test_a_pending_reference_is_refused_and_names_the_reference(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0148 §6, ADR-0152 §6, §11, §13: refused before an ``ActionRequest`` is built.

        The refusal **may** name the connection reference and does — ADR-0149 §3's
        split between a loggable handle and a Tier 1 value — and never names the
        identity.
        """
        self.register_egress(binder, SEND_EMAIL, state=ProvisioningState.PENDING)

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

        assert REFERENCE in str(raised.value)
        assert IDENTITY not in str(raised.value)

    async def test_an_absent_record_is_refused(self, binder: EgressBinder) -> None:
        """ADR-0148 §6: a reference whose record is absent is not connectable either."""
        self.register_egress(binder, SEND_EMAIL)
        self.remove_connection(binder, REFERENCE)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_a_record_going_pending_after_registration_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §13: the case a registration snapshot would have passed.

        "Connectability is read at each of those moments and is never carried over
        from an earlier one" (ADR-0148 §6). A seam that took the state at
        registration time would bind this call happily.
        """
        self.register_egress(binder, SEND_EMAIL)
        self.set_connection(binder, REFERENCE, identity=IDENTITY, state=ProvisioningState.PENDING)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_the_currently_recorded_identity_is_the_one_carried(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §13: an ``ACTIVE`` reference whose identity moved since registration.

        Only the identity moves, which is why only the identity is re-read
        (ADR-0152 §8).
        """
        self.register_egress(binder, SEND_EMAIL)
        self.set_connection(binder, REFERENCE, identity="rotated@example.com")

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
            provenance=_no_provenance(),
        )

        assert bound is not None
        assert bound.binding.account.identity == "rotated@example.com"

    async def test_the_read_budget_is_one_record_per_egress_call(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §10, §13: one read for an egress call, none for a non-egress one.

        Asserted against the subject's own instrumentation rather than by
        inspection, and for ``rebind`` as well as ``bind``.
        """
        self.register_egress(binder, SEND_EMAIL)
        self.register(binder, NOT_EGRESS)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }

        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        await binder.bind(NOT_EGRESS, parameters={"query": "q"}, provenance=_no_provenance())
        await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)
        await binder.rebind(NOT_EGRESS, parameters={"query": "q"}, approved=None)

        assert self.reads(binder) == (REFERENCE, REFERENCE)

    async def test_a_store_outage_raises_rather_than_refusing(self, binder: EgressBinder) -> None:
        """ADR-0152 §9, §13: ``ConnectionStoreError``, never ``EgressBindingError``.

        A store that could not be read asserts nothing about the call: it may be
        perfectly bindable a second later, and the remedy is not a different call.
        Conflating the two writes a falsehood into a returned value and makes
        retryability unreadable.
        """
        self.register_egress(binder, SEND_EMAIL)
        self.fail_next_read(binder)

        with pytest.raises(ConnectionStoreError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    # --- ADR-0152 §1, §5: provenance ----------------------------------------

    async def test_a_named_span_carries_its_origin_and_every_other_is_system_selected(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0146 §2, ADR-0152 §5: carried, never derived, fail-closed default written.

        The default is written by the component building the span rather than
        supplied by a field, which is why
        :attr:`~ai_assistant.core.types.EgressSpan.provenance` has none.
        """
        self.register_egress(binder, SEND_EMAIL)

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
            provenance=CarriedProvenance(
                spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED}
            ),
        )

        assert bound is not None
        located = {(span.argument, span.index): span.provenance for span in bound.binding.spans}
        assert located[("body", None)] is DiscloserProvenance.USER_AUTHORED
        assert located[("subject", None)] is DiscloserProvenance.SYSTEM_SELECTED
        assert located[("to", 0)] is DiscloserProvenance.SYSTEM_SELECTED

    async def test_a_provenance_entry_naming_no_span_is_refused_rather_than_dropped(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §5: a caller and this derivation disagreeing about the payload.

        Refused rather than dropped, because a silent drop is exactly what would
        hide the disagreement. The message names a count and nothing of the
        locator, whose ``argument`` is caller-supplied text (ADR-0152 §11).
        """
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=CarriedProvenance(
                    spans={
                        EgressSpanLocator(argument="attachment"): DiscloserProvenance.USER_AUTHORED
                    }
                ),
            )

        assert "attachment" not in str(raised.value)

    # --- ADR-0152 §1: the registry original and the returned pair -----------

    async def test_a_definition_unequal_to_the_registered_original_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0029 §1 and ADR-0152 §1: the check performed one stage earlier.

        The seam is the only place the caller's definition and an untampered
        original meet before the ruling. It is not a substitute for ``invoke``'s
        own, which still runs.
        """
        self.register_egress(binder, SEND_EMAIL)
        substituted = ToolDefinition.model_validate(
            SEND_EMAIL.model_dump() | {"risk_level": RiskLevel.LOW.value}
        )

        with pytest.raises(EgressBindingError):
            await binder.bind(
                substituted,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=_no_provenance(),
            )

    async def test_the_returned_call_carries_the_tool_and_parameters_it_derived_under(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: three fields, so the caller never reaches for its own objects."""
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }

        bound = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())

        assert isinstance(bound, BoundEgressCall)
        assert bound.tool == SEND_EMAIL
        assert dict(bound.parameters) == {
            "to": ("a@example.com",),
            "subject": "s",
            "body": "b",
        }
        assert set(BoundEgressCall.model_fields) == {"binding", "tool", "parameters"}

    async def test_a_mutation_during_the_read_reaches_neither_the_derivation_nor_the_result(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1, §13: the detachment case, one per validated argument.

        Mutated with ``object.__setattr__`` **while the member is suspended on the
        awaited connection-record read** — the window the detachment exists to
        close. A test that mutated a copy would satisfy nothing, and one that
        mutated before the await would be testing revalidation instead.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {"to": ["a@example.com"], "subject": "s", "body": "b"}
        carrier = CarriedProvenance(
            spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED}
        )
        held = self.suspend_next_read(binder)

        async with held_at_its_first_await(
            held, binder.bind(SEND_EMAIL, parameters=parameters, provenance=carrier)
        ) as task:
            object.__setattr__(SEND_EMAIL, "id", "somebody-else")
            object.__setattr__(carrier, "spans", {})
            parameters["subject"] = "rewritten while the seam was suspended"
        try:
            bound = await task
        finally:
            object.__setattr__(SEND_EMAIL, "id", "send_email@work")

        assert bound is not None
        assert bound.tool.id == "send_email@work"
        located = {(span.argument, span.index): span for span in bound.binding.spans}
        assert located[("body", None)].provenance is DiscloserProvenance.USER_AUTHORED
        assert located[("subject", None)].extent == len("s")
        assert bound.parameters["subject"] == "s"

    # --- ADR-0152 §1: the bypass cases --------------------------------------

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_a_carrier_built_by_model_construct_is_refused_with_a_chained_error(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: chained from the ``ValidationError``, never a bare one.

        Exercised against a tool this seam holds **no** egress registration for as
        well as against a registered one: that is the branch ADR-0152 §8 would
        otherwise answer ``None`` for, so it is where the revalidation ordering is
        actually pinned, and a suite exercising only the egress branch leaves it
        unpinned.
        """
        tool = SEND_EMAIL if registered else NOT_EGRESS
        if registered:
            self.register_egress(binder, tool)
        else:
            self.register(binder, tool)
        forged = CarriedProvenance.model_construct(spans={"body": "hearsay"})

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(tool, parameters={}, provenance=forged)

        assert raised.value.__cause__ is not None
        assert type(raised.value.__cause__).__name__ == "ValidationError"

    async def test_a_carrier_rewritten_after_construction_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: ``object.__setattr__`` defeats ``frozen=True`` (ADR-0018 §3)."""
        self.register(binder, NOT_EGRESS)
        carrier = CarriedProvenance(spans={})
        object.__setattr__(carrier, "spans", {object(): object()})

        with pytest.raises(EgressBindingError):
            await binder.bind(NOT_EGRESS, parameters={}, provenance=carrier)

    async def test_a_tool_built_by_model_construct_is_refused(self, binder: EgressBinder) -> None:
        """ADR-0152 §1: ``model_construct`` is a documented escape hatch, and it is public."""
        forged = ToolDefinition.model_construct(id="", capability="")

        with pytest.raises(EgressBindingError):
            await binder.bind(forged, parameters={}, provenance=_no_provenance())

    async def test_parameters_carrying_a_refused_value_are_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: ``FrozenJsonMapping`` is an alias, and Python enforces no annotation."""
        self.register(binder, NOT_EGRESS)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                NOT_EGRESS,
                parameters={"query": float("nan")},
                provenance=_no_provenance(),
            )

    async def test_an_approved_binding_built_by_model_construct_is_refused(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1, §13: ``rebind``'s arguments, which a ``bind``-only suite leaves untested."""
        self.register_egress(binder, SEND_EMAIL)
        forged = EgressBinding.model_construct(spans="not a tuple", account=None)

        with pytest.raises(EgressBindingError) as raised:
            await binder.rebind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                approved=forged,
            )

        assert raised.value.__cause__ is not None

    # --- ADR-0152 §7: the resuming path -------------------------------------

    async def test_rebind_returns_the_derived_binding_when_it_equals_the_approved_one(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §7: the rebuilt request carries a value this seam produced.

        Never the one read back out of a store, so a tampered trail row cannot
        become the binding a second ruling is taken over.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None

        again = await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

        assert again is not None
        assert again.binding == first.binding
        assert again.binding is not first.binding

    async def test_rebind_refuses_a_forged_canonical_form(self, binder: EgressBinder) -> None:
        """ADR-0150 §12 and ADR-0152 §7, §13: the case ``bind``'s by-construction discharge costs.

        On the deriving path no caller can present an occurrence whose canonical
        form is not what the seam computes. Here one can: a decision read back out
        of the trail carrying a forged occurrence is compared against a freshly
        derived binding, and ``rebind`` refuses before ``resolve`` is reached.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        forged = _with_forged_canonical(first.binding)

        with pytest.raises(EgressBindingError):
            await binder.rebind(SEND_EMAIL, parameters=parameters, approved=forged)

    @pytest.mark.parametrize(
        "field",
        ["extent", "supplied", "identity", "reference", "transport_endpoint"],
    )
    async def test_rebind_refuses_each_single_field_difference(
        self, binder: EgressBinder, field: str
    ) -> None:
        """ADR-0152 §7, §13: ADR-0150 §9's equality is over the whole value.

        One span's extent, one occurrence's supplied form, the account's identity,
        the account's reference and the transport endpoint, each separately — every
        field, because a comparison that missed one would let that field move
        between the question and the answer.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None

        with pytest.raises(EgressBindingError):
            await binder.rebind(
                SEND_EMAIL, parameters=parameters, approved=_differing(first.binding, field)
            )

    async def test_rebind_keeps_a_user_authored_provenance(self, binder: EgressBinder) -> None:
        """ADR-0152 §7, §13: the case a ``rebind`` re-deriving provenance would fail.

        Provenance is a fact about an act that happened before the confirmation was
        parked, plausibly before a restart. A member taking a fresh carrier would
        get an empty one, describe every span as ``SYSTEM_SELECTED`` and refuse
        every resumed call whose user typed anything.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(
            SEND_EMAIL,
            parameters=parameters,
            provenance=CarriedProvenance(
                spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED}
            ),
        )
        assert first is not None

        again = await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

        assert again is not None
        located = {(span.argument, span.index): span.provenance for span in again.binding.spans}
        assert located[("body", None)] is DiscloserProvenance.USER_AUTHORED

    async def test_rebind_refuses_a_reference_that_went_pending_while_parked(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §7, §13: read afresh, never a state read before the user was asked."""
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        self.set_connection(binder, REFERENCE, identity=IDENTITY, state=ProvisioningState.PENDING)

        with pytest.raises(EgressBindingError):
            await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

    async def test_rebind_refuses_an_approved_binding_for_an_unregistered_tool(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §7: the answer to a disagreement is a refusal, not the weaker reading.

        A recorded decision stating an egress call and a registry stating a
        non-egress tool disagree about what was authorised.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        stranded = self.canonicalising_nothing()
        self.register(stranded, NOT_EGRESS)

        with pytest.raises(EgressBindingError):
            await stranded.rebind(NOT_EGRESS, parameters={"query": "q"}, approved=first.binding)

    async def test_rebind_with_no_approved_binding_answers_none_for_a_non_egress_tool(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §7: the same condition ``bind`` states, and no second one."""
        self.register(binder, NOT_EGRESS)

        assert await binder.rebind(NOT_EGRESS, parameters={"query": "q"}, approved=None) is None
        assert self.reads(binder) == ()


def _destination_keywords() -> dict[str, FrozenJson]:
    """The two keywords a destination-bearing argument carries."""
    return {"x-egress-destination": "smtp", "x-egress-tier": "personal"}


def _with_forged_canonical(binding: EgressBinding) -> EgressBinding:
    """``binding`` with one occurrence's canonical form replaced by a lie."""
    dumped = binding.model_dump()
    for span in dumped["spans"]:
        if span["destination"] is not None:
            span["destination"]["canonical"] = "mallory@example.com"
            break
    return EgressBinding.model_validate(dumped)


def _differing(binding: EgressBinding, field: str) -> EgressBinding:
    """``binding`` with exactly one field moved, for the equality cases."""
    dumped = binding.model_dump()
    if field == "extent":
        dumped["spans"][0]["extent"] += 1
    elif field == "supplied":
        for span in dumped["spans"]:
            if span["destination"] is not None:
                span["destination"]["supplied"] = "b@example.com"
                span["destination"]["canonical"] = "b@example.com"
                break
    elif field == "transport_endpoint":
        dumped["transport_endpoint"] = "test://endpoint/other"
    else:
        dumped["account"][field] = f"other-{dumped['account'][field]}"
    return EgressBinding.model_validate(dumped)
