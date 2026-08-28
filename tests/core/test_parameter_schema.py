"""ADR-0145's schema enforcement, from the `core` side.

Most of these pin a *refusal*. The decision's whole value is that a call whose
arguments the declared schema rejects never reaches a permission ruling, a trail
record or a claim — so the evidence is that things do not happen, not that an
exception was raised somewhere.

Two obligations of ADR-0145 §13 are deliberately absent, because they are about a
stage this lane does not own: the selection stage's `INVALID_PARAMETERS` outcome
with nothing committed and the step still `PENDING` (§4, §7), and the seam not
synthesising `INVALID_REQUEST` for a violation (§3). The `core` halves of both are
here — the construction refusal, and the evaluation-failure path's refusal that
names only the exception's type.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING, Any

import pytest
from pydantic import ValidationError

from ai_assistant.core import types as core_types
from ai_assistant.core.logging import redact_sensitive
from ai_assistant.core.types import (
    _MAX_JSON_DEPTH,
    _MAX_REPORTED_VIOLATIONS,
    _MAX_SCHEMA_DEPTH,
    ActionRequest,
    CostBasis,
    DataTier,
    Disposition,
    Idempotency,
    ParameterViolation,
    PermissionDecision,
    PermissionOutcome,
    PermissionRuling,
    Reversibility,
    RiskLevel,
    ToolCost,
    ToolDefinition,
    parameter_violations,
)
from ai_assistant.tools.builtin import CURRENT_TIME
from ai_assistant.tools.send_email import SEND_EMAIL

if TYPE_CHECKING:
    from collections.abc import Mapping

_AT = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
_FREE = ToolCost(basis=CostBasis.FREE)

# The two strings ADR-0145 §8 fixes as the fixtures for the leak it closes: the
# reference implementation renders the first as an argument *value* and the second
# as an argument *key*, verified against jsonschema 4.26.0 on Python 3.14.6.
_ARGUMENT_VALUE = "alice@example.com"
_ARGUMENT_KEY = "X-Secret"

_LEAKY_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {"n": {"type": "integer"}},
    "additionalProperties": False,
}
_LEAKY_PARAMETERS: Mapping[str, Any] = {"n": _ARGUMENT_VALUE, _ARGUMENT_KEY: "anything"}


def _definition(**overrides: object) -> ToolDefinition:
    """Build a valid definition with ``overrides`` applied."""
    fields: dict[str, object] = {
        "id": "smtp",
        "capability": "send_email",
        "description": "Send an email.",
        "risk_level": RiskLevel.HIGH,
        "reversibility": Reversibility.IRREVERSIBLE,
        "side_effecting": True,
        "reads": (DataTier.PERSONAL,),
        "writes": (),
        "discloses": (DataTier.PERSONAL,),
        "cost": _FREE,
        "idempotency": Idempotency.NONE,
    }
    fields.update(overrides)
    return ToolDefinition(**fields)  # type: ignore[arg-type]  # heterogeneous test kwargs


def _nested_schema(levels: int) -> dict[str, Any]:
    """A schema whose JSON document nests exactly ``levels`` containers deep."""
    if levels < 1:
        msg = "a schema document is at least one container deep"
        raise ValueError(msg)
    document: dict[str, Any] = {"type": "object"}
    current = document
    # Each `properties` wrapper plus the subschema it holds is two container
    # levels, so the loop adds two at a time and the root supplies the first.
    while _json_depth(document) + 2 <= levels:
        child: dict[str, Any] = {"type": "object"}
        current["properties"] = {"a": child}
        current = child
    if _json_depth(document) + 1 == levels:
        # An empty `properties` mapping is exactly one more container level, which
        # is what lets the chain land on an even depth as well as an odd one.
        current["properties"] = {}
    return document


def _nested_instance(levels: int) -> dict[str, Any]:
    """A mapping nested to match ``_nested_schema``'s property chain."""
    instance: dict[str, Any] = {}
    current = instance
    while _json_depth(instance) + 1 <= levels:
        child: dict[str, Any] = {}
        current["a"] = child
        current = child
    return instance


