"""Decision replay backtests for TradingAgents final decisions."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import pandas as pd

from tradingagents.rating import parse_rating

from .market_data import fetch_ohlcv_frame
from .responses import fail, ok
from .trade_gate import build_paper_trade_gate
from .trade_style_fit import build_trade_style_fit

DEFAULT_HORIZONS = (1, 2, 5, 10, 20, 60, 120)
_STOP_RE = re.compile(
    r"\bstop(?:[-\s]?loss)?\s*(?:at|below|under|near|around|of|:)?\s*\$?\s*"
    r"([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_TRIM_RE = re.compile(
    r"\b(?:trim|reduce|sell)\s+(?:by\s+)?([0-9]+(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE,
)


def run_decision_replay_backtest(
    symbol: str,
    final_state: dict[str, Any],
    analysis_date: str,
    *,
    benchmark_symbol: str | None = "SPY",
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    interval: str = "1d",
) -> dict[str, Any]:
    """Replay the final TradingAgents decision over forward horizons."""
    meta = {
        "mode": "decision_replay",
        "symbol": symbol,
        "analysis_date": analysis_date,
        "benchmark_symbol": benchmark_symbol,
        "horizons": list(horizons),
        "interval": interval,
    }
    try:
        start, end = _fetch_window(analysis_date, horizons)
        asset_frame = fetch_ohlcv_frame(symbol, interval=interval, start=start, end=end)
        benchmark_frame = None
        benchmark_error = None
        if benchmark_symbol and not _symbols_match(symbol, benchmark_symbol):
            try:
                benchmark_frame = fetch_ohlcv_frame(
                    benchmark_symbol,
                    interval=interval,
                    start=start,
                    end=end,
                )
            except Exception as exc:  # noqa: BLE001 - benchmark should not block decision replay
                benchmark_error = str(exc)

        result = run_decision_replay_backtest_on_frames(
            asset_frame,
            final_state=final_state,
            analysis_date=analysis_date,
            symbol=symbol,
            benchmark_frame=benchmark_frame,
            benchmark_symbol=benchmark_symbol,
            benchmark_error=benchmark_error,
            horizons=horizons,
        )
        result["meta"] = {**result.get("meta", {}), **meta}
        return result
    except Exception as exc:  # noqa: BLE001
        return fail(str(exc), code="DECISION_BACKTEST_ERROR", meta=meta)


def run_decision_replay_backtest_on_frames(
    asset_frame: pd.DataFrame,
    *,
    final_state: dict[str, Any],
    analysis_date: str,
    symbol: str,
    benchmark_frame: pd.DataFrame | None = None,
    benchmark_symbol: str | None = "SPY",
    benchmark_error: str | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Replay a final decision using already-loaded OHLCV frames."""
    decision_text = _final_decision_text(final_state)
    rating = parse_rating(decision_text)
    action = _action_from_rating(rating)
    stop_loss = _extract_stop_loss(decision_text)
    post_decision_exposure = _post_decision_exposure(action, rating, decision_text)
    benchmark_identity_match = _symbols_match(symbol, benchmark_symbol)
    benchmark_warning = None
    if benchmark_identity_match:
        benchmark_warning = (
            f"Benchmark {benchmark_symbol} matches {symbol}; benchmark alpha is disabled."
        )

    close = _series(asset_frame, "close")
    low = _series(asset_frame, "low") if "low" in asset_frame.columns else close
    entry_pos = _first_position_on_or_after(close.index, analysis_date)
    if entry_pos is None:
        summary = _summary_for_horizons([])
        data = {
            "mode": "decision_replay",
            "symbol": symbol,
            "action": action,
            "rating": rating,
            "decision_text": decision_text,
            "entry_date": None,
            "entry_price": None,
            "post_decision_exposure": post_decision_exposure,
            "stop_loss": stop_loss,
            "benchmark_symbol": benchmark_symbol,
            "benchmark_error": benchmark_error,
            "benchmark_identity_match": benchmark_identity_match,
            "benchmark_warning": benchmark_warning,
            "horizons": [],
            "pending_horizons": [int(horizon) for horizon in horizons],
            "status": "pending",
            "pending_reason": "no forward price data on or after analysis_date",
            "summary": summary,
            "learning": _learning_for_replay(
                action=action,
                rating=rating,
                horizons=[],
                summary=summary,
                stop_loss=stop_loss,
            ),
        }
        data["trade_style_fit"] = build_trade_style_fit(data)
        data["paper_trade_gate"] = build_paper_trade_gate(data)
        return ok(
            data,
            meta={
                "mode": "decision_replay",
                "symbol": symbol,
                "analysis_date": analysis_date,
            },
        )

    entry_date = _date_value(close.index[entry_pos])
    entry_price = float(close.iloc[entry_pos])
    stop_loss = _extract_stop_loss(decision_text, reference_price=entry_price)
    benchmark_close = (
        _series(benchmark_frame, "close")
        if benchmark_frame is not None and not benchmark_identity_match
        else None
    )

    horizons_payload = []
    pending_horizons = []
    for horizon in horizons:
        exit_pos = entry_pos + int(horizon)
        if exit_pos >= len(close):
            pending_horizons.append(int(horizon))
            continue

        period_close = close.iloc[entry_pos : exit_pos + 1]
        period_low = low.iloc[entry_pos : exit_pos + 1]
        buy_hold_return = float(period_close.iloc[-1] / entry_price - 1)
        stop = _stop_result(action, stop_loss, entry_price, period_low)
        decision_return = _decision_return(
            action=action,
            buy_hold_return=buy_hold_return,
            post_decision_exposure=post_decision_exposure,
            stop_return=stop["return"],
        )
        benchmark_return = _benchmark_return(benchmark_close, entry_date, int(horizon))
        horizons_payload.append(
            {
                "horizon_days": int(horizon),
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": _date_value(period_close.index[-1]),
                "exit_price": float(period_close.iloc[-1]),
                "decision_return": decision_return,
                "buy_hold_return": buy_hold_return,
                "benchmark_return": benchmark_return,
                "alpha_vs_buy_hold": decision_return - buy_hold_return,
                "alpha_vs_benchmark": (
                    decision_return - benchmark_return if benchmark_return is not None else None
                ),
                "asset_max_drawdown": _max_drawdown(period_close),
                "stop_loss": stop_loss,
                "stop_hit": stop["hit"],
                "stop_date": stop["date"],
            }
        )

    status = "partial" if horizons_payload and pending_horizons else "evaluated"
    if not horizons_payload:
        status = "pending"

    summary = _summary_for_horizons(horizons_payload)
    data = {
        "mode": "decision_replay",
        "symbol": symbol,
        "action": action,
        "rating": rating,
        "decision_text": decision_text,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "post_decision_exposure": post_decision_exposure,
        "stop_loss": stop_loss,
        "benchmark_symbol": benchmark_symbol,
        "benchmark_error": benchmark_error,
        "benchmark_identity_match": benchmark_identity_match,
        "benchmark_warning": benchmark_warning,
        "horizons": horizons_payload,
        "pending_horizons": pending_horizons,
        "status": status,
        "summary": summary,
        "learning": _learning_for_replay(
            action=action,
            rating=rating,
            horizons=horizons_payload,
            summary=summary,
            stop_loss=stop_loss,
        ),
    }
    data["trade_style_fit"] = build_trade_style_fit(data)
    data["paper_trade_gate"] = build_paper_trade_gate(data)
    return ok(
        data,
        meta={
            "mode": "decision_replay",
            "symbol": symbol,
            "analysis_date": analysis_date,
        },
    )


