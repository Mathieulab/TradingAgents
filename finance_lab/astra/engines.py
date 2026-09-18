"""Bounded engine comparison: one frozen bracket, same ordered quote sequence.

Not the full swing strategy migration. No financing/latency/depth calibration.
Backtrader consumes midpoint point-bars; Nautilus consumes actual bid/ask quotes.
"""

from decimal import Decimal
from importlib.metadata import version
from typing import Protocol
from zoneinfo import ZoneInfo

import backtrader as bt
import pandas as pd

from finance_lab.ftmo.config import TestConfig, rule_headroom
from finance_lab.ftmo.engine import SameBarBracketBroker

from .catalog import digest


class ExecutionEngine(Protocol):
    def run(self, quotes, instrument, proposal, gate, account) -> dict: ...


def validate_scenario(quotes, instrument, proposal, gate, account):
    if gate.verdict != "APPROVE" or gate.units <= 0 or proposal.direction == "NO TRADE":
        raise ValueError("Execution comparison requires a frozen approved candidate")
    if len(quotes) < 3 or any(
        a.timestamp >= b.timestamp for a, b in zip(quotes, quotes[1:], strict=False)
    ):
        raise ValueError("POC requires at least three strictly ordered distinct quote timestamps")
    if any(q.symbol != instrument.symbol or q.feed_id != instrument.feed_id for q in quotes):
        raise ValueError("Quote feed/instrument mismatch")
    if (
        instrument.base_currency != "EUR"
        or instrument.quote_currency != "USD"
        or account.currency != "USD"
    ):
        raise ValueError("POC supports EUR/USD with USD accounting only")
    if (
        account.positions
        or account.pending_orders
        or account.day_start_balance is None
        or account.breached
    ):
        raise ValueError("POC requires an unbreached flat account with known daily baseline")
    if proposal.instrument != instrument.symbol or account.feed_id != instrument.feed_id:
        raise ValueError("Candidate/account does not match the recorded instrument")
    if quotes[0].timestamp < account.timestamp:
        raise ValueError("POC cannot execute before the candidate account snapshot")
    entry = quotes[1].ask if proposal.direction == "LONG" else quotes[1].bid
    if not proposal.entry_low <= entry <= proposal.entry_high:
        raise ValueError("Execution quote is outside the frozen entry zone")
    if quotes[-1].timestamp - quotes[0].timestamp > pd.Timedelta(hours=4):
        raise ValueError("POC excludes overnight financing and multi-day risk resets")
    if any(q.timestamp.astimezone(ZoneInfo("Europe/Prague")).date() != account.day for q in quotes):
        raise ValueError("POC must stay within the account's Prague day")
    return digest(
        {
            "quotes": [q.model_dump(mode="json") for q in quotes],
            "instrument": instrument.model_dump(mode="json"),
            "proposal": proposal.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
            "account": account.model_dump(mode="json"),
        }
    )


def report(engine, fingerprint, fills, curve, account):
    return {
        "engine": engine,
        "version": version("backtrader" if engine == "Backtrader" else "nautilus_trader"),
        "scenario_hash": fingerprint,
        "fills": fills,
        "curve": curve,
        "net_pnl": curve[-1]["equity"] - account.equity if curve else 0,
        "limitations": [
            "Execution mechanics POC, not profitability evidence",
            "Zero commissions, swaps and latency; no calibrated depth or partial fills",
            "Backtrader midpoint point-bars vs Nautilus bid/ask",
            "Observed risk ledger only, not full FTMO liquidation control",
        ],
        "order_sent": False,
    }


class BacktraderEngine:
    def run(self, quotes, instrument, proposal, gate, account):
        fingerprint = validate_scenario(quotes, instrument, proposal, gate, account)
        fills, curve = [], []
        frame = pd.DataFrame(
            {k: [q.mid for q in quotes] for k in ("open", "high", "low", "close")},
            index=pd.DatetimeIndex([q.timestamp for q in quotes]).tz_localize(None),
        )
        config = TestConfig(balance=account.initial_balance)

        class FrozenBracket(bt.Strategy):
            def next(self):
                if len(self) == 1:
                    method = self.buy_bracket if proposal.direction == "LONG" else self.sell_bracket
                    method(
                        size=gate.units,
                        exectype=bt.Order.Market,
                        stopprice=proposal.stop_loss,
                        limitprice=proposal.take_profits[0],
                    )
                equity = self.broker.getvalue()
                curve.append(
                    {
                        "timestamp": quotes[len(self) - 1].timestamp.isoformat(),
                        "equity": equity,
                        **rule_headroom(config, account.day_start_balance, equity),
                    }
                )

            def notify_order(self, order):
                if order.status == order.Completed:
                    fills.append(
                        {
                            "side": "BUY" if order.isbuy() else "SELL",
                            "price": order.executed.price,
                            "units": abs(order.executed.size),
                        }
                    )

        cerebro = bt.Cerebro(stdstats=False)
        broker = SameBarBracketBroker()
        broker.setcash(account.equity)
        broker.setcommission(commission=0, leverage=10)
        cerebro.setbroker(broker)
        cerebro.adddata(bt.feeds.PandasData(dataname=frame))
        cerebro.addstrategy(FrozenBracket)
        cerebro.run(runonce=False)
        return report("Backtrader", fingerprint, fills, curve, account)


