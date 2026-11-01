from app.extractor import extract_page_lines, join_lines, open_pdf
from app.layout import FurnitureProfile, detect_furniture, furniture_key
from tests.helpers import make_text_pdf


def test_detect_furniture_finds_repeated_header_and_footer(tmp_path):
    pdf = make_text_pdf(tmp_path / "three-pages.pdf", pages=3)
    doc = open_pdf(pdf)
    try:
        profile = detect_furniture(doc)
        assert furniture_key("Synthetic Header") in profile.keys
        assert furniture_key("Page 1 of 3") in profile.keys
        assert furniture_key("Page 2 of 3") in profile.keys

        lines = extract_page_lines(doc[0])
        kept, removed = profile.remove(lines)
        text = join_lines(kept)
        assert removed >= 2
        assert "Synthetic Header" not in text
        assert "Page 1 of 3" not in text
        assert "Page 1 body text." in text
    finally:
        doc.close()


def test_single_page_document_has_no_furniture(tmp_path):
    pdf = make_text_pdf(tmp_path / "one-page.pdf", pages=1)
    doc = open_pdf(pdf)
    try:
        profile = detect_furniture(doc)
        assert profile.keys == ()
    finally:
        doc.close()


def test_furniture_profile_round_trips():
    profile = FurnitureProfile(
        keys=("synthetic header", "page # of #"),
        margin=72.0,
        threshold=0.6,
        page_count=3,
    )
    restored = FurnitureProfile.from_dict(profile.to_dict())
    assert restored == profile
