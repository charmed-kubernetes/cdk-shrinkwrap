from shrinkwrap import remove_suffix, remove_prefix


def test_remove_prefix():
    assert remove_prefix("something-abc", "something") == "-abc"
    assert remove_prefix("abc", "something") == "abc"
    assert remove_prefix("abc-something", "something") == "abc-something"


def test_remove_suffix():
    assert remove_suffix("something-abc", "something") == "something-abc"
    assert remove_suffix("abc", "something") == "abc"
    assert remove_suffix("abc-something", "something") == "abc-"

