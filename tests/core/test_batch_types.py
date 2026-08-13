"""The batch seam's types, annotations and boundaries (ADR-0143 §§1, 5, 8, 9).

The rows of ADR-0143 §13's table that are not behavioural — what was added, how it
is spelled, what it is bound to, and where it is not allowed to reach. Each test
names its clause, so the table can be walked rather than the file.

The **annotations** are asserted as the literal strings the modules declare, not
as the objects pydantic resolves them to. ``core/types.py`` and
``core/protocols.py`` both carry ``from __future__ import annotations``, so their
``__annotations__`` are the spellings an author wrote — and the spelling is what
§9 fixes. A test against the resolved object could not tell
:data:`NonBlankEncodableText` from :data:`Identifier` at all: both erase to ``str``
with metadata, which is exactly the distinction §9 says is load-bearing.
"""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from ai_assistant.core import errors, protocols, types
from ai_assistant.core.errors import (
    ModelAuthError,
    ModelContentFilterError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelUnavailableError,
)
from ai_assistant.core.protocols import BatchCompleter, ModelProvider
from ai_assistant.core.types import (
    BatchFailureKind,
    BatchHandle,
    BatchItemFailure,
    BatchItemOutcome,
    BatchOutcomeKind,
    BatchRequest,
    BatchState,
    BatchStatus,
    Message,
    Role,
)

_SRC: Final = Path(__file__).resolve().parents[2] / "src" / "ai_assistant"

#: The eight public names ADR-0143 §9 permits the implementing lane to add, and no
#: ninth. The section caps the count in as many words — "No other public name is
#: added to ``core/types.py`` by that lane" — so that a large file cannot quietly
#: grow by one more type per round.
_THE_EIGHT: Final = frozenset(
    {
        "BatchRequest",
        "BatchHandle",
        "BatchState",
        "BatchStatus",
        "BatchOutcomeKind",
        "BatchItemOutcome",
        "BatchFailureKind",
        "BatchItemFailure",
    }
)

#: The annotation §9 fixes for every field of the eight types, spelled exactly.
_FIELD_ANNOTATIONS: Final[dict[type, dict[str, str]]] = {
    BatchRequest: {
        "item_id": "NonBlankEncodableText",
        "messages": "Sequence[Message]",
    },
    BatchHandle: {
        "batch_key": "NonBlankEncodableText",
        "batch_id": "NonBlankEncodableText",
        "issuer": "NonBlankEncodableText",
        "submitted_at": "UtcInstant",
    },
    BatchStatus: {
        "handle": "BatchHandle",
        "state": "BatchState",
        "total": "int",
        "settled": "int",
        "results_expire_at": "UtcInstant | None",
    },
    BatchItemOutcome: {
        "item_id": "NonBlankEncodableText",
        "kind": "BatchOutcomeKind",
        "message": "Message | None",
        "failure": "BatchItemFailure | None",
    },
    BatchItemFailure: {
        "kind": "BatchFailureKind",
        "detail": "EncodableText",
    },
}

#: The annotation §9 fixes for each parameter and return of the three members.
_MEMBER_SIGNATURES: Final[dict[str, dict[str, str]]] = {
    "submit": {
        "batch_key": "NonBlankEncodableText",
        "items": "Sequence[BatchRequest]",
        "model": "str | None",
        "return": "BatchHandle",
    },
    "poll": {"handle": "BatchHandle", "return": "BatchStatus"},
    "fetch": {"handle": "BatchHandle", "return": "Sequence[BatchItemOutcome]"},
}

