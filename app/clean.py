"""Six-stage text cleaning chain for extracted PDF text."""

from __future__ import annotations

import re
import unicodedata

try:  # Optional at import time; listed in requirements.txt.
    import ftfy
except ImportError:  # pragma: no cover - exercised only in minimal installs
    ftfy = None  # type: ignore[assignment]

try:  # Optional at import time; listed in requirements.txt.
    import contractions
except ImportError:  # pragma: no cover - exercised only in minimal installs
    contractions = None  # type: ignore[assignment]

_PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:page\s+)?\d+(?:\s*(?:of|/)\s*\d+)?\s*$", re.IGNORECASE
)
_DASH_PAGE_RE = re.compile(r"^\s*[-–—]\s*\d+\s*[-–—]\s*$")
_DOI_RE = re.compile(
    r"^\s*(?:doi\s*:?\s*|https?://(?:dx\.)?doi\.org/)\S+\s*$",
    re.IGNORECASE,
)
_COPYRIGHT_RE = re.compile(r"^\s*(?:copyright|©|\(c\))\s*.{0,160}$", re.IGNORECASE)
_RIGHTS_RE = re.compile(r"^\s*all rights reserved\.?\s*$", re.IGNORECASE)
_DOT_LEADER_RE = re.compile(r"\.{4,}")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_SPACE_AROUND_NEWLINE_RE = re.compile(r" *\n *")

_ALLOWED_PUNCTUATION = set(
    ".,;:!?()[]{}'\"“”‘’—–-/\\&%+*=<>@#§°_$€£₹"
)


def fix_encoding_issues(text: str) -> str:
    """Stage 1: repair mojibake before any regex sees the characters."""

    if ftfy is None:
        return text
    try:
        return ftfy.fix_text(text)
    except Exception:  # pragma: no cover - defensive around a best-effort fixer
        return text


def remove_page_furniture(text: str) -> str:
    """Stage 2: drop standalone page numbers, DOI lines and copyright lines."""

    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for line in normalised.split("\n"):
        stripped = line.strip()
        if not stripped:
            kept.append("")
            continue
        if (
            _PAGE_NUMBER_RE.match(stripped)
            or _DASH_PAGE_RE.match(stripped)
            or _DOI_RE.match(stripped)
            or _COPYRIGHT_RE.match(stripped)
            or _RIGHTS_RE.match(stripped)
        ):
            continue
        kept.append(line)
    return "\n".join(kept)


def expand_contractions(text: str) -> str:
    """Stage 3: expand common contractions so query/document wording aligns."""

    if contractions is None:
        return text
    try:
        return contractions.fix(text)
    except Exception:  # pragma: no cover - defensive around a best-effort fixer
        return text


def clean_whitespace(text: str) -> str:
    """Stage 4: stabilise whitespace and remove dot leaders."""

    text = _DOT_LEADER_RE.sub(" ", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = _MULTI_SPACE_RE.sub(" ", text)
    text = _SPACE_AROUND_NEWLINE_RE.sub("\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _keep_character(character: str) -> bool:
    if character == "\n":
        return True
    if character in _ALLOWED_PUNCTUATION:
        return True
    category = unicodedata.category(character)
    return category[0] in {"L", "N"} or category == "Zs"


def clean_special_chars(text: str) -> str:
    """Stage 5: remove bullets, box glyphs, control characters and emoji."""

    text = text.replace("\t", " ")
    cleaned = "".join(character for character in text if _keep_character(character))
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return _SPACE_AROUND_NEWLINE_RE.sub("\n", cleaned)


def normalize_text(text: str, *, lowercase: bool = False) -> str:
    """Stage 6: Unicode-normalise, trim, and optionally lowercase."""

    text = unicodedata.normalize("NFC", text).strip()
    if lowercase:
        text = text.lower()
    return text


def clean_text(
    text: str,
    *,
    lowercase: bool = False,
    expand_contractions_enabled: bool = True,
) -> str:
    """Run the six cleaning passes in the documented order."""

    text = fix_encoding_issues(text)
    text = remove_page_furniture(text)
    if expand_contractions_enabled:
        text = expand_contractions(text)
    text = clean_whitespace(text)
    text = clean_special_chars(text)
    return normalize_text(text, lowercase=lowercase)
