"""page_verify.py のユニットテスト。"""
from PIL import Image

import pytest

from page_verify import (
    DEFAULT_BLOCK_CONTENT_ROI,
    DEFAULT_CONTENT_ROI,
    PageChangeState,
    block_diff_scores,
    diff_ratio,
    page_changed,
    top_k_mean,
    verify_page_change,
)


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


def _content_fixture(kind: str, *, variant: int) -> Image.Image:
    image = _solid((255, 255, 255), size=(1000, 800))
    pixels = image.load()
    if kind == "vertical":
        boxes = [(700, 140, 720, 660), (650, 140, 670, 660)]
    elif kind == "horizontal":
        boxes = [(220, 220, 780, 242), (220, 270, 680, 292)]
    elif kind == "sparse":
        boxes = [
            (300, 230, 700, 250),
            (300, 280, 650, 300),
            (300, 330, 620, 350),
        ]
    elif kind == "figure":
        boxes = [(260, 180, 740, 560)]
    elif kind == "table":
        boxes = [(240, 180, 760, 200), (240, 400, 760, 420), (480, 180, 500, 620)]
    else:
        raise ValueError(kind)
    shade = 0 if variant == 1 else 110
    for left, top, right, bottom in boxes:
        for y in range(top, bottom):
            for x in range(left, right):
                pixels[x, y] = (shade, shade, shade)
    return image


@pytest.mark.parametrize("kind", ["vertical", "horizontal", "sparse", "figure", "table"])
def test_content_roi_detects_supported_layout_changes(kind):
    before = _content_fixture(kind, variant=1)
    after = _content_fixture(kind, variant=2)
    assert page_changed(before, after, threshold=0.01, roi=DEFAULT_CONTENT_ROI)


def test_ui_only_change_outside_content_roi_is_ignored():
    before = _solid((255, 255, 255), size=(1000, 800))
    after = before.copy()
    for y in range(0, 60):
        for x in range(0, 1000):
            after.putpixel((x, y), (0, 0, 0))
    assert diff_ratio(before, after, roi=None) > 0.01
    assert page_changed(before, after, threshold=0.01, roi=DEFAULT_CONTENT_ROI) is False


def _localized_change(kind: str) -> tuple[Image.Image, Image.Image]:
    before = _solid((255, 255, 255), size=(1000, 800))
    after = before.copy()
    boxes = {
        "horizontal_sparse": [(300, 260, 700, 280), (300, 320, 640, 340)],
        "vertical_right": [(850, 160, 875, 650)],
        "vertical_left": [(125, 160, 150, 650)],
        "central": [(350, 250, 650, 500)],
        "figure_corner": [(780, 560, 930, 720)],
        "heading": [(250, 180, 600, 215)],
    }
    if kind == "wide_table":
        boxes[kind] = [
            (120, 220, 880, 232),
            (120, 350, 880, 362),
            (120, 480, 880, 492),
            (120, 220, 132, 500),
            (500, 220, 512, 500),
            (868, 220, 880, 500),
        ]
    for left, top, right, bottom in boxes[kind]:
        for y in range(top, bottom):
            for x in range(left, right):
                after.putpixel((x, y), (0, 0, 0))
    return before, after


@pytest.mark.parametrize(
    "kind",
    [
        "horizontal_sparse",
        "vertical_right",
        "vertical_left",
        "central",
        "figure_corner",
        "wide_table",
        "heading",
    ],
)
def test_block_detector_finds_localized_content_changes(kind):
    before, after = _localized_change(kind)
    assert page_changed(before, after, threshold=0.01)


def test_block_detector_ignores_toolbar_only_change():
    before = _solid((255, 255, 255), size=(1000, 800))
    after = before.copy()
    for y in range(0, 60):
        for x in range(1000):
            after.putpixel((x, y), (0, 0, 0))
    assert page_changed(before, after, threshold=0.01) is False


def test_block_detector_ignores_tiny_noise():
    before = _solid((255, 255, 255), size=(1000, 800))
    after = before.copy()
    for point in ((400, 300), (402, 301), (405, 303), (600, 400)):
        after.putpixel(point, (0, 0, 0))
    assert page_changed(before, after, threshold=0.01) is False


def test_block_configuration_and_top_k_are_validated():
    image = _solid((255, 255, 255))
    with pytest.raises(ValueError):
        block_diff_scores(image, image, grid=(0, 4))
    with pytest.raises(ValueError):
        top_k_mean([0.0], top_k=2)


@pytest.mark.parametrize(
    "roi",
    [(-0.1, 0.1, 0.9, 0.9), (0.5, 0.1, 0.5, 0.9), (0.1, 0.9, 0.9, 0.1)],
)
def test_invalid_roi_rejected(roi):
    image = _solid((255, 255, 255))
    with pytest.raises(ValueError):
        diff_ratio(image, image, roi=roi)


def test_retry_confirms_late_change():
    before = _content_fixture("horizontal", variant=1)
    changed = _content_fixture("horizontal", variant=2)
    frames = iter([before.copy(), changed])
    sleeps = []
    state = verify_page_change(
        before,
        lambda: next(frames),
        retry_count=2,
        stabilization_wait=0.1,
        sleep=sleeps.append,
    )
    assert state is PageChangeState.CHANGE_CONFIRMED
    assert sleeps == [0.1, 0.1]


def test_retry_exhaustion_is_not_final_page():
    before = _solid((255, 255, 255))
    state = verify_page_change(
        before,
        lambda: before.copy(),
        retry_count=2,
        stabilization_wait=0,
        sleep=lambda _seconds: None,
    )
    assert state is PageChangeState.NO_CHANGE_RETRY_EXHAUSTED
    assert "final" not in state.value