def _fetch_window(analysis_date: str, horizons: tuple[int, ...]) -> tuple[str, str]:
    start = date.fromisoformat(analysis_date)
    max_horizon = max((int(h) for h in horizons), default=max(DEFAULT_HORIZONS))
    # Daily market data has weekends and holidays, so request a wider calendar window.
    end = start + timedelta(days=max_horizon * 2 + 14)
    return start.isoformat(), end.isoformat()


def _final_decision_text(final_state: dict[str, Any]) -> str:
    if final_state.get("final_trade_decision"):
        return str(final_state["final_trade_decision"]).strip()
    risk_state = final_state.get("risk_debate_state")
    if isinstance(risk_state, dict):
        return str(risk_state.get("judge_decision") or "").strip()
    return ""


def _action_from_rating(rating: str) -> str:
    if rating in {"Buy", "Overweight"}:
        return "Buy"
    if rating in {"Sell", "Underweight"}:
        return "Sell"
    return "Hold"


def _extract_stop_loss(text: str, reference_price: float | None = None) -> float | None:
    source = text or ""
    if reference_price is not None:
        relative = re.search(
            r"\bstops?(?:[-\s]?loss)?\b[^.;\n]{0,80}?\$?\s*"
            r"([0-9]+(?:\.[0-9]+)?)\s*(%)?\s*"
            r"(?:points?|pts?|dollars?|usd)?\s*"
            r"(?:below|under)\s*(?:the\s+)?"
            r"(?:close|entry|entry\s+price|current\s+price)",
            source,
            re.IGNORECASE,
        )
        if relative:
            amount = float(relative.group(1))
            if relative.group(2):
                return max(0.0, reference_price * (1.0 - amount / 100.0))
            return max(0.0, reference_price - amount)

    match = _STOP_RE.search(source)
    if not match:
        return None
    suffix = source[match.end() : match.end() + 80]
    if re.match(
        r"\s*%?\s*(?:below|under)\s*(?:the\s+)?"
        r"(?:close|entry|entry\s+price|current\s+price)",
        suffix,
        re.IGNORECASE,
    ):
        return None
    return float(match.group(1))


