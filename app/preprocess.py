"""Lightweight image preprocessing for OCR."""

from __future__ import annotations

from PIL import Image, ImageOps


def preprocess_image(
    image: Image.Image,
    *,
    grayscale: bool = True,
    autocontrast: bool = True,
    threshold: int | None = None,
) -> Image.Image:
    """Apply a small, deterministic preprocessing chain.

    The goal is to remove colour noise and improve contrast without pulling in
    an OpenCV dependency. Deskewing and denoising are deliberately out of scope
    for this demo.
    """

    output = image
    if grayscale or threshold is not None:
        output = output.convert("L")
    if autocontrast:
        output = ImageOps.autocontrast(output)
    if threshold is not None:
        output = output.convert("L").point(
            lambda value: 255 if value >= threshold else 0
        )
    return output
