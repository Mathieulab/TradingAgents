from cli.decision_summary import (
    build_decision_summary,
    render_decision_summary_markdown,
)


def test_build_decision_summary_from_structured_pm_markdown():
    final_state = {
        "final_trade_decision": (
            "**Rating**: Overweight\n\n"
            "**Executive Summary**: Add gradually with a 4% position cap and a stop below $90.\n\n"
            "**Investment Thesis**: Revenue momentum is improving, but elevated risk remains from valuation.\n\n"
            "**Price Target**: 120.5\n\n"
            "**Time Horizon**: 3-6 months\n"
        ),
        "investment_debate_state": {
            "bull_history": "- Product adoption is accelerating across enterprise customers.",
            "bear_history": "- Valuation is stretched relative to near-term cash flow.",
        },
        "risk_debate_state": {
            "aggressive_history": "- Upside remains attractive if margins expand.",
            "conservative_history": "- Elevated risk from multiple compression.",
            "neutral_history": "- Position sizing should stay moderate until volatility settles.",
        },
    }

    summary = build_decision_summary(final_state)

    assert summary is not None
    assert summary.action == "Buy"
    assert summary.rating == "Overweight"
    assert summary.confidence == "Medium"
    assert summary.risk_level == "High"
    assert summary.price_target == "120.5"
    assert summary.time_horizon == "3-6 months"
    assert summary.bullish_points == [
        "Product adoption is accelerating across enterprise customers.",
        "Upside remains attractive if margins expand.",
    ]
    assert summary.bearish_points == [
        "Valuation is stretched relative to near-term cash flow.",
        "Elevated risk from multiple compression.",
    ]


def test_render_decision_summary_markdown_contains_disclaimer_and_points():
    final_state = {
        "final_trade_decision": (
            "**Rating**: Sell\n\n"
            "**Executive Summary**: Exit while downside risk dominates.\n\n"
            "**Investment Thesis**: High risk and weak catalysts create an unfavorable setup."
        ),
        "risk_debate_state": {
            "conservative_history": "- Balance sheet stress could worsen.",
            "neutral_history": "- Wait for clearer evidence before re-entering.",
        },
    }

    summary = build_decision_summary(final_state)
    markdown = render_decision_summary_markdown(summary)

    assert "- **Action**: Sell" in markdown
    assert "- **Rating**: Sell" in markdown
    assert "**Bearish Points**" in markdown
    assert "Balance sheet stress could worsen." in markdown
    assert "Not financial advice" in markdown
