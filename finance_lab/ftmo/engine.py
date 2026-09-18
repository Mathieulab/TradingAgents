"""Backtrader execution and chronological holdout evaluation for one fixed strategy."""

from dataclasses import asdict, replace
from math import floor, isfinite

import backtrader as bt
import pandas as pd

from .config import TestConfig, rule_headroom
from .data import data_summary, swing_candles, validate_bars


class SameBarBracketBroker(bt.brokers.BackBroker):
    """Activate protection on the entry candle; stop is queued before target."""

    def _bracketize(self, order, cancel=False):
        super()._bracketize(order, cancel=cancel)
        # Backtrader normally delays child activation until the next bar.
        # Here market entries execute at the open, so protection must apply immediately.
        while self._toactivate:
            self._toactivate.popleft().activate()

    def _try_exec(self, order):
        if order.exectype == bt.Order.Stop and order.parent:
            for sibling in self._pchildren.get(order.parent.ref, ()):
                if sibling.exectype == bt.Order.Limit and sibling.alive():
                    opening = order.data.open[0]
                    if (sibling.isbuy() and opening <= sibling.created.price) or (
                        sibling.issell() and opening >= sibling.created.price
                    ):
                        # A target marketable at the open precedes later intrabar extremes.
                        return
        super()._try_exec(order)


class FxCosts(bt.CommInfoBase):
    params = (
        ("stocklike", True),
        ("commtype", bt.CommInfoBase.COMM_FIXED),
        ("unit_cost", 0.0),
        ("swap_long", -8.0),
        ("swap_short", -4.0),
    )

    def __init__(self):
        super().__init__()
        self.financing = []

    def _getcommission(self, size, price, pseudoexec):
        return abs(size) * self.p.unit_cost

    def get_credit_interest(self, data, pos, dt):
        start = pd.Timestamp(pos.datetime).tz_localize("UTC")
        end = pd.Timestamp(dt).tz_localize("UTC")
        amount = financing_cost(start, end, pos.size, self.p.swap_long, self.p.swap_short)
        if amount:
            self.financing.append({"time": end.isoformat(), "cost": amount})
        return amount


def financing_cost(start, end, size, long_rate, short_rate):
    """Estimated FX rollover: 17:00 New York, weekdays, triple Wednesday."""
    local_start = start.tz_convert("America/New_York")
    local_end = end.tz_convert("America/New_York")
    rate = long_rate if size > 0 else short_rate
    cost = 0.0
    for date in pd.date_range(local_start.date(), local_end.date(), freq="D"):
        rollover = (date + pd.Timedelta(hours=17)).tz_localize("America/New_York")
        if local_start < rollover <= local_end and rollover.dayofweek < 5:
            cost -= abs(size) / 100000 * rate * (3 if rollover.dayofweek == 2 else 1)
    return cost


class SwingStudy(bt.Strategy):
    params = (("config", None),)

    def __init__(self):
        c = self.p.config
        self.fast = bt.ind.EMA(self.data.close, period=c.fast_period)
        self.slow = bt.ind.EMA(self.data.close, period=c.slow_period)
        self.atr = bt.ind.ATR(self.data, period=c.atr_period)
        self.upper = bt.ind.Highest(self.data.high(-1), period=c.breakout_period)
        self.lower = bt.ind.Lowest(self.data.low(-1), period=c.breakout_period)
        self.features = []

    def next(self):
        self.features.append(
            {
                "time": pd.Timestamp(self.data.datetime.datetime(0)).tz_localize("UTC"),
                **{
                    name: getattr(self, name)[0]
                    for name in ("fast", "slow", "atr", "upper", "lower")
                },
            }
        )


class SwingFeed(bt.feeds.PandasData):
    lines = ("fast", "slow", "atr", "upper", "lower", "fresh")
    params = tuple((name, -1) for name in lines)


