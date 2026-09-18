"""Compact, role-specific evidence from immutable as-of observations."""

from datetime import timedelta

import backtrader as bt
import pandas as pd

from finance_lab.ftmo.config import TestConfig, rule_headroom
from finance_lab.ftmo.data import swing_candles
from finance_lab.ftmo.engine import SwingStudy, add_swing_features

from .catalog import canonical


def candle_records(frame, count):
    return [
        {"time": time.isoformat(), **{k: float(row[k]) for k in ("open", "high", "low", "close")}}
        for time, row in frame.tail(count).iterrows()
    ]


def technical_context(bars, as_of):
    eligible = [
        b
        for b in bars
        if b.timeframe == "M15"
        and b.complete
        and b.close_time <= as_of
        and (b.received_at is None or b.received_at <= as_of)
    ]
    if len({(b.feed_id, b.symbol, b.basis) for b in eligible}) > 1:
        raise ValueError("Mixed bar feeds, symbols or price bases")
    if len({b.open_time for b in eligible}) != len(eligible):
        raise ValueError("Conflicting revisions for the same M15 candle")
    if not eligible:
        return {"ready": False, "reason": "No complete M15 source candles", "chart": []}
    frame = pd.DataFrame([b.model_dump() for b in eligible]).set_index("open_time").sort_index()
    frame = frame[["open", "high", "low", "close", "volume"]]
    config = TestConfig()
    h4 = swing_candles(frame)
    h4.index += pd.Timedelta(minutes=15)
    result = {
        "ready": False,
        "basis": eligible[0].basis,
        "h4_alignment": "UTC 00/04/08/12/16/20",
        "m15": candle_records(frame, 8),
        "h4": candle_records(h4, 12),
        "chart": candle_records(h4, 90),
        "h4_trend": "unavailable",
        "d1_trend": "unavailable",
    }
    # swing_candles uses the last M15 OPEN index; add_swing_features sees only
    # bars already closed at as_of, so its forward fill cannot expose future H4s.
    if len(h4) < config.slow_period + 2:
        result["reason"] = "Insufficient complete H4 warmup"
        return result
    enriched = add_swing_features(frame, config)
    row = enriched.iloc[-1]
    trend = "bullish" if row.fast > row.slow else "bearish" if row.fast < row.slow else "neutral"
    h4_close = h4.iloc[-1].close
    setup = (
        "LONG"
        if h4_close > row.upper and trend == "bullish"
        else "SHORT"
        if h4_close < row.lower and trend == "bearish"
        else "NONE"
    )
    result.update(
        ready=True,
        h4_trend=trend,
        last_h4_close=h4.index[-1].isoformat(),
        ema20=float(row.fast),
        ema50=float(row.slow),
        atr14=float(row.atr),
        resistance=float(row.upper),
        support=float(row.lower),
        setup=setup,
        setup_role="Evidence only, not an order or authorization",
        stop_distance=float(row.atr * config.atr_stop),
        target_r=2.0,
    )
    grouped = frame.resample("1D", closed="left", label="left")
    daily = grouped.agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    daily = daily[grouped.close.count() == 96]
    result["d1"] = candle_records(daily, 8)
    if len(daily) >= config.slow_period + 2 and as_of - daily.index[-1].to_pydatetime() < timedelta(
        days=4
    ):
        study = bt.Cerebro(stdstats=False)
        daily.index = daily.index.tz_localize(None)
        study.adddata(bt.feeds.PandasData(dataname=daily))
        study.addstrategy(SwingStudy, config=config)
        features = study.run(runonce=False)[0].features[-1]
        result["d1_trend"] = "bullish" if features["fast"] > features["slow"] else "bearish"
    if as_of - h4.index[-1].to_pydatetime() > timedelta(hours=4):
        result.update(ready=False, reason="Latest complete H4 is stale or missing")
    return result


def build_snapshot(catalog, feed_id, symbol, as_of):
    instrument = catalog.get_instrument(feed_id, symbol)
    quotes = catalog.records("quote", feed_id, symbol, as_of, start=as_of - timedelta(minutes=5))
    accounts = catalog.records("account", feed_id, "", as_of, start=as_of - timedelta(minutes=5))
    bars = catalog.records("bar", feed_id, symbol, as_of, start=as_of - timedelta(days=180))
    evidence = catalog.records("evidence", "evidence", "", as_of, start=as_of - timedelta(days=7))
    technical = technical_context(bars, as_of)
    account = accounts[-1] if accounts else None
    quote = quotes[-1] if quotes else None
    headroom = (
        rule_headroom(
            TestConfig(balance=account.initial_balance), account.day_start_balance, account.equity
        )
        if account and account.day_start_balance is not None
        else None
    )
    snapshot = {
        "schema_version": 1,
        "as_of": as_of.isoformat(),
        "instrument": instrument.model_dump(mode="json"),
        "quote": quote.model_dump(mode="json") if quote else None,
        "account": account.model_dump(mode="json") if account else None,
        "headroom": headroom,
        "technical": technical,
        "evidence": [e.model_dump(mode="json") for e in evidence[-30:]],
        "validation": dict.fromkeys(
            ("development", "validation", "holdout", "stress", "live_forward")
        ),
    }
    return snapshot


def role_context(snapshot, role):
    header = {
        "as_of": snapshot["as_of"],
        "instrument": snapshot["instrument"]["symbol"],
        "feed": snapshot["instrument"]["feed_id"],
        "mode": "SHADOW / NO ORDERS",
        "constraints": "Use only recorded evidence. No future knowledge, external tools or invented prices. Missing data is unavailable. LONG/SHORT/NO TRADE; setup is evidence, never authorization.",
    }
    technical = {k: v for k, v in snapshot["technical"].items() if k != "chart"}
    summary = {k: v for k, v in technical.items() if k not in ("m15", "h4", "d1")}
    if role == "Market Analyst":
        header.update(technical=technical, quote=snapshot["quote"])
    elif role in ("News Analyst", "Sentiment Analyst", "Fundamentals Analyst"):
        kinds = {
            "News Analyst": {"news", "macro"},
            "Sentiment Analyst": {"sentiment"},
            "Fundamentals Analyst": {"fundamentals", "macro"},
        }[role]
        header["evidence"] = [e for e in snapshot["evidence"] if e["kind"] in kinds]
        header["missing_evidence"] = not header["evidence"]
    else:
        header.update(technical_summary=summary)
        if role in (
            "Trader",
            "Aggressive Analyst",
            "Conservative Analyst",
            "Neutral Analyst",
            "Portfolio Manager",
        ):
            header.update(
                account=snapshot["account"],
                ftmo_headroom=snapshot["headroom"],
                quote=snapshot["quote"],
            )
    return canonical(header)
