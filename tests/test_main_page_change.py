"""ページ変化未確認時のrun_loop停止契約。"""
from types import SimpleNamespace

from PIL import Image

import main
from page_verify import PageChangeState


def _config():
    return {
        "target_window_title": "Synthetic Reader",
        "turn_key": "right",
        "min_interval": 0,
        "max_interval": 0,
        "jitter_distribution": "uniform",
        "max_turns": 10,
        "verify_page_change": True,
        "diff_threshold": 0.01,
        "max_consecutive_no_change": 2,
        "auto_flip_on_no_change": False,
        "screen_capture": {"enabled": False},
    }


def test_no_change_limit_is_controlled_stop_not_final_page(monkeypatch, caplog):
    controller = main.Controller()
    controller.paused = False
    image = Image.new("RGB", (100, 100), "white")
    sent = []

    monkeypatch.setattr(main, "calc_wait_time", lambda *_args: 0)
    monkeypatch.setattr(main, "find_target_window", lambda _title: SimpleNamespace(_hWnd=123))
    monkeypatch.setattr(main, "capture_hwnd", lambda _hwnd: image)
    monkeypatch.setattr(main, "send_key_to_hwnd", lambda hwnd, key: sent.append((hwnd, key)))
    monkeypatch.setattr(
        main,
        "verify_page_change",
        lambda *_args, **_kwargs: PageChangeState.NO_CHANGE_RETRY_EXHAUSTED,
    )

    with caplog.at_level("INFO"):
        main.run_loop(_config(), controller)

    assert controller.stopped is True
    assert controller.turn_count == 2
    assert len(sent) == 2
    assert "ページ変化確認不能により自動停止" in caplog.text
    assert "最終ページに到達" not in caplog.text


def test_verified_change_count_is_not_derived_from_turn_attempts(monkeypatch, caplog):
    controller = main.Controller()
    controller.paused = False
    config = _config()
    config["max_consecutive_no_change"] = 1
    states = iter(
        [PageChangeState.CHANGE_CONFIRMED, PageChangeState.NO_CHANGE_RETRY_EXHAUSTED]
    )

    monkeypatch.setattr(main, "calc_wait_time", lambda *_args: 0)
    monkeypatch.setattr(main, "find_target_window", lambda _title: SimpleNamespace(_hWnd=123))
    monkeypatch.setattr(main, "capture_hwnd", lambda _hwnd: Image.new("RGB", (10, 10), "white"))
    monkeypatch.setattr(main, "send_key_to_hwnd", lambda *_args: None)
    monkeypatch.setattr(main, "verify_page_change", lambda *_args, **_kwargs: next(states))

    with caplog.at_level("INFO"):
        main.run_loop(config, controller)

    assert "試行=2, 変化確認=1" in caplog.text

