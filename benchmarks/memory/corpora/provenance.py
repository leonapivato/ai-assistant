"""What each corpus is, where it was obtained, and under what licence.

**Every download is pinned twice** — to an immutable upstream revision and to a
SHA-256 of the bytes — because a benchmark whose corpus can change underneath it
cannot support a pre-registered prediction. #1029 freezes predictions at merge and
reports results against them; a corpus that silently moved between the prediction
and the result would make "refuted" unreadable. So a fetch that produces different
bytes fails loudly rather than scoring different data under the same name.

Every digest below was observed against the pinned revision on 2026-08-12, either by
downloading and hashing the file or — for the large Hugging Face artifacts — by
reading the ``x-linked-etag`` the LFS pointer resolves to, which *is* the SHA-256 of
the stored object. The digests are recorded here rather than in a lockfile of their
own so that changing one is a reviewed diff in the module that explains what it is.

**Licences bind what may be published, not just what may be downloaded.** LoCoMo is
CC BY-NC 4.0 — non-commercial, with attribution — which is the more restrictive of
the two and the one to check against before any write-up reproduces corpus text.
LongMemEval is MIT. Neither licence is a redistribution grant this repository takes:
nothing here is committed to the tree, and the fetch cache is ignored by git.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class CorpusFile:
    """One immutable artifact of a corpus.

    Attributes:
        name: The filename this is cached under, and the name upstream gives it.
        url: A URL naming the pinned revision, never a moving branch or ``main``.
        sha256: The digest the downloaded bytes must have, lowercase hex.
        size_bytes: The size upstream reports, used only to warn before a long
            download; the digest is what decides acceptance.
    """

    name: str
    url: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Corpus:
    """A benchmark dataset, with the provenance a write-up has to be able to cite.

    Attributes:
        key: How this corpus is named on the command line and in a run manifest.
        title: The dataset's published name.
        homepage: Where the dataset is documented.
        revision: The immutable upstream revision every file below is pinned to.
        licence: The licence's SPDX-ish name, as the publisher states it.
        licence_url: Where that licence text lives.
        citation: The paper to cite, in whatever form the publisher asks for.
        note: Anything a user of this corpus needs to know before reading a score
            computed on it.
        files: The artifacts to fetch.
    """

    key: str
    title: str
    homepage: str
    revision: str
    licence: str
    licence_url: str
    citation: str
    note: str
    files: tuple[CorpusFile, ...]


#: LoCoMo, in the form #1029 sizes its pilot against: ten dialogues, 1,986 questions.
#:
#: Pinned to the commit that last touched ``data/locomo10.json`` rather than to the
#: repository's current ``main``, which is a distinction with a reason: ``main`` has
#: moved since, and pinning to a *file's* last commit makes the pin stable against
#: every future change that does not touch this file.
LOCOMO: Final = Corpus(
    key="locomo",
    title="LoCoMo (Long Conversational Memory)",
    homepage="https://github.com/snap-research/locomo",
    revision="cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc",
    licence="CC BY-NC 4.0",
    licence_url="https://github.com/snap-research/locomo/blob/main/LICENSE.txt",
    citation=(
        "Maharana et al., 'Evaluating Very Long-Term Conversational Memory of LLM "
        "Agents', ACL 2024."
    ),
    note=(
        "Non-commercial licence. The ten dialogues carry 1,986 questions in five "
        "categories, of which category 5 (446 questions) is adversarial: the answer "
        "is not in the conversation and the graded behaviour is abstention. That is "
        "the population #1029's P7 is about, and it is large enough that an "
        "over-answering system loses more on LoCoMo than P7's wording suggests."
    ),
    files=(
        CorpusFile(
            name="locomo10.json",
            url=(
                "https://raw.githubusercontent.com/snap-research/locomo/"
                "cbfbc1dba6bc53d00625212a0f22d55ffee7c1fc/data/locomo10.json"
            ),
            sha256="79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
            size_bytes=2_805_274,
        ),
    ),
)

#: LongMemEval, **cleaned** — and the choice of variant is a finding rather than a
#: detail, so it is recorded here and flagged to the owner rather than made quietly.
#:
#: #1029 names "LongMemEval-S" without naming a variant. The dataset the original
#: paper published (``xiaowu0162/longmemeval``) is marked deprecated by its own
#: author, replaced by ``longmemeval-cleaned``, which "removes noisy history sessions
#: that interfere with the answer correctness". Those are different corpora and they
#: do not produce the same scores: the noisy sessions in the original make some
#: questions unanswerable-in-principle, so a system scores lower on it for reasons
#: that are not about the system. Published headline numbers are quoted against both,
#: which is precisely why the variant has to be pinned before a prediction is scored
#: against it rather than chosen at run time.
#:
#: The cleaned variant is taken as the default because it is the one upstream now
#: publishes and because scoring against a corpus its author has withdrawn would make
#: the pilot's numbers uncomparable to anything current. The original is reachable as
#: :data:`LONGMEMEVAL_ORIGINAL` for a comparison run, and #1029's owner decides which
#: the pre-registration is conditioned on.
LONGMEMEVAL_CLEANED: Final = Corpus(
    key="longmemeval",
    title="LongMemEval (cleaned)",
    homepage="https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
    revision="98d7416c24c778c2fee6e6f3006e7a073259d48f",
    licence="MIT",
    licence_url="https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned",
    citation=(
        "Wu et al., 'LongMemEval: Benchmarking Chat Assistants on Long-Term "
        "Interactive Memory', ICLR 2025."
    ),
    note=(
        "Replaces the deprecated `xiaowu0162/longmemeval`. Six question types, and "
        "each question carries its own haystack — so a run ingests one store per "
        "question, not one per corpus. Question ids ending `_abs` are the abstention "
        "variants (#1029's P7)."
    ),
    files=(
        CorpusFile(
            name="longmemeval_s_cleaned.json",
            url=(
                "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
                "resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/"
                "longmemeval_s_cleaned.json"
            ),
            sha256="d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
            size_bytes=277_383_467,
        ),
        CorpusFile(
            name="longmemeval_oracle.json",
            url=(
                "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/"
                "resolve/98d7416c24c778c2fee6e6f3006e7a073259d48f/"
                "longmemeval_oracle.json"
            ),
            sha256="821a2034d219ab45846873dd14c14f12cfe7776e73527a483f9dac095d38620c",
            size_bytes=15_388_478,
        ),
    ),
)

#: The corpus the LongMemEval paper published, kept reachable and not default.
#:
#: Deprecated upstream. Here so that "did the variant change the number?" is a
#: question the harness can answer rather than one a reader has to take on trust.
LONGMEMEVAL_ORIGINAL: Final = Corpus(
    key="longmemeval-original",
    title="LongMemEval (original, deprecated upstream)",
    homepage="https://huggingface.co/datasets/xiaowu0162/longmemeval",
    revision="2ec2a557f339b6c0369619b1ed5793734cc87533",
    licence="MIT",
    licence_url="https://huggingface.co/datasets/xiaowu0162/longmemeval",
    citation=(
        "Wu et al., 'LongMemEval: Benchmarking Chat Assistants on Long-Term "
        "Interactive Memory', ICLR 2025."
    ),
    note=(
        "Withdrawn by its author in favour of the cleaned variant. Use only to "
        "measure what the cleaning changed."
    ),
    files=(
        CorpusFile(
            name="longmemeval_s.json",
            url=(
                "https://huggingface.co/datasets/xiaowu0162/longmemeval/resolve/"
                "2ec2a557f339b6c0369619b1ed5793734cc87533/longmemeval_s"
            ),
            sha256="08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894",
            size_bytes=278_025_796,
        ),
    ),
)

#: Every corpus the harness knows, by the key the command line takes.
CORPORA: Final[dict[str, Corpus]] = {
    corpus.key: corpus for corpus in (LOCOMO, LONGMEMEVAL_CLEANED, LONGMEMEVAL_ORIGINAL)
}


def corpus_by_key(key: str) -> Corpus:
    """Look up a corpus by its command-line key.

    Args:
        key: One of the keys in :data:`CORPORA`.

    Returns:
        The corpus.

    Raises:
        KeyError: If no corpus carries that key, with the known keys in the message
            — a mistyped key is the most likely way to reach this and the fix is
            always to read the list.
    """
    try:
        return CORPORA[key]
    except KeyError:
        known = ", ".join(sorted(CORPORA))
        msg = f"unknown corpus {key!r}; known corpora are {known}"
        raise KeyError(msg) from None
