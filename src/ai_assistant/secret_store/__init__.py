"""The one keyring-backed implementation of ADR-0125's seam.

A **leaf package**, in the shape `readers/` and `evaluation/` already have and for
the reason recorded for both: `core` holds the Protocols, so the edge that would
invert the dependency is one an implementation could plausibly reach for, and a
package outside every subsystem is what makes the inversion impossible rather than
discouraged (ADR-0125 §8).

**Its name avoids the one collision ADR-0125 §8 warns about.**
``ai_assistant.secrets`` would shadow the standard-library module that
:mod:`ai_assistant.wire.credential` uses to mint a credential, and while absolute
imports make that safe, "it is a name that will confuse every reader of a file
that needs both".

**The `keyring` library is imported here and nowhere else**, which is ADR-0125
§8's marked clause and is enforced by an import-linter contract in
``pyproject.toml`` rather than by this docstring — golden rule 4's shape applied to
a second external dependency, so ADR-0004 §3's single-path rule stops being a
convention. The history of *that* convention is that it stayed unimplemented from
ADR-0004's ratification until a third consumer made it blocking.

**One class, several instances** (ADR-0125 §1). ``PROVIDER``, ``INTEGRATION`` and
``ENROLMENT`` are three instances of :class:`KeyringSecretStore` over one keyring
backing, each taking the same installation namespace, so the scope is what differs
between them and nothing else. Whoever composes an instance chooses those two
facts; nothing here reads a setting.
"""

from __future__ import annotations

from ai_assistant.secret_store.backend import (
    PROTECTED_BACKEND_MODULES,
    KeyringBackend,
    select_backend,
)
from ai_assistant.secret_store.store import KeyringSecretStore

__all__ = [
    "PROTECTED_BACKEND_MODULES",
    "KeyringBackend",
    "KeyringSecretStore",
    "select_backend",
]
