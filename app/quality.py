"""Heuristics for deciding whether a text layer is usable."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextQuality:
    usable: bool
    reason: str
    char_count: int
    alnum_ratio: float


def assess_text(
    text: str,
    *,
    min_chars: int = 40,
    min_alnum_ratio: float = 0.25,
) -> TextQuality:
    """Return whether extracted text is substantial enough to skip OCR."""

    stripped = text.strip()
    char_count = len(stripped)
    if char_count == 0:
        return TextQuality(False, "empty", 0, 0.0)

    visible = [character for character in stripped if not character.isspace()]
    alnum = sum(character.isalnum() for character in visible)
    alnum_ratio = alnum / len(visible) if visible else 0.0

    if char_count < min_chars:
        return TextQuality(
            False,
            f"too_short:{char_count}<{min_chars}",
            char_count,
            alnum_ratio,
        )
    replacement_ratio = stripped.count("\ufffd") / char_count
    if replacement_ratio > 0.05:
        return TextQuality(
            False, "replacement_characters", char_count, alnum_ratio
        )
    if alnum_ratio < min_alnum_ratio:
        return TextQuality(
            False,
            f"low_alnum_ratio:{alnum_ratio:.2f}<{min_alnum_ratio}",
            char_count,
            alnum_ratio,
        )
    return TextQuality(True, "ok", char_count, alnum_ratio)
