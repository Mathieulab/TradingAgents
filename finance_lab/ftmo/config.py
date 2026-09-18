"""Explicit assumptions for a USD-denominated EUR/USD two-step test."""

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class TestConfig:
    __test__ = False

    balance: float = 10000.0
    phase: str = "challenge"
    risk_pct: float = 0.25
    spread_pips: float = 1.0
    slippage_pips: float = 0.2
    commission_per_lot_side: float = 3.5
    swap_long_per_lot: float = -8.0
    swap_short_per_lot: float = -4.0
    max_hold_days: int = 10
    fast_period: int = 20
    slow_period: int = 50
    breakout_period: int = 20
    atr_period: int = 14
    atr_stop: float = 2.0
    reward_risk: float = 2.0
    max_trades_per_day: int = 1
    daily_stop_pct: float = 1.0
    leverage: float = 10.0

    def __post_init__(self):
        if self.phase not in {"challenge", "verification"}:
            raise ValueError("Phase must be challenge or verification (two-step only).")
        for name in (
            "balance",
            "risk_pct",
            "atr_stop",
            "reward_risk",
            "leverage",
            "daily_stop_pct",
        ):
            if not isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if not self.risk_pct <= self.daily_stop_pct < 5:
            raise ValueError(
                "Risk per trade must not exceed the internal daily stop, which must be below 5%."
            )
        for name in ("spread_pips", "slippage_pips", "commission_per_lot_side"):
            if not isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be finite and non-negative.")
        for name in ("swap_long_per_lot", "swap_short_per_lot"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be a finite USD amount (negative = debit).")
        for name in (
            "fast_period",
            "slow_period",
            "breakout_period",
            "atr_period",
            "max_trades_per_day",
            "max_hold_days",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if self.fast_period >= self.slow_period:
            raise ValueError("Fast EMA must be shorter than slow EMA.")

    @property
    def target_pct(self):
        return 10.0 if self.phase == "challenge" else 5.0

    @property
    def cost_per_unit_side(self):
        return self.spread_pips * 0.0001 / 2 + self.commission_per_lot_side / 100000

    @property
    def warmup(self):
        return (max(self.slow_period, self.breakout_period + 1, self.atr_period + 1) + 2) * 16


def rule_headroom(config, day_start_balance, worst_equity):
    """Two-step static loss floor, and daily floor reset at Prague midnight."""
    return {
        "daily_remaining": worst_equity - (day_start_balance - config.balance * 0.05),
        "total_remaining": worst_equity - config.balance * 0.90,
        "internal_remaining": worst_equity
        - (day_start_balance - config.balance * config.daily_stop_pct / 100),
    }
