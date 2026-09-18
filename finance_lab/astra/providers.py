"""Provider-independent read APIs. This module deliberately has no order methods."""

import csv
import hashlib
import time
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

import pandas as pd

from .models import AccountSnapshot, Bar, Instrument, Position, Quote

SECONDS = {"M15": 900, "H4": 14400, "D1": 86400}


def inspect_mt5_terminal(terminal_path=None, *, sdk=None):
    """Read connected account identity and EUR/USD symbols for the setup picker."""
    if sdk is None:
        import MetaTrader5 as sdk
    connected = sdk.initialize(terminal_path) if terminal_path else sdk.initialize()
    if not connected:
        raise RuntimeError("MT5 is unavailable. Open the FTMO terminal and log in before connecting")
    try:
        account = sdk.account_info()
        symbols = sdk.symbols_get()
        if account is None or symbols is None:
            raise RuntimeError("The terminal has no connected account or symbol list")
        if account.currency != "USD":
            raise ValueError("The current FTMO integration requires a USD-denominated account")
        choices = [s.name for s in symbols if s.currency_base == "EUR" and s.currency_profit == "USD"]
        if not choices:
            raise ValueError("No EUR/USD symbol was found on this terminal")
        return {"server": account.server, "login": account.login, "currency": account.currency,
                "symbols": choices}
    finally:
        sdk.shutdown()


class MarketDataProvider(Protocol):
    def get_quote(self, symbol: str, as_of: datetime) -> Quote | None: ...
    def get_ticks(self, symbol: str, start: datetime, end: datetime) -> list[Quote]: ...
    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]: ...
    def subscribe_quotes(self, symbol: str) -> Iterator[Quote]: ...
    def subscribe_bars(self, symbol: str, timeframe: str) -> Iterator[Bar]: ...
    def get_instrument_metadata(self, symbol: str) -> Instrument: ...


def bars_from_quotes(quotes, timeframe, as_of, basis="mid"):
    if as_of.tzinfo is None:
        raise ValueError("An aware as-of instant is required")
    quotes = [
        q
        for q in quotes
        if q.timestamp <= as_of and (q.received_at is None or q.received_at <= as_of)
    ]
    if not quotes:
        return []
    if len({(q.symbol, q.feed_id) for q in quotes}) != 1:
        raise ValueError("Cannot aggregate quotes from different instruments/feeds")
    frame = pd.DataFrame(
        {"price": [getattr(q, basis) for q in quotes]},
        index=pd.DatetimeIndex([q.timestamp for q in quotes]),
    )
    frame = frame.sort_index(kind="stable")
    groups = frame.price.resample(f"{SECONDS[timeframe]}s", closed="left", label="left")
    result = []
    for opening, series in groups:
        closing = opening.to_pydatetime() + timedelta(seconds=SECONDS[timeframe])
        if series.empty or closing > as_of:
            continue
        receipts = [
            q.received_at for q in quotes if opening <= q.timestamp < closing and q.received_at
        ]
        result.append(
            Bar(
                symbol=quotes[0].symbol,
                feed_id=quotes[0].feed_id,
                open_time=opening.to_pydatetime(),
                close_time=closing,
                received_at=max([closing, *receipts]) if receipts else None,
                timeframe=timeframe,
                basis=basis,
                open=series.iloc[0],
                high=series.max(),
                low=series.min(),
                close=series.iloc[-1],
                volume=len(series),
            )
        )
    return result


