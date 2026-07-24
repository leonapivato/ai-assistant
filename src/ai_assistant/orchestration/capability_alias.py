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

import unicodedata
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

#: Unicode general-category initials that are *word-forming* — letters (``L``),
#: numbers (``N``) and marks (``M``, the combining marks a decomposition or a
#: casefold can attach to a letter). Everything else — spaces, hyphens,
#: underscores, punctuation — is a separator. Keeping marks is deliberate:
#: ``"İ".casefold()`` is ``"i"`` + a combining dot, and dropping the dot as a
#: separator would fold ``İ`` onto a plain ``i`` — rewriting one word into another,
#: the very thing surface folding must not do.
_WORD_CATEGORIES = frozenset({"L", "N", "M"})

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
    # recall_memory (recall_memory, ADR-0048 §2). Retrieval synonyms only: a
    # *write* synonym like "remember" is deliberately absent — ADR-0048 ships no
    # writer, and aliasing a store-intent onto a read is the wrong-tool hazard
    # this layer exists to avoid. It is added when a memory-write tool exists.
    "recall": "recall_memory",
    "recall_memories": "recall_memory",
    "search_memory": "recall_memory",
    "search_memories": "recall_memory",
    "retrieve_memory": "recall_memory",
    "memory_recall": "recall_memory",
    "memory_search": "recall_memory",
    "lookup_memory": "recall_memory",
}


def _normalize(capability: str) -> str:
    """Fold a capability string to a case- and separator-insensitive key.

    Case-folds, then collapses every run of *non-alphanumeric* characters to a
    single underscore and strips leading/trailing underscores, so ``"Get Time"``,
    ``"get-time"`` and ``"GET_TIME"`` all yield ``"get_time"``.

    A character is word-forming if its Unicode general category is a letter,
    number or mark (:data:`_WORD_CATEGORIES`) — **Unicode-aware**, so a letter or
    digit in any script is kept and only genuine separators fold. That is what
    makes this surface folding *only* — it never rewrites one word into another.
    An ASCII-only rule would treat a letter like ``é`` as a separator, so
    ``"deleteéaccount"`` would fold onto ``"delete_account"`` and select a tool
    the plan never named; and dropping the combining mark ``casefold`` attaches to
    ``İ`` would fold it onto a plain ``i``. Keeping letters *and* their marks
    forecloses both.
    """
    out: list[str] = []
    prev_separator = False
    for char in capability.casefold():
        if unicodedata.category(char)[0] in _WORD_CATEGORIES:
            out.append(char)
            prev_separator = False
        elif not prev_separator:
            out.append("_")
            prev_separator = True
    return "".join(out).strip("_")


def resolve_capability(emitted: str, advertised: Collection[str]) -> str:
    """Resolve ``emitted`` onto an advertised capability, or return it unchanged.

    The registry is the authority on ``advertised`` (ADR-0016 §5), and every
    branch that rewrites lands on a member of it — so the result is always either
    an advertised capability or the caller's own string verbatim, never an
    invented third value.

    Resolution, in order:

    1. **Exact.** ``emitted`` is already an advertised capability — return it
       untouched, so the common case pays no folding and no table lookup.
    2. **Surface variant.** ``emitted`` folds (:func:`_normalize`) onto exactly
       one advertised capability — return that advertised name in its canonical
       form. If two *distinct* advertised capabilities fold to the same key
       (``delete-user`` and ``delete_user``), the fold is ambiguous and this
       branch declines: choosing one would be a ranking rule this layer refuses
       to invent (ADR-0037 §1), so ``emitted`` falls through unresolved.
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

    # Fold the advertised names once. A key that two *distinct* advertised
    # capabilities fold to is ambiguous — resolving it would silently rank them —
    # so it is dropped rather than decided (ADR-0037 §1).
    canonical: dict[str, str] = {}
    ambiguous: set[str] = set()
    for capability in advertised:
        folded = _normalize(capability)
        if folded in canonical and canonical[folded] != capability:
            ambiguous.add(folded)
        else:
            canonical[folded] = capability

    key = _normalize(emitted)
    if key in canonical:
        # The emitted name is a surface variant of at least one advertised
        # capability, so the synonym table does not apply — it is for names that
        # match no advertised capability. Resolve the unique fold; decline the
        # ambiguous one rather than letting an alias leapfrog it (ADR-0037 §1).
        return emitted if key in ambiguous else canonical[key]

    target = CAPABILITY_ALIASES.get(key)
    if target is not None and target in advertised_set:
        return target

    return emitted


__all__ = ["CAPABILITY_ALIASES", "resolve_capability"]