def _json_depth(value: object) -> int:
    """Count container nesting the way the production bound does."""
    if isinstance(value, dict):
        return 1 + max((_json_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((_json_depth(item) for item in value), default=0)
    return 0


# --- §1: the refusal is at construction, before anything is spent ------------


def test_an_action_request_is_refused_when_the_arguments_violate_the_schema() -> None:
    """The pairing of a tool and its arguments is where the check lands (§1)."""
    tool = _definition(parameters_schema={"properties": {"n": {"type": "integer"}}})
    with pytest.raises(ValidationError, match="parameters do not satisfy"):
        ActionRequest(tool=tool, parameters={"n": "not an integer"})


def test_an_action_request_is_built_when_the_arguments_satisfy_the_schema() -> None:
    """The refusal discriminates: a conforming payload constructs."""
    tool = _definition(parameters_schema={"properties": {"n": {"type": "integer"}}})
    assert ActionRequest(tool=tool, parameters={"n": 3}).parameters["n"] == 3


def test_no_permission_decision_can_be_made_about_a_refused_request() -> None:
    """The point of §1's placement, asserted as absence rather than as an exception.

    A request that was never built cannot be ruled on, recorded, claimed or
    digested. There is no object to hand :meth:`PermissionDecision.from_request`,
    which is what makes the four costs §1 enumerates unreachable *without anything
    being sequenced correctly*.
    """
    tool = _definition(parameters_schema={"required": ["to"]})
    with pytest.raises(ValidationError):
        ActionRequest(tool=tool, parameters={})

    # And the ruling has nothing to be made about: `from_request` is the only
    # construction path, and it takes a request that does not exist.
    allowed = ActionRequest(tool=tool, parameters={"to": "someone"})
    decision = PermissionDecision.from_request(
        allowed,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="fine"),
        id="d-1",
        decided_at=_AT,
    )
    assert decision.parameters_digest == allowed.parameters_digest


def test_a_revalidated_request_re_runs_the_schema_check() -> None:
    """The seam inherits the check with no fourth step of its own (§1, ADR-0029 §2).

    ADR-0029 §2's step 1 revalidates the whole call through ADR-0018 §4's
    ``model_dump()``/``model_validate()`` idiom, which reconstructs the nested
    request and therefore re-runs this validator. Swapping the parameters past
    ``frozen=True`` is the bypass that idiom exists to catch.
    """
    tool = _definition(parameters_schema={"properties": {"n": {"type": "integer"}}})
    request = ActionRequest(tool=tool, parameters={"n": 3})
    object.__setattr__(request, "__dict__", {**request.__dict__, "parameters": {"n": "wrong"}})

    with pytest.raises(ValidationError, match="parameters do not satisfy"):
        ActionRequest.model_validate(request.model_dump())


# --- §5, §6: one dialect, and a schema that cannot be read does not load ------


def test_a_schema_declaring_draft_07_refuses_the_definition() -> None:
    """Reinterpreting a schema in a dialect its author did not use fails open (§5)."""
    with pytest.raises(ValidationError, match=r"a \$schema other than JSON Schema draft 2020-12"):
        _definition(parameters_schema={"$schema": "http://json-schema.org/draft-07/schema#"})


def test_a_draft_07_array_bound_does_not_load_rather_than_being_read_permissively() -> None:
    """The fail-open case that motivates the dialect refusal, pinned as a rejection (§5).

    ``additionalItems`` is draft-07's array bound and 2020-12 does not know the
    keyword, so reading this schema as 2020-12 would *silently drop* the bound and
    hand the tool a payload its author believed was refused.
    """
    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": {"xs": {"items": {"type": "string"}, "additionalItems": False}},
    }
    with pytest.raises(ValidationError, match="draft 2020-12"):
        _definition(parameters_schema=schema)


def test_a_schema_with_no_dialect_declared_is_read_as_2020_12() -> None:
    """Schemas in the wild overwhelmingly omit ``$schema``; §5 reads those as 2020-12."""
    tool = _definition(parameters_schema={"type": "object", "properties": {"n": {"type": "null"}}})
    assert parameter_violations(tool.parameters_schema, {"n": None}) == ()
    assert parameter_violations(tool.parameters_schema, {"n": 1})[0].keyword == "type"


@pytest.mark.parametrize(
    "declared",
    [
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/schema#",
    ],
)
def test_the_2020_12_dialect_may_be_declared_explicitly(declared: str) -> None:
    """The empty-fragment spelling is the same URI, so accepting it reinterprets nothing."""
    assert _definition(parameters_schema={"$schema": declared}).parameters_schema


def test_an_invalid_schema_refuses_the_definition() -> None:
    """A declaration nobody can evaluate is one nobody can check (§6, ADR-0016 §1)."""
    with pytest.raises(ValidationError, match="not a valid draft 2020-12 schema"):
        _definition(parameters_schema={"type": "not-a-json-type"})


def test_a_root_type_that_excludes_an_object_refuses_the_definition() -> None:
    """Pasting the wrong schema is the mistake an adapter makes; one lookup says so (§6)."""
    with pytest.raises(ValidationError, match="does not admit an object"):
        _definition(parameters_schema={"type": "string"})


def test_a_root_type_listing_object_among_others_is_accepted() -> None:
    """The clause asks that the root ``type`` *admit* an object, not that it name only one."""
    assert _definition(parameters_schema={"type": ["object", "null"]}).parameters_schema


