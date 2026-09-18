"""Compact final-decision summary for normal CLI users."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from tradingagents.rating import parse_rating

DISCLAIMER = (
    "Research/backtesting output only. Not financial advice; verify independently "
    "before making investment decisions."
)

_FIELD_RE_TEMPLATE = (
    r"(?ims)^\s*(?:[-*]\s*)?(?:\*\*)?{field}(?:\*\*)?\s*:\s*(.*?)"
    r"(?=^\s*(?:[-*]\s*)?(?:\*\*)?[A-Z][A-Za-z ]+(?:\*\*)?\s*:|\Z)"
)


class DecisionSummary(BaseModel):
    """Machine-readable view of the final report for concise CLI display."""

    action: str = Field(description="Three-way action: Buy, Hold, or Sell.")
    rating: str = Field(description="Original five-tier Portfolio Manager rating.")
    confidence: str = Field(description="Low, Medium, or High confidence estimate.")
    risk_level: str = Field(description="Low, Medium, or High risk estimate.")
    executive_summary: str = Field(description="Short user-facing decision summary.")
    bullish_points: list[str] = Field(default_factory=list)
    bearish_points: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    price_target: str | None = None
    time_horizon: str | None = None
    disclaimer: str = DISCLAIMER


def build_decision_summary(final_state: dict) -> DecisionSummary | None:
    """Build a compact summary from the final graph state.

    The Portfolio Manager already emits deterministic markdown headers. This
    helper keeps that markdown as the source of truth and derives only display
    fields that are safe to infer, such as a three-way action and top points
    from the debate histories.
    """
    final_decision = _final_decision_text(final_state)
    if not final_decision:
        return None

    rating = parse_rating(final_decision)
    return DecisionSummary(
        action=_action_from_rating(rating),
        rating=rating,
        confidence=_infer_confidence(final_decision),
        risk_level=_infer_risk_level(final_decision, final_state),
        executive_summary=_summary_text(final_decision),
        bullish_points=_extract_points(
            _nested(final_state, "investment_debate_state", "bull_history"),
            _nested(final_state, "risk_debate_state", "aggressive_history"),
        ),
        bearish_points=_extract_points(
            _nested(final_state, "investment_debate_state", "bear_history"),
            _nested(final_state, "risk_debate_state", "conservative_history"),
        ),
        risk_notes=_extract_points(
            _nested(final_state, "risk_debate_state", "neutral_history"),
            _field(final_decision, "Investment Thesis"),
            max_points=2,
        ),
        price_target=_field(final_decision, "Price Target"),
        time_horizon=_field(final_decision, "Time Horizon"),
    )


def render_decision_summary_markdown(summary: DecisionSummary) -> str:
    """Render a DecisionSummary as markdown for Rich and saved reports."""
    lines = [
        "## Decision Summary",
        "",
        f"- **Action**: {summary.action}",
        f"- **Rating**: {summary.rating}",
        f"- **Confidence**: {summary.confidence}",
        f"- **Risk**: {summary.risk_level}",
    ]
    if summary.price_target:
        lines.append(f"- **Price Target**: {summary.price_target}")
    if summary.time_horizon:
        lines.append(f"- **Time Horizon**: {summary.time_horizon}")

    lines.extend(["", f"**Summary**: {summary.executive_summary}"])
    lines.extend(_section("Bullish Points", summary.bullish_points))
    lines.extend(_section("Bearish Points", summary.bearish_points))
    lines.extend(_section("Risk Notes", summary.risk_notes))
    lines.extend(["", f"> {summary.disclaimer}"])
    return "\n".join(lines)


def _final_decision_text(final_state: dict) -> str:
    if final_state.get("final_trade_decision"):
        return str(final_state["final_trade_decision"]).strip()
    return _nested(final_state, "risk_debate_state", "judge_decision")


def _field(markdown: str, field: str) -> str | None:
    pattern = re.compile(_FIELD_RE_TEMPLATE.format(field=re.escape(field)))
    match = pattern.search(markdown or "")
    if not match:
        return None
    value = _clean_text(match.group(1))
    return value or None


def _summary_text(final_decision: str) -> str:
    return (
        _field(final_decision, "Executive Summary")
        or _first_point(_field(final_decision, "Investment Thesis") or final_decision)
        or "No concise summary was produced."
    )


def _action_from_rating(rating: str) -> str:
    if rating in {"Buy", "Overweight"}:
        return "Buy"
    if rating in {"Sell", "Underweight"}:
        return "Sell"
    return "Hold"


def _infer_confidence(final_decision: str) -> str:
    explicit = _field(final_decision, "Confidence")
    if explicit:
        lowered = explicit.lower()
        if "high" in lowered:
            return "High"
        if "low" in lowered:
            return "Low"
        if "medium" in lowered or "moderate" in lowered:
            return "Medium"

    lowered = final_decision.lower()
    if any(term in lowered for term in ("strong conviction", "high confidence")):
        return "High"
    if any(term in lowered for term in ("low confidence", "limited data", "uncertain")):
        return "Low"
    return "Medium"


def _infer_risk_level(final_decision: str, final_state: dict) -> str:
    combined = " ".join([
        final_decision,
        _nested(final_state, "risk_debate_state", "aggressive_history"),
        _nested(final_state, "risk_debate_state", "conservative_history"),
        _nested(final_state, "risk_debate_state", "neutral_history"),
    ]).lower()

    if any(term in combined for term in ("high risk", "elevated risk", "speculative")):
        return "High"
    if any(term in combined for term in ("low risk", "limited downside", "defensive")):
        return "Low"
    return "Medium"


def _extract_points(*texts: str | None, max_points: int = 2) -> list[str]:
    points: list[str] = []
    for text in texts:
        for point in _candidate_points(text or ""):
            if point and point not in points:
                points.append(_truncate(point))
            if len(points) >= max_points:
                return points
    return points


def _candidate_points(text: str) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []

    bullet_points = []
    for line in cleaned.splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", line).strip()
        if len(line) >= 24:
            bullet_points.append(line)
    if bullet_points:
        return bullet_points

    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", cleaned)
        if len(sentence.strip()) >= 24
    ]


def _first_point(text: str) -> str:
    points = _candidate_points(text)
    return _truncate(points[0]) if points else ""


def _clean_text(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _truncate(text: str, limit: int = 220) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _nested(state: dict, section: str, key: str) -> str:
    value = state.get(section)
    if not isinstance(value, dict):
        return ""
    return str(value.get(key) or "").strip()


def _section(title: str, points: list[str]) -> list[str]:
    if not points:
        return []
    lines = ["", f"**{title}**:"]
    lines.extend(f"- {point}" for point in points)
    return lines
