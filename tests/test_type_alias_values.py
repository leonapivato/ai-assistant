"""Every PEP 695 ``type`` alias in ``src/`` can be resolved at runtime (#1706).

A PEP 695 alias is evaluated **lazily**: ``type X = Callable[[], int]`` compiles
to a descriptor whose right-hand side is not executed until something reads
``X.__value__``. So an alias whose value names a symbol imported only under
``if TYPE_CHECKING:`` type-checks clean, passes every static step of the gate,
and raises ``NameError`` the first time anything looks at it. Nothing in this
repository read ``__value__`` when #1706 was filed, which is precisely why eight
aliases had drifted into that state without a single check going red.

**Resolving one level is not enough**, and that is the second thing this module
learned rather than assumed. A value may resolve *into* a ``ForwardRef`` — which
is how a hidden name is usually written once someone notices the module cannot
import it — and reading ``__value__`` then succeeds while the alias stays just as
broken. ``orchestration.engine``'s two composer aliases were in that state: their
``__value__`` returned a ``Callable`` carrying ``ForwardRef('ComposedReply |
None')``, ``ForwardRef('TurnResult | None')`` and two more, every one of them
naming something the module imported only under ``if TYPE_CHECKING:``. So
:func:`resolution_errors` follows forward references to the end, against each
alias's own defining module. The fix there was to import the names *and* drop the
quotes, because a quoted name is a promise deferred to a resolver that may never
run — and because ``ruff``'s own ``TC001`` reads a quoted reference as
typing-only and would otherwise ask for the import back.

**The exposure is real rather than theoretical**, because the reader is never
this repository's own code. ``typing.get_type_hints`` resolves aliases it meets;
so does pydantic when a model comes to hold one; so would a documentation
generator, or a conformance check reading a declared callable shape.
:data:`~ai_assistant.core.clock.Clock` is the alias that makes it matter — it is
public, it is the named contract ten constructors across five subsystems declare
(ADR-0026 §1), and until this module landed it could not be resolved at all.

**The set is discovered, not declared.** A table of eight rows would have been
correct on the day it was written and silently wrong a week later: #1706
enumerated six aliases on 2026-08-27, and by the time the fix was written a
seventh (``orchestration.engine._Composer``, 2026-08-28) and an eighth
(``memory.sqlite_store._PreparedWrite``, 2026-08-31) had landed in exactly the
same shape. So two independent enumerations are taken and asserted to agree:
``src/`` is parsed for every ``ast.TypeAlias`` node, every module under
``ai_assistant`` is imported and asked for the aliases it owns, and
:func:`test_the_source_scan_and_the_runtime_walk_find_the_same_aliases` fails if
they differ. An alias the import walk cannot see — nested in a class body, or in
a module the walk never reaches — is then a failure that names itself rather
than a hole nothing can detect.

**The check is mutation-checked in the suite, not in a reviewer's memory.**
:func:`test_the_check_catches_a_type_checking_only_name` builds a module holding
both broken shapes and two controls, runs the same resolver over it, and asserts
exactly the two are reported. Without it, a resolver that swallowed every error
would pass forever and assert nothing — and without the ``Later`` control, one
that failed every ``ForwardRef`` on sight would look correct while rejecting the
ordinary, legitimate case of a name defined further down its own module.

:data:`_KNOWN_UNRESOLVED` is **empty**, and every alias in the tree resolves. It
is kept rather than deleted because the alternative to a ledger is not "no
exemptions" but an exemption argued in a review comment: the next alias that
cannot be fixed in the lane that finds it needs somewhere to be *recorded*, and
this is that place. It is written so that it can only shrink — the ledger test
asserts each entry still fails, so an entry whose defect gets fixed turns this
module red and names the row to delete.
"""

from __future__ import annotations

import ast
import importlib.util
import pkgutil
import sys
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Final, ForwardRef, TypeAliasType, get_args

import pytest

import ai_assistant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType

#: Aliases known to be unresolvable, each mapped to the issue that owns the fix.
#:
#: **Empty, and meant to stay that way.** Every alias in the tree resolves; the
#: last entry (``memory.sqlite_store._PreparedWrite``, #2040) was fixed in the
#: same PR that added this module rather than deferred.
#:
#: It is not an opt-out and not a suppression list. An entry exempts its alias
#: from :func:`test_every_type_alias_resolves_at_runtime` and immediately becomes
#: the subject of
#: :func:`test_the_known_unresolved_ledger_holds_only_aliases_that_still_fail`,
#: which asserts the entry still *exists* and still *fails* — so a row outlives
#: its defect by exactly zero runs. Add one only with an issue number: a row
#: without one is a defect hidden rather than deferred, and nothing else in the
#: suite would ever say so.
_KNOWN_UNRESOLVED: Final[dict[tuple[str, str], str]] = {}

#: The tree the source scan parses — the installed package's own directory, so a
#: run against a wheel and a run against the checkout read the same files.
_SRC: Final = Path(ai_assistant.__file__).resolve().parent


def _module_name(path: Path) -> str:
    """The dotted name of the module at ``path`` inside the package."""
    relative = path.relative_to(_SRC).with_suffix("")
    parts = relative.parts[:-1] if relative.name == "__init__" else relative.parts
    return ".".join((ai_assistant.__name__, *parts))


def declared_aliases() -> set[tuple[str, str]]:
    """Every ``type X = ...`` statement in the package, found by parsing it.

    Deliberately blind to nesting: an alias declared inside a class or a function
    body is reported here under its module, which is what makes the agreement
    check below fail rather than quietly under-count.
    """
    found: set[tuple[str, str]] = set()
    for path in sorted(_SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.TypeAlias):
                found.add((_module_name(path), node.name.id))
    return found


def _package_modules() -> Iterator[ModuleType]:
    """Every module under ``ai_assistant``, imported.

    ``onerror`` re-raises rather than defaulting to silence: a subpackage that
    cannot be imported would otherwise remove itself and everything beneath it
    from the walk, and this module's whole value is that its subject is the set.
    """

    def reraise(name: str) -> None:
        msg = f"{name} could not be imported, so the alias walk cannot cover it"
        raise ImportError(msg) from sys.exception()

    yield ai_assistant
    for info in pkgutil.walk_packages(ai_assistant.__path__, f"{ai_assistant.__name__}.", reraise):
        yield import_module(info.name)


def module_aliases(module: ModuleType) -> dict[str, TypeAliasType]:
    """The aliases ``module`` *defines*, keyed by name.

    ``__module__`` is checked because an alias imported from elsewhere is that
    module's obligation, not this one's — counting it twice would report one
    defect under two names.
    """
    return {
        name: value
        for name, value in vars(module).items()
        if isinstance(value, TypeAliasType) and value.__module__ == module.__name__
    }


def _namespace_of(alias: TypeAliasType) -> dict[str, object]:
    """The globals a name inside ``alias``'s value is resolved against.

    Its *defining* module's, followed across a nested alias rather than kept
    from the outer one: an alias in ``A`` whose value reaches an alias in ``B``
    carries ``B``'s forward references, and resolving those in ``A``'s namespace
    would report a failure ``B`` does not have or miss one it does.
    """
    origin = alias.__module__
    module = None if origin is None else sys.modules.get(origin)
    return {} if module is None else vars(module)