def test_the_object_spelling_of_false_still_loads() -> None:
    """What pins the root-``type`` clause as syntactic and not a satisfiability rule (§6).

    ``{"not": {}}`` is the object spelling of the boolean schema ``false``: no
    object satisfies it. Deciding that in general is not something a construction
    check can do, so it loads and fails visibly on the first call instead.
    """
    tool = _definition(parameters_schema={"not": {}})
    assert parameter_violations(tool.parameters_schema, {})[0].keyword == "not"


# --- §6: the reference model, as refusals and as acceptances -----------------


@pytest.mark.parametrize(
    ("case", "schema"),
    [
        ("external ref", {"properties": {"a": {"$ref": "https://example.com/s"}}}),
        ("non-root $id", {"$defs": {"a": {"$id": "urn:x", "type": "string"}}}),
        ("dynamic ref", {"properties": {"a": {"$dynamicRef": "#m"}}}),
        ("dynamic anchor", {"$defs": {"a": {"$dynamicAnchor": "m", "type": "string"}}}),
        ("dangling fragment", {"properties": {"a": {"$ref": "#/$defs/Absent"}}}),
        ("self reference", {"$ref": "#"}),
        ("two-hop cycle", {"$defs": {"a": {"$ref": "#/$defs/b"}, "b": {"$ref": "#/$defs/a"}}}),
    ],
)
def test_a_schema_breaching_the_reference_model_refuses_the_definition(
    case: str, schema: Mapping[str, Any]
) -> None:
    """Each is refused at *construction*, so no later stage ever meets one (§6).

    The two cycle cases are the ones that must be asserted as construction
    refusals and not merely as calls that fail: a test checking only the outcome
    would pass against an implementation that reaches it by exhausting the stack,
    which is the attack §6's cycle clause exists to remove.
    """
    assert case
    with pytest.raises(ValidationError):
        _definition(parameters_schema=schema)


def test_a_same_document_reference_and_an_anchor_are_accepted() -> None:
    """The model has to be usable, not merely restrictive (§6)."""
    tool = _definition(
        parameters_schema={
            "type": "object",
            "properties": {"a": {"$ref": "#/$defs/name"}, "b": {"$ref": "#tagged"}},
            "$defs": {
                "name": {"type": "string"},
                "tag": {"$anchor": "tagged", "type": "integer"},
            },
        }
    )
    assert parameter_violations(tool.parameters_schema, {"a": "x", "b": 1}) == ()
    assert {one.keyword for one in parameter_violations(tool.parameters_schema, {"a": 1, "b": "x"})}


def test_a_root_id_is_permitted() -> None:
    """``$id`` at the root re-bases nothing a ``#`` reference could reach past (§6)."""
    assert _definition(parameters_schema={"$id": "urn:tool:smtp", "type": "object"})


# --- §6: the check is computed once per document and given at every construction


