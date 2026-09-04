"""``EgressBindingSeam`` against the shared suite, and what is this seam's alone.

The production half of ADR-0152's triad. Everything the *contract* obliges lives
in ``egress_binder_contract.py`` and runs here through
:class:`TestEgressBindingSeamContract`; what is below the class is what belongs to
this implementation and to no other — that the extent it computes is the one
``core`` recomputes, that the two declaration keywords leave a schema readable and
validating identically, and that the registration table refuses a second account
for one tool.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import pytest
from egress_binder_contract import (
    ENDPOINT,
    IDENTITY,
    REFERENCE,
    SEND_EMAIL,
    EgressBinderContract,
    recipients,
    tool_declaring,
)

from ai_assistant.core.errors import ConnectionStoreError
from ai_assistant.core.types import (
    ActionRequest,
    CarriedProvenance,
    ProvisioningState,
    SecretName,
    SecretScope,
    SpanCoverage,
    parameter_violations,
)
from ai_assistant.testing import FakeAuditTrail
from ai_assistant.testing.cancellation import LoopSuspension
from ai_assistant.testing.egress import _canonical_smtp as fake_canonical
from ai_assistant.tools import egress_binder as seam_module
from ai_assistant.tools.connection_store import ConnectionEntry, StoredEntry
from ai_assistant.tools.destinations import (
    DestinationCanonicalisationError,
    canonicalise,
)
from ai_assistant.tools.destinations import (
    DestinationProtocol as SeamProtocol,
)
from ai_assistant.tools.egress_binder import (
    EgressBindingSeam,
    EgressRegistration,
    RegistrationTable,
)
from ai_assistant.tools.registry import InMemoryToolRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ai_assistant.core.protocols import EgressBinder
    from ai_assistant.core.types import FrozenJson, ToolDefinition
    from ai_assistant.testing.cancellation import SuspendedCall

#: A slot is never read by this seam and never crosses it (ADR-0152 §10); one is
#: put on every arranged record precisely so a case would notice if one did.
_SLOT: Final = SecretName(scope=SecretScope.INTEGRATION, key="unread-by-this-seam")


class _Records:
    """A connection store this suite can arrange, fail and suspend.

    Structurally the ``ConnectionRecords`` face
    :class:`~ai_assistant.tools.egress_binder.EgressBindingSeam` reads through —
    one method, one reference, one record — over the same
    :class:`~ai_assistant.tools.connection_store.ConnectionEntry` the SQLite store
    hands back, so what the seam is held to here is the shape it meets in
    production rather than a simplification of it.
    """

    def __init__(self) -> None:
        """Start with no record, nothing armed and nothing read."""
        self.records: dict[str, ConnectionEntry] = {}
        self.reads: list[str] = []
        self.fail_next = False
        self.suspension: LoopSuspension | None = None

    def put(self, reference: str, *, identity: str, state: ProvisioningState) -> None:
        """Record ``reference`` as a provisioning act's entry would."""
        self.records[reference] = ConnectionEntry(
            reference=reference, revision=1, identity=identity, state=state, slot=_SLOT
        )

    async def latest(self, reference: str, /) -> StoredEntry | None:
        """The reference's latest entry, or ``None``."""
        suspension, self.suspension = self.suspension, None
        if suspension is not None:
            await suspension.hold()
        if self.fail_next:
            self.fail_next = False
            msg = f"failed to read connection {reference!r}"
            raise ConnectionStoreError(msg)
        self.reads.append(reference)
        entry = self.records.get(reference)
        return None if entry is None else StoredEntry(1, entry)


class _Harness:
    """One seam and the two tables plus one store it was wired from."""

    def __init__(self, *, canonicalises: tuple[()] | None = None) -> None:
        """Wire a seam over an empty registry, an empty table and an empty store."""
        self.registry = InMemoryToolRegistry(ledger=FakeAuditTrail(), gate=FakeAuditTrail())
        self.table = RegistrationTable()
        self.records = _Records()
        self.seam = EgressBindingSeam(
            definitions=self.registry,
            registrations=self.table,
            records=self.records,
            canonicalises=canonicalises,
        )


