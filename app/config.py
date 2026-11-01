"""Environment-backed configuration for the demo service."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return None
    return int(raw)


@dataclass(frozen=True)
class Settings:
    """Runtime settings.

    The defaults are deliberately conservative: OCR only when the text layer is
    missing or unusable, 200 DPI, and no lowercasing so exported text stays
    readable.
    """

    data_dir: Path = Path(".data")
    max_upload_mb: int = 50
    ocr_mode: str = "auto"
    ocr_language: str = "eng"
    ocr_dpi: int = 200
    ocr_psm: int = 3
    min_text_chars: int = 40
    min_alnum_ratio: float = 0.25
    low_confidence_threshold: float = 0.60
    tesseract_cmd: str | None = None
    preprocess_grayscale: bool = True
    preprocess_autocontrast: bool = True
    preprocess_threshold: int | None = None
    remove_furniture: bool = True
    furniture_margin: float = 72.0
    furniture_threshold: float = 0.60
    expand_contractions: bool = True
    lowercase_text: bool = False
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        object.__setattr__(self, "data_dir", Path(self.data_dir))
        object.__setattr__(self, "ocr_mode", self.ocr_mode.lower())
        object.__setattr__(self, "log_level", self.log_level.upper())

        if self.ocr_mode not in {"auto", "always", "never"}:
            raise ValueError("OCR_MODE must be one of: auto, always, never")
        if not (100 <= self.ocr_dpi <= 600):
            raise ValueError("OCR_DPI must be between 100 and 600")
        if not (0 <= self.ocr_psm <= 13):
            raise ValueError("OCR_PSM must be between 0 and 13")
        if self.max_upload_mb < 1:
            raise ValueError("MAX_UPLOAD_MB must be at least 1")
        if self.min_text_chars < 0:
            raise ValueError("MIN_TEXT_CHARS must be zero or greater")
        if not (0.0 <= self.min_alnum_ratio <= 1.0):
            raise ValueError("MIN_ALNUM_RATIO must be between 0 and 1")
        if not (0.0 <= self.low_confidence_threshold <= 1.0):
            raise ValueError("LOW_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if self.preprocess_threshold is not None and not (
            0 <= self.preprocess_threshold <= 255
        ):
            raise ValueError("PREPROCESS_THRESHOLD must be between 0 and 255")
        if self.furniture_margin < 0:
            raise ValueError("FURNITURE_MARGIN must be zero or greater")
        if not (0.1 <= self.furniture_threshold <= 1.0):
            raise ValueError("FURNITURE_THRESHOLD must be between 0.1 and 1.0")

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            data_dir=Path(os.getenv("DATA_DIR", ".data")),
            max_upload_mb=_env_int("MAX_UPLOAD_MB", 50),
            ocr_mode=os.getenv("OCR_MODE", "auto"),
            ocr_language=os.getenv("OCR_LANGUAGE", "eng"),
            ocr_dpi=_env_int("OCR_DPI", 200),
            ocr_psm=_env_int("OCR_PSM", 3),
            min_text_chars=_env_int("MIN_TEXT_CHARS", 40),
            min_alnum_ratio=_env_float("MIN_ALNUM_RATIO", 0.25),
            low_confidence_threshold=_env_float("LOW_CONFIDENCE_THRESHOLD", 0.60),
            tesseract_cmd=os.getenv("TESSERACT_CMD") or None,
            preprocess_grayscale=_env_bool("PREPROCESS_GRAYSCALE", True),
            preprocess_autocontrast=_env_bool("PREPROCESS_AUTOCONTRAST", True),
            preprocess_threshold=_env_optional_int("PREPROCESS_THRESHOLD"),
            remove_furniture=_env_bool("REMOVE_FURNITURE", True),
            furniture_margin=_env_float("FURNITURE_MARGIN", 72.0),
            furniture_threshold=_env_float("FURNITURE_THRESHOLD", 0.60),
            expand_contractions=_env_bool("EXPAND_CONTRACTIONS", True),
            lowercase_text=_env_bool("LOWERCASE_TEXT", False),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )

    def with_overrides(self, **kwargs: object) -> "Settings":
        return replace(self, **kwargs)