class NautilusEngine:
    def run(self, quotes, instrument, proposal, gate, account):
        fingerprint = validate_scenario(quotes, instrument, proposal, gate, account)
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.config import BacktestEngineConfig, LoggingConfig
        from nautilus_trader.model.currencies import EUR, USD
        from nautilus_trader.model.data import QuoteTick
        from nautilus_trader.model.enums import AccountType, ContingencyType, OmsType, OrderSide
        from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
        from nautilus_trader.model.instruments import CurrencyPair
        from nautilus_trader.model.objects import Money, Price, Quantity
        from nautilus_trader.trading.strategy import Strategy

        precision = max(0, -Decimal(str(instrument.price_increment)).as_tuple().exponent)
        venue = Venue("ASTRA")
        pair = CurrencyPair(
            instrument_id=InstrumentId(Symbol(instrument.symbol), venue),
            raw_symbol=Symbol(instrument.symbol),
            base_currency=EUR,
            quote_currency=USD,
            price_precision=precision,
            size_precision=0,
            price_increment=Price(instrument.price_increment, precision),
            size_increment=Quantity(instrument.step_units, 0),
            lot_size=Quantity(instrument.contract_size, 0),
            ts_event=0,
            ts_init=0,
        )
        fills, curve = [], []
        config = TestConfig(balance=account.initial_balance)

        class FrozenBracket(Strategy):
            def on_start(self):
                self.count = 0
                self.subscribe_quote_ticks(pair.id)

            def on_quote_tick(self, tick):
                self.count += 1
                if self.count == 2:
                    orders = self.order_factory.bracket(
                        instrument_id=pair.id,
                        order_side=OrderSide.BUY
                        if proposal.direction == "LONG"
                        else OrderSide.SELL,
                        quantity=Quantity(gate.units, 0),
                        contingency_type=ContingencyType.OCO,
                        sl_trigger_price=Price(proposal.stop_loss, precision),
                        tp_price=Price(proposal.take_profits[0], precision),
                        tp_post_only=False,
                    )
                    self.submit_order_list(orders)
                cash = self.cache.account_for_venue(venue).balance_total(USD).as_double()
                unrealized = self.portfolio.unrealized_pnl(pair.id)
                equity = cash + (unrealized.as_double() if unrealized else 0)
                curve.append(
                    {
                        "timestamp": quotes[self.count - 1].timestamp.isoformat(),
                        "equity": equity,
                        **rule_headroom(config, account.day_start_balance, equity),
                    }
                )

            def on_order_filled(self, event):
                fills.append(
                    {
                        "side": "BUY" if event.order_side == OrderSide.BUY else "SELL",
                        "price": event.last_px.as_double(),
                        "units": event.last_qty.as_double(),
                    }
                )

        engine = BacktestEngine(
            config=BacktestEngineConfig(logging=LoggingConfig(bypass_logging=True))
        )
        try:
            engine.add_venue(
                venue=venue,
                oms_type=OmsType.NETTING,
                account_type=AccountType.MARGIN,
                base_currency=USD,
                starting_balances=[Money(account.equity, USD)],
                default_leverage=Decimal(10),
                use_message_queue=False,
            )
            engine.add_instrument(pair)
            ticks = [
                QuoteTick(
                    pair.id,
                    Price(q.bid, precision),
                    Price(q.ask, precision),
                    Quantity(10000000, 0),
                    Quantity(10000000, 0),
                    pd.Timestamp(q.timestamp).value,
                    pd.Timestamp(q.timestamp).value,
                )
                for q in quotes
            ]
            engine.add_data(ticks)
            strategy = FrozenBracket()
            engine.add_strategy(strategy)
            engine.run()
            return report("Nautilus", fingerprint, fills, curve, account)
        finally:
            engine.dispose()
