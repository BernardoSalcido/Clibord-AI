from clipboard_ai.appearance import AI_SETTINGS, LABELS, PAPER, stylesheet


def test_paper_themes_and_two_locales_have_matching_controls():
    assert set(PAPER) == {"light", "night"}
    assert PAPER["light"]["background"] == "#eee6dd"
    assert PAPER["night"]["background"] == "#303446"
    assert PAPER["light"]["accent"] == "#286983"
    assert PAPER["night"]["accent"] == "#11b7c5"
    assert set(LABELS) == {"es", "en"}
    assert LABELS["es"].keys() == LABELS["en"].keys()
    assert AI_SETTINGS["es"].keys() == AI_SETTINGS["en"].keys()
    for name in PAPER:
        css = stylesheet(name)
        assert PAPER[name]["background"] in css
        assert PAPER[name]["surface"] in css
        assert "QTabBar::tab:selected" in css
