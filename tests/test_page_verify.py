"""page_verify.py のユニットテスト。"""
from PIL import Image

from page_verify import diff_ratio, page_changed


def _solid(color, size=(100, 100)) -> Image.Image:
    return Image.new("RGB", size, color)


def test_identical_images_zero_diff():
    img = _solid((255, 255, 255))
    assert diff_ratio(img, img.copy()) == 0.0


def test_identical_images_not_changed():
    img = _solid((128, 128, 128))
    assert page_changed(img, img.copy()) is False


def test_black_vs_white_large_diff():
    black = _solid((0, 0, 0))
    white = _solid((255, 255, 255))
    assert diff_ratio(black, white) == 1.0
    assert page_changed(black, white) is True


def test_small_change_below_threshold():
    base = _solid((255, 255, 255))
    changed = base.copy()
    # 100x100=10000ピクセル中、1ピクセルだけ黒にする（差分はごく小さい）
    changed.putpixel((0, 0), (0, 0, 0))
    assert page_changed(base, changed, threshold=0.01) is False


def test_different_sizes_are_resized():
    small = _solid((0, 0, 0), size=(50, 50))
    large = _solid((255, 255, 255), size=(200, 200))
    # サイズが違ってもエラーにならず比較できる
    assert diff_ratio(small, large) == 1.0


def test_threshold_boundary():
    base = _solid((0, 0, 0))
    half = _solid((128, 128, 128))
    ratio = diff_ratio(base, half)
    assert page_changed(base, half, threshold=ratio - 0.001) is True
    assert page_changed(base, half, threshold=ratio + 0.001) is False
