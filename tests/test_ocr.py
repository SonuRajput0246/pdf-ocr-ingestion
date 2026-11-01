from pathlib import Path

from PIL import Image

from app.ocr import StubOCREngine, TesseractOCREngine, reconstruct_tesseract_data


def test_reconstruct_tesseract_data_groups_lines_and_confidence():
    data = {
        "text": ["Hello", "world", "Second", "line"],
        "conf": ["90", "80", "70", "-1"],
        "block_num": [1, 1, 1, 1],
        "par_num": [1, 1, 1, 1],
        "line_num": [1, 1, 2, 2],
    }
    text, confidence = reconstruct_tesseract_data(data)
    assert text == "Hello world\nSecond line"
    assert confidence == 0.8


def test_reconstruct_tesseract_data_handles_empty_result():
    text, confidence = reconstruct_tesseract_data({"text": []})
    assert text == ""
    assert confidence is None


def test_stub_ocr_engine_tracks_calls():
    engine = StubOCREngine("synthetic text", confidence=0.5)
    result = engine.image_to_text(Image.new("L", (4, 4)))
    assert result.text == "synthetic text"
    assert result.confidence == 0.5
    assert engine.calls == 1


def test_tesseract_engine_reports_missing_explicit_binary(tmp_path: Path):
    engine = TesseractOCREngine(str(tmp_path / "missing-tesseract"))
    assert engine.available() is False
