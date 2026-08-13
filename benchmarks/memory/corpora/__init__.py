"""Benchmark corpora: where they come from, and how their format becomes ours.

:mod:`~benchmarks.memory.corpora.provenance` is the record — URL, pinned revision,
SHA-256, licence — and it is the module to read before using any of this data for
anything published. :mod:`~benchmarks.memory.corpora.fetch` acquires and verifies;
:mod:`~benchmarks.memory.corpora.locomo` and
:mod:`~benchmarks.memory.corpora.longmemeval` parse.
"""

from __future__ import annotations
