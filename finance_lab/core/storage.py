"""SQLite memory store for finance-lab decisions and backtest results."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .responses import fail, ok

PriceLookup = Callable[[str, str, int], tuple[float, float]]


class FinanceMemoryStore:
    """Small SQLite repository for paper/research decisions.

    The store deliberately has no broker/order execution concepts.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "storage" / "schema.sql"
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))

    def save_strategy(
        self,
        strategy_name: str,
        *,
        symbol: str | None = None,
        description: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not strategy_name.strip():
            return fail("strategy_name is required", code="VALIDATION_ERROR")
        clean_strategy_name = strategy_name.strip()
        clean_symbol = _clean_symbol(symbol)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strategies (strategy_name, symbol, description, parameters_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_name, symbol) DO UPDATE SET
                    description = excluded.description,
                    parameters_json = excluded.parameters_json
                """,
                (
                    clean_strategy_name,
                    clean_symbol,
                    description,
                    _json(parameters or {}),
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM strategies
                WHERE strategy_name = ? AND symbol = ?
                """,
                (clean_strategy_name, clean_symbol),
            ).fetchone()
            strategy_id = int(row["id"])
        return ok({"strategy_id": int(strategy_id)})

    def save_trade_decision(
        self,
        symbol: str,
        decision: str,
        confidence: float,
        thesis: str,
        strategy_name: str | None = None,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision_value = decision.strip().upper()
        if decision_value not in {"BUY", "HOLD", "SELL"}:
            return fail("decision must be BUY, HOLD, or SELL", code="VALIDATION_ERROR")
        if not 0 <= confidence <= 1:
            return fail("confidence must be between 0 and 1", code="VALIDATION_ERROR")
        if not symbol.strip():
            return fail("symbol is required", code="VALIDATION_ERROR")

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO trade_decisions
                    (symbol, decision, confidence, thesis, strategy_name, created_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol.strip().upper(),
                    decision_value,
                    float(confidence),
                    thesis,
                    strategy_name,
                    _now(),
                    _json(metadata or {}),
                ),
            )
            decision_id = int(cursor.lastrowid)
        return ok({"decision_id": decision_id})

    def save_trade_result(
        self,
        decision_id: int,
        horizon_days: int,
        entry_price: float,
        exit_price: float,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision_row = self._get_decision_row(decision_id)
        if decision_row is None:
            return fail("decision_id not found", code="NOT_FOUND")
        if horizon_days <= 0:
            return fail("horizon_days must be positive", code="VALIDATION_ERROR")
        if entry_price <= 0 or exit_price <= 0:
            return fail("entry_price and exit_price must be positive", code="VALIDATION_ERROR")

        raw_return = exit_price / entry_price - 1
        decision_return = _decision_return(decision_row["decision"], raw_return)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trade_results
                    (
                        decision_id,
                        horizon_days,
                        entry_price,
                        exit_price,
                        raw_return,
                        decision_return,
                        evaluated_at,
                        metadata_json
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(decision_id, horizon_days) DO UPDATE SET
                    entry_price = excluded.entry_price,
                    exit_price = excluded.exit_price,
                    raw_return = excluded.raw_return,
                    decision_return = excluded.decision_return,
                    evaluated_at = excluded.evaluated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    int(decision_id),
                    int(horizon_days),
                    float(entry_price),
                    float(exit_price),
                    float(raw_return),
                    float(decision_return),
                    _now(),
                    _json(metadata or {}),
                ),
            )
            conn.execute(
                "UPDATE trade_decisions SET status = 'evaluated' WHERE id = ?",
                (int(decision_id),),
            )
        return ok(
            {
                "decision_id": int(decision_id),
                "horizon_days": int(horizon_days),
                "entry_price": float(entry_price),
                "exit_price": float(exit_price),
                "raw_return": float(raw_return),
                "decision_return": float(decision_return),
            }
        )

    def save_decision_replay_result(
        self,
        decision_id: int,
        replay_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist decision-replay horizons and outcome lessons for a decision."""
        decision_row = self._get_decision_row(decision_id)
        if decision_row is None:
            return fail("decision_id not found", code="NOT_FOUND")

        data = _replay_data(replay_result)
        if data.get("mode") != "decision_replay":
            return fail("replay_result must be decision_replay data", code="VALIDATION_ERROR")

        horizons = data.get("horizons") or []
        status = str(data.get("status") or ("evaluated" if horizons else "pending"))
        metadata = _load_json(decision_row["metadata_json"])
        metadata["decision_replay"] = {
            "status": status,
            "symbol": data.get("symbol"),
            "action": data.get("action"),
            "rating": data.get("rating"),
            "entry_date": data.get("entry_date"),
            "entry_price": data.get("entry_price"),
            "benchmark_symbol": data.get("benchmark_symbol"),
            "pending_horizons": data.get("pending_horizons", []),
            "summary": data.get("summary", {}),
            "learning": data.get("learning", {}),
            "trade_style_fit": data.get("trade_style_fit", {}),
            "paper_trade_gate": data.get("paper_trade_gate", {}),
        }

        with self._connect() as conn:
            for row in horizons:
                conn.execute(
                    """
                    INSERT INTO decision_replay_results
                        (
                            decision_id,
                            horizon_days,
                            entry_date,
                            exit_date,
                            entry_price,
                            exit_price,
                            decision_return,
                            buy_hold_return,
                            benchmark_return,
                            alpha_vs_buy_hold,
                            alpha_vs_benchmark,
                            asset_max_drawdown,
                            stop_loss,
                            stop_hit,
                            stop_date,
                            evaluated_at,
                            metadata_json
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(decision_id, horizon_days) DO UPDATE SET
                        entry_date = excluded.entry_date,
                        exit_date = excluded.exit_date,
                        entry_price = excluded.entry_price,
                        exit_price = excluded.exit_price,
                        decision_return = excluded.decision_return,
                        buy_hold_return = excluded.buy_hold_return,
                        benchmark_return = excluded.benchmark_return,
                        alpha_vs_buy_hold = excluded.alpha_vs_buy_hold,
                        alpha_vs_benchmark = excluded.alpha_vs_benchmark,
                        asset_max_drawdown = excluded.asset_max_drawdown,
                        stop_loss = excluded.stop_loss,
                        stop_hit = excluded.stop_hit,
                        stop_date = excluded.stop_date,
                        evaluated_at = excluded.evaluated_at,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        int(decision_id),
                        int(row["horizon_days"]),
                        str(row["entry_date"]),
                        str(row["exit_date"]),
                        float(row["entry_price"]),
                        float(row["exit_price"]),
                        float(row["decision_return"]),
                        float(row["buy_hold_return"]),
                        _optional_float(row.get("benchmark_return")),
                        float(row["alpha_vs_buy_hold"]),
                        _optional_float(row.get("alpha_vs_benchmark")),
                        float(row["asset_max_drawdown"]),
                        _optional_float(row.get("stop_loss")),
                        1 if row.get("stop_hit") else 0,
                        row.get("stop_date"),
                        _now(),
                        _json(row.get("metadata") or {}),
                    ),
                )
            conn.execute(
                """
                UPDATE trade_decisions
                SET status = ?, metadata_json = ?
                WHERE id = ?
                """,
                (status, _json(metadata), int(decision_id)),
            )

        return ok(
            {
                "decision_id": int(decision_id),
                "status": status,
                "saved_horizons": len(horizons),
                "learning": data.get("learning", {}),
                "paper_trade_gate": data.get("paper_trade_gate", {}),
            }
        )

    def evaluate_trade_result(
        self,
        decision_id: int,
        horizon_days: int,
        *,
        price_lookup: PriceLookup | None = None,
    ) -> dict[str, Any]:
        decision_row = self._get_decision_row(decision_id)
        if decision_row is None:
            return fail("decision_id not found", code="NOT_FOUND")
        lookup = price_lookup or _default_price_lookup
        try:
            entry_price, exit_price = lookup(
                decision_row["symbol"],
                decision_row["created_at"][:10],
                horizon_days,
            )
        except Exception as exc:  # noqa: BLE001
            return fail(str(exc), code="EVALUATION_ERROR")
        return self.save_trade_result(
            decision_id,
            horizon_days,
            entry_price,
            exit_price,
            metadata={"price_lookup": getattr(lookup, "__name__", "custom")},
        )

    def save_backtest(
        self,
        symbol: str,
        strategy_name: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO backtests (symbol, strategy_name, created_at, result_json)
                VALUES (?, ?, ?, ?)
                """,
                (symbol.strip().upper(), strategy_name, _now(), _json(result)),
            )
            backtest_id = int(cursor.lastrowid)
        return ok({"backtest_id": backtest_id})

    def get_strategy_memory(
        self,
        *,
        symbol: str | None = None,
        strategy_name: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        clauses = []
        params: list[Any] = []
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol.strip().upper())
        if strategy_name:
            clauses.append("strategy_name = ?")
            params.append(strategy_name)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))

        with self._connect() as conn:
            decisions = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT *
                    FROM trade_decisions
                    {where}
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
            ]
            decision_ids = [row["id"] for row in decisions]
            results_by_decision = self._results_for_decisions(conn, decision_ids)
            replay_by_decision = self._replay_results_for_decisions(conn, decision_ids)

        for decision_row in decisions:
            decision_row["metadata"] = _load_json(decision_row.pop("metadata_json"))
            decision_row["results"] = results_by_decision.get(decision_row["id"], [])
            decision_row["replay_results"] = replay_by_decision.get(decision_row["id"], [])
        return ok({"decisions": decisions})

    def get_learning_context(
        self,
        *,
        symbol: str | None = None,
        strategy_name: str | None = None,
        as_of_date: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Return compact replay-outcome lessons for prompt injection."""
        memory = self.get_strategy_memory(
            symbol=symbol,
            strategy_name=strategy_name,
            limit=max(int(limit) * 10, int(limit)),
        )
        if not memory.get("ok"):
            return memory

        lines = []
        for decision in memory["data"]["decisions"]:
            if not _decision_replay_known_by_as_of(decision, as_of_date):
                continue
            line = _learning_context_line(decision)
            if line:
                lines.append(line)
            if len(lines) >= int(limit):
                break

        context = ""
        if lines:
            context = "Finance Lab replay outcome lessons:\n" + "\n".join(lines)
        return ok({"context": context, "lesson_count": len(lines)})

    def _results_for_decisions(
        self,
        conn: sqlite3.Connection,
        decision_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not decision_ids:
            return {}
        placeholders = ",".join("?" for _ in decision_ids)
        rows = conn.execute(
            f"""
            SELECT *
            FROM trade_results
            WHERE decision_id IN ({placeholders})
            ORDER BY horizon_days
            """,
            decision_ids,
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            item["metadata"] = _load_json(item.pop("metadata_json"))
            grouped.setdefault(item["decision_id"], []).append(item)
        return grouped

    def _replay_results_for_decisions(
        self,
        conn: sqlite3.Connection,
        decision_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not decision_ids:
            return {}
        placeholders = ",".join("?" for _ in decision_ids)
        rows = conn.execute(
            f"""
            SELECT *
            FROM decision_replay_results
            WHERE decision_id IN ({placeholders})
            ORDER BY horizon_days
            """,
            decision_ids,
        ).fetchall()
        grouped: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            item = dict(row)
            item["stop_hit"] = bool(item["stop_hit"])
            item["metadata"] = _load_json(item.pop("metadata_json"))
            grouped.setdefault(item["decision_id"], []).append(item)
        return grouped

    def _get_decision_row(self, decision_id: int) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM trade_decisions WHERE id = ?",
                (int(decision_id),),
            ).fetchone()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _default_price_lookup(symbol: str, analysis_date: str, horizon_days: int) -> tuple[float, float]:
    from datetime import date, timedelta

    from .market_data import fetch_ohlcv_frame

    start = date.fromisoformat(analysis_date)
    end = start + timedelta(days=horizon_days + 10)
    frame = fetch_ohlcv_frame(symbol, start=start.isoformat(), end=end.isoformat())
    closes = frame["close"].dropna()
    if len(closes) < 2:
        raise ValueError("not enough close prices to evaluate result")
    exit_index = min(horizon_days, len(closes) - 1)
    return float(closes.iloc[0]), float(closes.iloc[exit_index])


def _decision_return(decision: str, raw_return: float) -> float:
    if decision == "BUY":
        return raw_return
    if decision == "SELL":
        return -raw_return
    return -abs(raw_return)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True)


def _load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    return json.loads(value)


def _replay_data(replay_result: dict[str, Any]) -> dict[str, Any]:
    if replay_result.get("ok") is True and isinstance(replay_result.get("data"), dict):
        return replay_result["data"]
    return replay_result


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _learning_context_line(decision: dict[str, Any]) -> str:
    metadata = decision.get("metadata") or {}
    replay = metadata.get("decision_replay") or {}
    learning = replay.get("learning") or {}
    if not learning:
        return ""

    trade_date = metadata.get("trade_date") or str(decision.get("created_at", ""))[:10]
    rating = replay.get("rating") or metadata.get("portfolio_rating") or decision.get("decision")
    summary = replay.get("summary") or {}
    avg_return = _format_pct(summary.get("average_decision_return"))
    avg_alpha = _format_pct(summary.get("average_alpha_vs_benchmark"))
    max_drawdown = _format_pct(summary.get("worst_asset_max_drawdown"))
    verdict = learning.get("verdict") or "No replay verdict."
    lessons = learning.get("lessons") or []
    lesson = str(lessons[0]) if lessons else str(learning.get("next_prompt") or "")
    return (
        f"- [{trade_date} | {decision.get('symbol')} | {rating}/{decision.get('decision')}] "
        f"avg_return={avg_return}, avg_alpha_vs_benchmark={avg_alpha}, "
        f"worst_drawdown={max_drawdown}. Verdict: {verdict} Lesson: {lesson}"
    )


def _decision_replay_known_by_as_of(decision: dict[str, Any], as_of_date: str | None) -> bool:
    if not as_of_date:
        return True
    as_of = _parse_date(as_of_date)
    if as_of is None:
        return True
    replay_results = decision.get("replay_results") or []
    if not replay_results:
        return False
    known_exit_dates = [
        parsed
        for parsed in (_parse_date(row.get("exit_date")) for row in replay_results)
        if parsed is not None
    ]
    return bool(known_exit_dates) and max(known_exit_dates) <= as_of


def _parse_date(value: Any):
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def _format_pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.2%}"


def _clean_symbol(symbol: str | None) -> str:
    if symbol is None or not symbol.strip():
        return ""
    return symbol.strip().upper()