def _counting_defect(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count calls to the memoised check, returning a one-element tally."""
    tally = [0]
    real = core_types._schema_defect

    def counted(schema: Mapping[str, Any], /) -> str | None:
        tally[0] += 1
        return real(schema)

    monkeypatch.setattr(core_types, "_schema_defect", counted)
    core_types._readable_schemas.clear()
    return tally


def test_a_second_construction_of_one_schema_is_meta_validated_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check is memoised on the document, which is the whole of #1758's fix (§6).

    Counted rather than timed, because a wall-clock assertion on a loaded machine
    is a flake and the count is the property the timing was evidence of. If a
    later change makes the key vary per construction — an object identity, an
    instance counter — the answers stay correct and the recomputation comes back,
    and only this case notices.
    """
    tally = _counting_defect(monkeypatch)
    schema = {"type": "object", "properties": {"memoised": {"type": "integer"}}}

    assert _definition(parameters_schema=schema).parameters_schema
    assert tally == [1]

    assert _definition(parameters_schema=dict(schema)).parameters_schema
    assert tally == [1]

    assert _definition(parameters_schema={"type": "object"}).parameters_schema
    assert tally == [2]


def test_a_refusal_is_recomputed_every_time_and_is_verbatim_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The memo remembers a *readable* answer only, and a refusal is unchanged by it.

    A reason is rendered from the document — ``SchemaError.json_path`` names where
    the metaschema failed — so it is not a bounded string and remembering it would
    bound entries without bounding memory. Recomputing it costs nothing that
    matters, because a schema that refuses builds no definition and so has no
    repeat construction to be a hot path for, and it keeps the memo's one
    direction fail-closed: it can say a document was readable and can never say
    one was refused.
    """
    tally = _counting_defect(monkeypatch)
    schema = {"type": "not-a-json-type"}

    with pytest.raises(ValidationError) as first:
        _definition(parameters_schema=schema)
    with pytest.raises(ValidationError) as second:
        _definition(parameters_schema=dict(schema))

    assert str(first.value) == str(second.value)
    assert tally == [2]
    assert core_types._readable_schemas == set()


def test_a_provider_authored_reason_is_never_retained(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reason a refusal renders is unbounded, so nothing keeps one (§6, §7).

    ``SchemaError.json_path`` carries the failing keyword's location, so a
    property name a provider made 200 kB long comes back inside the reason. The
    message is unchanged — it is the diagnostic a tool author needs — and it is
    simply not remembered.
    """
    _counting_defect(monkeypatch)
    sprawling = "x" * 200_000
    schema: Mapping[str, Any] = {"properties": {sprawling: {"type": "not-a-json-type"}}}

    reason = core_types._unreadable_schema_reason(schema)

    assert reason is not None
    assert sprawling in reason  # the diagnostic still names where it failed
    assert core_types._readable_schemas == set()


def test_a_bool_and_the_int_it_equals_are_two_schemas_and_not_one() -> None:
    """Why the memo is keyed on the canonical encoding rather than the frozen value.

    ``True == 1`` and ``hash(True) == hash(1)`` in Python, so a memo keyed on the
    ``FrozenDict``'s own equality would answer ``{"minLength": True}`` from
    ``{"minLength": 1}``'s entry — and jsonschema's ``integer`` type check
    excludes ``bool``, so the second is a schema §6 accepts and the first is one
    it refuses. ADR-0021 §1's encoding spells them ``true`` and ``1``.

    Run in both orders, because a key that conflates them fails in whichever
    direction is asked second and only one of the two orders is the dangerous
    one — the accepted schema laundering the refused one.
    """
    readable: Mapping[str, Any] = {"type": "object", "properties": {"n": {"minLength": 1}}}
    unreadable: Mapping[str, Any] = {"type": "object", "properties": {"n": {"minLength": True}}}
    assert readable == unreadable  # the Python-value equality a hash key would use

    core_types._readable_schemas.clear()
    assert _definition(parameters_schema=readable).parameters_schema
    with pytest.raises(ValidationError, match="not a valid draft 2020-12 schema"):
        _definition(parameters_schema=unreadable)

    core_types._readable_schemas.clear()
    with pytest.raises(ValidationError, match="not a valid draft 2020-12 schema"):
        _definition(parameters_schema=unreadable)
    assert _definition(parameters_schema=readable).parameters_schema


def test_a_definition_mutated_past_its_guard_is_still_refused_on_revalidation() -> None:
    """The memo does not launder the corruption route §6's revalidation clause closes.

    A definition whose ``parameters_schema`` is swapped through
    ``object.__setattr__`` keeps its object identity and loses its canonical
    encoding, so the mutated document digests differently, misses the entry the
    original filled and is meta-validated afresh. Assigning the definition to a
    model-typed field re-runs the ``after`` model validator, which is the
    revalidation ADR-0029 §2's step 1 and ADR-0018 §4 already perform.
    """
    tool = _definition(parameters_schema={"type": "object"})
    object.__setattr__(tool, "__dict__", {**tool.__dict__, "parameters_schema": {"type": "string"}})

    with pytest.raises(ValidationError, match="does not admit an object"):
        ActionRequest(tool=tool, parameters={})


def test_a_schema_with_no_canonical_encoding_is_answered_unmemoised() -> None:
    """A document the key cannot be built from is answered as it was before the memo.

    Pydantic refuses a ``parameters_schema`` holding a value with no JSON encoding
    long before this validator sees one, so the only way here is the corrupted
    instance above. The answer must be the one the checks give, not an exception
    from the encoder standing in for it, and nothing may be remembered under a key
    that could not be computed.
    """
    corrupted: Mapping[str, Any] = {"unknown-keyword": object()}
    core_types._readable_schemas.clear()

    assert core_types._unreadable_schema_reason(corrupted) is None
    assert core_types._readable_schemas == set()


def test_the_memo_is_bounded_so_a_stream_of_schemas_cannot_grow_it() -> None:
    """The documents are provider-authored, so the memo holds a fixed number (§6, §7)."""
    core_types._readable_schemas.clear()
    for index in range(core_types._MAX_CACHED_SCHEMAS + 20):
        assert _definition(
            parameters_schema={"type": "object", "properties": {f"p{index}": {}}}
        ).parameters_schema

    assert 0 < len(core_types._readable_schemas) <= core_types._MAX_CACHED_SCHEMAS


def test_the_memo_is_read_and_written_only_under_its_lock() -> None:
    """What makes the bound a bound rather than a typical outcome (§6, §7).

    Testing the capacity and adding are one critical section because separately
    they are not: several threads observing one short of the bound each add a
    distinct digest and the memo ends above it. This repository runs store work in
    threads (``_run_to_completion``), so the single-threaded reading is not the one
    to hold the claim to.

    Asserted by holding the lock and watching a construction fail to finish: with
    the lock taken, no construction can reach either the lookup or the insert, so
    the wait times out and the memo is still empty. Verified to discriminate —
    with both critical sections removed this case fails, and it fails in the safe
    direction, since a box slow enough to take a quarter-second over one
    meta-validation would stop it discriminating rather than start it flaking.
    """
    core_types._readable_schemas.clear()
    finished = threading.Event()

    def build() -> None:
        _definition(parameters_schema={"type": "object", "properties": {"locked": {}}})
        finished.set()

    worker = threading.Thread(target=build)
    with core_types._schema_memo_lock:
        worker.start()
        assert not finished.wait(0.25)
        assert core_types._readable_schemas == set()

    worker.join(timeout=10)
    assert finished.is_set()
    assert len(core_types._readable_schemas) == 1


def test_the_memo_retains_no_part_of_the_document_it_answers_about() -> None:
    """The entry bound is a memory bound only because an entry is a fixed size (§7).

    A ``parameters_schema`` is bounded in depth and in neither breadth nor bytes,
    so a memo holding documents would bound entries without bounding memory and
    would keep a provider's schemas alive past the definitions that carried them.
    What is held is a ``sha256`` digest and nothing else — asserted, because "we
    do not retain it" is exactly the kind of claim a later refactor reintroducing
    a document-shaped key would silently break.
    """
    core_types._readable_schemas.clear()
    bulky = {"type": "object", "$comment": "x" * 100_000}
    assert _definition(parameters_schema=bulky).parameters_schema

    assert [len(digest) for digest in core_types._readable_schemas] == [sha256().digest_size]


# --- §6: the depth bound, measured rather than asserted ----------------------


def test_a_schema_at_the_depth_bound_constructs_and_one_level_deeper_is_refused() -> None:
    """The bound is enforced, and enforced at the level it claims (§6)."""
    at_bound = _nested_schema(_MAX_SCHEMA_DEPTH)
    assert _json_depth(at_bound) == _MAX_SCHEMA_DEPTH
    assert _definition(parameters_schema=at_bound).parameters_schema

    too_deep = {"properties": {"a": at_bound}}
    assert _json_depth(too_deep) == _MAX_SCHEMA_DEPTH + 2
    with pytest.raises(ValidationError, match="nests deeper than"):
        _definition(parameters_schema=too_deep)


def test_the_schema_bound_sits_strictly_inside_the_frozen_json_ceiling() -> None:
    """Two constants whose ordering matters are two constants somebody can invert.

    ``parameters_schema`` is itself a ``FrozenJsonMapping``, so ADR-0196 §1's
    ingress check runs on it as a field validator — before the model validator
    that reads it as a schema. If the two bounds were equal, or if a later lane
    raised this one past the ceiling, the ingress would refuse every schema §6
    means to refuse, §6's message would become unreachable, its check would be
    dead code, and a tool author would be told about the wrong bound. This is the
    only mechanical guard on that (ADR-0196 §4 and §5(c)); no reader of either
    file would see the change otherwise.

    Ordering the two — tighter bound inside looser — is what keeps each refusal
    saying the thing it knows: evaluation spends more stack per level than
    freezing does, so the document that is *evaluated* is bounded more tightly
    than the value that is merely *frozen*.
    """
    assert _MAX_SCHEMA_DEPTH < _MAX_JSON_DEPTH

    between = _nested_schema(_MAX_SCHEMA_DEPTH + 2)
    assert _MAX_SCHEMA_DEPTH < _json_depth(between) <= _MAX_JSON_DEPTH
    with pytest.raises(ValidationError) as refusal:
        _definition(parameters_schema=between)
    assert "nests deeper than" in str(refusal.value)
    assert "nests containers deeper than" not in str(refusal.value)


def test_a_schema_past_the_frozen_json_ceiling_is_refused_by_the_ingress() -> None:
    """Past the looser bound the ingress answers first, and says so (ADR-0196 §1).

    The schema check never sees it: the field validator runs before the model
    validator. That is the right way round — a schema that deep is refused as a
    *value* before anything tries to read it as a document — and it is why §4
    only requires the band between the two bounds to reach §6.
    """
    past: dict[str, Any] = {"type": "object"}
    for _ in range(_MAX_JSON_DEPTH):
        past = {"properties": {"a": past}}
    with pytest.raises(ValidationError, match="nests containers deeper than"):
        _definition(parameters_schema=past)


def test_a_schema_at_the_depth_bound_evaluates_within_the_recursion_limit() -> None:
    """A bound nobody checked against the recursion limit is a number, not a guarantee (§6).

    §6 requires the constant to be "fixed low enough that evaluating a schema at
    the bound against an instance of comparable depth completes well inside the
    interpreter's recursion limit". This measures the headroom rather than
    asserting it: the evaluation runs under a limit cut to a fraction of the
    default and still completes.
    """
    schema = _nested_schema(_MAX_SCHEMA_DEPTH)
    instance = _nested_instance(_MAX_SCHEMA_DEPTH)
    assert _json_depth(instance) >= _MAX_SCHEMA_DEPTH - 1

    original = sys.getrecursionlimit()
    sys.setrecursionlimit(400)
    try:
        assert parameter_violations(schema, instance) == ()
    finally:
        sys.setrecursionlimit(original)


# --- §7: no I/O, nothing modified, and a raise is a refusal ------------------


def test_the_evaluator_raises_rather_than_retrieving_an_external_reference() -> None:
    """The belt tested without the brace (§7, §13).

    §6's construction check is what stops an external ``$ref`` ever reaching an
    evaluator, so this goes around it and hands one to the evaluator directly. A
    validator that fetched would be an unauthorised egress performed from ``core``
    (ADR-0004 §2, ADR-0017 §1), and it would make what a call may contain depend on
    a document a third party can change between one call and the next. The host is
    in the reserved ``.invalid`` TLD, so a run that *did* retrieve would fail
    loudly rather than reach anything.
    """
    with pytest.raises(Exception, match=r"[Uu]nresolvable|resolve|[Rr]etriev"):
        parameter_violations({"$ref": "https://example.invalid/schema"}, {"a": 1})


def test_a_schema_default_is_not_applied_and_the_digest_is_unchanged() -> None:
    """Filling a default would change the arguments after the caller chose them (§7)."""
    tool = _definition(
        parameters_schema={
            "type": "object",
            "properties": {"n": {"type": "integer", "default": 7}},
        }
    )
    before = ActionRequest(tool=_definition(), parameters={"other": 1}).parameters_digest
    request = ActionRequest(tool=tool, parameters={"other": 1})

    assert "n" not in request.parameters
    assert request.parameters_digest == before
    assert parameter_violations(tool.parameters_schema, request.parameters) == ()
    assert request.parameters_digest == before


def test_an_evaluation_that_raises_refuses_and_names_only_the_exception_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No evaluation failure is ever read as a pass, and none of it is rendered (§7).

    A fake evaluator that raises, because the real one only raises on documents
    §6 refuses at construction. The exception's ``str()``, ``args`` and
    ``__notes__`` each carry a distinctive argument value, because a failure path
    exempted from §8 would be the one path on which an untrusted schema could make
    the leak happen on demand: publish a schema that raises, and the argument
    values arrive in the log.
    """

    class _Exploding:
        """Stands where the evaluator stands, and blows up where it would walk."""

        def __init__(self, _schema: object) -> None:
            pass

        @staticmethod
        def check_schema(_schema: object) -> None:
            """The construction check is not what this fixture is about."""

        def iter_errors(self, _instance: object) -> object:
            error = RuntimeError(f"walking {_ARGUMENT_VALUE}")
            error.add_note(f"note naming {_ARGUMENT_VALUE}")
            raise error

    monkeypatch.setattr(core_types, "Draft202012Validator", _Exploding)
    tool = _definition(
        parameters_schema={"type": "object", "properties": {"n": {"type": "string"}}}
    )

    with pytest.raises(ValidationError) as raised:
        ActionRequest(tool=tool, parameters={"n": _ARGUMENT_VALUE})

    rendered = str(raised.value)
    assert _ARGUMENT_VALUE not in rendered
    assert "note naming" not in rendered
    assert "walking" not in rendered
    assert "RuntimeError" in rendered
    assert raised.value.__cause__ is None


def test_an_evaluation_that_raises_yields_no_violation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The violations an evaluation failure yields are none rather than partial (§7)."""

    class _Exploding:
        def __init__(self, _schema: object) -> None:
            pass

        @staticmethod
        def check_schema(_schema: object) -> None:
            """The construction check is not what this fixture is about."""

        def iter_errors(self, _instance: object) -> object:
            raise RecursionError

    monkeypatch.setattr(core_types, "Draft202012Validator", _Exploding)
    with pytest.raises(RecursionError):
        parameter_violations({"type": "object"}, {"n": 1})


# --- §8: no message renders any part of the arguments ------------------------


def test_a_violation_carries_neither_an_argument_value_nor_an_argument_key() -> None:
    """The sharpest hazard in the decision, pinned with §8's own two fixtures.

    The reference implementation renders ``'alice@example.com' is not of type
    'integer'`` and ``Additional properties are not allowed ('X-Secret' was
    unexpected)``. Neither string may survive into a violation, a rendering or a
    log record — ``core/logging.py`` redacts by *key*, and its own docstring names
    an interpolated message as the leak it cannot see (ADR-0029 §3).
    """
    violations = parameter_violations(_LEAKY_SCHEMA, _LEAKY_PARAMETERS)
    assert {one.keyword for one in violations} == {"type", "additionalProperties"}

    for one in violations:
        serialised = json.dumps(one.model_dump(mode="json"))
        assert _ARGUMENT_VALUE not in serialised
        assert _ARGUMENT_KEY not in serialised


def test_the_construction_refusal_renders_neither_an_argument_value_nor_a_key() -> None:
    """The rendering half of §8's obligation: the message a caller actually sees."""
    tool = _definition(parameters_schema=_LEAKY_SCHEMA)
    with pytest.raises(ValidationError) as raised:
        ActionRequest(tool=tool, parameters=_LEAKY_PARAMETERS)

    rendered = str(raised.value)
    assert _ARGUMENT_VALUE not in rendered
    assert _ARGUMENT_KEY not in rendered
    assert "additionalProperties" in rendered


def test_a_logged_violation_leaks_neither_the_value_nor_the_key() -> None:
    """The log-record half of §8's obligation, through the real redaction net."""
    violations = parameter_violations(_LEAKY_SCHEMA, _LEAKY_PARAMETERS)
    event = dict(
        redact_sensitive(
            None,
            "info",
            {"event": "parameters refused", "violations": [v.model_dump() for v in violations]},
        )
    )
    rendered = repr(event)
    assert _ARGUMENT_VALUE not in rendered
    assert _ARGUMENT_KEY not in rendered


def test_a_path_names_a_property_the_schema_names_and_elides_one_it_does_not() -> None:
    """§8's path rule, in both directions.

    A key the schema names is schema-side text and is rendered; a key it does not
    name can be an address or an identifier, so it is elided rather than
    reproduced. ``patternProperties`` keys are patterns, not names, which is why
    the matched key is elided even though the schema constrained it.
    """
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"declared": {"type": "integer"}},
        "patternProperties": {"^x-": {"type": "integer"}},
    }
    named = parameter_violations(schema, {"declared": "no"})
    assert [one.path for one in named] == ["/declared"]

    unnamed = parameter_violations(schema, {f"x-{_ARGUMENT_VALUE}": "no"})
    assert [one.path for one in unnamed] == ["/<elided>"]
    assert _ARGUMENT_VALUE not in repr(unnamed)


