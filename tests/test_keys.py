"""keys.py のユニットテスト。"""
from keys import SUPPORTED_KEYS, VK_MAP, opposite_key


def test_left_right_are_opposite():
    assert opposite_key("left") == "right"
    assert opposite_key("right") == "left"


def test_pageup_pagedown_are_opposite():
    assert opposite_key("pagedown") == "pageup"
    assert opposite_key("pageup") == "pagedown"


def test_opposite_is_case_insensitive():
    assert opposite_key("LEFT") == "right"


def test_space_has_no_opposite():
    assert opposite_key("space") is None


def test_supported_keys_include_arrows():
    for key in ("left", "right", "pageup", "pagedown", "space"):
        assert key in SUPPORTED_KEYS
        assert key in VK_MAP