def _symbols_match(symbol: str | None, benchmark_symbol: str | None) -> bool:
    return bool(symbol and benchmark_symbol) and _symbol_key(symbol) == _symbol_key(benchmark_symbol)


def _symbol_key(symbol: str | None) -> str:
    return str(symbol or "").strip().upper()


def _post_decision_exposure(action: str, rating: str, text: str) -> float:
    if action in {"Buy", "Hold"}:
        return 1.0
    lowered = (text or "").lower()
    if any(term in lowered for term in ("exit", "fully sell", "sell all", "close the position")):
        return 0.0
    trim = _TRIM_RE.search(text or "")
    if trim:
        return max(0.0, min(1.0, 1.0 - float(trim.group(1)) / 100.0))
    if rating == "Underweight":
        return 0.5
    return 0.0


def _decision_return(
    *,
    action: str,
    buy_hold_return: float,
    post_decision_exposure: float,
    stop_return: float | None,
) -> float:
    if action in {"Buy", "Hold"}:
        return stop_return if stop_return is not None else buy_hold_return
    return post_decision_exposure * buy_hold_return


def _stop_result(
    action: str,
    stop_loss: float | None,
    entry_price: float,
    period_low: pd.Series,
) -> dict[str, Any]:
    if action not in {"Buy", "Hold"} or stop_loss is None:
        return {"hit": False, "date": None, "return": None}
    hits = period_low[period_low <= stop_loss]
    if hits.empty:
        return {"hit": False, "date": None, "return": None}
    return {
        "hit": True,
        "date": _date_value(hits.index[0]),
        "return": float(stop_loss / entry_price - 1),
    }


def _benchmark_return(
    benchmark_close: pd.Series | None,
    entry_date: str,
    horizon: int,
) -> float | None:
    if benchmark_close is None or benchmark_close.empty:
        return None
    entry_pos = _first_position_on_or_after(benchmark_close.index, entry_date)
    if entry_pos is None:
        return None
    exit_pos = entry_pos + horizon
    if exit_pos >= len(benchmark_close):
        return None
    entry_price = float(benchmark_close.iloc[entry_pos])
    return float(benchmark_close.iloc[exit_pos] / entry_price - 1)


def _first_position_on_or_after(index: pd.Index, target_date: str) -> int | None:
    target = pd.Timestamp(target_date)
    normalized = pd.to_datetime(index).tz_localize(None)
    positions = [i for i, value in enumerate(normalized) if value >= target]
    return positions[0] if positions else None


def _series(frame: pd.DataFrame | None, column: str) -> pd.Series:
    if frame is None or frame.empty:
        raise ValueError("frame must not be empty")
    if column not in frame.columns:
        raise ValueError(f"frame must contain a {column} column")
    values = pd.to_numeric(frame[column], errors="coerce").dropna().astype(float)
    if values.empty:
        raise ValueError(f"frame has no usable {column} values")
    return values.sort_index()


