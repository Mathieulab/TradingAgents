"""Trade-style fit scoring for Finance Lab decision replay."""

from __future__ import annotations

from typing import Any

DAILY_STYLE_PROFILES = (
    {
        "style": "short_term",
        "label": "Short-term",
        "data_kind": "daily",
        "interval": "1d",
        "horizons": (1, 2, 5),
    },
    {
        "style": "swing",
        "label": "Swing",
        "data_kind": "daily",
        "interval": "1d",
        "horizons": (5, 10, 20),
    },
    {
        "style": "position",
        "label": "Position",
        "data_kind": "daily",
        "interval": "1d",
        "horizons": (60, 120),
    },
)

INTRADAY_STYLE_PROFILES = (
    {
        "style": "scalping",
        "label": "Scalping",
        "data_kind": "intraday",
        "interval": "1m/5m",
        "horizons": (),
        "note": "Requires intraday bars from CSV, Alpaca, or Polygon/Massive.",
    },
    {
        "style": "intraday",
        "label": "Intraday",
        "data_kind": "intraday",
        "interval": "5m/15m",
        "horizons": (),
        "note": "Requires intraday bars from CSV, Alpaca, or Polygon/Massive.",
    },
)

DEFAULT_STYLE_PROFILES = (*INTRADAY_STYLE_PROFILES, *DAILY_STYLE_PROFILES)


def build_trade_style_fit(
    replay_data: dict[str, Any],
    *,
    profiles: tuple[dict[str, Any], ...] = DEFAULT_STYLE_PROFILES,
) -> dict[str, Any]:
    """Score which trading style best fits evaluated replay horizons."""
    horizons = replay_data.get("horizons") or []
    rows_by_horizon = {int(row["horizon_days"]): row for row in horizons}
    style_rows = [_score_profile(profile, rows_by_horizon) for profile in profiles]
    evaluated_rows = [row for row in style_rows if row.get("status") == "evaluated"]
    best = max(evaluated_rows, key=lambda row: row["score"], default=None)
    weakest = min(evaluated_rows, key=lambda row: row["score"], default=None)
    return {
        "mode": "trade_style_fit",
        "styles": style_rows,
        "best_style": best["style"] if best else None,
        "best_label": best["label"] if best else None,
        "weakest_style": weakest["style"] if weakest else None,
        "weakest_label": weakest["label"] if weakest else None,
        "summary": _summary_note(best, weakest),
    }


def _score_profile(profile: dict[str, Any], rows_by_horizon: dict[int, dict[str, Any]]) -> dict[str, Any]:
    base = {
        "style": profile["style"],
        "label": profile["label"],
        "data_kind": profile["data_kind"],
        "interval": profile["interval"],
        "configured_horizons": list(profile.get("horizons") or []),
    }
    if profile["data_kind"] != "daily":
        return {
            **base,
            "status": "dataset_required",
            "fit": "Needs dataset",
            "score": None,
            "evaluated_horizons": [],
            "note": profile.get("note", "Requires intraday bars."),
        }

    matched = [rows_by_horizon[horizon] for horizon in profile["horizons"] if horizon in rows_by_horizon]
    if not matched:
        return {
            **base,
            "status": "pending",
            "fit": "Pending",
            "score": None,
            "evaluated_horizons": [],
            "note": "No evaluated replay horizons are available for this style yet.",
        }

    avg_decision = _average(row.get("decision_return") for row in matched)
    avg_alpha_hold = _average(row.get("alpha_vs_buy_hold") for row in matched)
    avg_alpha_benchmark = _average(row.get("alpha_vs_benchmark") for row in matched)
    worst_drawdown = min(float(row.get("asset_max_drawdown") or 0.0) for row in matched)
    score = _style_score(avg_decision, avg_alpha_hold, avg_alpha_benchmark, worst_drawdown)
    return {
        **base,
        "status": "evaluated",
        "fit": _fit_label(score, worst_drawdown),
        "score": score,
        "evaluated_horizons": [int(row["horizon_days"]) for row in matched],
        "average_decision_return": avg_decision,
        "average_alpha_vs_buy_hold": avg_alpha_hold,
        "average_alpha_vs_benchmark": avg_alpha_benchmark,
        "worst_asset_max_drawdown": worst_drawdown,
        "positive_alpha_vs_buy_hold": sum(1 for row in matched if row["alpha_vs_buy_hold"] > 0),
        "positive_alpha_vs_benchmark": sum(
            1
            for row in matched
            if row.get("alpha_vs_benchmark") is not None and row["alpha_vs_benchmark"] > 0
        ),
    }


def _average(values: Any) -> float | None:
    usable = [float(value) for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _style_score(
    avg_decision: float | None,
    avg_alpha_hold: float | None,
    avg_alpha_benchmark: float | None,
    worst_drawdown: float,
) -> float:
    relative_edge = avg_alpha_benchmark if avg_alpha_benchmark is not None else avg_alpha_hold
    score = 0.0
    if relative_edge is not None:
        score += relative_edge
    if avg_decision is not None:
        score += avg_decision * 0.5
    score += worst_drawdown * 0.25
    return score


def _fit_label(score: float, worst_drawdown: float) -> str:
    if score > 0.02 and worst_drawdown > -0.10:
        return "Strong"
    if score > 0.0:
        return "Mixed"
    return "Weak"


def _summary_note(best: dict[str, Any] | None, weakest: dict[str, Any] | None) -> str:
    if not best:
        return "No daily trade style has enough evaluated horizons yet."
    if weakest and weakest["style"] != best["style"]:
        return "Best fit: {best}. Weakest fit: {weakest}.".format(
            best=best["label"],
            weakest=weakest["label"],
        )
    return "Best fit: {best}.".format(best=best["label"])