def test_a_violation_carries_the_schemas_own_value_for_the_failing_keyword() -> None:
    """The three schema-side facts §8 permits, and correction needs no echo (§8)."""
    (violation,) = parameter_violations(
        {"properties": {"n": {"type": "integer", "minimum": 5}}}, {"n": 1}
    )
    assert violation == ParameterViolation(path="/n", keyword="minimum", schema_value=5)


# --- §8: all violations, deterministically ordered, truncation stated --------


def test_every_violation_is_reported_in_a_deterministic_order() -> None:
    """One at a time turns a correction into a sequence of round trips (§8)."""
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
            "c": {"type": "integer"},
        },
        "required": ["missing"],
    }
    parameters: Mapping[str, Any] = {"a": "x", "b": "y", "c": "z"}
    first = parameter_violations(schema, parameters)

    assert len(first) == 4
    assert [one.path for one in first] == ["", "/a", "/b", "/c"]
    assert first == parameter_violations(schema, parameters)


def test_a_truncated_report_says_so_rather_than_truncating_silently() -> None:
    """A silently truncated list makes a caller believe it has fixed everything (§8)."""
    count = _MAX_REPORTED_VIOLATIONS + 5
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {f"p{index:04d}": {"type": "integer"} for index in range(count)},
    }
    parameters: Mapping[str, Any] = {f"p{index:04d}": "no" for index in range(count)}
    violations = parameter_violations(schema, parameters)

    assert len(violations) == _MAX_REPORTED_VIOLATIONS + 1
    assert violations[-1].keyword == "<truncated>"
    assert violations[-1].schema_value == count
    assert all(one.keyword == "type" for one in violations[:-1])