async def _refuses(
    parameters: Mapping[str, FrozenJson],
    *,
    idempotency_key: str | None,
) -> FrozenJson:
    """A callable that is never reached: nothing here is invoked (ADR-0017 §2)."""
    msg = "this tool transmits nothing; ai_assistant.tools.egress stays undesignated"
    raise AssertionError(msg)


class TestEgressBindingSeamContract(EgressBinderContract):
    """The production seam honours every obligation ADR-0152 states."""

    _wiring: dict[int, _Harness]

    @pytest.fixture
    def binder(self) -> EgressBinder:
        """A seam over an empty registry, registration table and connection store."""
        return self._build()

    def _build(self, *, canonicalises: tuple[()] | None = None) -> EgressBinder:
        """Wire a fresh seam and remember what it was wired from."""
        harness = _Harness(canonicalises=canonicalises)
        if not hasattr(self, "_wiring"):
            self._wiring = {}
        self._wiring[id(harness.seam)] = harness
        return harness.seam

    def _of(self, binder: EgressBinder) -> _Harness:
        """The wiring behind ``binder``, which no seam face exposes and none should."""
        return self._wiring[id(binder)]

    def register(self, binder: EgressBinder, tool: ToolDefinition) -> None:
        """Hold ``tool`` in the registry, bound to no connected account."""
        self._of(binder).registry.register(tool, _refuses)

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
        """Register ``tool`` against a connected account and record that account."""
        harness = self._of(binder)
        harness.registry.register(tool, _refuses)
        harness.table.register(
            EgressRegistration(
                tool_id=tool.id, reference=reference, transport_endpoint=transport_endpoint
            )
        )
        harness.records.put(reference, identity=identity, state=state)

    def set_connection(
        self,
        binder: EgressBinder,
        reference: str,
        *,
        identity: str,
        state: ProvisioningState = ProvisioningState.ACTIVE,
    ) -> None:
        """Rewrite the record ``reference`` names."""
        self._of(binder).records.put(reference, identity=identity, state=state)

    def remove_connection(self, binder: EgressBinder, reference: str) -> None:
        """Drop the record, as a disconnection's removal entry does."""
        self._of(binder).records.records.pop(reference, None)

    def fail_next_read(self, binder: EgressBinder) -> None:
        """Arm the store to raise ``ConnectionStoreError`` on the next read."""
        self._of(binder).records.fail_next = True

    def suspend_next_read(self, binder: EgressBinder) -> SuspendedCall:
        """Hold the store's next read open, inside ADR-0152 §10's one await."""
        suspension = LoopSuspension()
        self._of(binder).records.suspension = suspension
        return suspension

    def reads(self, binder: EgressBinder) -> tuple[str, ...]:
        """Every reference the store has been asked for, in order."""
        return tuple(self._of(binder).records.reads)

    def canonicalising_nothing(self) -> EgressBinder:
        """A seam whose canonicaliser set has been narrowed to nothing."""
        return self._build(canonicalises=())


