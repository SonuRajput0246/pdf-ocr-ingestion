from app.quality import assess_text


def test_empty_text_is_not_usable():
    quality = assess_text("")
    assert quality.usable is False
    assert quality.reason == "empty"


def test_short_text_is_not_usable():
    quality = assess_text("short", min_chars=20)
    assert quality.usable is False
    assert quality.reason.startswith("too_short")


def test_low_alphanumeric_ratio_is_not_usable():
    quality = assess_text("!@#$%^&*()", min_chars=1, min_alnum_ratio=0.25)
    assert quality.usable is False
    assert quality.reason.startswith("low_alnum_ratio")


def test_normal_text_is_usable():
    quality = assess_text(
        "This is a normal synthetic paragraph with enough words.",
        min_chars=10,
    )
    assert quality.usable is True
    assert quality.reason == "ok"


def test_replacement_characters_are_not_usable():
    quality = assess_text("abc" + "\ufffd" * 20, min_chars=5)
    assert quality.usable is False
    assert quality.reason == "replacement_characters"


def test_zero_minimum_accepts_short_alphanumeric_text():
    quality = assess_text("abc", min_chars=0)
    assert quality.usable is True
