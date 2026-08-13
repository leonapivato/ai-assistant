"""The provenance record has to be usable as a citation, so it is checked like one."""

from __future__ import annotations

import re

import pytest
from benchmarks.memory.corpora.provenance import (
    CORPORA,
    LOCOMO,
    LONGMEMEVAL_CLEANED,
    Corpus,
    corpus_by_key,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")


@pytest.mark.parametrize("corpus", CORPORA.values(), ids=lambda corpus: corpus.key)
def test_every_file_is_fetched_over_https(corpus: Corpus) -> None:
    """The fetcher refuses anything else; the record should never ask it to."""
    for file in corpus.files:
        assert file.url.startswith("https://")


@pytest.mark.parametrize("corpus", CORPORA.values(), ids=lambda corpus: corpus.key)
def test_every_url_names_the_pinned_revision(corpus: Corpus) -> None:
    """A URL naming a branch is a corpus that can move under a frozen prediction."""
    for file in corpus.files:
        assert corpus.revision in file.url, (
            f"{corpus.key}/{file.name} is not pinned to {corpus.revision}"
        )
        assert "/main/" not in file.url


@pytest.mark.parametrize("corpus", CORPORA.values(), ids=lambda corpus: corpus.key)
def test_every_digest_is_a_lowercase_sha256(corpus: Corpus) -> None:
    """An uppercase or truncated digest compares unequal to what hashing produces."""
    for file in corpus.files:
        assert SHA256.match(file.sha256), f"{corpus.key}/{file.name}: {file.sha256!r}"


@pytest.mark.parametrize("corpus", CORPORA.values(), ids=lambda corpus: corpus.key)
def test_every_corpus_records_a_licence_and_a_citation(corpus: Corpus) -> None:
    """A benchmark result that cannot cite its corpus is not publishable."""
    assert corpus.licence
    assert corpus.licence_url.startswith("https://")
    assert corpus.citation


def test_locomo_is_recorded_as_non_commercial() -> None:
    """The one licence fact a write-up must not get wrong."""
    assert LOCOMO.licence == "CC BY-NC 4.0"


def test_the_default_longmemeval_is_the_cleaned_variant() -> None:
    """The key `longmemeval` resolves to the corpus upstream still publishes."""
    assert corpus_by_key("longmemeval") is LONGMEMEVAL_CLEANED


def test_keys_are_unique_and_self_describing() -> None:
    """The mapping is built from the corpora, so a duplicated key would lose one."""
    assert len(CORPORA) == 3
    for key, corpus in CORPORA.items():
        assert corpus.key == key


def test_an_unknown_key_names_the_known_ones() -> None:
    """A mistyped key is the likeliest way here and the fix is always to read the list."""
    with pytest.raises(KeyError, match="locomo"):
        corpus_by_key("locomoo")
