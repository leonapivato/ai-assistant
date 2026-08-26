"""The one shape a detached, validated snapshot of a record takes in this package.

Two stores here take a snapshot of a caller's record and keep it — the audit
trail's ``record`` and ``claim_invocation``, and the recipient-grant store's
``record`` — and both owe the same two things about it. **Read the field state
through the class**, because ``model_dump`` is an ordinary overridable method and
an instance can shadow it through ``__dict__``, so a value that describes itself
falsely would otherwise become the record. And **rebuild recursively**, because a
snapshot that reuses the caller's nested models is not detached at all: the
caller still holds every object beneath the root and can rewrite one after the
snapshot was taken.

:func:`field_state` is that read. It refuses, rather than silently drops,
anything the rebuild after it would lose — state the class declares no field for,
and a model-valued field holding something other than exactly its declared type —
so the mapping it returns rebuilds into a model equal to the one that was passed,
with nothing of the caller's object left inside it.

**Why this is duplicated in ``ai_assistant.testing`` rather than shared with it.**
The canonical fakes owe their Protocols' clauses in the same words the durable
stores do, and a fake that reached into a subsystem would invert the dependency
``lint-imports`` forbids — the canonical fakes stand in *for* these stores and
must not import them. A single home would have to be ``core``, which is the
contract surface rather than a place for concrete helpers; putting it there is an
architecture decision owed its own ADR (#563, and ``_transactions.py`` states the
same reasoning about the same boundary). Two copies of one module is what that
boundary costs, and it is the floor rather than an oversight.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from typing import Any, cast, get_args

from pydantic import BaseModel

from ai_assistant.core.types import describe_untrusted

__all__ = ["field_state"]


def field_state(kind: type[BaseModel], given: object) -> Any:
    """The declared field values of ``given``, read by ``kind``'s **own** serializer.

    ``given.model_dump()`` is an ordinary attribute: a subclass can override the
    method and an instance can shadow it through ``__dict__``, and either can return
    a valid-but-false mapping. Everything downstream then rebuilds *that* — so the
    equality check ``claim_invocation`` runs would compare the store's row against a
    decision the caller never held, and a completion would record a cost nobody
    submitted. ``orchestration/executor.py`` states the same reasoning for
    ``ToolResult`` and is the precedent this follows: the class serializer is
    resolved on the class, reads the instance's field values, and consults no
    instance attribute.

    A value that is not a ``kind`` at all is handed back untouched, for
    ``model_validate`` to refuse — nothing is read off it here (ADR-0152 §1's
    ordering). That test is **inside** the guard below with everything else, because
    ``isinstance`` consults the value's ``__class__``, which can be a property that
    raises: asking what something is is as much a read of it as reading a field.

    **Anything the serializer would silently drop is refused instead**, which is
    :func:`_refuse_undeclared`'s whole subject and is what makes the value this
    returns rebuild into a model equal to the one that was passed.

    ``warnings=False`` because a ``__dict__``-tampered enum serialises with a
    ``PydanticSerializationUnexpectedValue`` warning that is noise here; the
    ``model_validate`` downstream is what rejects it.

    **Every other way this can fail is an argument fault too**, and that is why the
    read is wrapped. The value is the caller's from top to bottom, so a container
    whose ``__len__`` or ``__iter__`` raises, a ``__dict__``-tampered field the
    serializer cannot render — it raises ``AttributeError`` on one, which ``main``
    lets through — and anything else reached while reading it are all faults *of the
    argument*. ADR-0192 §2's order is exhaustive over the classes a refusal arrives
    in, so none of them may leave as itself. ``Exception`` and never
    ``BaseException``: a cancellation is not a fault of the argument and is never
    absorbed (ADR-0060 §1). Nothing of the caller's is interpolated into the message,
    for :func:`_refuse_undeclared`'s reason.

    Raises:
        ValueError: If ``given`` carries state ``kind`` declares no field for, if a
            model-valued field anywhere beneath it holds something other than exactly
            its declared type, or if the value cannot be read as a ``kind`` at all.
    """
    try:
        if not isinstance(given, kind):
            return given
        _refuse_undeclared(kind, given)
        return kind.__pydantic_serializer__.to_python(given, warnings=False)
    except ValueError:
        raise  # this module's own refusals, and pydantic's, already the right class
    except Exception as exc:
        msg = f"the value cannot be read as a {kind.__name__} at all"
        raise ValueError(msg) from exc


def _refuse_undeclared(kind: type[BaseModel], given: BaseModel) -> None:
    """Refuse state ``kind`` does not declare, on ``given`` and beneath it.

    Two refusals serving one rule — **what is stored is what was handed over, or
    nothing is** — because either kind of state would otherwise be dropped in
    silence by the class serializer :func:`field_state` reads the value with.

    *State the class declares no field for* sits on the value itself: a subclass's
    extra field, or anything written straight into ``__dict__``. Refusing it keeps
    the guarantee the declared type already carries.

    *A model-valued field holding something other than exactly its declared type* is
    the same loss one level down, and it arrives through a **normally constructed**
    value rather than a tampered one. ``PermissionDecision.tool`` is declared a
    ``ToolDefinition``, and pydantic's default ``revalidate_instances="never"`` keeps
    whatever instance the caller passed — so a ``ToolDefinition`` subclass carrying a
    field of its own survives validation. ``PermissionDecision``'s serializer then
    emits the *declared* fields of it and drops that one, and the snapshot rebuilt
    from the mapping compares **equal** to a decision the caller never held. That is
    ADR-0192 §1's own attack shape: an ``ALLOW`` the trail recorded would admit a
    claim under a tool carrying state it never approved, where §1 requires the
    decision the ledger was *passed* to equal the one the store holds under that id —
    "the whole value, by the frozen model's own equality".

    This refusal is the half of that equality about state the rebuild would **drop**,
    and it is the half ``record`` owes as well, because a record smaller than the
    value it was handed is wrong whether or not anything is later admitted over it.
    The other half — a rebuild that *normalises* rather than drops, so the value is
    not the one that was passed even though nothing was lost — is the ledger's own
    ``_refuse_unless_as_passed``, on its claim path alone. Neither is the other's
    subset: this one refuses a value the trail must not store at all, and that one
    refuses an admission for a value the trail stores perfectly well.

    Both alternatives are worse. Comparing the caller's live object inside the lock
    satisfies §1 literally and re-reads the decision after a suspension point, which
    ADR-0065 forbids and
    ``test_the_submitted_decision_is_observed_before_the_first_await`` exists to
    catch. Carrying the nested subclass's own state through the snapshot would store
    what ``ToolDefinition``'s ``extra="forbid"`` refuses — a record the type says
    cannot exist. ``record`` reaches this helper too and is tightened in the same
    direction by the same clause: what the trail stores is what it was given.

    The refusal is on the *type* and not on whether this particular subclass happens
    to declare a field of its own, because the second is a property of the class a
    caller supplies and the first is the contract.

    **Nothing here hashes or compares a key or a class the caller controls.** A
    model's ``__dict__`` is annotated ``dict[str, Any]`` and nothing enforces it at
    runtime, so a key can be any hashable object at all — including one whose
    ``__hash__`` collides with a field name and whose ``__eq__`` raises on the
    comparison that collision provokes. Building a ``set`` of the keys, or asking
    ``key in declared`` of a non-``str``, walks straight into it and this refusal
    leaves as whatever that ``__eq__`` threw. A caller's *class* is the same hazard
    through its metaclass, so the type test below is by identity rather than by
    membership. So: iterate (which hashes nothing), classify anything that is not
    *exactly* ``str`` as undeclared without touching it, and only then ask a real
    ``str`` — whose hash and equality are the interpreter's — whether it names a
    field.

    The one recursion descends the **declared** model graph, because a value of any
    other type is refused rather than followed; it is therefore bounded exactly as
    the serializer over the same value is. Containers are walked with an explicit
    stack instead (:func:`_models_within`), their depth being the caller's to choose.

    Raises:
        ValueError: If ``given`` carries state ``kind`` declares no field for, or a
            model-valued field beneath it holds something other than exactly its
            declared type.
    """
    declared = set(kind.model_fields)
    undeclared = [key for key in given.__dict__ if type(key) is not str or key not in declared]
    if undeclared:
        # Described *before* sorting, and described by
        # :func:`~ai_assistant.core.types.describe_untrusted`. Sorting the keys
        # directly raises ``TypeError`` the moment two of them are of different
        # types, and ``repr`` on one can raise anything at all — either way the
        # diagnostic would destroy the diagnosis and this refusal would leave as a
        # class ADR-0192 §2's order does not admit. Sorting the *descriptions*
        # keeps the message deterministic and cannot raise.
        named = sorted(describe_untrusted(key) for key in undeclared)
        msg = f"the value carries state {kind.__name__} has no field for: {named}"
        raise ValueError(msg)
    for name, value in given.__dict__.items():
        admits = _declared_models(kind.model_fields[name].annotation)
        for nested in _models_within(value):
            held = type(nested)
            if not any(held is each for each in admits):
                shown = ", ".join(sorted(each.__name__ for each in admits))
                msg = (
                    f"the value's {name!r} field declares {shown or 'no model'} and "
                    f"holds {describe_untrusted(held)}: a value of another type "
                    f"would be recorded as less than it is"
                )
                raise ValueError(msg)
            _refuse_undeclared(held, nested)


def _declared_models(annotation: object) -> tuple[type[BaseModel], ...]:
    """Every model class ``annotation`` admits, flattened out of unions and containers.

    ``get_args`` unwraps ``X | None``, ``tuple[X, ...]`` and ``Annotated[X, ...]``
    alike, so one walk covers every shape a field of these models is declared with.
    Anything that is not a model class contributes nothing, which is the right
    answer: a field declaring no model admits none.

    Flattened rather than positional. Whether a model sits in the arm of the
    annotation it was put in is ``model_validate``'s question and it refuses one that
    does not; the only question here is whether a value would be recorded as less
    than it is, and every class named anywhere in the annotation serialises whole.
    """
    found: list[type[BaseModel]] = []
    pending: list[object] = [annotation]
    while pending:
        item = pending.pop()
        if isinstance(item, type) and issubclass(item, BaseModel):
            found.append(item)
            continue
        pending.extend(get_args(item))
    return tuple(found)


def _models_within(value: object) -> Iterator[BaseModel]:
    """Every model instance ``value`` is or holds inside a plain container.

    Iterative rather than recursive: a container's nesting depth is the caller's to
    choose, and a ``RecursionError`` is neither ``ValueError`` nor any class
    ADR-0192 §2's refusal order admits. A container that refuses to be iterated
    raises here exactly as it would inside the serializer one call later, so this
    walk widens nothing that can leave.

    **A container that contains itself is refused**, which is what keeps an iterative
    walk from being worse than a recursive one. ``spans[0] is spans`` is a single
    ``__dict__`` write away, and a stack that simply re-expanded it would spin for
    good — synchronously, before the first ``await``, so the event loop stops being
    serviced and the ``AuditError`` §2 requires never arrives. Refusing is also the
    only *correct* answer: the serializer below cannot render a cycle either, and on
    ``main`` it leaves as an ``AttributeError``, which is outside the classes §2's
    order admits. A container merely reached **twice** is not that and is not
    refused; see the note on the two sets below.

    **The recognised containers are a list and not a universe, and what is outside it
    is safe by two other clauses rather than by this one.** A model hidden inside some
    other container type is not found here — and it cannot be *admitted*, because the
    ledger's claim path compares the value as passed, and it
    cannot *leak*, because every failure of this walk or of the rebuild after it is an
    argument fault (:func:`field_state`). What is left is that ``record`` stores the
    validated snapshot ADR-0021 §4 asks for rather than the caller's exact object,
    which is what that clause promises.
    """
    if isinstance(value, BaseModel):
        yield value
        return
    if not _is_container(value):
        return
    # A depth-first walk with the path made explicit, because the two things that
    # can go wrong here need different answers. `open` is what is being walked
    # *right now*: a container that turns up inside itself is a cycle, and there is
    # no rendering of one, so it is refused. `closed` is what has been walked
    # already: the same container reached again from somewhere else is neither a
    # cycle nor new, so it is skipped — which is what keeps a shared subtree from
    # being re-walked once per route to it, and what makes two empty tuples in one
    # schema the ordinary thing they are rather than a refusal. `()` is interned, so
    # a walk that refused every repeated identity would refuse a valid decision.
    #
    # Identities and never the containers: a `set` of the containers themselves
    # would hash and compare two caller-supplied values, and on a cycle that
    # comparison does not terminate either. `id` yields machine integers, whose hash
    # and equality are the interpreter's.
    stack: list[tuple[int, Iterator[object]]] = [(id(value), _members(value))]
    open_ids: set[int] = {id(value)}
    closed_ids: set[int] = set()
    while stack:
        marker, cursor = stack[-1]
        for item in cursor:
            if isinstance(item, BaseModel):
                yield item
                continue
            if not _is_container(item):
                continue
            below = id(item)
            if below in open_ids:
                msg = "the value holds a container that contains itself: a cycle"
                raise ValueError(msg)
            if below in closed_ids:
                continue
            open_ids.add(below)
            stack.append((below, _members(item)))
            break
        else:
            stack.pop()
            open_ids.discard(marker)
            closed_ids.add(marker)


def _is_container(value: object) -> bool:
    """Whether the walk descends into ``value``.

    ``Mapping`` and not ``dict``, because :data:`~ai_assistant.core.types.FrozenJson`
    renders a mapping as a ``FrozenDict``, which is a ``Mapping`` and not a ``dict``
    at all: a field declared :data:`~ai_assistant.core.types.FrozenJsonMapping` would
    otherwise be walked past. ``str`` and ``bytes`` are iterable and are deliberately
    not here — they hold no model and iterating them would only yield themselves.
    """
    return isinstance(value, list | tuple | set | frozenset | Mapping)


def _members(value: object) -> Iterator[object]:
    """The members of a container this walk descends into.

    A ``Mapping``'s *values*: a model can only be a value, and reading the keys would
    be reading objects whose ``__hash__`` and ``__eq__`` the caller wrote
    (:func:`_refuse_undeclared` states that hazard in full).
    """
    if isinstance(value, Mapping):
        pairs: Mapping[object, object] = value
        return iter(pairs.values())
    return iter(cast("Iterable[object]", value))