class CSVMarketDataProvider:
    def __init__(self, path: Path, instrument: Instrument):
        self.instrument = instrument
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            self.quotes = [
                Quote(
                    symbol=instrument.symbol,
                    feed_id=instrument.feed_id,
                    timestamp=row["timestamp"],
                    received_at=row.get("received_at") or None,
                    bid=row["bid"],
                    ask=row["ask"],
                    volume=row.get("volume") or None,
                )
                for row in csv.DictReader(stream)
            ]
        if any(
            a.timestamp > b.timestamp for a, b in zip(self.quotes, self.quotes[1:], strict=False)
        ):
            raise ValueError("Quote CSV must be chronologically ordered")

    def get_instrument_metadata(self, symbol):
        if symbol != self.instrument.symbol:
            raise ValueError("Instrument does not match the CSV specification")
        return self.instrument

    def get_ticks(self, symbol, start, end):
        self.get_instrument_metadata(symbol)
        return [
            q
            for q in self.quotes
            if start <= q.timestamp <= end and (q.received_at is None or q.received_at <= end)
        ]

    def get_quote(self, symbol, as_of):
        ticks = self.get_ticks(symbol, datetime.min.replace(tzinfo=timezone.utc), as_of)
        return ticks[-1] if ticks else None

    def get_bars(self, symbol, timeframe, start, end):
        return bars_from_quotes(self.get_ticks(symbol, start, end), timeframe, end)

    def subscribe_quotes(self, symbol):
        self.get_instrument_metadata(symbol)
        yield from self.quotes

    def subscribe_bars(self, symbol, timeframe):
        self.get_instrument_metadata(symbol)
        if self.quotes:
            yield from bars_from_quotes(self.quotes, timeframe, self.quotes[-1].timestamp)