def _max_drawdown(close: pd.Series) -> float:
    drawdown = close / close.cummax() - 1
    return float(drawdown.min())


def _summary_for_horizons(horizons: list[dict[str, Any]]) -> dict[str, Any]:
    if not horizons:
        return {
            "evaluated_horizons": 0,
            "positive_alpha_vs_buy_hold": 0,
            "positive_alpha_vs_benchmark": 0,
            "positive_decision_returns": 0,
            "average_alpha_vs_buy_hold": None,
            "average_alpha_vs_benchmark": None,
            "average_decision_return": None,
            "worst_asset_max_drawdown": None,
            "best_decision_return_horizon": None,
            "worst_decision_return_horizon": None,
            "best_alpha_vs_benchmark_horizon": None,
            "worst_alpha_vs_benchmark_horizon": None,
        }

    alpha_hold = [float(row["alpha_vs_buy_hold"]) for row in horizons]
    decision_returns = [float(row["decision_return"]) for row in horizons]
    drawdowns = [float(row["asset_max_drawdown"]) for row in horizons]
    alpha_benchmark = [
        float(row["alpha_vs_benchmark"])
        for row in horizons
        if row.get("alpha_vs_benchmark") is not None
    ]
    benchmark_rows = [row for row in horizons if row.get("alpha_vs_benchmark") is not None]
    has_return_spread = len(decision_returns) == 1 or max(decision_returns) != min(decision_returns)
    best_return = max(horizons, key=lambda row: row["decision_return"]) if has_return_spread else None
    worst_return = min(horizons, key=lambda row: row["decision_return"]) if has_return_spread else None
    best_benchmark = (
        max(benchmark_rows, key=lambda row: row["alpha_vs_benchmark"])
        if benchmark_rows
        else None
    )
    worst_benchmark = (
        min(benchmark_rows, key=lambda row: row["alpha_vs_benchmark"])
        if benchmark_rows
        else None
    )
    return {
        "evaluated_horizons": len(horizons),
        "positive_alpha_vs_buy_hold": sum(1 for value in alpha_hold if value > 0),
        "positive_alpha_vs_benchmark": sum(1 for value in alpha_benchmark if value > 0),
        "positive_decision_returns": sum(1 for value in decision_returns if value > 0),
        "average_alpha_vs_buy_hold": sum(alpha_hold) / len(alpha_hold),
        "average_alpha_vs_benchmark": (
            sum(alpha_benchmark) / len(alpha_benchmark) if alpha_benchmark else None
        ),
        "average_decision_return": sum(decision_returns) / len(decision_returns),
        "worst_asset_max_drawdown": min(drawdowns),
        "best_decision_return_horizon": (
            int(best_return["horizon_days"]) if best_return else None
        ),
        "worst_decision_return_horizon": (
            int(worst_return["horizon_days"]) if worst_return else None
        ),
        "best_alpha_vs_benchmark_horizon": (
            int(best_benchmark["horizon_days"]) if best_benchmark else None
        ),
        "worst_alpha_vs_benchmark_horizon": (
            int(worst_benchmark["horizon_days"]) if worst_benchmark else None
        ),
    }