def test_the_cap_bounds_the_work_and_not_only_the_report() -> None:
    """The cap is a real bound, not a slice taken after the cost was paid (§8).

    A schema over an array of failing items yields one error per item, so a
    report capped *after* every violation had been built and sorted would exhaust
    memory on the way to a refusal — on a path every tool call takes, over a
    document an untrusted server authored. Counting the models actually
    constructed is what tells the two implementations apart; asserting the length
    of the result cannot, because both produce the same list.

    The evaluation's own cost still scales with the instance. That is #1108's,
    parked by ADR-0145 §14, and this pins the half that was this decision's.
    """
    built = 0
    real = core_types.ParameterViolation

    class _Counting(real):  # type: ignore[valid-type, misc]  # a frozen model subclass
        def __init__(self, **fields: Any) -> None:
            nonlocal built
            built += 1
            super().__init__(**fields)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(core_types, "ParameterViolation", _Counting)
    try:
        errors = _MAX_REPORTED_VIOLATIONS * 50
        schema: Mapping[str, Any] = {
            "type": "object",
            "properties": {"xs": {"type": "array", "items": {"type": "integer"}}},
        }
        violations = parameter_violations(schema, {"xs": ["no"] * errors})
    finally:
        monkeypatch.undo()

    assert len(violations) == _MAX_REPORTED_VIOLATIONS + 1
    assert violations[-1].schema_value == errors
    assert built == _MAX_REPORTED_VIOLATIONS + 1