def add_swing_features(frame, config):
    h4 = swing_candles(frame)
    study = bt.Cerebro(stdstats=False)
    feed = h4.copy()
    feed.index = feed.index.tz_localize(None)
    study.adddata(bt.feeds.PandasData(dataname=feed))
    study.addstrategy(SwingStudy, config=config)
    features = study.run(runonce=False)[0].features
    if not features:
        raise ValueError("Not enough complete H4 candles to warm the swing indicators.")
    features = pd.DataFrame(features).set_index("time")
    enriched = frame.join(features.reindex(frame.index, method="ffill"))
    enriched["fresh"] = enriched.index.isin(features.index).astype(int)
    return enriched


class TrendBreakout(bt.Strategy):
    params = (("config", None), ("trade_from", None), ("last_bar", None))

    def __init__(self):
        self.cfg = self.p.config
        self.fast, self.slow, self.atr = self.data.fast, self.data.slow, self.data.atr
        self.upper, self.lower = self.data.upper, self.data.lower
        self.funding_cursor = 0
        self.balance = self.cfg.balance
        self.day_start = self.balance
        self.day = None
        self.day_trades = 0
        self.day_low = self.balance
        self.trading_days = set()
        self.curve = []
        self.trades = []
        self.orders = []
        self.open_trade = None
        self.exposures = []
        self.signal = 0
        self.signal_atr = 0
        self.peak = self.balance
        self.breaches = []
        self.rejections = 0
        self.objective_met = False

    def timestamp(self):
        return pd.Timestamp(self.data.datetime.datetime(0)).tz_localize("UTC")

    def next_open(self):
        now = self.timestamp()
        today = now.tz_convert("Europe/Prague").date()
        if today != self.day:
            self.day = today
            self.day_start = self.balance
            self.day_low = self.balance
            self.day_trades = 0
        self.exposures = [self.open_trade] if self.open_trade else []
        internal_remaining = (
            self.day_low - self.day_start + self.cfg.balance * self.cfg.daily_stop_pct / 100
        )
        timed_out = self.open_trade and now - pd.Timestamp(
            self.open_trade["entry_time"]
        ) >= pd.Timedelta(days=self.cfg.max_hold_days)
        must_close = (
            timed_out or now == self.p.last_bar or bool(self.breaches) or internal_remaining <= 0
        )
        if self.position and must_close:
            for order in self.orders:
                self.cancel(order)
            reason = (
                "rule breach"
                if self.breaches
                else "daily cutoff"
                if internal_remaining <= 0
                else "time/end"
            )
            self.close().addinfo(reason=reason)
            return
        if (
            must_close
            or self.position
            or any(o.alive() for o in self.orders)
            or self.objective_met
            or not self.signal
            or now < self.p.trade_from
            or not 7 <= now.hour < 16
            or self.day_trades >= self.cfg.max_trades_per_day
        ):
            return
        stop_distance = self.signal_atr * self.cfg.atr_stop
        slip = self.cfg.slippage_pips * 0.0001
        equity = self.broker.getvalue()
        risk = min(
            equity * self.cfg.risk_pct / 100,
            max(0, internal_remaining) * 0.9,
            max(0, equity - self.cfg.balance * 0.9) * 0.9,
        )
        unit_risk = stop_distance + 2 * self.cfg.cost_per_unit_side + 2 * slip
        size = (
            floor(min(risk / unit_risk, equity * self.cfg.leverage / self.data.open[0]) / 1000)
            * 1000
        )
        if size < 1000:
            return
        entry = self.data.open[0] + self.signal * slip
        stop = entry - self.signal * stop_distance
        target = entry + self.signal * stop_distance * self.cfg.reward_risk
        bracket = self.buy_bracket if self.signal > 0 else self.sell_bracket
        self.orders = bracket(
            size=size, exectype=bt.Order.Market, stopprice=stop, limitprice=target
        )
        self.orders[0].addinfo(
            reason="entry",
            stop=stop,
            target=target,
            risk=size * unit_risk,
            signal_time=self.curve[-1]["time"],
        )
        self.orders[1].addinfo(reason="stop")
        self.orders[2].addinfo(reason="target")

    prenext_open = next_open
    nextstart_open = next_open

    def notify_order(self, order):
        self.apply_financing()
        if order.status in (order.Margin, order.Rejected):
            self.rejections += 1
        if order.status != order.Completed:
            return
        now = pd.Timestamp(bt.num2date(order.executed.dt)).tz_localize("UTC")
        reason = order.info.get("reason", "exit")
        if reason == "entry":
            self.open_trade = {
                "entry_time": now.isoformat(),
                "signal_time": order.info.signal_time,
                "entry": order.executed.price,
                "size": order.executed.size,
                "stop": order.info.stop,
                "target": order.info.target,
                "risk": order.info.risk,
                "entry_cost": order.executed.comm,
                "financing": 0.0,
                "base_balance": self.balance,
                "side": "LONG" if order.isbuy() else "SHORT",
            }
            self.balance -= order.executed.comm
            self.exposures.append(self.open_trade)
            self.day_trades += 1
            self.trading_days.add(now.tz_convert("Europe/Prague").date().isoformat())
        elif self.open_trade:
            trade = self.open_trade
            self.balance += order.executed.pnl - order.executed.comm
            trade.update(
                exit_time=now.isoformat(),
                exit=order.executed.price,
                exit_at_open=reason == "target"
                and (
                    (trade["size"] > 0 and self.data.open[0] >= trade["target"])
                    or (trade["size"] < 0 and self.data.open[0] <= trade["target"])
                ),
                exit_reason=reason,
                costs=trade["entry_cost"] + order.executed.comm + trade["financing"],
                pnl=order.executed.pnl
                - order.executed.comm
                - trade["entry_cost"]
                - trade["financing"],
            )
            trade["r_multiple"] = trade["pnl"] / trade["risk"]
            self.trades.append(dict(trade))
            self.open_trade = None

    def apply_financing(self):
        events = self.broker.getcommissioninfo(self.data).financing
        for event in events[self.funding_cursor :]:
            self.balance -= event["cost"]
            if self.open_trade:
                self.open_trade["financing"] += event["cost"]
        self.funding_cursor = len(events)

    def next(self):
        self.apply_financing()
        now = self.timestamp()
        equity = self.broker.getvalue()
        low_equity = equity
        for trade in self.exposures:
            size = trade["size"]
            if trade.get("exit_time") == now.isoformat() and (
                trade.get("exit_at_open")
                or trade.get("exit_reason") in {"time/end", "daily cutoff", "rule breach", "stop"}
            ):
                adverse = trade["exit"]
            else:
                # With stop-first OCO fills, a surviving trade cannot travel beyond its stop.
                adverse = (
                    max(self.data.low[0], trade["stop"])
                    if size > 0
                    else min(self.data.high[0], trade["stop"])
                )
            worst = (
                trade["base_balance"]
                - trade["entry_cost"]
                - trade["financing"]
                + size * (adverse - trade["entry"])
                - abs(size) * self.cfg.cost_per_unit_side
            )
            low_equity = min(low_equity, worst)
        self.day_low = min(self.day_low, low_equity)
        headroom = rule_headroom(self.cfg, self.day_start, low_equity)
        for rule in ("daily_remaining", "total_remaining"):
            if headroom[rule] < -1e-8 and not any(b["rule"] == rule for b in self.breaches):
                self.breaches.append(
                    {"time": now.isoformat(), "rule": rule, "excess": -headroom[rule]}
                )
        ready = all(
            isfinite(line[0]) for line in (self.fast, self.slow, self.atr, self.upper, self.lower)
        )
        self.signal = 0
        if ready and self.data.fresh[0]:
            if self.fast[0] > self.slow[0] and self.data.close[0] > self.upper[0]:
                self.signal = 1
            elif self.fast[0] < self.slow[0] and self.data.close[0] < self.lower[0]:
                self.signal = -1
            self.signal_atr = self.atr[0]
        if not self.position and not self.breaches and len(self.trading_days) >= 4:
            self.objective_met = self.balance >= self.cfg.balance * (1 + self.cfg.target_pct / 100)
        drawdown = min(0.0, low_equity / self.peak - 1)
        self.peak = max(self.peak, equity)
        self.curve.append(
            {
                "time": now.isoformat(),
                "equity": equity,
                "balance": self.balance,
                "worst_equity": low_equity,
                "drawdown": drawdown,
                "daily_floor": self.day_start - self.cfg.balance * 0.05,
                "internal_floor": self.day_start - self.cfg.balance * self.cfg.daily_stop_pct / 100,
                "day_low": self.day_low,
                "position": self.position.size,
                "fast": self.fast[0] if ready else None,
                "slow": self.slow[0] if ready else None,
                "atr": self.atr[0] if ready else None,
                "upper": self.upper[0] if ready else None,
                "lower": self.lower[0] if ready else None,
                "signal": self.signal,
                "h4_close": bool(self.data.fresh[0]),
                "stop": self.open_trade["stop"] if self.open_trade else None,
                "target": self.open_trade["target"] if self.open_trade else None,
                **headroom,
            }
        )

    prenext = next


