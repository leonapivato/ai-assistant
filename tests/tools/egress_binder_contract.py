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
from typing import TYPE_CHECKING, Any, Final

import pytest

from ai_assistant.core.errors import ConnectionStoreError, EgressBindingError
from ai_assistant.core.protocols import EgressBinder
from ai_assistant.core.types import (
    ActionRequest,
    BoundEgressCall,
    CarriedProvenance,
    CostBasis,
    DataTier,
    DiscloserProvenance,
    EgressBinding,
    EgressSpanLocator,
    Idempotency,
    PermissionOutcome,
    ProvisioningState,
    Reversibility,
    RiskLevel,
    SpanCoverage,
    ToolCost,
    ToolDefinition,
)
from ai_assistant.permissions.policy import ThresholdActionPolicy
from ai_assistant.testing.cancellation import held_at_its_first_await

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from ai_assistant.core.types import FrozenJson
    from ai_assistant.testing.cancellation import SuspendedCall

__all__ = ["EgressBinderContract", "either", "recipients", "tool_declaring"]

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


#: The two branches ADR-0157 §1's third form holds, spelled once so a case varying
#: one of them varies exactly one thing.
STRING_BRANCH: Final[Mapping[str, FrozenJson]] = {"type": "string"}
ARRAY_BRANCH: Final[Mapping[str, FrozenJson]] = {"type": "array", "items": {"type": "string"}}


def _destination_keywords() -> dict[str, FrozenJson]:
    """The two keywords a destination-bearing argument carries.

    Defined above the suite rather than below it because the declaration cases are
    parametrised, and a decorator's arguments are evaluated while the class body
    is.
    """
    return {"x-egress-destination": "smtp", "x-egress-tier": "personal"}


