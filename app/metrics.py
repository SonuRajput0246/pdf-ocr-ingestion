"""Small text metrics used by the extraction evaluation harness."""

from __future__ import annotations

import re

_NON_WORD_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_metrics(text: str) -> str:
    """Case-fold, strip punctuation and collapse whitespace."""

    text = text.casefold()
    text = _NON_WORD_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def levenshtein_distance(reference: str, hypothesis: str) -> int:
    """Memory-efficient edit distance."""

    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference

    previous = list(range(len(hypothesis) + 1))
    for row, reference_character in enumerate(reference, start=1):
        current = [row]
        for column, hypothesis_character in enumerate(hypothesis, start=1):
            insert = current[column - 1] + 1
            delete = previous[column] + 1
            substitute = previous[column - 1] + (
                reference_character != hypothesis_character
            )
            current.append(min(insert, delete, substitute))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    reference = normalize_for_metrics(reference)
    hypothesis = normalize_for_metrics(hypothesis)
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return levenshtein_distance(reference, hypothesis) / len(reference)


def word_error_rate(reference: str, hypothesis: str) -> float:
    reference_words = normalize_for_metrics(reference).split()
    hypothesis_words = normalize_for_metrics(hypothesis).split()
    if not reference_words:
        return 0.0 if not hypothesis_words else 1.0
    return (
        levenshtein_distance(reference_words, hypothesis_words)
        / len(reference_words)
    )