def _resolve(
    value: object, namespace: dict[str, object], seen: list[object], errors: list[str]
) -> None:
    """Depth-first, recording every name in ``value`` that will not resolve.

    ``seen`` holds the objects visited rather than their ``id``s, on purpose:
    identity by ``id`` is only sound while the object is alive, and the values
    walked here are largely temporaries that a reused address would silently
    conflate. Holding the reference makes the identity real, and it is what
    terminates a self-referential alias such as
    :data:`~ai_assistant.core.types.FrozenJson`.
    """
    if any(value is other for other in seen):
        return
    seen.append(value)
    if isinstance(value, str):
        # `Callable[["X"], Y]` converts to `ForwardRef`; `tuple["X", Y]` does
        # not, so both spellings arrive here and both must be followed.
        value = ForwardRef(value)
        seen.append(value)
    if isinstance(value, ForwardRef):
        try:
            evaluated: object = value.evaluate(globals=namespace, locals=namespace)
        except Exception as exc:  # the failure *is* the finding
            errors.append(f"{value.__forward_arg__!r} — {type(exc).__name__}: {exc}")
            return
        _resolve(evaluated, namespace, seen, errors)
        return
    if isinstance(value, TypeAliasType):
        try:
            inner: object = value.__value__
        except Exception as exc:  # the failure *is* the finding
            errors.append(f"{value.__name__} — {type(exc).__name__}: {exc}")
            return
        _resolve(inner, _namespace_of(value), seen, errors)
        return
    arguments = get_args(value)
    for argument in arguments:
        _resolve(argument, namespace, seen, errors)
    if not arguments and isinstance(value, list | tuple):
        # `get_args(Callable[[A, B], R])` hands back the parameter list itself.
        for argument in value:
            _resolve(argument, namespace, seen, errors)


def resolution_errors(alias: TypeAliasType) -> list[str]:
    """Every name in ``alias`` that will not resolve, nested ones included.

    Two levels, because reading ``__value__`` is only the first. A value may
    resolve into a `ForwardRef` — from a quoted element, which is what a name the
    module cannot import at runtime is usually written as — and a consumer that
    walks the alias (``typing.get_type_hints``, or pydantic building a model that
    came to hold one) evaluates those too. An alias whose ``__value__`` succeeds
    while a name inside it does not is broken for every such consumer, and
    stopping at the first level would report it as sound.

    Every exception is caught, not just ``NameError``: a name that cannot be
    resolved is the finding regardless of which exception says so, and narrowing
    the catch would let a novel failure mode escape the check that exists to
    notice it.
    """
    errors: list[str] = []
    _resolve(alias, _namespace_of(alias), [], errors)
    return errors


def unresolved(module: ModuleType) -> dict[str, list[str]]:
    """The aliases ``module`` defines that carry a name which will not resolve."""
    return {
        name: errors
        for name, alias in module_aliases(module).items()
        if (errors := resolution_errors(alias))
    }


def _all_aliases() -> dict[tuple[str, str], TypeAliasType]:
    """Every alias the package defines, keyed by ``(module, name)``."""
    return {
        (module.__name__, name): alias
        for module in _package_modules()
        for name, alias in module_aliases(module).items()
    }


_ALIASES: Final = _all_aliases()


def test_the_scan_actually_finds_the_aliases() -> None:
    """A discovery that silently found nothing would pass forever."""
    assert {
        ("ai_assistant.core.clock", "Clock"),
        ("ai_assistant.core.types", "UtcInstant"),
        ("ai_assistant.core.types", "FrozenJson"),
        ("ai_assistant.orchestration.loop", "SupplyFilter"),
        ("ai_assistant.service.enrolment", "ExpelCallback"),
    } <= set(_ALIASES)


def test_the_source_scan_and_the_runtime_walk_find_the_same_aliases() -> None:
    """The import walk sees every ``type`` statement ``src/`` actually contains.

    The two enumerations are independent — one parses files, the other imports
    modules and reads namespaces — so a disagreement means the runtime walk has a
    blind spot, and an alias hiding in that blind spot is exactly the thing this
    module would otherwise fail to check. A ``type`` statement nested inside a
    class or a function lands here: extend :func:`module_aliases` to descend into
    it rather than deleting the assertion.
    """
    assert declared_aliases() == set(_ALIASES)