def _learning_for_replay(
    *,
    action: str,
    rating: str,
    horizons: list[dict[str, Any]],
    summary: dict[str, Any],
    stop_loss: float | None,
) -> dict[str, Any]:
    if not horizons:
        return {
            "verdict": "Pending: not enough forward market data to score this decision yet.",
            "lessons": [
                "Re-evaluate when at least one configured forward horizon has market data.",
            ],
            "next_prompt": "Do not treat this decision as validated until forward outcomes exist.",
        }

    evaluated = int(summary.get("evaluated_horizons") or len(horizons))
    avg_alpha_hold = summary.get("average_alpha_vs_buy_hold")
    avg_alpha_benchmark = summary.get("average_alpha_vs_benchmark")
    avg_decision_return = summary.get("average_decision_return")
    worst_drawdown = summary.get("worst_asset_max_drawdown")
    positive_benchmark = int(summary.get("positive_alpha_vs_benchmark") or 0)
    positive_returns = int(summary.get("positive_decision_returns") or 0)
    worst_horizon = summary.get("worst_decision_return_horizon")
    best_horizon = summary.get("best_decision_return_horizon")

    lessons: list[str] = []
    if action == "Buy":
        lessons.append(
            "For Buy/Overweight decisions, alpha vs buy-and-hold is expected to be near zero; "
            "judge the call against the benchmark, drawdown, and whether the thesis gave usable risk controls."
        )
    elif action == "Sell":
        lessons.append(
            "For Sell/Underweight decisions, positive alpha means reducing exposure helped versus staying fully invested."
        )
    else:
        lessons.append(
            "For Hold decisions, compare opportunity cost against both the asset move and benchmark move."
        )

    if avg_alpha_benchmark is not None and avg_alpha_benchmark > 0:
        lessons.append(
            f"The decision beat the benchmark on average across {positive_benchmark}/{evaluated} "
            "evaluable horizons."
        )
    elif avg_alpha_benchmark is not None:
        lessons.append(
            "The decision did not beat the benchmark on average; future calls need stronger relative-strength evidence."
        )

    if avg_decision_return is not None:
        if avg_decision_return > 0:
            lessons.append(
                f"The average decision return was positive across {positive_returns}/{evaluated} horizons."
            )
        elif avg_decision_return < 0:
            lessons.append(
                "The average decision return was negative; future calls should demand clearer invalidation criteria."
            )
        else:
            lessons.append(
                "The average decision return was flat; future calls should judge whether cash exposure was worth the opportunity cost."
            )

    if worst_drawdown is not None and worst_drawdown <= -0.15:
        if stop_loss is None:
            lessons.append(
                "Large drawdown occurred without a detected stop-loss; future Buy/Overweight decisions should include an explicit stop or smaller exposure."
            )
        else:
            lessons.append(
                "Large drawdown occurred; future decisions should verify the stop-loss is close enough to cap thesis failure."
            )

    if worst_horizon and best_horizon and worst_horizon != best_horizon:
        lessons.append(
            f"The best return horizon was {best_horizon}d and the worst was {worst_horizon}d; "
            "future recommendations should align action, exit rules, and time horizon."
        )

    verdict = _learning_verdict(avg_alpha_benchmark, avg_decision_return, worst_drawdown)
    next_prompt = " ".join(lessons[:3])
    return {
        "verdict": verdict,
        "lessons": lessons,
        "next_prompt": next_prompt,
        "metrics": {
            "average_alpha_vs_buy_hold": avg_alpha_hold,
            "average_alpha_vs_benchmark": avg_alpha_benchmark,
            "average_decision_return": avg_decision_return,
            "worst_asset_max_drawdown": worst_drawdown,
        },
    }


def _learning_verdict(
    avg_alpha_benchmark: float | None,
    avg_decision_return: float | None,
    worst_drawdown: float | None,
) -> str:
    benchmark_helped = avg_alpha_benchmark is not None and avg_alpha_benchmark > 0
    return_helped = avg_decision_return is not None and avg_decision_return > 0
    high_drawdown = worst_drawdown is not None and worst_drawdown <= -0.15
    if avg_alpha_benchmark is None:
        if return_helped and high_drawdown:
            return "Mixed call: positive absolute return, but risk control was weak."
        if return_helped:
            return "Mixed call: positive absolute return; benchmark edge was not evaluated."
        return "Weak call: no positive absolute return; benchmark edge was not evaluated."
    if benchmark_helped and return_helped and high_drawdown:
        return "Useful call, but risk control was weak."
    if benchmark_helped and return_helped:
        return "Useful call: positive return and benchmark outperformance."
    if benchmark_helped:
        return "Mixed call: beat benchmark but did not produce a positive absolute return."
    if return_helped:
        return "Mixed call: positive absolute return but weak relative performance."
    return "Weak call: no positive absolute or benchmark-adjusted edge."


def _date_value(index_value: Any) -> str:
    if hasattr(index_value, "date"):
        return index_value.date().isoformat()
    return str(index_value)
