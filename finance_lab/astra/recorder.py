"""Read-only, bounded polling. Run separately from slow agent invocations."""

import time
from datetime import datetime, timedelta, timezone


def record_mt5(provider, catalog, symbol, initial_balance, seconds, *, history_days=180):
    if seconds <= 0 or not 0 <= history_days <= 365:
        raise ValueError("Recording duration must be positive and history_days between 0 and 365")
    instrument = provider.get_instrument_metadata(symbol)
    catalog.instrument(instrument)
    now = datetime.now(timezone.utc)
    count = {"quotes": 0, "bars": 0, "accounts": 0, "polls": 0}
    # Backfilled bars become available when received, not retroactively. Replay
    # imports without receipt timestamps must be separately labelled assumptions.
    if history_days:
        for bar in provider.get_bars(symbol, "M15", now - timedelta(days=history_days), now):
            count["bars"] += catalog.append(
                bar.model_copy(update={"received_at": datetime.now(timezone.utc)})
            )
    deadline = time.monotonic() + seconds
    cursor = now - timedelta(seconds=1)
    last_bars = now
    while time.monotonic() < deadline:
        end = datetime.now(timezone.utc)
        for quote in provider.get_ticks(symbol, cursor - timedelta(seconds=1), end):
            count["quotes"] += catalog.append(
                quote.model_copy(update={"received_at": datetime.now(timezone.utc)})
            )
        cursor = end
        if (end - last_bars).total_seconds() >= 15:
            for bar in provider.get_bars(symbol, "M15", last_bars - timedelta(minutes=15), end):
                count["bars"] += catalog.append(
                    bar.model_copy(update={"received_at": datetime.now(timezone.utc)})
                )
            last_bars = end
        count["accounts"] += catalog.append(provider.get_account_snapshot(initial_balance))
        count["polls"] += 1
        time.sleep(min(1, max(0, deadline - time.monotonic())))
    return {"feed_id": instrument.feed_id, **count, "order_sent": False}