def test_a_truncated_report_is_a_stable_prefix_of_the_whole_ordering() -> None:
    """What survives the cap is the deterministic first N, not the first N seen (§8)."""
    count = _MAX_REPORTED_VIOLATIONS + 20
    schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {f"p{index:04d}": {"type": "integer"} for index in range(count)},
    }
    parameters: Mapping[str, Any] = {f"p{index:04d}": "no" for index in range(count)}
    violations = parameter_violations(schema, parameters)

    assert [one.path for one in violations[:-1]] == [
        f"/p{index:04d}" for index in range(_MAX_REPORTED_VIOLATIONS)
    ]
    assert violations == parameter_violations(schema, parameters)


# --- §9: an absent schema declares no constraint -----------------------------


def test_an_empty_schema_accepts_every_mapping_including_one_with_keys() -> None:
    """The field's default declares *no constraint*, and that is not an error (§9)."""
    tool = _definition()
    assert tool.parameters_schema == {}
    assert parameter_violations(tool.parameters_schema, {"anything": [1, {"deep": True}]}) == ()
    assert ActionRequest(tool=tool, parameters={"anything": 1}).parameters["anything"] == 1


def test_an_empty_schema_is_distinguishable_from_checked_and_passed() -> None:
    """ "No constraint" is not a claim that the arguments were checked (§9).

    The two are told apart by the declaration, not by the result: both report no
    violations, and only the schema says whether anything was asked of them.
    """
    absent = _definition()
    declared = _definition(parameters_schema={"type": "object", "required": ["to"]})

    assert parameter_violations(absent.parameters_schema, {"to": "x"}) == ()
    assert parameter_violations(declared.parameters_schema, {"to": "x"}) == ()
    assert not absent.parameters_schema
    assert declared.parameters_schema