# --- what is this implementation's alone -------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("plain text", id="a-string"),
        pytest.param(["one", "two"], id="an-array-of-strings"),
        pytest.param({"nested": {"deep": [1, 2, 3]}}, id="an-object"),
        pytest.param([{"a": 1}, {"b": None}], id="an-array-of-objects"),
        pytest.param(42, id="a-number"),
        pytest.param(True, id="a-boolean"),
        pytest.param(None, id="null"),
        pytest.param("naïve — ünïcode 😀", id="astral-and-accented-text"),
    ],
)
async def test_the_derived_extent_is_the_one_core_recomputes(value: FrozenJson) -> None:
    """ADR-0150 §4: the seam's measure and ``ActionRequest``'s recomputation agree.

    This seam computes a span's extent and ``ActionRequest`` recomputes it, so a
    seam that measured differently would build a binding ``core`` refuses. The
    agreement is asserted against the **real validator** across every JSON shape a
    span can hold, rather than by copying a constant out of ``core/types.py`` —
    which is what keeps the two from drifting when one of them changes.
    """
    tool = tool_declaring({"to": recipients(), "payload": {}})
    harness = _Harness()
    harness.registry.register(tool, _refuses)
    harness.table.register(
        EgressRegistration(tool_id=tool.id, reference=REFERENCE, transport_endpoint=ENDPOINT)
    )
    harness.records.put(REFERENCE, identity=IDENTITY, state=ProvisioningState.ACTIVE)

    bound = await harness.seam.bind(
        tool,
        parameters={"to": ["a@example.com"], "payload": value},
        provenance=CarriedProvenance(
            spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
        ),
    )

    assert bound is not None
    request = ActionRequest(
        tool=bound.tool, parameters=bound.parameters, egress_binding=bound.binding
    )
    assert request.egress_binding == bound.binding


def test_the_declaration_keywords_leave_the_schema_readable_and_validating_identically() -> None:
    """ADR-0152 §3, §13: the schema-readability pin.

    JSON Schema draft 2020-12 treats an unknown keyword as an annotation and
    ignores it for validation, so a schema carrying both keywords validates exactly
    as the same schema without them — ADR-0145 §5's one-dialect rule and §6's
    readability refusal both untouched. Demonstrated against **this repository's own
    evaluator** rather than against the specification, which is what §13 asks for:
    a dialect this repository could not read would fail at ``ToolDefinition``
    construction, and one that read the keywords as constraints would report
    different violations here.
    """
    declared = tool_declaring({"to": recipients(), "body": {"type": "string"}})
    bare = tool_declaring(
        {"to": {"type": "array", "items": {"type": "string"}}, "body": {"type": "string"}}
    )
    cases: list[dict[str, FrozenJson]] = [
        {"to": ["a@example.com"], "body": "b"},
        {"to": "not an array", "body": "b"},
        {"to": [1], "body": "b"},
        {"body": 7},
        {},
    ]

    for arguments in cases:
        assert parameter_violations(declared.parameters_schema, arguments) == parameter_violations(
            bare.parameters_schema, arguments
        )


def test_a_second_account_for_one_tool_is_refused_at_registration() -> None:
    """ADR-0148 §6's one-account clause, held where the table is built.

    Two would make "the connected account this tool is bound to" ambiguous, and it
    is also what keeps the seam's read budget at exactly one record per egress
    call: one reference per registered tool, so no lookup and no enumeration.
    """
    table = RegistrationTable(
        [EgressRegistration(tool_id="t", reference="conn-a", transport_endpoint=ENDPOINT)]
    )

    with pytest.raises(ValueError, match="two connected accounts"):
        table.register(
            EgressRegistration(tool_id="t", reference="conn-b", transport_endpoint=ENDPOINT)
        )


def test_an_unregistered_tool_has_no_registration() -> None:
    """The lookup answers ``None`` rather than raising: ADR-0152 §8 branches on it."""
    assert RegistrationTable().registration("nobody") is None


def test_the_registry_hands_back_a_detached_original() -> None:
    """``original`` is a *query*, so it may not hand out the registry's own object.

    :meth:`~ai_assistant.tools.registry.InMemoryToolRegistry.all_tools`' reason
    exactly: a holder of a query that received the live definition could rewrite
    what the registry considers registered, and here that would silently defeat
    ADR-0152 §1's registry-original comparison — the caller's tampered definition
    and the "original" would be the same object and could never differ.
    """
    registry = InMemoryToolRegistry(ledger=FakeAuditTrail(), gate=FakeAuditTrail())
    registry.register(SEND_EMAIL, _refuses)

    first = registry.original(SEND_EMAIL.id)
    assert first is not None
    object.__setattr__(first, "id", "rewritten")

    second = registry.original(SEND_EMAIL.id)
    assert second is not None
    assert second.id == SEND_EMAIL.id
    assert registry.original("nobody") is None


