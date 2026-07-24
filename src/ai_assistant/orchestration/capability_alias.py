"""Resolve a synonymous capability name onto an advertised one (ADR-0053).

``ModelBackedPlanner`` (ADR-0047) emits capability strings from an *open*
vocabulary and is kept blind to the tool set (ADR-0014 §2), so a real utterance
like "what time is it" may name ``get_time`` while the only tool that can serve
it advertises ``report_current_time`` (ADR-0048). Without a bridge that step is
``SKIPPED``/``NO_CAPABLE_TOOL`` (ADR-0037 §1) — a legitimate, detectable outcome,
but one that means the wired tools never fire from natural language.

This module is that bridge, at *selection* time and nowhere else: a pure function
:func:`resolve_capability` that :class:`~ai_assistant.orchestration.runner.StepRunner`
calls just before ``ToolRegistry.find``. It is deliberately **non-contract** —
the ``Planner.plan`` Protocol is unchanged and the planner learns nothing about
the tool set. ADR-0053 records why the richer "publish the registry's vocabulary
to the planner" option (issue #60's territory) stays deferred: it constrains the
planner to the tools that exist today.

**The rule is honest by construction: an alias maps a *known synonym*, it never
guesses.** Two things bound it, and both are checked against the live registry,
which stays the authority on the vocabulary (ADR-0016 §5):

- Resolution is total on an explicit, author-curated table (:data:`CAPABILITY_ALIASES`)
  plus case/separator folding onto an *already advertised* name. An emitted
  string that is neither an exact advertised capability, a case/separator variant
  of one, nor an enumerated synonym is returned **unchanged** — so an unknown
  capability still reaches ``find`` unmodified and still yields
  ``NO_CAPABLE_TOOL``. Nothing is invented.
- An alias only ever resolves onto a name the registry *currently advertises*.
  The target is verified against the advertised set on every call, so a synonym
  can never rewrite a step onto a capability no tool serves — the "does not fire
  the wrong tool" property is a structural consequence, not a discipline. If two
  tools advertise the resolved capability the runner's own ambiguity rule
  (ADR-0037 §1) still declines to choose; aliasing changes *which* capability is
  looked up, never *how many* candidates a lookup is allowed to pick from.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

#: Curated synonym → advertised-capability map (ADR-0053).
#:
#: Each key is a capability string a planner might plausibly emit for a request
#: the corresponding tool serves; each value is the exact capability an ADR-0048
#: tool advertises. Keys are stored already normalised (:func:`_normalize`), so a
#: surface variant of a listed synonym — ``"Get Time"``, ``"get-time"`` — folds
#: onto the same entry. This is a hand-maintained table of *deliberate* synonyms,
#: not a similarity heuristic: adding a tool with a new vocabulary adds entries
#: here, it does not teach this module to guess.
CAPABILITY_ALIASES: Mapping[str, str] = {
    # report_current_time (current_time, ADR-0048 §2)
    "get_time": "report_current_time",
    "tell_time": "report_current_time",
    "tell_the_time": "report_current_time",
    "what_time": "report_current_time",
    "what_time_is_it": "report_current_time",
    "current_time": "report_current_time",
    "time_now": "report_current_time",
    "get_current_time": "report_current_time",
    "check_time": "report_current_time",
    # recall_memory (recall_memory, ADR-0048 §2)
    "recall": "recall_memory",
    "recall_memories": "recall_memory",
    "remember": "recall_memory",
    "search_memory": "recall_memory",
    "search_memories": "recall_memory",
    "retrieve_memory": "recall_memory",
    "memory_recall": "recall_memory",
    "memory_search": "recall_memory",
    "lookup_memory": "recall_memory",
}

#: Any run of characters that is not a lowercase letter or digit, used to fold
#: separators (spaces, hyphens, underscores, punctuation) to a single ``_``.
_SEPARATOR = re.compile(r"[^a-z0-9]+")


def _normalize(capability: str) -> str:
    """Fold a capability string to a case- and separator-insensitive key.

    Lowercases, then collapses every run of non-alphanumeric characters to a
    single underscore and strips leading/trailing underscores, so ``"Get Time"``,
    ``"get-time"`` and ``"GET_TIME"`` all yield ``"get_time"``. This is surface
    folding only — it never changes which *word* was named, so it cannot turn one
    capability into a different one; it only lets a trivial rendering variant of a
    name match the same name.
    """
    return _SEPARATOR.sub("_", capability.lower()).strip("_")


def resolve_capability(emitted: str, advertised: Collection[str]) -> str:
    """Resolve ``emitted`` onto an advertised capability, or return it unchanged.

    The registry is the authority on ``advertised`` (ADR-0016 §5), and every
    branch that rewrites lands on a member of it — so the result is always either
    an advertised capability or the caller's own string verbatim, never an
    invented third value.

    Resolution, in order:

    1. **Exact.** ``emitted`` is already an advertised capability — return it
       untouched, so the common case pays no folding and no table lookup.
    2. **Surface variant.** ``emitted`` folds (:func:`_normalize`) onto an
       advertised capability — return that advertised name in its canonical form.
    3. **Curated synonym.** ``emitted`` folds onto a key of
       :data:`CAPABILITY_ALIASES` whose target is *currently advertised* — return
       the target. The advertised-set check is what keeps a synonym from ever
       resolving onto a capability no tool serves.
    4. **Unknown.** None of the above — return ``emitted`` unchanged, so an
       unrecognised capability reaches ``find`` as the planner named it and is
       reported ``NO_CAPABLE_TOOL`` honestly.

    Args:
        emitted: The capability string the plan step carries, as the planner
            named it.
        advertised: Every capability the registry currently advertises
            (``ToolRegistry.capabilities()``). The authority on what a rewrite may
            resolve onto.

    Returns:
        An advertised capability when ``emitted`` is one, a surface variant of
        one, or a curated synonym of one; otherwise ``emitted`` unchanged.
    """
    advertised_set = set(advertised)
    if emitted in advertised_set:
        return emitted

    # Fold the advertised names once; first writer wins so the result is stable
    # under the caller's ordering (`capabilities()` is sorted and de-duplicated).
    canonical: dict[str, str] = {}
    for capability in advertised:
        canonical.setdefault(_normalize(capability), capability)

    key = _normalize(emitted)
    if key in canonical:
        return canonical[key]

    target = CAPABILITY_ALIASES.get(key)
    if target is not None and target in advertised_set:
        return target

    return emitted


__all__ = ["CAPABILITY_ALIASES", "resolve_capability"]
