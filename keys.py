"""キー名とWindows仮想キーコード（VK）の対応、および左右反転マップ。
ctypesに依存しない純粋ロジックのみを置く（テスト容易性のため）。
"""

# キー名 -> 仮想キーコード（VK）
VK_MAP = {
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "pageup": 0x21,
    "pagedown": 0x22,
    "space": 0x20,
    "return": 0x0D,
    "enter": 0x0D,
}

# 拡張キー扱いにするキー（矢印・PageUp/Down等）
EXTENDED_KEYS = {"left", "up", "right", "down", "pageup", "pagedown"}

# 逆方向のキー（自動反転の保険機能で使用）
_OPPOSITE = {
    "left": "right",
    "right": "left",
    "pageup": "pagedown",
    "pagedown": "pageup",
    "up": "down",
    "down": "up",
}

SUPPORTED_KEYS = frozenset(VK_MAP)


def opposite_key(name: str):
    """逆方向のキー名を返す。対になるキーがなければNone。"""
    return _OPPOSITE.get(name.lower())
