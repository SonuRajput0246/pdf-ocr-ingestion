"""OCR engine adapters."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from .errors import OCREngineUnavailable


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float | None = None
    engine: str = "unknown"


class OCREngine(Protocol):
    name: str

    def available(self) -> bool: ...

    def image_to_text(
        self,
        image: Image.Image,
        *,
        language: str = "eng",
        psm: int = 3,
    ) -> OCRResult: ...


def _value(data: dict[str, list[Any]], key: str, index: int, default: Any) -> Any:
    values = data.get(key, [])
    if index < len(values):
        return values[index]
    return default


def reconstruct_tesseract_data(data: dict[str, list[Any]]) -> tuple[str, float | None]:
    """Rebuild line-oriented text and mean confidence from ``image_to_data``."""

    groups: dict[tuple[int, int, int], list[tuple[str, float]]] = {}
    words = data.get("text", [])

    for index, raw_word in enumerate(words):
        word = str(raw_word).strip()
        if not word:
            continue

        try:
            confidence = float(_value(data, "conf", index, -1.0))
        except (TypeError, ValueError):
            confidence = -1.0

        key = (
            int(_value(data, "block_num", index, 0)),
            int(_value(data, "par_num", index, 0)),
            int(_value(data, "line_num", index, 0)),
        )
        groups.setdefault(key, []).append((word, confidence))

    lines: list[str] = []
    confidences: list[float] = []
    for key in sorted(groups):
        line_words = groups[key]
        lines.append(" ".join(word for word, _ in line_words))
        confidences.extend(
            confidence for _, confidence in line_words if confidence >= 0
        )

    text = "\n".join(lines)
    mean_confidence = (
        sum(confidences) / len(confidences) / 100.0 if confidences else None
    )
    return text, mean_confidence


class TesseractOCREngine:
    """Thin pytesseract adapter with lazy imports and explicit errors."""

    name = "tesseract"

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        self.tesseract_cmd = tesseract_cmd

    def _load(self) -> tuple[Any, Any]:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise OCREngineUnavailable(
                "pytesseract is not installed; run pip install -r requirements.txt"
            ) from exc

        if self.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
        return pytesseract, Output

    def available(self) -> bool:
        if self.tesseract_cmd:
            return Path(self.tesseract_cmd).exists()
        return shutil.which("tesseract") is not None

    def image_to_text(
        self,
        image: Image.Image,
        *,
        language: str = "eng",
        psm: int = 3,
    ) -> OCRResult:
        pytesseract, output = self._load()
        config = f"--psm {psm}"
        try:
            data = pytesseract.image_to_data(
                image,
                lang=language,
                config=config,
                output_type=output.DICT,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OCREngineUnavailable(
                "The Tesseract binary was not found. Install it and set TESSERACT_CMD "
                "if it is not on PATH."
            ) from exc
        except pytesseract.TesseractError as exc:
            raise OCREngineUnavailable(f"Tesseract failed: {exc}") from exc

        text, confidence = reconstruct_tesseract_data(data)
        return OCRResult(text=text, confidence=confidence, engine=self.name)


class StubOCREngine:
    """Deterministic OCR engine for tests and offline demos."""

    name = "stub"

    def __init__(self, text: str = "Stub OCR text.", confidence: float = 0.95) -> None:
        self.text = text
        self.confidence = confidence
        self.calls = 0

    def available(self) -> bool:
        return True

    def image_to_text(
        self,
        image: Image.Image,
        *,
        language: str = "eng",
        psm: int = 3,
    ) -> OCRResult:
        self.calls += 1
        return OCRResult(
            text=self.text, confidence=self.confidence, engine=self.name
        )