@pytest.mark.parametrize(
    "qualified",
    [pytest.param(key, id=f"{key[0]}.{key[1]}") for key in sorted(_ALIASES)],
)
def test_every_type_alias_resolves_at_runtime(qualified: tuple[str, str]) -> None:
    """Reading ``__value__`` raises nothing (#1706).

    Nested forward references included: an alias whose ``__value__`` succeeds
    into a ``ForwardRef`` naming something the module cannot see is broken for
    every consumer that walks it, and the first level alone would call it sound.

    The failure this pins is not a typing error — ``mypy --strict`` is happy with
    every one of the aliases that used to fail — but a name the module never
    imported at runtime. The fix is to move that import out of the module's
    ``if TYPE_CHECKING:`` block; where the name was quoted only to survive being
    hidden, unquote it too, so the alias means what it says instead of deferring
    to a resolver that may never run.
    """
    if qualified in _KNOWN_UNRESOLVED:
        pytest.skip(f"known unresolved, owned by {_KNOWN_UNRESOLVED[qualified]}")
    module, name = qualified
    errors = resolution_errors(_ALIASES[qualified])
    assert not errors, (
        f"{module}.{name} cannot be resolved at runtime: {'; '.join(errors)}. "
        f"Move the name it references out of {module}'s `if TYPE_CHECKING:` block."
    )


def test_the_known_unresolved_ledger_holds_only_aliases_that_still_fail() -> None:
    """The ledger can only shrink.

    An entry that has been fixed fails here, naming the row to delete — so the
    exemption cannot outlive the defect it was written for, which is the failure
    mode a plain skip-list has and this one does not.

    Vacuous while :data:`_KNOWN_UNRESOLVED` is empty, which is the state the tree
    is in and should stay in. It is kept armed rather than deleted because the
    cost of an empty loop is nothing and the cost of re-deriving this rule the
    next time an alias cannot be fixed in the lane that finds it is an exemption
    nothing checks.
    """
    for qualified, owner in _KNOWN_UNRESOLVED.items():
        assert qualified in _ALIASES, f"{qualified} no longer exists; delete its ledger row"
        module, name = qualified
        assert resolution_errors(_ALIASES[qualified]), (
            f"{module}.{name} now resolves — delete its row from _KNOWN_UNRESOLVED "
            f"and close {owner}."
        )


def test_the_check_catches_a_type_checking_only_name(tmp_path: Path) -> None:
    """The mutation check: both shapes are reported, and neither control is.

    Written against a module built here rather than by re-hiding an import in
    ``src/``, so the negative case is asserted on every run instead of once by
    hand. Four aliases, because the check has two ways to be wrong and both are
    pinned:

    * ``Hidden`` is the shape all eight offenders had — ``Callable`` reachable to
      a type checker and to nothing else — and its ``__value__`` raises.
    * ``Nested`` is the shape adversarial round 2 found in
      ``orchestration.engine``: ``__value__`` *succeeds* into a ``ForwardRef``
      whose name is hidden. A resolver that stopped at the first level would
      pass it, which is the regression this alias exists to catch.
    * ``Later`` is the control that keeps the check from over-firing. Its
      forward reference names a class defined further down the same module — a
      genuine forward reference, resolvable the moment the module finishes
      executing — and it must **not** be reported. Without it, a resolver that
      failed every ``ForwardRef`` on sight would look correct.
    * ``Fine`` names nothing at all.
    """
    source = tmp_path / "hidden_name_alias.py"
    source.write_text(
        "from __future__ import annotations\n"
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from collections.abc import Callable, Sequence\n"
        "type Hidden = Callable[[], int]\n"
        "type Nested = tuple['Sequence[int] | None', str]\n"
        "type Later = tuple['DefinedLater', int]\n"
        "type Fine = tuple[int, ...]\n"
        "class DefinedLater: ...\n",
        encoding="utf-8",
    )
    spec = importlib.util.spec_from_file_location("hidden_name_alias", source)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert set(module_aliases(module)) == {"Hidden", "Nested", "Later", "Fine"}
        failures = unresolved(module)
    finally:
        del sys.modules[spec.name]
    assert set(failures) == {"Hidden", "Nested"}
    assert "Callable" in failures["Hidden"][0]
    assert "Sequence" in failures["Nested"][0]