def run_backtest(frame, config: TestConfig, *, trade_from=None):
    frame = validate_bars(frame)
    if len(frame) <= config.warmup:
        raise ValueError("Dataset is too short for the configured indicator warmup.")
    trade_from = pd.Timestamp(trade_from) if trade_from is not None else frame.index[config.warmup]
    if trade_from.tzinfo is None:
        raise ValueError("trade_from must include a timezone.")
    if trade_from >= frame.index[-1] or trade_from < frame.index[0]:
        raise ValueError("trade_from must be within the dataset and before its final candle.")
    cerebro = bt.Cerebro(stdstats=False, cheat_on_open=True)
    broker = SameBarBracketBroker()
    broker.setcash(config.balance)
    broker.set_shortcash(False)
    broker.addcommissioninfo(
        FxCosts(
            unit_cost=config.cost_per_unit_side,
            leverage=config.leverage,
            swap_long=config.swap_long_per_lot,
            swap_short=config.swap_short_per_lot,
        )
    )
    broker.set_int2pnl(False)
    broker.set_slippage_fixed(
        config.slippage_pips * 0.0001, slip_open=True, slip_match=True, slip_out=True
    )
    cerebro.setbroker(broker)
    # Backtrader internally uses naive UTC datetimes.
    feed = add_swing_features(frame, config)
    feed.index = feed.index.tz_convert("UTC").tz_localize(None)
    cerebro.adddata(SwingFeed(dataname=feed, timeframe=bt.TimeFrame.Minutes, compression=15))
    cerebro.addstrategy(
        TrendBreakout, config=config, trade_from=trade_from, last_bar=frame.index[-1]
    )
    strategy = cerebro.run(runonce=False)[0]
    curve = [row for row in strategy.curve if pd.Timestamp(row["time"]) >= trade_from]
    trades = strategy.trades
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]
    final = curve[-1]["equity"]
    if strategy.position:
        raise RuntimeError("Backtest ended with an unclosed position.")
    if abs(final - (config.balance + sum(t["pnl"] for t in trades))) > 0.01:
        raise RuntimeError("Trade ledger does not reconcile with broker equity.")
    return {
        "parameters": asdict(config),
        "metrics": {
            "final_equity": final,
            "return_pct": (final / config.balance - 1) * 100,
            "trades": len(trades),
            "trading_days": len(strategy.trading_days),
            "win_rate": len(wins) / len(trades) if trades else None,
            "profit_factor": sum(wins) / -sum(losses) if losses else None,
            "expectancy": sum(t["pnl"] for t in trades) / len(trades) if trades else None,
            "costs": sum(t["costs"] for t in trades),
            "financing": sum(t["financing"] for t in trades),
            "max_drawdown_pct": -min(r["drawdown"] for r in curve) * 100,
            "min_daily_headroom": min(r["daily_remaining"] for r in curve),
            "min_total_headroom": min(r["total_remaining"] for r in curve),
            "status": "BREACHED"
            if strategy.breaches
            else "OBJECTIVE MET"
            if strategy.objective_met
            else "INCOMPLETE",
            "rejected_orders": strategy.rejections,
        },
        "trades": trades,
        "curve": curve,
        "breaches": strategy.breaches,
    }