#: What ADR-0143 §5 pairs each failure kind with in ``core/errors.py``. ``None``
#: means the kind corresponds to no class and takes ADR-0066 §3's disposition for
#: a malformed request instead — the two gaps §5 records as decisions rather than
#: omissions.
_ERROR_CLASS_BY_KIND: Final[dict[BatchFailureKind, type[ModelError] | None]] = {
    BatchFailureKind.AUTHENTICATION: ModelAuthError,
    BatchFailureKind.RATE_LIMITED: ModelRateLimitError,
    BatchFailureKind.UNAVAILABLE: ModelUnavailableError,
    BatchFailureKind.CONTENT_FILTER: ModelContentFilterError,
    BatchFailureKind.UNUSABLE_RESPONSE: ModelResponseError,
    BatchFailureKind.UNKNOWN: ModelError,
    BatchFailureKind.INVALID_REQUEST: None,
}

_VENDOR_PACKAGES: Final = ("anthropic", "openai", "pydantic_ai", "tiktoken", "httpx")


def _imported_roots(path: Path) -> set[str]:
    """Every top-level package name ``path`` imports, at module scope or below."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".", 1)[0])
    return roots


class TestWhatTheLaneAdded:
    """§1 and §9: the Protocol is a sibling, and the types are exactly eight."""

    def test_model_provider_still_declares_exactly_complete(self) -> None:
        declared = {
            name
            for name in vars(ModelProvider)
            if not name.startswith("_") and callable(getattr(ModelProvider, name, None))
        }
        assert declared == {"complete"}, (
            "ADR-0143 §1 adds no member to ModelProvider. A new member on a "
            "structural Protocol silently unsatisfies every existing implementation "
            "and every test double at once, and — since ModelProvider is "
            "@runtime_checkable — changes what isinstance answers about all of them"
        )

    def test_batch_completer_does_not_inherit_from_model_provider(self) -> None:
        assert not issubclass(BatchCompleter, ModelProvider), (
            "a sibling, not a specialisation: an object may implement both, and "
            "nothing requires that it does (ADR-0143 §1)"
        )

    def test_exactly_eight_public_batch_names_were_added_to_core_types(self) -> None:
        public = {
            name
            for name, value in vars(types).items()
            if name.startswith("Batch") and not name.startswith("_") and isinstance(value, type)
        }
        assert public == set(_THE_EIGHT)

    @pytest.mark.parametrize("name", sorted(_THE_EIGHT))
    def test_each_of_the_eight_is_reachable_from_the_module(self, name: str) -> None:
        # `core/types.py` declares no `__all__`; a name is exported by being
        # declared at module scope, which is the convention every other type in
        # the file follows.
        assert getattr(types, name).__module__ == types.__name__


class TestTheAnnotationsAreTheOnesRatified:
    """§9: every field and every member signature, spelled as the ADR fixes it."""

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            pytest.param(model, expected, id=model.__name__)
            for model, expected in _FIELD_ANNOTATIONS.items()
        ],
    )
    def test_each_model_declares_the_annotations_the_adr_fixed(
        self, model: type, expected: dict[str, str]
    ) -> None:
        assert model.__annotations__ == expected

    @pytest.mark.parametrize(("member", "expected"), sorted(_MEMBER_SIGNATURES.items()))
    def test_each_member_declares_the_signature_the_adr_fixed(
        self, member: str, expected: dict[str, str]
    ) -> None:
        signature = inspect.signature(getattr(BatchCompleter, member))
        declared = {
            name: parameter.annotation
            for name, parameter in signature.parameters.items()
            if name != "self"
        }
        declared["return"] = signature.return_annotation
        assert declared == expected

    def test_the_model_override_is_keyword_only_and_defaults_to_none(self) -> None:
        model = inspect.signature(BatchCompleter.submit).parameters["model"]
        assert model.kind is inspect.Parameter.KEYWORD_ONLY
        assert model.default is None

    def test_no_annotation_is_any_or_names_a_vendor_or_models_type(self) -> None:
        spellings = [
            annotation
            for group in (*_FIELD_ANNOTATIONS.values(), *_MEMBER_SIGNATURES.values())
            for annotation in group.values()
        ]
        for annotation in spellings:
            assert "Any" not in annotation
            assert "models" not in annotation
            for vendor in _VENDOR_PACKAGES:
                assert vendor not in annotation

    def test_the_identity_fields_are_never_normalised(self) -> None:
        # `Identifier` is the obvious choice and is wrong here: its validator
        # "reject[s] a blank identifier, returning it stripped", and §4 has the
        # caller matching outcomes to requests by `item_id`, which a normalisation
        # on one side of the round trip quietly breaks.
        padded = "  padded  "
        assert BatchRequest(item_id=padded, messages=[_a_turn()]).item_id == padded
        handle = BatchHandle(
            batch_key=padded, batch_id=padded, issuer=padded, submitted_at=_AN_INSTANT
        )
        assert (handle.batch_key, handle.batch_id, handle.issuer) == (padded, padded, padded)

    def test_a_blank_item_id_is_still_refused(self) -> None:
        with pytest.raises(ValueError, match="blank"):
            BatchRequest(item_id="   ", messages=[_a_turn()])

    @pytest.mark.parametrize("field", ["batch_key", "batch_id", "issuer"])
    def test_a_blank_handle_field_is_still_refused(self, field: str) -> None:
        # `NonBlankEncodableText` drops `Identifier`'s *normalising* half and keeps
        # its *rejecting* half: a value copied between two fields must compare
        # equal to its source, and a value naming nothing legible is still refused.
        fields = {"batch_key": "k", "batch_id": "b", "issuer": "i"} | {field: "   "}
        with pytest.raises(ValueError, match="blank"):
            BatchHandle(
                batch_key=fields["batch_key"],
                batch_id=fields["batch_id"],
                issuer=fields["issuer"],
                submitted_at=_AN_INSTANT,
            )


class TestTheDispositionsMirrorModelError:
    """§5: seven kinds, exhaustively mapped, matching ``core/errors.py`` class by class."""

    def test_the_correspondence_is_exhaustive_over_the_enum(self) -> None:
        assert set(_ERROR_CLASS_BY_KIND) == set(BatchFailureKind)

    @pytest.mark.parametrize("kind", list(BatchFailureKind))
    def test_each_kind_takes_its_error_classs_two_flags(self, kind: BatchFailureKind) -> None:
        error_class = _ERROR_CLASS_BY_KIND[kind]
        if error_class is None:
            # ADR-0066 §3's disposition for a malformed request: it reproduces
            # identically on every attempt from every route.
            assert not kind.retryable
            assert not kind.routable
            return
        assert kind.retryable is error_class.retryable
        assert kind.routable is error_class.routable

    def test_a_kind_with_no_declared_disposition_raises_rather_than_defaulting(self) -> None:
        # The mapping is read by identity, so a member added without an entry has
        # no value to fall back on — loud by construction, as `ToolFailureKind`
        # already is, because a default would let a new kind acquire a retry
        # policy nobody chose.
        for mapping_name in ("_BATCH_RETRYABLE_BY_KIND", "_BATCH_ROUTABLE_BY_KIND"):
            mapping = getattr(types, mapping_name)
            assert set(mapping) == set(BatchFailureKind), mapping_name

    def test_there_is_no_counterpart_to_a_model_timeout(self) -> None:
        assert not any("TIME" in kind.name for kind in BatchFailureKind), (
            "a batch item has no per-request deadline of its own; the only clock "
            "over it is the processing window, whose exhaustion is the EXPIRED "
            "outcome and not a failure (ADR-0143 §5)"
        )


class TestTheValidatorsBindWhatTheAdrBinds:
    """§9: the two cross-field rules, both directions each."""

    def test_a_status_may_not_settle_more_items_than_it_holds(self) -> None:
        with pytest.raises(ValueError, match="exceed"):
            BatchStatus(handle=_A_HANDLE, state=BatchState.COMPLETE, total=2, settled=3)

    def test_a_complete_status_must_be_fully_settled(self) -> None:
        with pytest.raises(ValueError, match="COMPLETE"):
            BatchStatus(handle=_A_HANDLE, state=BatchState.COMPLETE, total=3, settled=1)

    def test_a_fully_settled_status_may_not_call_itself_pending(self) -> None:
        with pytest.raises(ValueError, match="COMPLETE"):
            BatchStatus(handle=_A_HANDLE, state=BatchState.PENDING, total=3, settled=3)

    def test_no_progress_reported_on_a_pending_batch_is_accepted(self) -> None:
        status = BatchStatus(handle=_A_HANDLE, state=BatchState.PENDING, total=9, settled=0)
        assert status.settled == 0

    def test_a_batch_of_nothing_has_no_status_to_report(self) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            BatchStatus(handle=_A_HANDLE, state=BatchState.PENDING, total=0, settled=0)

    @pytest.mark.parametrize("kind", list(BatchOutcomeKind))
    def test_each_kind_rejects_the_payload_combinations_it_does_not_carry(
        self, kind: BatchOutcomeKind
    ) -> None:
        message = Message(role=Role.ASSISTANT, content="an answer")
        failure = BatchItemFailure(kind=BatchFailureKind.UNKNOWN, detail="why")
        wants_message = kind is BatchOutcomeKind.SUCCEEDED
        wants_failure = kind is BatchOutcomeKind.FAILED

        # The combination the kind does carry constructs.
        BatchItemOutcome(
            item_id="i",
            kind=kind,
            message=message if wants_message else None,
            failure=failure if wants_failure else None,
        )
        # Its opposite on each field does not.
        with pytest.raises(ValueError, match="message"):
            BatchItemOutcome(
                item_id="i",
                kind=kind,
                message=None if wants_message else message,
                failure=failure if wants_failure else None,
            )
        with pytest.raises(ValueError, match="failure"):
            BatchItemOutcome(
                item_id="i",
                kind=kind,
                message=message if wants_message else None,
                failure=None if wants_failure else failure,
            )


class TestTheSeamsBoundaries:
    """§8: which package may import a vendor, and where a batch may not live."""

    @pytest.mark.parametrize("module", ["types.py", "protocols.py", "errors.py"])
    def test_no_core_module_of_this_seam_imports_a_vendor_package(self, module: str) -> None:
        roots = _imported_roots(_SRC / "core" / module)
        assert not roots.intersection(_VENDOR_PACKAGES), (
            "golden rule 4 confines provider SDKs to models/, and `lint-imports` "
            "enforces it; this asserts the same thing about the modules this seam "
            "actually touched, so a breach names itself rather than a contract"
        )

    def test_the_vendor_import_lives_only_under_models(self) -> None:
        importers = {
            path.relative_to(_SRC).as_posix()
            for path in _SRC.rglob("*.py")
            if "anthropic" in _imported_roots(path)
        }
        assert importers == {"models/batch.py"}

    @pytest.mark.parametrize("package", ["service", "app"])
    def test_no_batch_completer_is_wired_into_the_hub_or_the_composition_root(
        self, package: str
    ) -> None:
        named = [
            path.relative_to(_SRC).as_posix()
            for path in (_SRC / package).rglob("*.py")
            if "BatchCompleter" in path.read_text(encoding="utf-8")
        ]
        assert named == [], (
            "ADR-0143 §8 keeps a batch in the process that submits it and never in "
            "the hub, and §11 leaves wiring one into `app` deferred until a "
            "subsystem — not a harness — needs bulk inference"
        )

    def test_the_protocol_is_declared_in_core_and_nowhere_else(self) -> None:
        assert BatchCompleter.__module__ == protocols.__name__
        assert errors.ModelError.__module__ == "ai_assistant.core.errors"


def _a_turn() -> Message:
    """One user turn, so a request under test is well formed."""
    return Message(role=Role.USER, content="hello")


_AN_INSTANT: Final = datetime(2026, 1, 1, tzinfo=UTC)

_A_HANDLE: Final = BatchHandle(batch_key="k", batch_id="b", issuer="i", submitted_at=_AN_INSTANT)