async def test_no_refusal_message_renders_a_destination_form_or_an_identity() -> None:
    """ADR-0152 §11, §13: nothing on this surface renders an address or an identity.

    Swept over every refusal a single arrangement can reach, because the clause is
    stated over the surface rather than over one message — a case asserting the
    discipline for one refusal leaves the others free to breach it.
    """
    harness = _Harness()
    harness.registry.register(SEND_EMAIL, _refuses)
    harness.table.register(
        EgressRegistration(tool_id=SEND_EMAIL.id, reference=REFERENCE, transport_endpoint=ENDPOINT)
    )
    harness.records.put(REFERENCE, identity=IDENTITY, state=ProvisioningState.ACTIVE)
    address = "Mallory@Example.COM"  # a Tier 1 recipient, never rendered
    refusals: list[str] = []

    for arguments in (
        {"to": [address, "not an address"], "subject": "s", "body": "b"},
        {"to": {"one": address}, "subject": "s", "body": "b"},
        {"to": [address], "subject": "s", "body": "b", "X-Secret": address},
    ):
        with pytest.raises(Exception) as raised:  # noqa: PT011 — the message is the subject, not the type
            await harness.seam.bind(
                SEND_EMAIL,
                parameters=cast("dict[str, FrozenJson]", arguments),
                provenance=CarriedProvenance(
                    spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
                ),
            )
        refusals.append(str(raised.value))

    harness.records.put(REFERENCE, identity=IDENTITY, state=ProvisioningState.PENDING)
    with pytest.raises(Exception) as pending:  # noqa: PT011 — the message is the subject, not the type
        await harness.seam.bind(
            SEND_EMAIL,
            parameters={"to": [address], "subject": "s", "body": "b"},
            provenance=CarriedProvenance(
                spans={}, planned_with_external_content=False, coverage=SpanCoverage.NOT_COVERED
            ),
        )
    refusals.append(str(pending.value))

    assert refusals
    for message in refusals:
        assert address not in message
        assert IDENTITY not in message
        assert "X-Secret" not in message
        assert _SLOT.key not in message
    # The permitted half of the clause, exercised rather than assumed: ADR-0152 §11
    # lets a refusal name the tool id, an argument the declaration **statically
    # names**, and the connection reference — so a discipline that named nothing at
    # all would pass every assertion above while leaving a refusal unreadable.
    assert "'to'" in refusals[0]
    assert SEND_EMAIL.id in refusals[0]
    assert REFERENCE in refusals[-1]


def test_the_seam_holds_no_keyring_face_and_no_collaborator_beyond_its_three() -> None:
    """ADR-0152 §10, §13: the half of the read-budget pin an instrumented double cannot see.

    "It reads no keyring… The implementation holds no ``Secrets`` and no
    ``SecretStore`` face, and holding this seam is not holding one" (ADR-0125 §8,
    ADR-0149 §8). A doubles-based assertion can only show that a *given* keyring
    was not called; what makes the claim structural is that the module names no
    such face to call and this object holds no fourth collaborator to hide one
    behind.

    Asserted against the module's own syntax tree rather than against its text, so
    the docstring naming the classes it does **not** hold does not satisfy it.
    """
    tree = ast.parse(Path(str(seam_module.__file__)).read_text(encoding="utf-8"))
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom | ast.Import)
        for alias in node.names
    }
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert not ({"Secrets", "SecretStore", "SecretName", "SecretValue"} & imported)
    assert not any("secret" in module for module in modules)
    assert set(EgressBindingSeam.__slots__) == {
        "_canonicalises",
        "_definitions",
        "_records",
        "_registrations",
    }


# --- the fake never certifies a seam production would refuse ------------------

