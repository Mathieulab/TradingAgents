"""Track trade decisions and evaluate their outcomes against real price data.

Each time the CLI completes an analysis, the decision (BUY/SELL/HOLD) is
saved as a *pending outcome*.  On the next run, pending outcomes that are at
least one trading day old are evaluated:
  - BUY  → correct if the next-day close is higher than the entry close
  - SELL → correct if the next-day close is lower
  - HOLD → correct if |change| < 1 %

Evaluated outcomes are written back to the ``trader_memory`` (or any
``FinancialSituationMemory`` instance you supply) so agents automatically
see their historical success rate and learn from past mistakes.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf


class OutcomeTracker:
    """Records pending trade decisions and evaluates outcomes when data is available."""

    PENDING_FILENAME = "pending_outcome.json"

    def __init__(self, results_dir: str = "results"):
        self.results_dir = Path(results_dir)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_pending(
        self,
        ticker: str,
        date: str,
        action: str,
        situation_summary: str,
        price_at_decision: Optional[float] = None,
    ) -> Path:
        """Save a trade decision so its outcome can be evaluated later.

        Args:
            ticker: Stock ticker symbol (e.g. "SPY").
            date: Analysis date in ``YYYY-MM-DD`` format.
            action: One of ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
            situation_summary: Short text summarising the final analysis
                (used to feed the outcome back into agent memory).
            price_at_decision: Closing price on *date*.  Fetched via
                yfinance if not provided.

        Returns:
            Path to the written JSON file.
        """
        decision_dir = self.results_dir / ticker / date
        decision_dir.mkdir(parents=True, exist_ok=True)
        pending_path = decision_dir / self.PENDING_FILENAME

        if price_at_decision is None:
            price_at_decision = self._fetch_price(ticker, date)

        payload = {
            "ticker": ticker,
            "decision_date": date,
            "action": self._normalize_action(action),
            "price_at_decision": price_at_decision,
            "situation_summary": situation_summary,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "evaluated": False,
        }

        with open(pending_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        return pending_path

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def get_pending_outcomes(self) -> list:
        """Return all unevaluated pending outcome records (as dicts)."""
        pending = []
        if not self.results_dir.exists():
            return pending

        for pending_file in self.results_dir.rglob(self.PENDING_FILENAME):
            try:
                with open(pending_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not data.get("evaluated", False):
                    data["_path"] = str(pending_file)
                    pending.append(data)
            except (OSError, json.JSONDecodeError):
                continue

        return pending

    def evaluate_pending(self, memory_instance=None) -> list:
        """Evaluate all pending outcomes that are at least one day old.

        For each outcome:
        - Fetches the next trading-day close price via yfinance.
        - Determines whether the decision was correct.
        - Optionally writes the result into *memory_instance* so that
          agents can refer to historical correctness in their prompts.
        - Marks the on-disk record as evaluated.

        Args:
            memory_instance: A ``FinancialSituationMemory`` instance to
                update with outcome metadata (optional).

        Returns:
            List of evaluation result dicts.
        """
        results = []

        for record in self.get_pending_outcomes():
            ticker = record["ticker"]
            decision_date = record["decision_date"]
            action = record["action"]
            price_at_decision = record.get("price_at_decision")

            try:
                decision_dt = datetime.strptime(decision_date, "%Y-%m-%d")
            except ValueError:
                continue

            # Only evaluate if at least 1 calendar day has passed.
            if (datetime.now() - decision_dt).days < 1:
                continue

            next_price = self._fetch_next_day_price(ticker, decision_dt)
            if next_price is None or price_at_decision is None:
                continue

            price_change_pct = round(
                (next_price - price_at_decision) / price_at_decision * 100, 2
            )

            if action == "BUY":
                was_correct = next_price > price_at_decision
            elif action == "SELL":
                was_correct = next_price < price_at_decision
            else:  # HOLD
                was_correct = abs(price_change_pct) < 1.0

            evaluation = {
                "ticker": ticker,
                "decision_date": decision_date,
                "action": action,
                "price_at_decision": price_at_decision,
                "next_day_price": next_price,
                "price_change_pct": price_change_pct,
                "was_correct": was_correct,
            }

            # Feed the outcome back into agent memory.
            if memory_instance and record.get("situation_summary"):
                recommendation = f"{action} {ticker} on {decision_date}"
                memory_instance.add_situations(
                    [(record["situation_summary"], recommendation)],
                    metadata_list=[
                        {
                            "ticker": ticker,
                            "trade_date": decision_date,
                            "action": action,
                            "returns_losses": price_change_pct,
                            "was_correct": was_correct,
                        }
                    ],
                )

            # Mark the record as evaluated on disk.
            record_path = Path(record["_path"])
            try:
                with open(record_path, "r", encoding="utf-8") as fh:
                    full_record = json.load(fh)
                full_record.update(
                    {
                        "evaluated": True,
                        "next_day_price": next_price,
                        "price_change_pct": price_change_pct,
                        "was_correct": was_correct,
                        "evaluated_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                with open(record_path, "w", encoding="utf-8") as fh:
                    json.dump(full_record, fh, indent=2)
            except (OSError, json.JSONDecodeError):
                pass

            results.append(evaluation)

        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_action(text: str) -> str:
        """Extract BUY / SELL / HOLD from potentially noisy LLM output."""
        upper = text.upper().strip()
        for action in ("BUY", "SELL", "HOLD"):
            if action in upper:
                return action
        return "HOLD"

    def _fetch_price(self, ticker: str, date: str) -> Optional[float]:
        """Fetch the closing price on or after *date*."""
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            end = (dt + timedelta(days=7)).strftime("%Y-%m-%d")
            data = yf.download(
                ticker, start=date, end=end, progress=False, auto_adjust=True
            )
            if data.empty:
                return None
            close = data["Close"]
            # Handle MultiIndex columns (multi-ticker download)
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            return float(close.iloc[0])
        except Exception:
            return None

    def _fetch_next_day_price(
        self, ticker: str, decision_dt: datetime
    ) -> Optional[float]:
        """Fetch the closing price for the first trading day after *decision_dt*."""
        try:
            start = (decision_dt + timedelta(days=1)).strftime("%Y-%m-%d")
            end = (decision_dt + timedelta(days=8)).strftime("%Y-%m-%d")
            data = yf.download(
                ticker, start=start, end=end, progress=False, auto_adjust=True
            )
            if data.empty:
                return None
            close = data["Close"]
            if hasattr(close, "columns"):
                close = close.iloc[:, 0]
            return float(close.iloc[0])
        except Exception:
            return None
