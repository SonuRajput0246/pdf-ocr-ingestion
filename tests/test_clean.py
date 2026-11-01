from app.clean import (
    clean_special_chars,
    clean_text,
    clean_whitespace,
    expand_contractions,
    fix_encoding_issues,
    normalize_text,
    remove_page_furniture,
)


def test_fix_encoding_issues_repairs_mojibake():
    repaired = fix_encoding_issues("Itâ€™s a synthetic document.")
    assert "â" not in repaired
    assert "It" in repaired


def test_remove_page_furniture_removes_standalone_page_and_doi_lines():
    text = (
        "Page 1 of 3\n"
        "DOI: 10.1234/synthetic\n"
        "All rights reserved.\n"
        "The actual protocol content stays."
    )
    cleaned = remove_page_furniture(text)
    assert "Page 1 of 3" not in cleaned
    assert "DOI" not in cleaned
    assert "All rights reserved" not in cleaned
    assert "actual protocol content" in cleaned


def test_expand_contractions():
    assert "does not" in expand_contractions("The study doesn't stop.")


def test_clean_whitespace_removes_dot_leaders_and_collapses_runs():
    assert clean_whitespace("A....B\n\n\n\nC   D") == "A B\n\nC D"


def test_clean_special_chars_removes_bullets_but_keeps_unicode_letters():
    cleaned = clean_special_chars("• Café — naïve\n▪ next")
    assert "•" not in cleaned
    assert "▪" not in cleaned
    assert "Café" in cleaned
    assert "—" in cleaned


def test_normalize_text_can_lowercase():
    assert normalize_text("  Héllo  ", lowercase=True) == "héllo"
    assert normalize_text("  Héllo  ") == "Héllo"


def test_clean_text_runs_the_chain_and_preserves_case_by_default():
    text = "Page 1 of 3\n\n• The study doesn't stop.\n\n\nNext line."
    cleaned = clean_text(text)
    assert "Page 1 of 3" not in cleaned
    assert "does not" in cleaned
    assert "The study" in cleaned
    assert "•" not in cleaned


def test_clean_text_can_skip_contraction_expansion():
    cleaned = clean_text("It doesn't change.", expand_contractions_enabled=False)
    assert "doesn't" in cleaned
