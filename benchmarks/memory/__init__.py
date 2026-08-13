"""The memory-benchmark harness: LoCoMo and LongMemEval against the real pipeline.

Built for the pilot pre-registered in issue #1029. **Running it is a separate act
from building it**, and #1029's ground rule 1 governs that act: the pre-registration
is finalised by the owner before any scored evaluation, and until then only smoke
runs — a handful of questions, to validate plumbing — are permitted, with their
outputs not read as scores.

The harness makes that distinction structural rather than a convention. Every run
writes a :class:`~benchmarks.memory.records.RunManifest` carrying a
:class:`~benchmarks.memory.records.RunMode`, and ``SMOKE`` is the default: a scored
run has to be asked for by name, is refused unless the operator states the
pre-registration is final, and lands under a different output directory. So "has a
scored run happened?" is answerable by looking at the artifacts instead of by
remembering.

What the modules do:

* :mod:`benchmarks.memory.corpora` — where the datasets come from, how they are
  fetched and verified, and how each one's published format becomes this harness's
  own :mod:`~benchmarks.memory.cases` types. Provenance lives there.
* :mod:`benchmarks.memory.cases` — the corpus-neutral shape everything downstream
  reads: a conversation to ingest, and the questions asked about it.
* :mod:`benchmarks.memory.wiring` — the harness's own composition, mirroring the
  slice of ``ai_assistant.app.composition`` a benchmark needs, plus the counting
  store that answers #1029's P4.
* :mod:`benchmarks.memory.ingest` — a case's sessions through the real capture and
  observation path.
* :mod:`benchmarks.memory.answer` — the retrieval-only answering path, through the
  ``ModelProvider`` seam.
* :mod:`benchmarks.memory.grade` — how an answer is judged.
* :mod:`benchmarks.memory.records` — the per-question record and the run manifest.
* :mod:`benchmarks.memory.run` — the loop that composes all of the above.
"""

from __future__ import annotations