def either(*, tier: str = "personal", protocol: str = "smtp") -> dict[str, FrozenJson]:
    """A destination-bearing subschema in ADR-0157 §1's third form: both, at once.

    The union the per-call clause has always admitted, now declarable — an
    ``anyOf`` holding exactly the two subschemas :func:`recipients` and the string
    form declare separately.
    """
    return {
        "anyOf": [dict(STRING_BRANCH), dict(ARRAY_BRANCH)],
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
#: A **synthetic** id, not a shipped one: what these cases need is any local tool
#: with a query-shaped argument, and the id it used to carry (``recall_memory``)
#: names a tool ADR-0208 §2 deleted, which would send a reader looking for it.
NOT_EGRESS: Final = tool_declaring({"query": {"type": "string"}}, tool_id="local_lookup")

#: A **well-formed credential literal**, for ADR-0146 §9's case (#1150). It names
#: nothing this repository holds and unlocks nothing; what the clause needs is a
#: value a reader would classify Tier 0 arriving in a field that establishes no
#: tier, which is ADR-0017 §3's named attack in its own words — "an implementation
#: could classify a pasted OAuth token as Tier 1 because it arrived in
#: conversation, pass inspection, and disclose a credential under weaker policy".
#: Shaped like a bearer key rather than being one: prefix, dash, high-entropy body.
CREDENTIAL_LITERAL: Final = "sk-live-B1nQ8xR2vTgW7yZ1pL4mB6dK9sA0fH5jC2"


#: Supplied forms **every** implementation must canonicalise, and to what.
#:
#: ADR-0148 §2's one-canonicaliser clause is stated over *integrations at the
#: seam*, and its point is that the rule lives in **one** place. A canonical fake
#: cannot share the production canonicaliser — ``lint-imports`` forbids
#: ``testing`` importing ``tools`` — so the triad's two implementations are
#: independent by design, and **this** is the artifact that states what they must
#: agree on. Porting the production rules into ``testing/`` would create the second
#: copy that clause exists to prevent; a corpus both subjects run makes a future
#: divergence fail a test instead.
#:
#: The single transformation is RFC 5321 §2.4's: the domain is case-insensitive
#: and is lowered, the local part's semantics belong to the receiving host and it
#: is copied byte for byte.
#: RFC 5321 §4.5.3.1.1, §4.5.3.1.2 and RFC 1035 §2.3.4's ceilings. A boundary is
#: exactly what an enumerated corpus is for: the pair either side of each limit is
#: where two implementations most easily part company, and neither is reachable by
#: reading a rule off the other's source.
_MAX_LOCAL_PART: Final = "a" * 64 + "@example.com"
_OVER_LOCAL_PART: Final = "a" * 65 + "@example.com"
_MAX_LABEL: Final = "a@" + "b" * 63 + ".com"
_OVER_LABEL: Final = "a@" + "b" * 64 + ".com"
_OVER_DOMAIN: Final = "a@" + ("b" * 61 + ".") * 4 + "bbbbbbbbb.com"

CANONICALISES: Final = (
    ("bob@x.io", "bob@x.io"),
    ("Alice@Example.COM", "Alice@example.com"),
    ("a.b@sub.example.com", "a.b@sub.example.com"),
    ("first+tag@EXAMPLE.org", "first+tag@example.org"),
    ("UPPER@lower.EXAMPLE.com", "UPPER@lower.example.com"),
    (_MAX_LOCAL_PART, _MAX_LOCAL_PART),
    (_MAX_LABEL, _MAX_LABEL),
)

#: Supplied forms **every** implementation must refuse, so none is described by a
#: binding one implementation would build and another would not.
#:
#: The first five are the divergence adversarial review found between the two
#: implementations of this Protocol — each accepted by the canonical fake and
#: refused by production — which is a fake certifying a weaker seam than the one it
#: stands in for. The rest are the boundary those five sit on: RFC 5321 §2.4
#: assigns the local part to the receiving host and RFC 5321 §4.1.3 assigns an
#: address literal's equivalence class to the IP stack, so neither is a form this
#: seam may assert an equivalence for (ADR-0148 §1's third clause, ADR-0148 §2).
REFUSES: Final = (
    "a..b@example.com",
    ".a@example.com",
    'q"x"@example.com',
    "a@exa_mple.com",
    "a@b..c.com",
    "a.@example.com",
    "a@[192.0.2.1]",
    "a@example.com.",
    "a@-lead.com",
    "a@trail-.com",
    "a b@example.com",
    "two@at@example.com",
    "no-at-sign",
    "caf\u00e9@example.com",
    "@example.com",
    "a@",
    "",
    "not an address",
    _OVER_LOCAL_PART,
    _OVER_LABEL,
    _OVER_DOMAIN,
)


def _no_provenance() -> CarriedProvenance:
    """A carrier over an empty mapping, passed deliberately (ADR-0152 §1)."""
    return CarriedProvenance(
        spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
    )


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

    # --- ADR-0148 §2: what two implementations must agree on ----------------

    @pytest.mark.parametrize(("supplied", "canonical"), CANONICALISES)
    async def test_every_implementation_canonicalises_the_corpus_identically(
        self, binder: EgressBinder, supplied: str, canonical: str
    ) -> None:
        """ADR-0148 §2: one canonical form per supplied form, whoever computes it.

        Both forms survive — ADR-0148 §2's fourth clause requires the supplied one
        in the description and the audit record, and ADR-0148 §14 names
        reconstructing it from the canonical one as a failure in terms — so the
        supplied form is asserted unaltered beside the computed one.
        """
        self.register_egress(binder, SEND_EMAIL)

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={"to": [supplied], "subject": "s", "body": "b"},
            provenance=_no_provenance(),
        )

        assert bound is not None
        occurrence = bound.binding.spans[-1].destination
        assert occurrence is not None
        assert occurrence.supplied == supplied
        assert occurrence.canonical == canonical

    @pytest.mark.parametrize("supplied", REFUSES)
    async def test_every_implementation_refuses_the_same_forms(
        self, binder: EgressBinder, supplied: str
    ) -> None:
        """ADR-0148 §1, §2: a form with no canonical form is refused, never passed through.

        The case that makes this corpus worth having is an implementation that
        *accepts* here: a canonical fake admitting a form production refuses lets a
        consumer's test park and approve a call production would never make, which
        is a double certifying a weaker seam than the one it stands in for.
        """
        self.register_egress(binder, SEND_EMAIL)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                SEND_EMAIL,
                parameters={"to": [supplied], "subject": "s", "body": "b"},
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
            # ADR-0157 §1's second clause: every *other* spelling of the union the
            # third form admits. The shorthand first, which §1 refuses most firmly
            # — under draft 2020-12 ``items`` applies only to an array instance, so
            # this decides the element type in a sibling keyword rather than in the
            # type declaration a reader looks at.
            pytest.param(
                {
                    "type": ["string", "array"],
                    "items": {"type": "string"},
                    **_destination_keywords(),
                },
                id="a-union-of-string-and-array",
            ),
            pytest.param(
                {"oneOf": [dict(STRING_BRANCH), dict(ARRAY_BRANCH)], **_destination_keywords()},
                id="a-oneof-of-both-forms",
            ),
            pytest.param(
                {"allOf": [dict(STRING_BRANCH)], **_destination_keywords()},
                id="an-allof",
            ),
            pytest.param(
                {"not": {"type": "object"}, **_destination_keywords()},
                id="a-not",
            ),
            pytest.param(
                {
                    "if": {"type": "string"},
                    "then": dict(STRING_BRANCH),
                    "else": dict(ARRAY_BRANCH),
                    **_destination_keywords(),
                },
                id="an-if-then-else",
            ),
            pytest.param(
                {"anyOf": [dict(STRING_BRANCH)], **_destination_keywords()},
                id="an-anyof-with-one-branch",
            ),
            pytest.param(
                {
                    "anyOf": [dict(STRING_BRANCH), dict(ARRAY_BRANCH), dict(STRING_BRANCH)],
                    **_destination_keywords(),
                },
                id="an-anyof-with-three-branches",
            ),
            pytest.param(
                {
                    "anyOf": [dict(STRING_BRANCH), dict(STRING_BRANCH)],
                    **_destination_keywords(),
                },
                id="an-anyof-of-two-strings",
            ),
            pytest.param(
                {
                    "anyOf": [dict(ARRAY_BRANCH), dict(ARRAY_BRANCH)],
                    **_destination_keywords(),
                },
                id="an-anyof-of-two-arrays",
            ),
            pytest.param(
                {
                    "anyOf": [
                        {"anyOf": [dict(STRING_BRANCH), dict(ARRAY_BRANCH)]},
                        dict(ARRAY_BRANCH),
                    ],
                    **_destination_keywords(),
                },
                id="an-anyof-whose-branch-is-an-applicator",
            ),
            pytest.param(
                {
                    "$defs": {"r": {"type": "string"}},
                    "anyOf": [{"$ref": "#/properties/to/$defs/r"}, dict(ARRAY_BRANCH)],
                    **_destination_keywords(),
                },
                id="an-anyof-whose-branch-is-a-ref",
            ),
            pytest.param(
                {
                    "anyOf": [
                        dict(STRING_BRANCH),
                        {"type": "array", "items": {"type": "object"}},
                    ],
                    **_destination_keywords(),
                },
                id="an-anyof-whose-array-branch-holds-objects",
            ),
            pytest.param(
                {"type": "string", **either()},
                id="an-anyof-beside-a-sibling-type",
            ),
            pytest.param(
                {"oneOf": [dict(STRING_BRANCH)], **either()},
                id="an-anyof-beside-a-sibling-applicator",
            ),
        ],
    )
    async def test_a_non_flat_destination_bearing_declaration_is_refused(
        self, binder: EgressBinder, subschema: Mapping[str, FrozenJson]
    ) -> None:
        """ADR-0152 §4, §13 and ADR-0157 §1: three forms, and no other spelling.

        Refused when the declaration is read, before any call is made — which is
        why each case here binds a call that would otherwise succeed.

        The ``anyOf`` cases are ADR-0157 §1's second clause, which admits *one*
        spelling of the union rather than every equivalent one. ``oneOf`` would be
        equivalent here — no instance is both a string and an array — and is
        refused anyway, because two spellings of one fact in one vocabulary is the
        duplication the corpus is named against; the rest are refused because they
        decide the shape somewhere the seam does not read.
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

    @pytest.mark.parametrize(
        "branches",
        [
            pytest.param((STRING_BRANCH, ARRAY_BRANCH), id="string-first"),
            pytest.param((ARRAY_BRANCH, STRING_BRANCH), id="array-first"),
        ],
    )
    async def test_the_third_flat_form_is_admitted_in_either_branch_order(
        self, binder: EgressBinder, branches: tuple[Mapping[str, FrozenJson], ...]
    ) -> None:
        """ADR-0157 §1: an ``anyOf`` of exactly the two forms, in either order.

        The declaration half of the change, and the whole of what it adds: a tool
        author may now state the union the per-call clause already admitted.
        """
        union = tool_declaring(
            {"to": {"anyOf": [dict(branch) for branch in branches], **_destination_keywords()}}
        )
        self.register_egress(binder, union)

        bound = await binder.bind(
            union, parameters={"to": "Alice@Example.COM"}, provenance=_no_provenance()
        )

        assert bound is not None
        assert [span.index for span in bound.binding.spans] == [None]

    @pytest.mark.parametrize(
        ("value", "indices"),
        [
            pytest.param("Alice@Example.COM", [None], id="a-string-yields-one-indexless-span"),
            pytest.param(("Alice@Example.COM",), [0], id="an-array-yields-one-span-per-element"),
            pytest.param(("a@example.com", "b@example.com"), [0, 1], id="two-elements-two-spans"),
        ],
    )
    async def test_one_union_declaration_binds_both_forms_with_the_locators_of_each(
        self, binder: EgressBinder, value: FrozenJson, indices: list[int | None]
    ) -> None:
        """ADR-0157 §3: the seam's derivation is untouched, and one declaration reaches it.

        The consequence ADR-0157 §3 states rather than leaves to be discovered: the
        same recipient reaches a **different locator** depending on which form the
        caller composed — no index for a string, its position for an element — and
        this ADR is what makes both reachable through one declaration for the first
        time. Nothing depends on the two agreeing: a decision is bound to its own
        parameters digest and ``rebind`` re-derives from the same parameters.
        """
        union = tool_declaring({"to": either()})
        self.register_egress(binder, union)

        bound = await binder.bind(union, parameters={"to": value}, provenance=_no_provenance())

        assert bound is not None
        assert [span.index for span in bound.binding.spans] == indices
        assert all(span.destination is not None for span in bound.binding.spans)

    async def test_an_array_constraint_beside_anyof_does_not_unflatten_a_declaration(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0157 §1's fifth clause, and one of the two cases it separates.

        A keyword sitting beside ``anyOf`` on the argument's **own** subschema does
        not bear on flatness. Keywords on one subschema are conjunctive, so a
        sibling can only *narrow* what the subschema admits and can never reach
        ADR-0157 §2's structural bar — and refusing a misplaced ``minItems`` would
        need a model of which keywords constrain arrays, which is exactly the
        dialect model this seam deliberately does not have.

        Stated in the shared suite because it is where two conforming
        implementations would otherwise diverge on whether a tool **loads**.
        """
        tolerant = tool_declaring({"to": {**either(), "minItems": 1}})
        self.register_egress(binder, tolerant)

        bound = await binder.bind(
            tolerant, parameters={"to": "Alice@Example.COM"}, provenance=_no_provenance()
        )

        assert bound is not None

    async def test_a_sibling_ref_beside_anyof_is_refused(self, binder: EgressBinder) -> None:
        """ADR-0157 §1's fifth clause, and the other case it separates.

        The two exceptions to the tolerance above are ``"type"`` and ``"$ref"``,
        and neither is an exception to the conjunctivity that carries it: they are
        refused because they put the shape somewhere the seam does not read, not
        because they widen. ``$ref`` has been guarded before every other read since
        ADR-0152 §4, and ADR-0157 §2's first clause refuses it here too.
        """
        indirect = tool_declaring(
            {
                "to": {
                    "$defs": {"r": {"type": "string"}},
                    "$ref": "#/properties/to/$defs/r",
                    **either(),
                }
            }
        )
        self.register_egress(binder, indirect)

        with pytest.raises(EgressBindingError):
            await binder.bind(
                indirect, parameters={"to": "a@example.com"}, provenance=_no_provenance()
            )

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

    async def test_a_store_outage_on_the_resuming_path_raises_too(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §9, §13: ``bind`` and ``rebind`` **each** raise it.

        Stated over both members, and asserted over both: an implementation
        converting the outage on the resuming path alone would satisfy the
        ``bind`` case above while turning a store fault into a refusal at exactly
        the moment a user is waiting on an answer they have already given.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        self.fail_next_read(binder)

        with pytest.raises(ConnectionStoreError):
            await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

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
                spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
                planned_with_external_content=False,
                coverage=SpanCoverage.NOT_COVERED,
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
                    },
                    planned_with_external_content=False,
                    coverage=SpanCoverage.NOT_COVERED,
                ),
            )

        assert "attachment" not in str(raised.value)

    async def test_a_user_authored_credential_in_free_text_is_untiered_and_clears_no_gate(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0146 §9's marked clause, whole and over **one** span (#1150).

        §9: "A lane that implements §5 for a payload description ships a test
        asserting that a user-authored free-text span carrying a well-formed
        credential is described with its provenance and **no tier**, and that no
        gate in the path treats it as tier-cleared. A test asserting only that the
        span is present does not satisfy this clause."

        **Why the halves are in one case rather than two.** They were in two, over
        two different spans, with no credential in either — the ``tier is None``
        assertion sat on a ``SYSTEM_SELECTED`` span and the ``USER_AUTHORED`` case
        collected ``provenance`` and never asserted ``tier``. Two tests that each
        hold half of a conjunction over a different subject do not hold the
        conjunction, which is what #1150 records and what §9's closing sentence is
        written against.

        **The gate half is three assertions, because one outcome is not a
        property.** ``CONFIRM`` alone would be satisfiable for reasons having
        nothing to do with the span, so:

        1. the ruling equals the ruling for the same call with a plain,
           system-selected body — the span's provenance and its *absent* tier moved
           nothing;
        2. it equals the ruling for a request carrying **no binding at all** — the
           gate's answer does not consult the binding, which is the whole of
           ADR-0146 §5's fifth clause rather than the one field of it §9 names;
        3. it is ``CONFIRM`` under the most permissive configuration the policy
           admits — all four thresholds off — so the floor is not something a
           deployment can turn off and reach ``ALLOW`` through.

        **The real policy, deliberately, and it is the path's.**
        ``ThresholdActionPolicy`` is the only ``ActionPolicy``
        ``ai_assistant.app.composition`` wires (its ``StepRunner`` takes
        ``policy=ThresholdActionPolicy(...)`` with the four thresholds from
        ``Settings``), so exercising this class across its whole threshold space is
        exercising the gate in the path for every deployment — which is why 3 above
        is the assertion that answers "the gate in the path" and not merely "a
        gate". A fake ``ActionPolicy`` would make the clause vacuous: a double that
        never reads a tier proves only that the double does not.

        ADR-0154 §4's condition 7 attests the un-configurability as the ground of
        designation — ``_DISCLOSURE_FLOOR`` is a module constant no constructor
        argument reaches, and the combination is a maximum over outcomes — so 3 is
        that attested property held by a test rather than by a reading.

        **What this case does not reach, said rather than implied.** A *different*
        ``ActionPolicy`` implementation, wired by someone into the runner, is not
        exercised here and could not be without dragging ``orchestration`` into a
        suite the canonical fake also runs. What stands behind that today is
        structural rather than asserted here: nothing under
        ``src/ai_assistant/permissions/`` or ``src/ai_assistant/orchestration/``
        reads ``.tier`` or ``.spans`` at all, so there is no gate in the tree that
        could clear one. This is the one place the binder's suite reaches out of its
        own subsystem, and it is the clause's own subject that puts it there.
        """
        self.register_egress(binder, SEND_EMAIL)
        recipient: Mapping[str, FrozenJson] = {"to": ["a@example.com"], "subject": "s"}
        user_authored = CarriedProvenance(
            spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
            planned_with_external_content=False,
            coverage=SpanCoverage.NOT_COVERED,
        )

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={**recipient, "body": CREDENTIAL_LITERAL},
            provenance=user_authored,
        )
        plain = await binder.bind(
            SEND_EMAIL, parameters={**recipient, "body": "b"}, provenance=_no_provenance()
        )

        assert bound is not None
        located = {(span.argument, span.index): span for span in bound.binding.spans}
        body = located[("body", None)]
        # Described with its provenance, and with no tier — the two halves §9 wants
        # on one span. ``subject`` and ``body`` establish none (ADR-0146 §5's own
        # worked split), so the credential acquires no Tier 1 claim by being typed.
        assert body.provenance is DiscloserProvenance.USER_AUTHORED
        assert body.tier is None
        assert body.extent == len(CREDENTIAL_LITERAL)
        # ADR-0150 §10: the description holds no content, so the credential is
        # counted and never carried — a binding that rendered it would put a Tier 0
        # value into the recorded decision the audit trail persists.
        assert CREDENTIAL_LITERAL not in repr(bound.binding)

        # The class the composition root wires, at its own defaults — which are the
        # ones ``Settings`` reproduces for an unconfigured deployment.
        policy = ThresholdActionPolicy()
        ruling = await policy.decide(
            ActionRequest(
                tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
            )
        )

        assert plain is not None
        unmarked = await policy.decide(
            ActionRequest(
                tool=plain.tool, parameters=plain.parameters, egress_binding=plain.binding
            )
        )
        unbound = await policy.decide(ActionRequest(tool=bound.tool, parameters=bound.parameters))
        # Every threshold off: the most permissive policy this class can be built
        # as, and the configuration under which an ``ALLOW`` would be reachable if
        # the disclosure floor were a threshold rather than a constant.
        permissive = await ThresholdActionPolicy(
            confirm_at_risk=None,
            confirm_at_reversibility=None,
            deny_at_risk=None,
            deny_at_reversibility=None,
        ).decide(
            ActionRequest(
                tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
            )
        )

        assert ruling.outcome is PermissionOutcome.CONFIRM
        assert ruling == unmarked
        assert ruling == unbound
        assert permissive.outcome is PermissionOutcome.CONFIRM
        assert CREDENTIAL_LITERAL not in ruling.reason

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

    # --- ADR-0152 §1, §13: the detachment cases, one per validated argument --
    #
    # Each mutates the caller's own object with `object.__setattr__` **while the
    # member is suspended on §10's awaited connection-record read** — the window the
    # detachment exists to close. §13: "A test that mutates a copy satisfies none of
    # these; one that mutates before the await tests revalidation rather than
    # detachment; and one covering `approved` alone leaves every argument the
    # suspension window actually exposes untested."

    async def test_a_tool_mutated_during_the_read_changes_neither_derivation_nor_result(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: the declaration the binding is derived under is the detached one.

        The mutation is on the **declaration** rather than on a label, because that
        is what the clause names: a caller that hands in a registry-equal
        definition, lets it revalidate and compare, suspends the seam on its read
        and then strips the destination keyword would otherwise have the binding
        derived under a schema no longer equal to the registered original — with the
        ruling recorded before ``invoke``'s own check ever runs.
        """
        tool = tool_declaring({"to": recipients(), "body": {"type": "string"}})
        self.register_egress(binder, tool)
        held = self.suspend_next_read(binder)

        async with held_at_its_first_await(
            held,
            binder.bind(
                tool,
                parameters={"to": ["a@example.com"], "body": "b"},
                provenance=_no_provenance(),
            ),
        ) as task:
            object.__setattr__(
                tool,
                "parameters_schema",
                {"type": "object", "properties": {"to": {"type": "array"}, "body": {}}},
            )
            object.__setattr__(tool, "id", "somebody-else")
        bound = await task

        assert bound is not None
        assert bound.tool.id == "send_email@work"
        located = {(span.argument, span.index): span for span in bound.binding.spans}
        assert located[("to", 0)].destination is not None
        assert located[("to", 0)].destination.canonical == "a@example.com"
        assert located[("to", 0)].tier is DataTier.PERSONAL

    async def test_parameters_mutated_during_the_read_change_no_span_and_no_refusal(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: neither the spans derived nor any refusal condition of §6.

        The mutation adds a key the schema never statically names *and* rewrites a
        described one, so a seam reading the caller's mapping after the await would
        either refuse under §6 or describe a payload nobody proposed.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "hello",
        }
        held = self.suspend_next_read(binder)

        async with held_at_its_first_await(
            held, binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        ) as task:
            parameters["body"] = "rewritten while the seam was suspended"
            parameters["X-Secret"] = "sk-live-0001"
        bound = await task

        assert bound is not None
        located = {(span.argument, span.index): span for span in bound.binding.spans}
        assert set(located) == {("body", None), ("subject", None), ("to", 0)}
        assert located[("body", None)].extent == len("hello")
        assert bound.parameters["body"] == "hello"
        assert "X-Secret" not in bound.parameters

    async def test_a_carrier_mutated_during_the_read_changes_no_provenance(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1: neither the provenance written into a span nor §5's absent-span refusal.

        Emptying the carrier mid-flight would silently downgrade a user-authored
        span to ``SYSTEM_SELECTED``; naming an absent span would make §5's refusal
        fire on a call that never carried one.
        """
        self.register_egress(binder, SEND_EMAIL)
        carrier = CarriedProvenance(
            spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
            planned_with_external_content=False,
            coverage=SpanCoverage.NOT_COVERED,
        )
        held = self.suspend_next_read(binder)

        async with held_at_its_first_await(
            held,
            binder.bind(
                SEND_EMAIL,
                parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
                provenance=carrier,
            ),
        ) as task:
            object.__setattr__(
                carrier,
                "spans",
                {EgressSpanLocator(argument="attachment"): DiscloserProvenance.USER_AUTHORED},
            )
        bound = await task

        assert bound is not None
        located = {(span.argument, span.index): span.provenance for span in bound.binding.spans}
        assert located[("body", None)] is DiscloserProvenance.USER_AUTHORED
        assert located[("subject", None)] is DiscloserProvenance.SYSTEM_SELECTED

    async def test_an_approved_binding_mutated_during_the_read_changes_nothing_it_decides(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0152 §1, §13: ``rebind``'s own argument across its own awaited read.

        A caller that hands in a matching binding and swaps in another while the
        seam is suspended would otherwise have §7's equality decided against a value
        nobody approved. Asserted in both directions: the resume still succeeds, and
        what comes back is the **derived** binding rather than the substituted one.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        approved = EgressBinding.model_validate(first.binding.model_dump())
        held = self.suspend_next_read(binder)

        async with held_at_its_first_await(
            held, binder.rebind(SEND_EMAIL, parameters=parameters, approved=approved)
        ) as task:
            object.__setattr__(approved, "transport_endpoint", "test://somewhere-else")
        again = await task

        assert again is not None
        assert again.binding == first.binding
        assert again.binding.transport_endpoint == ENDPOINT

    # --- ADR-0152 §1: the bypass cases --------------------------------------
    #
    # ADR-0152 §13: "Each is exercised against a tool this seam holds **no** egress
    # registration for and whose schema carries neither §3 keyword, as well as
    # against a registered one: that is the branch §8 would otherwise answer with
    # `None`, so it is where the revalidation ordering §8 states is actually
    # pinned." So every shape below is parametrized over both sides of §8's
    # partition, and every one asserts the **chained** `ValidationError` — which is
    # what distinguishes "revalidated first" from "looked the registration up first
    # and refused for another reason".

    def _bypass_subject(self, binder: EgressBinder, *, registered: bool) -> ToolDefinition:
        """The tool a bypass case is aimed at, on each side of ADR-0152 §8's partition."""
        if registered:
            self.register_egress(binder, SEND_EMAIL)
            return SEND_EMAIL
        self.register(binder, NOT_EGRESS)
        return NOT_EGRESS

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_a_carrier_built_by_model_construct_is_refused_with_a_chained_error(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: chained from the ``ValidationError``, never a bare one.

        ``model_construct`` builds an instance without running validators and is
        public, so the annotation on the argument is not the enforcement.
        """
        tool = self._bypass_subject(binder, registered=registered)
        forged = CarriedProvenance.model_construct(spans={"body": "hearsay"})

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(tool, parameters={}, provenance=forged)

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_a_carrier_rewritten_after_construction_is_refused(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1: ``object.__setattr__`` defeats ``frozen=True`` (ADR-0018 §3).

        A different hole from the one above: this carrier passed every validator on
        the way in and was corrupted afterwards.
        """
        tool = self._bypass_subject(binder, registered=registered)
        carrier = CarriedProvenance(
            spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
        )
        object.__setattr__(carrier, "spans", {object(): object()})

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(tool, parameters={}, provenance=carrier)

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_a_locator_built_by_model_construct_is_refused_at_the_seam(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: the locator shape, exercised by calling ``bind`` directly.

        Its refusal *at construction* is pinned in
        ``tests/core/test_egress_binding_seam_types.py``; §13 states this one over
        the seam, because a carrier holding a forged key can only be built by a
        caller and can only be refused where the seam revalidates it.
        """
        tool = self._bypass_subject(binder, registered=registered)
        forged = CarriedProvenance.model_construct(
            spans={
                EgressSpanLocator.model_construct(argument=object(), index="nine"): (
                    DiscloserProvenance.USER_AUTHORED
                )
            }
        )

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(tool, parameters={}, provenance=forged)

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_a_tool_built_by_model_construct_is_refused(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: the ``tool`` shape, on both sides of the partition.

        The forged definition carries the **registered** id on the egress side, so
        the case really does reach the branch a registration lookup would take.
        """
        registered_tool = self._bypass_subject(binder, registered=registered)
        forged = ToolDefinition.model_construct(id=registered_tool.id, capability="")

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(forged, parameters={}, provenance=_no_provenance())

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_parameters_carrying_a_refused_value_are_refused(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: ``FrozenJsonMapping`` is an alias, and Python enforces none.

        A non-finite float satisfies ``float`` and has no JSON representation, so it
        would validate against the annotation and fail far away — the
        "accepted, then unusable" shape ADR-0014 §2 exists to close.
        """
        tool = self._bypass_subject(binder, registered=registered)
        argument = "body" if registered else "query"

        with pytest.raises(EgressBindingError) as raised:
            await binder.bind(
                tool, parameters={argument: float("nan")}, provenance=_no_provenance()
            )

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_an_approved_binding_built_by_model_construct_is_refused(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: ``rebind``'s own argument, which a ``bind``-only suite leaves untested.

        On the non-egress side this is where §8's ordering is pinned for
        ``approved``: an implementation looking the registration up first would
        refuse for a different reason and carry no chained ``ValidationError``.
        """
        tool = self._bypass_subject(binder, registered=registered)
        forged = EgressBinding.model_construct(spans="not a tuple", account=None)

        with pytest.raises(EgressBindingError) as raised:
            await binder.rebind(tool, parameters={}, approved=forged)

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    async def test_an_approved_binding_rewritten_after_construction_is_refused(
        self, binder: EgressBinder, *, registered: bool
    ) -> None:
        """ADR-0152 §1, §13: the second ``approved`` bypass, which the first does not reach.

        §13 names **two** hostile shapes for ``approved``: one built by
        ``EgressBinding.model_construct``, and one "whose field was replaced by
        ``object.__setattr__`` after construction". They are different holes — the
        first skips every validator on the way in, the second passes them all and is
        corrupted afterwards, which is what ``frozen=True`` does not stop (ADR-0018
        §3). An implementation revalidating only what looked unconstructed would
        pass the first and read the second's forged account as the one a user
        approved.
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        corrupted = EgressBinding.model_validate(first.binding.model_dump())
        object.__setattr__(corrupted, "account", None)
        subject = SEND_EMAIL if registered else NOT_EGRESS
        if not registered:
            self.register(binder, NOT_EGRESS)

        with pytest.raises(EgressBindingError) as raised:
            await binder.rebind(
                subject,
                parameters=parameters if registered else {"query": "q"},
                approved=corrupted,
            )

        assert type(raised.value.__cause__).__name__ == "ValidationError"

    @pytest.mark.parametrize("registered", [True, False], ids=["egress-tool", "non-egress-tool"])
    @pytest.mark.parametrize("argument", ["tool", "parameters", "provenance", "approved"])
    async def test_a_raw_non_model_argument_is_refused_with_a_chained_error(
        self, binder: EgressBinder, argument: str, *, registered: bool
    ) -> None:
        """ADR-0152 §1: revalidated "before reading any field of it", for **every** argument.

        ``model_dump()`` is a field read, so a seam that called it before
        validating would let a value that is not a model at all escape as an
        ``AttributeError`` — never the chained refusal §1 promises, and never a
        refusal a caller could act on.

        **This case is stated over all four revalidated arguments, not over the two
        that happened to be broken.** §13's bypass list enumerates model instances
        only — ``model_construct``ed or ``object.__setattr__``-corrupted — and it
        illustrates §1's clause rather than closing it. A suite that tracked the
        list would leave every raw shape outside it to be found by review one
        variant at a time; this tracks the clause instead, so the next raw shape
        fails here.
        """
        tool = self._bypass_subject(binder, registered=registered)
        raw: Any = {}
        unmapped: Any = "not a mapping"
        calls: dict[str, Callable[[], Awaitable[BoundEgressCall | None]]] = {
            "tool": lambda: binder.bind(raw, parameters={}, provenance=_no_provenance()),
            "parameters": lambda: binder.bind(
                tool, parameters=unmapped, provenance=_no_provenance()
            ),
            "provenance": lambda: binder.bind(tool, parameters={}, provenance=raw),
            "approved": lambda: binder.rebind(tool, parameters={}, approved=raw),
        }

        with pytest.raises(EgressBindingError) as raised:
            await calls[argument]()

        assert type(raised.value.__cause__).__name__ == "ValidationError"

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

    async def test_rebind_refuses_an_approved_binding_with_a_destination_omitted(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0150 §11's second routed refusal, ADR-0152 §6, §13: the omitted destination.

        §13 states it as "a call whose declaration marks an argument
        destination-bearing and whose derivation would produce that argument's span
        with no ``EgressDestination`` is refused before a ruling is sought, so no
        decision is recorded holding an account-only canonical destination set for
        it", and rules out two shapes that do not reach it: a binding also malformed
        under ADR-0150 §4, and one whose declaration marks no argument
        destination-bearing.

        On the deriving path the case has **no instance**: ADR-0152 §4 makes a
        destination-bearing argument's value a string or an array of strings, so
        every span of one carries an occurrence by construction and a supplied form
        with no canonical form is refused instead. So it is exercised where an
        omission really can arrive — a binding read back out of the trail — and the
        assertion above the refusal is the thing the refusal prevents: that binding's
        derived set names the **account alone**, which ADR-0150 §3's condition clause
        forbids reading as "this call selected no recipient".
        """
        self.register_egress(binder, SEND_EMAIL)
        parameters: dict[str, FrozenJson] = {
            "to": ["a@example.com"],
            "subject": "s",
            "body": "b",
        }
        first = await binder.bind(SEND_EMAIL, parameters=parameters, provenance=_no_provenance())
        assert first is not None
        stripped = _without_destinations(first.binding)
        assert [member.account for member in stripped.canonical_destination_set] == [
            stripped.account
        ]

        with pytest.raises(EgressBindingError):
            await binder.rebind(SEND_EMAIL, parameters=parameters, approved=stripped)

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
                spans={EgressSpanLocator(argument="body"): DiscloserProvenance.USER_AUTHORED},
                planned_with_external_content=False,
                coverage=SpanCoverage.NOT_COVERED,
            ),
        )
        assert first is not None

        again = await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

        assert again is not None
        located = {(span.argument, span.index): span.provenance for span in again.binding.spans}
        assert located[("body", None)] is DiscloserProvenance.USER_AUTHORED

    # --- ADR-0181 §3, §4: the call-level origin, carried and transcribed --------

    @pytest.mark.parametrize("selected_external", [True, False])
    async def test_the_binding_carries_the_carriers_planned_with_external_content(
        self, binder: EgressBinder, selected_external: bool
    ) -> None:
        """ADR-0181 §3's second clause, §10's second case: carried, unchanged.

        Both states, because the ``False`` half is what fails a seam that derived a
        value of its own rather than taking the caller's — such a seam would answer
        ``False`` here and pass the ``True`` case by accident of its own default.
        The seam derives nothing for this field: ADR-0181 §4's second clause forbids
        recovering it from an argument's value, its field or its shape, and the
        arguments below are identical across the two runs.
        """
        self.register_egress(binder, SEND_EMAIL)

        bound = await binder.bind(
            SEND_EMAIL,
            parameters={"to": ["a@example.com"], "subject": "s", "body": "b"},
            provenance=CarriedProvenance(
                spans={},
                planned_with_external_content=selected_external,
                coverage=SpanCoverage.NOT_COVERED,
            ),
        )

        assert bound is not None
        assert bound.binding.planned_with_external_content is selected_external

    async def test_rebind_transcribes_planned_with_external_content_from_approved(
        self, binder: EgressBinder
    ) -> None:
        """ADR-0181 §3's fifth and sixth clauses: the **second** thing taken from ``approved``.

        ``rebind`` receives no carrier and no selection set — the selection happened
        before the confirmation was parked, plausibly before a restart — so a member
        that re-derived this field would answer ``False``, compare unequal to the
        approved binding, and refuse the very call the user was asked about and
        approved. The equality assertion below is what makes that visible: it is the
        refusal ADR-0152 §7 already states, reached through this field alone.

        This narrows ADR-0152 §7's count from exactly one to exactly two and narrows
        nothing else in it: everything else is still re-derived, and the resumed
        binding still has to equal the approved one whole.
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
                spans={}, planned_with_external_content=True, coverage=SpanCoverage.NOT_COVERED
            ),
        )
        assert first is not None
        assert first.binding.planned_with_external_content is True

        again = await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

        assert again is not None
        assert again.binding.planned_with_external_content is True
        assert again.binding == first.binding, (
            "the re-derived binding equals the approved one, so ADR-0152 §7's "
            "equality refusal does not fire on the field ADR-0181 §3 adds"
        )

    async def test_rebind_answers_false_where_the_approved_binding_said_false(
        self, binder: EgressBinder
    ) -> None:
        """The other half of the transcription, so it is not a constant ``True``.

        A seam that hard-coded the resuming answer would pass the case above and
        fail this one, and would then authorise a resumed call whose recorded origin
        disagrees with what the approver was shown (ADR-0181 §6's fourth clause
        renders the fact in both states).
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
                spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
            ),
        )
        assert first is not None

        again = await binder.rebind(SEND_EMAIL, parameters=parameters, approved=first.binding)

        assert again is not None
        assert again.binding.planned_with_external_content is False
        assert again.binding == first.binding

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


def _without_destinations(binding: EgressBinding) -> EgressBinding:
    """``binding`` with every occurrence dropped, its spans otherwise unchanged.

    Well-formed under ADR-0150 §3 and §4 — which is the point: §13 rules out a case
    whose binding is *also* malformed, because such a case demonstrates the wrong
    refusal.
    """
    dumped = binding.model_dump()
    for span in dumped["spans"]:
        span["destination"] = None
    return EgressBinding.model_validate(dumped)


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
