"""Deterministic paper-trade gate for Finance Lab replay results."""

from __future__ import annotations

from typing import Any

MAX_ACCEPTED_DRAWDOWN = -0.10
MAX_HARD_DRAWDOWN = -0.15


def build_paper_trade_gate(replay_data: dict[str, Any]) -> dict[str, Any]:
    """Return a conservative No/Watchlist/Yes gate before any execution layer."""
    action = str(replay_data.get("action") or "Hold")
    stop_loss = replay_data.get("stop_loss")
    style_fit = replay_data.get("trade_style_fit") or {}
    styles = style_fit.get("styles") or []
    evaluated_styles = [row for row in styles if row.get("status") == "evaluated"]
    best = _best_style(style_fit, evaluated_styles)

    passed: list[str] = []
    failed: list[str] = []
    warnings: list[str] = []
    reasons: list[str] = []

    if not best:
        return _gate(
            candidate="no",
            execution_intent="skip",
            position_size=0.0,
            best_style=None,
            best_label=None,
            passed=passed,
            failed=["no_evaluated_style"],
            warnings=warnings,
            reasons=["No evaluated daily trade style is available yet."],
            stop_loss=stop_loss,
        )

    fit = str(best.get("fit") or "")
    avg_decision = _optional_float(best.get("average_decision_return"))
    avg_alpha_benchmark = _optional_float(best.get("average_alpha_vs_benchmark"))
    avg_alpha_hold = _optional_float(best.get("average_alpha_vs_buy_hold"))
    worst_drawdown = _optional_float(best.get("worst_asset_max_drawdown")) or 0.0

    if fit == "Weak":
        failed.append("weak_best_style")
        reasons.append(f"Best evaluated style is still weak: {best.get('label')}.")
    else:
        passed.append("style_fit")

    if avg_decision is None or avg_decision <= 0:
        failed.append("non_positive_expectancy")
        reasons.append("Best style does not have positive average decision return.")
    else:
        passed.append("positive_expectancy")

    relative_edge = avg_alpha_benchmark if avg_alpha_benchmark is not None else avg_alpha_hold
    if relative_edge is None:
        warnings.append("benchmark_edge_not_available")
    elif relative_edge <= 0:
        failed.append("no_relative_edge")
        reasons.append("Best style does not show positive benchmark/hold edge.")
    else:
        passed.append("positive_relative_edge")

    if worst_drawdown <= MAX_HARD_DRAWDOWN:
        failed.append("drawdown_hard_limit")
        reasons.append("Worst drawdown breaches the hard paper-trade limit.")
    elif worst_drawdown <= MAX_ACCEPTED_DRAWDOWN:
        warnings.append("drawdown_near_limit")
        reasons.append("Worst drawdown is near the maximum accepted paper-trade limit.")
    else:
        passed.append("drawdown_ok")

    if action == "Buy":
        if stop_loss is None:
            failed.append("missing_stop_loss")
            reasons.append("Buy/Overweight decisions require a detected stop-loss before execution.")
        else:
            passed.append("stop_loss_present")
        candidate = "yes" if not failed else "no"
        intent = "paper_long" if candidate == "yes" else "skip"
        size = _position_size(fit, worst_drawdown) if candidate == "yes" else 0.0
    elif action == "Hold":
        failed.append("hold_is_not_new_entry")
        reasons.append("Hold is not a new-entry signal; use it only to manage or watch an existing position.")
        candidate = "watchlist" if fit != "Weak" and avg_decision and avg_decision > 0 else "no"
        intent = "hold_existing_or_watch" if candidate == "watchlist" else "skip"
        size = 0.0
    else:
        failed.append("position_context_required")
        reasons.append("Sell/Underweight can only execute against confirmed existing position context.")
        candidate = "watchlist" if fit != "Weak" and relative_edge and relative_edge > 0 else "no"
        intent = "reduce_or_exit_existing" if candidate == "watchlist" else "skip"
        size = 0.0

    return _gate(
        candidate=candidate,
        execution_intent=intent,
        position_size=size,
        best_style=str(best.get("style") or ""),
        best_label=str(best.get("label") or best.get("style") or ""),
        passed=passed,
        failed=failed,
        warnings=warnings,
        reasons=reasons,
        stop_loss=stop_loss,
    )


def _gate(
    *,
    candidate: str,
    execution_intent: str,
    position_size: float,
    best_style: str | None,
    best_label: str | None,
    passed: list[str],
    failed: list[str],
    warnings: list[str],
    reasons: list[str],
    stop_loss: Any,
) -> dict[str, Any]:
    return {
        "mode": "paper_trade_gate",
        "candidate": candidate,
        "execution_intent": execution_intent,
        "position_size": position_size,
        "best_style": best_style,
        "best_label": best_label,
        "stop_loss": stop_loss,
        "requires_manual_approval": candidate != "no",
        "passed_rules": _dedupe(passed),
        "failed_rules": _dedupe(failed),
        "warnings": _dedupe(warnings),
        "reasons": _dedupe(reasons),
    }


def _best_style(
    style_fit: dict[str, Any],
    evaluated_styles: list[dict[str, Any]],
) -> dict[str, Any] | None:
    best_style = style_fit.get("best_style")
    for row in evaluated_styles:
        if row.get("style") == best_style:
            return row
    return max(evaluated_styles, key=lambda row: row.get("score") or 0.0, default=None)


def _position_size(fit: str, worst_drawdown: float) -> float:
    if fit == "Strong" and worst_drawdown > -0.05:
        return 0.50
    if fit in {"Strong", "Mixed"}:
        return 0.25
    return 0.0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
