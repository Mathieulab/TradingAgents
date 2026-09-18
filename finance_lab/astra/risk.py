"""Conservative flat-account shadow gate, never a broker execution authorization."""

import math
from zoneinfo import ZoneInfo

from finance_lab.ftmo.config import TestConfig, rule_headroom

from .models import GateResult, RiskPolicy


def evaluate(proposal, instrument, quote, account, as_of, policy=None):
    policy = policy or RiskPolicy()
    reasons = []
    if proposal.direction == "NO TRADE":
        return GateResult(verdict="NO TRADE", reasons=[proposal.no_trade_reason])
    if as_of.tzinfo is None:
        raise ValueError("Risk decisions require an aware instant")
    if proposal.instrument != instrument.symbol:
        reasons.append("Proposal instrument mismatch")
    if instrument.base_currency != "EUR" or instrument.quote_currency != "USD":
        reasons.append("Only EUR/USD is validated in this initial shadow gate")
    if quote is None or account is None:
        return GateResult(verdict="REJECT", reasons=reasons + ["Missing quote or account state"])
    if (
        quote.symbol != instrument.symbol
        or quote.feed_id != instrument.feed_id
        or account.feed_id != instrument.feed_id
    ):
        reasons.append("Feed/account/instrument mismatch")
    for name, timestamp in (("Quote", quote.timestamp), ("Account", account.timestamp)):
        age = (as_of - timestamp).total_seconds()
        if age < 0 or age > policy.max_quote_age_seconds:
            reasons.append(f"{name} is stale or from the future")
    if quote.received_at is not None and quote.received_at > as_of:
        reasons.append("Quote was not available at decision time")
    if account.currency != "USD":
        reasons.append("USD account required; currency conversion not implemented")
    if account.breached:
        reasons.append("Account breach is latched")
    if account.positions:
        reasons.append(
            "Existing positions require portfolio risk reconciliation; flat account required"
        )
    if account.pending_orders:
        reasons.append("Pending broker orders require exposure reconciliation")
    if account.day != as_of.astimezone(ZoneInfo("Europe/Prague")).date():
        reasons.append("Account daily baseline is not for the current Prague day")
    if account.day_start_balance is None:
        return GateResult(verdict="REJECT", reasons=reasons + ["Unknown daily baseline"])
    config = TestConfig(
        balance=account.initial_balance,
        daily_stop_pct=policy.daily_cutoff_percent,
        risk_pct=min(policy.max_risk_percent, policy.daily_cutoff_percent),
    )
    headroom = rule_headroom(config, account.day_start_balance, account.equity)
    if min(headroom.values()) <= 0 or account.equity <= 0:
        reasons.append("FTMO or internal loss floor reached")
    if abs(account.equity - account.balance) > 0.01 and not account.positions:
        reasons.append("Unexplained floating PnL on a flat account")
    spread = quote.spread / instrument.pip_size
    if spread > policy.max_spread_pips:
        reasons.append("Spread exceeds policy")
    entry = quote.ask if proposal.direction == "LONG" else quote.bid
    if not proposal.entry_low <= entry <= proposal.entry_high:
        reasons.append("Executable price is outside the proposed entry zone")
    sign = 1 if proposal.direction == "LONG" else -1
    stop_distance = sign * (entry - proposal.stop_loss)
    target_distance = min(sign * (target - entry) for target in proposal.take_profits)
    # Spread is already in executable entry/exit sides. Reserve adverse slippage,
    # round-trip commission and conservative calendar-day financing separately.
    costs = (
        2 * policy.slippage_pips * instrument.pip_size
        + 2 * policy.commission_per_lot_side / instrument.contract_size
        + policy.financing_reserve_per_lot_day
        * math.ceil(proposal.holding_hours / 24)
        / instrument.contract_size
    )
    unit_risk = stop_distance + costs
    rr = (target_distance - costs) / unit_risk if unit_risk > 0 else 0
    if stop_distance <= 0 or rr < policy.min_reward_risk:
        reasons.append("Invalid stop or insufficient net reward/risk after reserved costs")
    for level in (proposal.stop_loss, *proposal.take_profits):
        if not math.isclose(
            level / instrument.price_increment,
            round(level / instrument.price_increment),
            abs_tol=1e-6,
        ):
            reasons.append("SL/TP not aligned to the instrument price increment")
            break
    risk_budget = min(
        account.equity * min(proposal.risk_percent, policy.max_risk_percent) / 100,
        *headroom.values(),
    )
    units = 0
    if not reasons:
        raw = min(
            risk_budget / unit_risk,
            account.equity * policy.leverage_cap / entry,
            instrument.max_units,
            proposal.suggested_units or instrument.max_units,
        )
        units = math.floor(raw / instrument.step_units) * instrument.step_units
        if units < instrument.min_units or units * unit_risk >= min(headroom.values()):
            reasons.append("Minimum tradable size exceeds available loss budget")
            units = 0
    return GateResult(
        verdict="REJECT" if reasons else "APPROVE",
        reasons=reasons or ["Shadow candidate only; no order transport"],
        units=units,
        risk_at_stop=units * max(unit_risk, 0),
        reward_risk=rr,
        daily_remaining=headroom["daily_remaining"],
        total_remaining=headroom["total_remaining"],
        spread_pips=spread,
    )
