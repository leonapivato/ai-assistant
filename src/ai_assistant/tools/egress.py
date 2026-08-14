"""The `tools/` egress seam: named, approved, undesignated, transmitting nothing.

This is the seam ADR-0017 §2 anticipates and ADR-0147 §3 names:
``ai_assistant.tools.egress`` — **one module, not a package**, holding outbound
transport and nothing else. `tools/` also owns definitions, the registry and the
invocation path, and none of those has any business holding a network client;
that is why the seam is a module the boundary can be drawn *around* rather than a
package the boundary would follow wherever the code grew. Naming it is what issue
#66 asked for since the architecture review of PR #64 — a name "precise enough for
an import-linter contract to pin the module" — and the contract that pins it is
``network transports are confined to the tools egress seam`` in ``pyproject.toml``.

**Nothing here authorises a byte to leave this device.** ADR-0147 §3 says so in a
marked clause: naming the seam is not designating it, that ADR designates nothing
and attests no condition of ADR-0017 §3, and all fourteen of §3's conditions stand
exactly as written and undischarged. No lane may cite ADR-0147 — or the existence
of this module — toward any of them. The seam is **approved and undesignated**, and
an approved boundary transmits nothing. It becomes designated, and only then
transmits, when every one of those conditions holds in code *and* a later ADR names
which, attests how, and records the transition.

**So this module is deliberately empty, and the emptiness is the content.** It holds
no client, no connection, no callable that opens a socket or launches a subprocess,
and no constant describing its own status. A raise-on-use stub would be a shape for
a later lane to fill in, and a status constant would be a value some consumer could
read and branch on; both would put something here that a reader could mistake for
the beginning of permission. What this module supplies is a *name* — the thing a
contract can pin and a designating ADR can attest against — and nothing else.
``tests/tools/test_egress_seam.py`` holds it to that.

Two clauses of ADR-0147 §3 govern what may be written here, and they reach
different distances:

- **The rule.** No module under ``ai_assistant.tools`` other than this one opens a
  network connection or launches a subprocess, by any route: a client library, an
  HTTP or socket API, a standard-library module, or a wrapper around any of them.
  That binds an author and a reviewer; it is not a claim about what a check can see.
- **The check.** The import-linter contract forbids an *enumerated* set of modules
  to every `tools/` module but this one. ADR-0017 §4 is why the two are stated
  separately rather than collapsed: "an import contract is a net, not a proof. It
  matches module names, so it cannot see a subsystem reaching the network through
  ``urllib``, a raw socket, a library added after the contract was written, or an
  internal wrapper." The enumeration names ``urllib`` and the raw socket module, so
  the first two of those examples are inside the net; what stays outside is a
  dependency nobody added to the list. A clause claiming the contract pinned the
  *universal* rule would be claiming exactly the proof §4 denies.

When transport does eventually land here, MCP protocol handling — the JSON-RPC
message shapes, discovery, the mapping from a declaration to a ``ToolDefinition``
and from a result to a ``ToolResult`` — stays **outside** this module and holds no
transport of its own (ADR-0147 §3). It receives a connected channel from the seam
and never constructs one. A module holding both is a module whose egress boundary
extends wherever the protocol code grows, which is the property #66 asks a contract
to be able to pin.
"""
