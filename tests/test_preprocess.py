from PIL import Image

from app.preprocess import preprocess_image


def test_preprocess_converts_to_grayscale():
    image = Image.new("RGB", (8, 8), (120, 120, 120))
    output = preprocess_image(image, grayscale=True, autocontrast=False)
    assert output.mode == "L"


def test_preprocess_threshold_produces_binary_values():
    dark = preprocess_image(
        Image.new("RGB", (8, 8), (120, 120, 120)),
        grayscale=True,
        autocontrast=False,
        threshold=128,
    )
    bright = preprocess_image(
        Image.new("RGB", (8, 8), (120, 120, 120)),
        grayscale=True,
        autocontrast=False,
        threshold=100,
    )
    assert set(dark.getdata()) == {0}
    assert set(bright.getdata()) == {255}


def test_preprocess_autocontrast_keeps_grayscale_mode():
    image = Image.new("RGB", (8, 8), (120, 120, 120))
    output = preprocess_image(image, grayscale=True, autocontrast=True)
    assert output.mode == "L"
