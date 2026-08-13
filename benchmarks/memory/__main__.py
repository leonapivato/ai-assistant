"""The harness's command line: ``uv run python -m benchmarks.memory``.

Four commands, and the order they are listed in is the order they are used in.

``corpora`` prints the provenance record — what each dataset is, where it comes from,
and under what licence. Read it before publishing anything computed from this data;
LoCoMo is non-commercial.

``fetch`` acquires and verifies. It is separate from ``run`` because a 278 MiB
download failing in the middle of a paid run is a bad place to discover a network
problem, and because a verified cache makes every later run start instantly.

``plan`` says what a run would cost — cases, questions, and model calls split by what
makes them — and contacts nothing. It is the command to run before spending.

``run`` executes. It defaults to a **smoke** run of five questions with a grader that
makes no model call, because #1029's ground rule 1 permits smoke runs and forbids
reading their output as scores until the pre-registration is final. A scored run has
to be asked for by name and confirmed.

**This is not an ``assistant`` subcommand and it is not a console script.** The
offline-tool family in ``pyproject.toml`` exists because those tools take the hub's
instance lock and live in ``service``, which nothing may import (ADR-0084 §6). None of
that applies here: this is outside the package entirely, so ``python -m`` is the whole
mechanism it needs and adding an entry point would put a benchmark harness in the
wheel.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from ai_assistant.core.config import Settings
from benchmarks.memory.corpora import locomo, longmemeval
from benchmarks.memory.corpora.fetch import DEFAULT_CACHE, digest_of, ensure_corpus
from benchmarks.memory.corpora.provenance import CORPORA, Corpus, corpus_by_key
from benchmarks.memory.records import RunMode
from benchmarks.memory.run import (
    build_grader,
    execute_run,
    plan_run,
    refuse_unconfirmed_scored_run,
)
from benchmarks.memory.select import first_questions, first_sessions

if TYPE_CHECKING:
    from benchmarks.memory.cases import BenchCase

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="The memory benchmark harness (issue #1029). Build-and-smoke; scored runs are gated.",
)
console = Console()

#: Where runs land, beside the harness and ignored by git.
DEFAULT_RUNS = Path(__file__).resolve().parent.parent / ".runs"

#: How many questions a smoke run takes when none is asked for. Five, because a smoke
#: run exists to prove the plumbing carries an answer end to end and #1029 calls that
#: "a handful of questions".
SMOKE_DEFAULT = 5


@app.command()
def corpora() -> None:
    """Print the provenance record for every corpus the harness knows."""
    for corpus in CORPORA.values():
        console.print(f"[bold]{corpus.key}[/bold] — {corpus.title}")
        console.print(f"  homepage  {corpus.homepage}")
        console.print(f"  revision  {corpus.revision}")
        console.print(f"  licence   {corpus.licence}  ({corpus.licence_url})")
        console.print(f"  citation  {corpus.citation}")
        console.print(f"  note      {corpus.note}")
        for file in corpus.files:
            cached = DEFAULT_CACHE / file.name
            state = "cached" if cached.exists() else "not fetched"
            console.print(f"  file      {file.name}  {file.size_bytes:,} bytes  [{state}]")
            console.print(f"            sha256 {file.sha256}")
        console.print()


@app.command()
def fetch(
    corpus_key: Annotated[str, typer.Argument(help="Corpus key; see `corpora`.")],
    cache: Annotated[Path | None, typer.Option(help="Cache root.")] = None,
) -> None:
    """Download and verify a corpus, or confirm a cached copy still verifies."""
    corpus = corpus_by_key(corpus_key)
    paths = ensure_corpus(corpus, cache=cache)
    for name, path in paths.items():
        console.print(f"[green]verified[/green] {name}  {path}")


@app.command()
def plan(
    corpus_key: Annotated[str, typer.Argument(help="Corpus key; see `corpora`.")],
    limit: Annotated[int, typer.Option(help="Questions to include; 0 means all.")] = 0,
    seed: Annotated[int, typer.Option(help="Seed for a stratified slice.")] = 1029,
    max_sessions: Annotated[
        int, typer.Option(help="Truncate each case to its first N sessions; 0 means all.")
    ] = 0,
    cache: Annotated[Path | None, typer.Option(help="Cache root.")] = None,
) -> None:
    """Report what a run would cost. Contacts no provider and opens no store."""
    settings = Settings()
    corpus, cases, _ = _select(
        corpus_key, limit=limit, seed=seed, max_sessions=max_sessions, cache=cache
    )
    computed = plan_run(corpus, cases, batch_size=settings.observation_batch_size)

    table = Table(title=f"{corpus.title}: what this run would do", show_header=False)
    table.add_row("cases (one store each)", f"{len(computed.cases):,}")
    table.add_row("questions", f"{computed.question_count:,}")
    table.add_row("turns captured", f"{computed.turn_count:,}")
    table.add_row("observation model calls", f"{computed.observation_calls:,}")
    table.add_row("answering model calls", f"{computed.answer_calls:,}")
    table.add_row("judging model calls (at most)", f"{computed.judge_calls:,}")
    table.add_row("[bold]total model calls (at most)", f"[bold]{computed.model_calls:,}")
    table.add_row("embedder", str(settings.embedder))
    table.add_row("answer route", settings.default_model)
    table.add_row("episode retention", _retention(settings))
    console.print(table)
    _warn_about_configuration(settings, computed.cases)


@app.command()
def run(  # noqa: PLR0913 — each option is an axis of the experiment and every one lands in the manifest
    corpus_key: Annotated[str, typer.Argument(help="Corpus key; see `corpora`.")],
    limit: Annotated[int, typer.Option(help="Questions to include; 0 means all.")] = SMOKE_DEFAULT,
    seed: Annotated[int, typer.Option(help="Seed for a stratified slice.")] = 1029,
    max_sessions: Annotated[
        int, typer.Option(help="Truncate each case to its first N sessions; 0 means all.")
    ] = 0,
    mode: Annotated[RunMode, typer.Option(help="smoke or scored.")] = RunMode.SMOKE,
    grader: Annotated[str, typer.Option(help="'exact' (no model call) or 'model'.")] = "exact",
    preregistration_final: Annotated[
        bool, typer.Option(help="Confirm #1029 ground rule 1 is discharged.")
    ] = False,
    keep_stores: Annotated[bool, typer.Option(help="Keep each case's databases.")] = False,
    notes: Annotated[str, typer.Option(help="Attached to the manifest.")] = "",
    output: Annotated[Path | None, typer.Option(help="Where run directories go.")] = None,
    cache: Annotated[Path | None, typer.Option(help="Cache root.")] = None,
) -> None:
    """Execute a run. Smoke by default; a scored run must be asked for and confirmed."""
    refuse_unconfirmed_scored_run(mode, preregistration_final=preregistration_final)
    settings = Settings()
    corpus, cases, digests = _select(
        corpus_key, limit=limit, seed=seed, max_sessions=max_sessions, cache=cache
    )
    computed = plan_run(corpus, cases, batch_size=settings.observation_batch_size)
    _warn_about_configuration(settings, computed.cases)

    manifest = asyncio.run(
        execute_run(
            computed,
            output_root=output if output is not None else DEFAULT_RUNS,
            mode=mode,
            corpus_digests=digests,
            settings=settings,
            grader=build_grader(settings, kind=grader),
            slice_seed=seed if limit else None,
            notes=notes,
            keep_stores=keep_stores,
        )
    )
    root = output if output is not None else DEFAULT_RUNS
    console.print(
        f"[green]{manifest.mode}[/green] run {manifest.run_id} -> {root / manifest.run_id}"
    )
    if manifest.mode is RunMode.SMOKE:
        console.print(
            "[yellow]Smoke run.[/yellow] Its outputs validate plumbing and are not scores "
            "(issue #1029, ground rule 1)."
        )


def _select(
    corpus_key: str, *, limit: int, seed: int, max_sessions: int, cache: Path | None
) -> tuple[Corpus, tuple[BenchCase, ...], dict[str, str]]:
    """Fetch, load and select the cases a command will work on.

    Args:
        corpus_key: Which corpus.
        limit: How many questions; ``0`` means all.
        seed: Seed for the stratified draw.
        max_sessions: Truncate each case to its first ``N`` sessions; ``0`` means all.
        cache: Cache root.

    Returns:
        The corpus, the selected cases, and each fetched file's digest.
    """
    corpus = corpus_by_key(corpus_key)
    paths = ensure_corpus(corpus, cache=cache)
    digests = {name: digest_of(path) for name, path in paths.items()}

    if corpus.key == "locomo":
        cases = locomo.load(paths["locomo10.json"])
        # LoCoMo asks ~199 questions of each dialogue, so a question limit is really a
        # limit on *cases* — taking 5 questions means ingesting one dialogue, not ten.
        # Truncating each case's question list is what makes a smoke run cost one
        # ingestion instead of ten.
        selected = first_questions(cases, limit)
    else:
        selected = longmemeval.load(next(iter(paths.values())))
        if limit:
            selected = longmemeval.stratified(selected, total=limit, seed=seed)
    return corpus, first_sessions(selected, max_sessions), digests


def _retention(settings: Settings) -> str:
    """The configured episode retention, as the manifest spells it.

    Args:
        settings: Loaded application settings.

    Returns:
        The horizon, or ``"none"``.
    """
    return "none" if settings.episode_retention is None else str(settings.episode_retention)


def _warn_about_configuration(settings: Settings, cases: tuple[BenchCase, ...]) -> None:
    """Say, loudly, when the configuration will quietly distort what is measured.

    Two conditions, both of which produce a run that completes and reports numbers
    about something other than the system under test.

    Args:
        settings: Loaded application settings.
        cases: The selected cases.
    """
    if str(settings.embedder) != "on-device":
        console.print(
            "[red]ASSISTANT_EMBEDDER is not 'on-device'.[/red] Retrieval is then "
            "non-semantic and the run measures plumbing, not memory (#1029 requires "
            "the real embedder)."
        )
    horizon = settings.episode_retention
    if horizon is None or not cases:
        return
    widest = max(
        (case.sessions[-1].occurred_at - case.sessions[0].occurred_at for case in cases),
        default=horizon,
    )
    if widest > horizon:
        console.print(
            f"[red]Episode retention is {horizon} but a case spans {widest}.[/red] "
            "The harness runs on the corpus clock, so early sessions' episodes expire "
            "before late ones are captured. Set ASSISTANT_EPISODE_RETENTION=none."
        )


if __name__ == "__main__":
    app()