def evaluate(frame, config=None, *, source="synthetic demo", synthetic=True):
    config = config or TestConfig()
    frame = validate_bars(frame)
    if len(frame) < max(300, config.warmup * 4):
        raise ValueError("More bars are needed for indicator warmup and independent test periods.")
    split = int(len(frame) * 0.7)
    development = run_backtest(frame.iloc[:split], config)
    holdout_frame = frame.iloc[max(0, split - max(200, config.warmup * 3)) :]
    holdout = run_backtest(holdout_frame, config, trade_from=frame.index[split])
    stress_config = replace(
        config,
        spread_pips=config.spread_pips * 2,
        slippage_pips=config.slippage_pips * 2,
        commission_per_lot_side=config.commission_per_lot_side * 2,
        swap_long_per_lot=config.swap_long_per_lot * (2 if config.swap_long_per_lot < 0 else 0.5),
        swap_short_per_lot=config.swap_short_per_lot
        * (2 if config.swap_short_per_lot < 0 else 0.5),
    )
    stress = run_backtest(holdout_frame, stress_config, trade_from=frame.index[split])
    reasons = []
    if synthetic:
        reasons.append("Synthetic data: validates software only; no strategy edge can be inferred.")
    if holdout["metrics"]["trades"] < 30:
        reasons.append("Fewer than 30 holdout trades; the evidence is too small.")
    if holdout["metrics"]["return_pct"] <= 0:
        reasons.append("Holdout net return is not positive.")
    if stress["metrics"]["return_pct"] <= 0:
        reasons.append("Holdout return is not positive under doubled costs.")
    if holdout["breaches"] or stress["breaches"]:
        reasons.append("A loss objective was breached in the holdout or cost stress run.")
    if any(r["metrics"]["rejected_orders"] for r in (development, holdout, stress)):
        reasons.append("Broker rejected orders; inspect execution assumptions.")
    summary = data_summary(frame)
    if summary["unexpected_gaps"]:
        reasons.append(
            f"Dataset contains {summary['unexpected_gaps']} non-weekend data gaps; inspect source coverage."
        )
    reasons.append(
        "Historical bar simulation; forward demo execution and broker reconciliation remain untested."
    )
    return {
        "schema_version": 1,
        "strategy": "H4 swing: EMA trend / Donchian breakout / ATR stop",
        "instrument": "EURUSD",
        "currency": "USD",
        "mode": "historical simulation",
        "synthetic": synthetic,
        "source": source,
        "config": asdict(config),
        "data": summary,
        "rules_source": "https://ftmo.com/en/trading-objectives/",
        "rules_checked": "2026-09-05",
        "rules_profile": "FTMO 2-Step",
        "split_time": frame.index[split].isoformat(),
        "development": development,
        "holdout": holdout,
        "stress": stress,
        "assessment": "SOFTWARE DEMO"
        if synthetic
        else "REVIEW REQUIRED"
        if len(reasons) > 1
        else "FORWARD DEMO CANDIDATE",
        "reasons": reasons,
        "candles": [
            {
                "time": idx.isoformat(),
                **{k: float(row[k]) for k in ("open", "high", "low", "close")},
            }
            for idx, row in frame.iterrows()
        ],
        "swing_candles": [
            {
                "time": idx.isoformat(),
                **{k: float(row[k]) for k in ("open", "high", "low", "close")},
            }
            for idx, row in swing_candles(frame).iterrows()
        ],
    }
