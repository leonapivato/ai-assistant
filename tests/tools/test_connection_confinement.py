"""One module under `tools/` may name the keyring seam (ADR-0149 §14).

ADR-0149 §14 asks the provisioner's lane for "the import-linter or equivalent
mechanical confinement that the provisioner's module is the only module under
``tools/`` naming ``SecretStore``, in the spirit of ADR-0125 §8's contract
confining the keyring library to one package".

**It is a test rather than an import-linter contract, and the reason is
mechanical.** ``lint-imports`` constrains which *modules* a module may import, and
``SecretStore`` is a name imported from ``ai_assistant.core.protocols`` — which
every subsystem may import and most do. No `forbidden` contract can express "not
this name from that module", so the confinement is written where it can be: a
source scan, in the shape ``tests/tools/test_egress_seam.py`` already uses for the
transport clauses next door. §14 admits exactly this by saying "or equivalent".

What ``lint-imports`` *does* already hold is the stronger half: no module under
``tools/`` may import :mod:`ai_assistant.secret_store` at all, so the provisioner
receives its face by injection and constructs none.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

#: Where the subsystem's modules live.
_TOOLS: Final = Path(__file__).resolve().parents[2] / "src" / "ai_assistant" / "tools"

#: The one module ADR-0149 §1 places the write face on.
_PROVISIONER: Final = "provisioning.py"

#: The two names ADR-0125 §1 splits the keyring seam into. ``Secrets`` is the
#: narrow face a tool may legitimately hold (ADR-0125 §8), so only the wide one is
#: confined here — the point of §14's clause is that exactly one module may express
#: ``set`` and ``delete``.
_WRITE_FACE: Final = "SecretStore"


def _modules() -> dict[str, Path]:
    """Every module under ``tools/``, by file name."""
    return {path.name: path for path in sorted(_TOOLS.rglob("*.py"))}


def _names(path: Path) -> set[str]:
    """Every bare name the module's source mentions, in any position.

    Parsed rather than grepped, so a mention inside a docstring or a comment — the
    two places a module legitimately *discusses* the seam without holding it —
    does not count. That distinction matters immediately:
    ``tools/provisioning.py``'s own siblings explain why they do not hold the face,
    and a lexical scan would fail them for saying so.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.asname or node.name.rsplit(".", maxsplit=1)[-1])
    return found


def test_only_the_provisioner_names_the_keyring_write_face() -> None:
    """ADR-0149 §14: one module under ``tools/`` may express ``set`` and ``delete``.

    ADR-0125 §1's argument, arriving a third time: "a tool holding a three-method
    store can delete the device's enrolment credential, and nothing in the type
    system or the review process would notice". Removing the write face from what
    a module's dependencies can express is a type rather than a promise — and this
    check is what keeps the type from being quietly re-added by a second holder.
    """
    holders = {name for name, path in _modules().items() if _WRITE_FACE in _names(path)}

    assert holders == {_PROVISIONER}, (
        f"{_WRITE_FACE} is named by {sorted(holders)}; ADR-0149 §1 puts the only "
        f"INTEGRATION-scoped write face on {_PROVISIONER}, and a second holder is a "
        f"component that can write another account's credential into a slot."
    )


def test_the_provisioner_module_exists_where_the_check_expects_it() -> None:
    """The negative control the check above needs.

    Without it, renaming the provisioner would make the assertion pass with an
    empty set on both sides — a confinement satisfied by there being nothing to
    confine.
    """
    assert _PROVISIONER in _modules()
