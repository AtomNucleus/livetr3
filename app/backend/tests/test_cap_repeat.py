from session import _drop_repeated_lead


def test_drops_word_repeated_across_cap_cut():
    assert _drop_repeated_lead("They are banned from", "from the Games.") == "the Games."
    assert _drop_repeated_lead("que están prohibidos de", "de los Juegos.") == "los Juegos."


def test_matches_up_to_three_words_ignoring_case_and_punctuation():
    assert _drop_repeated_lead("a path forward for myself,", "For myself in this") == "in this"


def test_keeps_text_without_exact_repeat():
    assert _drop_repeated_lead("perspectivas sobre", "en cuestiones particulares") == "en cuestiones particulares"
    assert _drop_repeated_lead("", "from the Games.") == "from the Games."


def test_never_removes_whole_caption():
    assert _drop_repeated_lead("banned from", "from") == "from"
