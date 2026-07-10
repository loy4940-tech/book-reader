"""timing.py のユニットテスト。"""
import pytest

from timing import calc_wait_time


def test_uniform_within_range():
    for _ in range(1000):
        v = calc_wait_time(8, 14, "uniform")
        assert 8 <= v <= 14


def test_gaussian_within_range():
    for _ in range(1000):
        v = calc_wait_time(8, 14, "gaussian")
        assert 8 <= v <= 14


def test_equal_min_max_returns_that_value():
    assert calc_wait_time(10, 10, "uniform") == 10


def test_negative_raises():
    with pytest.raises(ValueError):
        calc_wait_time(-1, 14)


def test_min_greater_than_max_raises():
    with pytest.raises(ValueError):
        calc_wait_time(14, 8)


def test_values_vary_between_calls():
    """毎回同じ値をキャッシュせず、値がばらつくことを確認する。"""
    values = {calc_wait_time(8, 14, "uniform") for _ in range(50)}
    assert len(values) > 1
