"""Serialisable domain models used by the job store and API."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

TERMINAL_JOB_STATUSES = {"completed", "completed_with_errors"}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a trailing ``Z``."""

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


@dataclass(frozen=True)
class JobOptions:
    """Extraction options that are part of the idempotency key."""

    ocr_mode: str = "auto"
    language: str = "eng"
    dpi: int = 200
    min_text_chars: int = 40
    min_alnum_ratio: float = 0.25
    preprocess_grayscale: bool = True
    preprocess_autocontrast: bool = True
    preprocess_threshold: int | None = None
    remove_furniture: bool = True
    furniture_margin: float = 72.0
    furniture_threshold: float = 0.60
    expand_contractions: bool = True
    lowercase_text: bool = False
    psm: int = 3

    def __post_init__(self) -> None:
        object.__setattr__(self, "ocr_mode", self.ocr_mode.lower())
        object.__setattr__(self, "language", self.language.strip())

        if self.ocr_mode not in {"auto", "always", "never"}:
            raise ValueError("ocr_mode must be one of: auto, always, never")
        if not re.fullmatch(r"[A-Za-z0-9_+-]{1,64}", self.language):
            raise ValueError("language must be a Tesseract language code such as eng or eng+fra")
        if not (100 <= self.dpi <= 600):
            raise ValueError("dpi must be between 100 and 600")
        if not (0 <= self.psm <= 13):
            raise ValueError("psm must be between 0 and 13")
        if self.min_text_chars < 0:
            raise ValueError("min_text_chars must be zero or greater")
        if not (0.0 <= self.min_alnum_ratio <= 1.0):
            raise ValueError("min_alnum_ratio must be between 0 and 1")
        if self.preprocess_threshold is not None and not (
            0 <= self.preprocess_threshold <= 255
        ):
            raise ValueError("preprocess_threshold must be between 0 and 255")
        if self.furniture_margin < 0:
            raise ValueError("furniture_margin must be zero or greater")
        if not (0.1 <= self.furniture_threshold <= 1.0):
            raise ValueError("furniture_threshold must be between 0.1 and 1.0")

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JobOptions:
        names = {item.name for item in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class JobRecord:
    job_id: str
    tenant_id: str
    application_id: str
    source_name: str
    source_sha256: str
    source_bytes: int
    options: dict[str, Any]
    status: str = "queued"
    stage: str = "queued"
    pages_total: int = 0
    pages_done: int = 0
    pages_text: int = 0
    pages_ocr: int = 0
    pages_empty: int = 0
    pages_failed: int = 0
    pages_low_confidence: int = 0
    mean_ocr_confidence: float | None = None
    document_type: str = "unknown"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    error: str | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> JobRecord:
        names = {item.name for item in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})

    def touch(self) -> None:
        self.updated_at = utc_now()

    @property
    def progress(self) -> float:
        if self.pages_total <= 0:
            return 0.0
        return round(min(self.pages_done / self.pages_total, 1.0), 4)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_JOB_STATUSES


@dataclass
class PageRecord:
    page_number: int
    status: str = "ok"
    method: str = "empty"
    text: str = ""
    char_count: int = 0
    word_count: int = 0
    confidence: float | None = None
    quality: str = "empty"
    ocr_attempted: bool = False
    ocr_error: str | None = None
    furniture_removed: int = 0
    duration_ms: int = 0
    extracted_at: str = field(default_factory=utc_now)
    text_sha256: str = ""
    error: str | None = None

    def __post_init__(self) -> None:
        if self.text and not self.char_count:
            self.char_count = len(self.text)
        if self.text and not self.word_count:
            self.word_count = count_words(self.text)
        if self.text and not self.text_sha256:
            self.text_sha256 = sha256_text(self.text)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PageRecord:
        names = {item.name for item in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})

    def summary(self) -> dict[str, Any]:
        preview = re.sub(r"\s+", " ", self.text).strip()[:200]
        return {
            "page_number": self.page_number,
            "status": self.status,
            "method": self.method,
            "quality": self.quality,
            "char_count": self.char_count,
            "word_count": self.word_count,
            "confidence": self.confidence,
            "ocr_attempted": self.ocr_attempted,
            "furniture_removed": self.furniture_removed,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "preview": preview,
        }
