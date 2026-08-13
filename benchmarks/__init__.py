"""Offline evaluation tooling that drives `ai_assistant` from outside the package.

**This tree is not the product.** It ships in no wheel — `pyproject.toml`'s
``[tool.hatch.build.targets.wheel] packages = ["src/ai_assistant"]`` decides that by
enumeration — and nothing under ``src/ai_assistant`` imports it or knows it exists.
It is developer tooling in the shape ``scripts/`` established: a top-level directory
outside ``src/``, listed in mypy's ``files`` so "type everything" reaches it.

**What is new here, and why it is worth stating.** The tools in ``scripts/`` read
repository metadata — ADRs, git, GitHub. This is the first non-``src`` tree that
*consumes the library*, and that difference is the whole reason for the placement. A
benchmark harness has to construct real stores, drive the real ingestion pipeline and
read what the real retrieval path returns — but it is not a subsystem, it is not the
composition root, and it must not become either. Inside ``src/ai_assistant`` it would
be a package every ``lint-imports`` contract has to be taught about, a package the
wheel would carry, and a second composition root sitting beside ``app/``. Here it is
an ordinary consumer of the published surface, importing ``ai_assistant`` exactly as
an external application would, and the architecture contracts are untouched because
none of them can see it.

**The one guarantee that placement costs, and how it is bought back.**
``[tool.importlinter] root_package = "ai_assistant"`` builds its graph from that
package alone, so no contract constrains what this tree imports — including golden
rule 4's "no provider SDK outside ``models/``". That is not left as a promise:
``tests/benchmarks/test_import_discipline.py`` parses every module here and fails on
a banned import, which is the same rule held by a different mechanism.
"""

from __future__ import annotations
