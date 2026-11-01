from app.metrics import (
    character_error_rate,
    levenshtein_distance,
    normalize_for_metrics,
    word_error_rate,
)


def test_normalize_for_metrics_casefolds_and_removes_punctuation():
    assert normalize_for_metrics("Hello,  WORLD!") == "hello world"


def test_levenshtein_distance_known_example():
    assert levenshtein_distance("kitten", "sitting") == 3


def test_character_error_rate_identical_text_is_zero():
    assert character_error_rate("hello world", "hello world") == 0.0


def test_character_error_rate_counts_substitutions():
    assert character_error_rate("abc", "adc") == 1 / 3


def test_word_error_rate_identical_text_is_zero():
    assert word_error_rate("hello world", "hello world") == 0.0


def test_word_error_rate_counts_a_missing_word():
    assert word_error_rate("one two three", "one three") == 1 / 3


def test_empty_reference_handling():
    assert character_error_rate("", "") == 0.0
    assert character_error_rate("", "text") == 1.0