class MT5MarketDataProvider:
    def __init__(self, *, expected_server, expected_login, terminal_path=None, sdk=None):
        if sdk is None:
            import MetaTrader5 as sdk
        self.sdk = sdk
        connected = sdk.initialize(terminal_path) if terminal_path else sdk.initialize()
        if not connected:
            raise RuntimeError(f"MT5 initialization failed: {sdk.last_error()}")
        info = sdk.account_info()
        if info is None or info.server != expected_server or info.login != expected_login:
            sdk.shutdown()
            raise ValueError(
                "Connected MT5 account/server does not match the explicitly selected server"
            )
        self.server = info.server
        self.login = info.login
        self.account_ref = hashlib.sha256(f"{info.server}:{info.login}".encode()).hexdigest()[:16]
        self.feed_id = f"mt5:{self.server}:{self.account_ref}"

    def _account(self):
        info = self.sdk.account_info()
        if info is None or info.server != self.server or info.login != self.login:
            raise RuntimeError("MT5 disconnected or account identity changed; recording stopped")
        return info

    def close(self):
        self.sdk.shutdown()

    def get_instrument_metadata(self, symbol):
        self._account()
        info = self.sdk.symbol_info(symbol)
        if info is None or not self.sdk.symbol_select(symbol, True):
            raise ValueError(f"Symbol is not available on this server: {symbol}")
        return Instrument(
            symbol=symbol,
            feed_id=self.feed_id,
            provider="mt5",
            server=self.server,
            account_ref=self.account_ref,
            base_currency=info.currency_base,
            quote_currency=info.currency_profit,
            contract_size=info.trade_contract_size,
            price_increment=info.trade_tick_size or info.point,
            min_units=info.volume_min * info.trade_contract_size,
            step_units=info.volume_step * info.trade_contract_size,
            max_units=info.volume_max * info.trade_contract_size,
            pip_size=info.point * (10 if info.digits in (3, 5) else 1),
        )

    def get_quote(self, symbol, as_of):
        ticks = self.get_ticks(symbol, as_of - timedelta(minutes=1), as_of)
        return ticks[-1] if ticks else None

    def get_ticks(self, symbol, start, end):
        self._account()
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("MT5 requests require timezone-aware instants")
        ticks = self.sdk.copy_ticks_range(
            symbol,
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
            self.sdk.COPY_TICKS_INFO,
        )
        if ticks is None:
            raise RuntimeError(f"MT5 tick history failed: {self.sdk.last_error()}")
        return [
            Quote(
                symbol=symbol,
                feed_id=self.feed_id,
                timestamp=datetime.fromtimestamp(int(row["time_msc"]) / 1000, timezone.utc),
                bid=float(row["bid"]),
                ask=float(row["ask"]),
                flags=int(row["flags"]),
            )
            for row in ticks
            if row["bid"] > 0
            and row["ask"] > 0
            and start.timestamp() * 1000 <= row["time_msc"] <= end.timestamp() * 1000
        ]

    def get_bars(self, symbol, timeframe, start, end):
        self._account()
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("MT5 requests require timezone-aware instants")
        if timeframe != "M15":
            raise ValueError(
                "Import authoritative M15 broker bars; build UTC H4/D1 in the context layer"
            )
        rates = self.sdk.copy_rates_range(
            symbol,
            self.sdk.TIMEFRAME_M15,
            start.astimezone(timezone.utc),
            end.astimezone(timezone.utc),
        )
        if rates is None:
            raise RuntimeError(f"MT5 bar history failed: {self.sdk.last_error()}")
        return [
            Bar(
                symbol=symbol,
                feed_id=self.feed_id,
                open_time=datetime.fromtimestamp(int(r["time"]), timezone.utc),
                close_time=datetime.fromtimestamp(int(r["time"]) + 900, timezone.utc),
                timeframe="M15",
                basis="bid",
                complete=True,
                open=r["open"],
                high=r["high"],
                low=r["low"],
                close=r["close"],
                volume=float(r["tick_volume"]),
            )
            for r in rates
            if r["time"] + 900 <= end.timestamp()
        ]

    def subscribe_quotes(self, symbol):
        cursor = datetime.now(timezone.utc)
        seen = set()
        while True:
            now = datetime.now(timezone.utc)
            quotes = self.get_ticks(symbol, cursor - timedelta(seconds=1), now)
            current = set()
            for q in quotes:
                key = (q.timestamp, q.bid, q.ask, q.flags)
                current.add(key)
                if key not in seen:
                    yield q.model_copy(update={"received_at": datetime.now(timezone.utc)})
            seen = current
            cursor = now
            time.sleep(0.25)

    def subscribe_bars(self, symbol, timeframe):
        if timeframe != "M15":
            raise ValueError("Subscribe to M15; derive complete UTC H4/D1 locally")
        last = datetime.now(timezone.utc)
        while True:
            now = datetime.now(timezone.utc)
            for bar in self.get_bars(symbol, timeframe, last - timedelta(minutes=15), now):
                if bar.close_time > last:
                    yield bar.model_copy(update={"received_at": datetime.now(timezone.utc)})
                    last = bar.close_time
            time.sleep(1)

    def get_account_snapshot(self, initial_balance):
        now = datetime.now(timezone.utc)
        info = self._account()
        day = now.astimezone(ZoneInfo("Europe/Prague")).date()
        midnight = datetime.combine(day, datetime.min.time(), tzinfo=ZoneInfo("Europe/Prague"))
        deals = self.sdk.history_deals_get(midnight.astimezone(timezone.utc), now)
        positions = self.sdk.positions_get()
        pending = self.sdk.orders_get()
        if deals is None or positions is None or pending is None:
            raise RuntimeError(
                "MT5 deal/position history unavailable; daily baseline cannot be established"
            )
        rows = []
        for p in positions:
            instrument = self.get_instrument_metadata(p.symbol)
            rows.append(
                Position(
                    symbol=p.symbol,
                    side="LONG" if p.type == self.sdk.POSITION_TYPE_BUY else "SHORT",
                    units=p.volume * instrument.contract_size,
                    entry=p.price_open,
                    stop_loss=p.sl or None,
                    unrealized_pnl=p.profit,
                )
            )
        day_cashflows = sum(d.profit + d.commission + d.swap + getattr(d, "fee", 0) for d in deals)
        after = self._account()
        if after.balance != info.balance or after.equity != info.equity:
            raise RuntimeError("Account changed during sampling; retry a coherent account snapshot")
        return AccountSnapshot(
            timestamp=datetime.now(timezone.utc),
            feed_id=self.feed_id,
            currency=info.currency,
            initial_balance=initial_balance,
            balance=info.balance,
            equity=info.equity,
            day_start_balance=info.balance - day_cashflows,
            day=day,
            positions=tuple(rows),
            pending_orders=len(pending),
            origin="mt5",
        )
