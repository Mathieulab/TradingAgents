"""Shared contracts. Prices/volumes are evidence, never inferred execution fills."""

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)

    @field_validator("*", mode="after")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if isinstance(value, datetime) else value


class Instrument(Record):
    symbol: str
    feed_id: str
    provider: str
    server: str | None = None
    account_ref: str | None = None
    base_currency: str = "EUR"
    quote_currency: str = "USD"
    contract_size: float = Field(default=100000, gt=0)
    price_increment: float = Field(default=0.00001, gt=0)
    min_units: float = Field(default=1000, gt=0)
    step_units: float = Field(default=1000, gt=0)
    max_units: float = Field(default=1000000, gt=0)
    pip_size: float = Field(default=0.0001, gt=0)

    @model_validator(mode="after")
    def valid_size_range(self):
        if self.max_units < self.min_units or self.step_units > self.max_units:
            raise ValueError("Invalid tradable size range")
        if not self.symbol.strip() or not self.feed_id.strip() or not self.provider.strip():
            raise ValueError("Instrument identity and provenance must not be empty")
        return self


class Quote(Record):
    symbol: str
    feed_id: str
    timestamp: AwareDatetime
    received_at: AwareDatetime | None = None
    bid: float = Field(gt=0)
    ask: float = Field(gt=0)
    volume: float | None = Field(default=None, ge=0)
    flags: int = 0

    @model_validator(mode="after")
    def valid_sides(self):
        if self.ask < self.bid:
            raise ValueError("Crossed quote: ask must be >= bid")
        if self.received_at is not None and self.received_at < self.timestamp:
            raise ValueError("Receipt time cannot precede the provider event timestamp")
        return self

    @property
    def mid(self):
        return (self.bid + self.ask) / 2

    @property
    def spread(self):
        return self.ask - self.bid


class Bar(Record):
    symbol: str
    feed_id: str
    open_time: AwareDatetime
    close_time: AwareDatetime
    received_at: AwareDatetime | None = None
    timeframe: Literal["M15", "H4", "D1"]
    basis: Literal["bid", "ask", "mid"]
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(default=0, ge=0)
    complete: bool = False

    @model_validator(mode="after")
    def valid_bar(self):
        if (
            self.close_time <= self.open_time
            or self.high < max(self.open, self.close, self.low)
            or self.low > min(self.open, self.close, self.high)
        ):
            raise ValueError("Invalid OHLC/time range")
        seconds = {"M15": 900, "H4": 14400, "D1": 86400}[self.timeframe]
        if (
            self.close_time - self.open_time
        ).total_seconds() != seconds or self.open_time.timestamp() % seconds:
            raise ValueError("Bars must use aligned UTC intervals")
        if self.received_at is not None and self.received_at < self.close_time:
            raise ValueError("A closed bar cannot be received before its close")
        return self


class Position(Record):
    symbol: str
    side: Literal["LONG", "SHORT"]
    units: float = Field(gt=0)
    entry: float = Field(gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    unrealized_pnl: float


class AccountSnapshot(Record):
    timestamp: AwareDatetime
    feed_id: str
    currency: str = "USD"
    initial_balance: float = Field(gt=0)
    balance: float
    equity: float
    day_start_balance: float | None = None
    day: date
    positions: tuple[Position, ...] = ()
    pending_orders: int = Field(default=0, ge=0)
    breached: bool = False
    origin: Literal["mt5", "recorded", "manual_test"]


class Evidence(Record):
    kind: Literal["news", "macro", "sentiment", "fundamentals"]
    published_at: AwareDatetime
    received_at: AwareDatetime | None = None
    source: str
    summary: str = Field(max_length=2000)


class SwingProposal(Record):
    instrument: str
    direction: Literal["LONG", "SHORT", "NO TRADE"]
    confidence: float = Field(ge=0, le=1)
    reasoning_summary: str = Field(min_length=1, max_length=3000)
    market_regime: str = Field(max_length=200)
    h4_trend: str = Field(max_length=200)
    d1_trend: str = Field(max_length=200)
    entry_low: float | None = Field(default=None, gt=0)
    entry_high: float | None = Field(default=None, gt=0)
    stop_loss: float | None = Field(default=None, gt=0)
    take_profits: list[float] = Field(default_factory=list, max_length=3)
    expected_reward_risk: float | None = Field(default=None, gt=0)
    risk_percent: float = Field(default=0.25, gt=0, le=1)
    suggested_units: float | None = Field(default=None, gt=0)
    holding_hours: int = Field(default=120, ge=1, le=240)
    invalidation_conditions: list[str] = Field(default_factory=list, max_length=8)
    macro_news_risks: list[str] = Field(default_factory=list, max_length=8)
    no_trade_reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def valid_proposal(self):
        if self.direction == "NO TRADE":
            if not self.no_trade_reason:
                raise ValueError("NO TRADE requires an explicit reason")
            return self
        if (
            self.entry_low is None
            or self.entry_high is None
            or self.stop_loss is None
            or not self.take_profits
        ):
            raise ValueError("A trade requires entry zone, stop and targets")
        if self.entry_low > self.entry_high or not self.invalidation_conditions:
            raise ValueError("Invalid entry zone or missing invalidation conditions")
        if (
            self.direction == "LONG"
            and not self.stop_loss < self.entry_low <= self.entry_high < min(self.take_profits)
        ):
            raise ValueError("LONG requires stop < entry zone < every target")
        if (
            self.direction == "SHORT"
            and not max(self.take_profits) < self.entry_low <= self.entry_high < self.stop_loss
        ):
            raise ValueError("SHORT requires every target < entry zone < stop")
        if min(self.take_profits) <= 0:
            raise ValueError("Targets must be positive")
        return self

    @classmethod
    def no_trade(cls, instrument, reason):
        return cls(
            instrument=instrument,
            direction="NO TRADE",
            confidence=0,
            reasoning_summary=reason,
            market_regime="unknown",
            h4_trend="unknown",
            d1_trend="unknown",
            no_trade_reason=reason,
        )


class RiskPolicy(Record):
    max_risk_percent: float = Field(default=0.25, gt=0, le=1)
    daily_cutoff_percent: float = Field(default=1.0, gt=0, lt=5)
    max_spread_pips: float = Field(default=2.5, gt=0)
    max_quote_age_seconds: float = Field(default=30, gt=0)
    min_reward_risk: float = Field(default=1.5, gt=0)
    commission_per_lot_side: float = Field(default=3.5, ge=0)
    slippage_pips: float = Field(default=0.2, ge=0)
    leverage_cap: float = Field(default=10, gt=0, le=30)
    financing_reserve_per_lot_day: float = Field(default=15, ge=0)


class GateResult(Record):
    verdict: Literal["APPROVE", "REJECT", "NO TRADE"]
    reasons: list[str]
    units: float = 0
    risk_at_stop: float = 0
    reward_risk: float | None = None
    daily_remaining: float | None = None
    total_remaining: float | None = None
    spread_pips: float | None = None
    order_sent: Literal[False] = False
