import pandas as pd
import pytest

from finance_lab.core.indicators import (
    calculate_ema_on_frame,
    calculate_macd_on_frame,
    calculate_rsi_on_frame,
)


def make_frame(values):
    return pd.DataFrame(
        {"close": values},
        index=pd.date_range("2024-01-01", periods=len(values), freq="D"),
    )


def test_calculate_rsi_on_frame_reaches_overbought_on_steady_rise():
    result = calculate_rsi_on_frame(make_frame(range(1, 40)), period=14)

    assert result["latest"]["value"] == pytest.approx(100.0)
    assert len(result["series"]) == 39


def test_calculate_ema_on_frame_returns_latest_value():
    result = calculate_ema_on_frame(make_frame([10, 11, 12, 13, 14]), period=3)

    assert result["latest"]["date"] == "2024-01-05"
    assert result["latest"]["value"] == pytest.approx(13.0625)


def test_calculate_macd_on_frame_returns_positive_momentum_for_rising_prices():
    result = calculate_macd_on_frame(
        make_frame(range(1, 80)),
        fast_period=12,
        slow_period=26,
        signal_period=9,
    )

    assert result["latest"]["macd"] > 0
    assert result["latest"]["histogram"] >= 0


def test_calculate_macd_rejects_invalid_period_order():
    with pytest.raises(ValueError, match="fast_period"):
        calculate_macd_on_frame(make_frame(range(1, 80)), fast_period=26, slow_period=12)
