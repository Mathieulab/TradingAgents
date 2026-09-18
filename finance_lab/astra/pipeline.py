"""Join frozen research decisions to deterministic execution reviews, never orders."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import AccountSnapshot, GateResult, Instrument, SwingProposal


def review_execution(catalog, row, until, *, engines=None):
    """Evaluate a single bounded execution POC once enough actual quotes exist.

    Reviews are separate from the immutable decision and never fed back into its gate.
    An evaluated POC is frozen; it is not a live position or a swing outcome score.
    """
    previous = catalog.execution_review(row["event_key"])
    if previous and previous.get("status") == "evaluated":
        return previous
    data = row.get("data") or {}
    gate_data = data.get("gate") or {}
    result = {
        "status": "not_run",
        "reason": "No approved candidate; no execution to simulate",
        "engines": [],
        "order_sent": False,
        "scope": "Bounded execution POC only; not swing profitability or paper execution",
        "evaluated_at": until.isoformat(),
    }
    if row.get("status") == "complete" and gate_data.get("verdict") == "APPROVE":
        try:
            start = datetime.fromisoformat(data["gate_as_of"])
            if until.tzinfo is None or start.tzinfo is None or until < start:
                raise ValueError("Review requires aware timestamps after the frozen gate")
            instrument = Instrument.model_validate(data["snapshot"]["instrument"])
            account = AccountSnapshot.model_validate(data["gate_account"])
            midnight = datetime.combine(
                account.day + timedelta(days=1), time.min, tzinfo=ZoneInfo("Europe/Prague")
            )
            end = min(
                until,
                start + timedelta(hours=4),
                midnight.astimezone(timezone.utc) - timedelta(microseconds=1),
            )
            quotes = catalog.records(
                "quote", instrument.feed_id, instrument.symbol, end, start=start
            )
            result.update(
                window_start=start.isoformat(), window_end=end.isoformat(), quote_count=len(quotes)
            )
            if len(quotes) < 3:
                result.update(
                    status="pending" if until <= end else "blocked",
                    reason="Waiting for at least three recorded post-decision quotes"
                    if until <= end
                    else "Insufficient quote coverage within the bounded replay window",
                )
            else:
                if quotes[0].timestamp - start > timedelta(seconds=30) or any(
                    b.timestamp - a.timestamp > timedelta(seconds=30)
                    for a, b in zip(quotes, quotes[1:], strict=False)
                ):
                    raise ValueError(
                        "Post-decision recording has gaps over 30 seconds; execution path is unknown"
                    )
                if engines is None:
                    from .engines import BacktraderEngine, NautilusEngine

                    engines = (BacktraderEngine(), NautilusEngine())
                proposal = SwingProposal.model_validate(data["proposal"])
                gate = GateResult.model_validate(gate_data)
                results = [
                    engine.run(quotes, instrument, proposal, gate, account) for engine in engines
                ]
                result.update(
                    status="evaluated",
                    reason="Same frozen candidate and real quotes replayed",
                    engines=results,
                )
        except (KeyError, TypeError, ValueError) as exc:
            result.update(status="blocked", reason=str(exc))
        except (ImportError, RuntimeError) as exc:
            result.update(
                status="unavailable", reason=f"Execution engine unavailable: {type(exc).__name__}"
            )
    catalog.save_execution_review(row["event_key"], result)
    return result