#: Local parts a hostile caller might supply, spanning every rule either
#: canonicaliser states: dot placement, quoting, atext, whitespace, the 64-octet
#: ceiling either side, and non-ASCII.
_LOCAL_PARTS: Final = (
    "a",
    "a.b",
    "a..b",
    ".a",
    "a.",
    'q"x"',
    "a\\b",
    "a b",
    "a+b",
    "a@b",
    "",
    "a" * 64,
    "a" * 65,
    "\u00fc\u00f1",
)

#: Domains likewise: label shape, the LDH set, address literals, trailing dots,
#: the 63-octet label and 255-octet domain ceilings either side, and non-ASCII.
_DOMAINS: Final = (
    "example.com",
    "EXAMPLE.COM",
    "exa_mple.com",
    "b..c.com",
    "-lead.com",
    "trail-.com",
    "[192.0.2.1]",
    "example.com.",
    "x.io",
    "",
    "b" * 63 + ".com",
    "b" * 64 + ".com",
    ("b" * 61 + ".") * 4 + "bbbbbbbbb.com",
    "\u00fc\u00f1.com",
)


def _hostile_forms() -> tuple[str, ...]:
    """Every combination of the fragments above, plus the degenerate spellings.

    Deterministic and generated rather than listed: what the property below needs
    is breadth across the *rules*, and a hand-written list is exactly what leaves
    the boundary nobody thought of uncovered — which is the pattern this test
    exists to end.
    """
    combined = tuple(f"{local}@{domain}" for local in _LOCAL_PARTS for domain in _DOMAINS)
    return (*combined, "", "no-at-sign", "@", "a@b@c", " ", "\n", "a@b\u0000c.com")


def test_the_fake_never_accepts_a_destination_production_refuses() -> None:
    """The canonical fake may be stricter than the seam, and may never be laxer.

    **This is the one-directional property, and it is the complete formalisation
    of the only hazard in play.** ADR-0152 §13 requires the fake and requires the
    shared conformance suite; it requires nowhere that the fake *equal*
    production, and ADR-0148 §2's one-canonicaliser clause is stated over
    integrations at the seam — so porting the production rules into
    ``ai_assistant.testing`` would create the second copy that clause exists to
    prevent, across a boundary ``lint-imports`` forbids. What actually harms
    anything is a double that certifies a **weaker** seam than the one it stands
    in for: a consumer's test that parks and approves a call production would
    never make. That is precisely ``fake_accepts ⊆ production_accepts``, and the
    safe direction — the fake refusing something production would take — cannot
    mislead a consumer's test in any way, because the call simply does not bind.

    Degeneration in the safe direction is not a hole either: ``CANONICALISES`` in
    the shared suite pins the forms **both** implementations must accept and the
    canonical form each must produce, so a fake that refused everything fails
    there. The two together bound the fake from both sides without either one
    copying the other's rules.

    This module is the only place the property can be stated: the conformance
    suite is shared and each subject runs it alone, whereas this test may import
    ``ai_assistant.testing`` and ``ai_assistant.tools`` together.
    """
    laxer: list[str] = []
    disagreed: list[str] = []
    accepted = 0

    for form in _hostile_forms():
        try:
            by_fake = fake_canonical(form)
        except ValueError:
            continue
        accepted += 1
        try:
            by_seam = canonicalise(SeamProtocol.SMTP, form).canonical
        except DestinationCanonicalisationError:
            laxer.append(form)
            continue
        if by_fake != by_seam:
            disagreed.append(form)

    assert not laxer, (
        f"{len(laxer)} form(s) the canonical fake accepts and the production "
        f"canonicaliser refuses. A fake that binds what the seam would not lets a "
        f"consumer's test park and approve a call production cannot make."
    )
    assert not disagreed, (
        f"{len(disagreed)} form(s) both accept and canonicalise differently, so one "
        f"supplied form has two canonical forms across the Protocol's implementations "
        f"(ADR-0148 §2)."
    )
    assert accepted >= 5, "the corpus must actually reach the accepting path"