# --- §6, §13: today's shipped definitions still load -------------------------


def test_todays_shipped_definitions_still_load() -> None:
    """The corpus this decision lands on is not refused by it (§6, §13).

    Imported rather than restated: a copy of these schemas would drift silently,
    which is the thing this check exists to catch. The pair is ``current_time`` and
    ``send_email`` since ADR-0208 §2 deleted ``recall_memory``, and ``send_email``
    carries the richer of the two schemas — a nested array with an item pattern —
    so the corpus this asserts over is no thinner than it was.
    """
    for tool in (CURRENT_TIME, SEND_EMAIL):
        assert ToolDefinition.model_validate(tool.model_dump()) == tool


def test_a_stored_decision_carrying_a_definition_with_parameters_round_trips() -> None:
    """A record whose tool carried a refused schema would become unreadable (§6).

    The definition is **constructed here** rather than imported, which is ADR-0208
    §2's instruction for a test needing a definition with parameters: what this case
    needs is any tool declaring a parameters schema, and borrowing a shipped one
    would make the case fail whenever that tool's own arguments changed.
    """
    request = ActionRequest(
        tool=_definition(
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"],
                "additionalProperties": False,
            }
        ),
        parameters={"query": "when", "limit": 3},
    )
    decision = PermissionDecision.from_request(
        request,
        PermissionRuling(outcome=PermissionOutcome.ALLOW, reason="read-only"),
        id="d-1",
        decided_at=_AT,
    )
    assert PermissionDecision.model_validate(decision.model_dump(mode="json")) == decision


# --- §4: the disposition the stage returns -----------------------------------


def test_disposition_gains_invalid_parameters_as_an_additive_wire_value() -> None:
    """One member, one value string, and every existing string byte-identical (§4)."""
    assert Disposition.INVALID_PARAMETERS.value == "invalid_parameters"
    assert Disposition("invalid_parameters") is Disposition.INVALID_PARAMETERS
    assert {member.value for member in Disposition} == {
        "executed",
        "denied",
        "awaiting_confirmation",
        "no_capable_tool",
        "ambiguous_capability",
        "invalid_parameters",
        # ADR-0152 §9's addition. It is listed because this assertion is a closure
        # over the enum rather than a claim about ADR-0145's own member: adding a
        # member is additive on the wire for the reason ADR-0145 §4 gives
        # (ADR-0084 §4), and what this still pins is that no *existing* value
        # string moved when one arrived.
        "egress_unbindable",
    }
