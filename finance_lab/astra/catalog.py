"""SQLite event catalog: immutable observations and idempotent shadow decisions."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import timezone
from pathlib import Path

from .models import AccountSnapshot, Bar, Evidence, Instrument, Quote


def canonical(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def instant(value):
    if value.tzinfo is None:
        raise ValueError("An aware UTC instant is required")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


class Catalog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL,
                    kind TEXT NOT NULL, feed_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    event_at TEXT NOT NULL, available_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS observation_time
                    ON observations(kind, feed_id, symbol, event_at, available_at);
                CREATE TABLE IF NOT EXISTS instruments (
                    fingerprint TEXT PRIMARY KEY, feed_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS decisions (
                    event_key TEXT PRIMARY KEY, status TEXT NOT NULL,
                    timestamp TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS breaches (
                    feed_id TEXT PRIMARY KEY, observed_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS execution_reviews (
                    decision_key TEXT PRIMARY KEY, payload TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def instrument(self, instrument: Instrument):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO instruments VALUES (?, ?, ?, ?)",
                (digest(instrument), instrument.feed_id, instrument.symbol, canonical(instrument)),
            )

    def get_instrument(self, feed_id, symbol):
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM instruments WHERE feed_id=? AND symbol=?", (feed_id, symbol)
            ).fetchall()
        if len(rows) != 1:
            raise ValueError(
                "Select a catalog with exactly one instrument specification version per feed/symbol"
            )
        return Instrument.model_validate_json(rows[0][0])

    def append(self, record):
        kinds = {Quote: "quote", Bar: "bar", AccountSnapshot: "account", Evidence: "evidence"}
        kind = kinds[type(record)]
        if isinstance(record, Bar):
            event_at = record.close_time
        elif isinstance(record, Evidence):
            event_at = record.published_at
        else:
            event_at = record.timestamp
        available = max(event_at, getattr(record, "received_at", None) or event_at)
        identity = record.model_dump(mode="json", exclude={"received_at"})
        with self.connect() as db:
            if isinstance(record, AccountSnapshot):
                breached = record.breached or record.equity <= record.initial_balance * 0.90
                if record.day_start_balance is not None:
                    breached |= (
                        record.equity <= record.day_start_balance - record.initial_balance * 0.05
                    )
                if breached:
                    db.execute(
                        "INSERT INTO breaches VALUES (?, ?) ON CONFLICT(feed_id) DO UPDATE SET observed_at=MIN(observed_at,excluded.observed_at)",
                        (record.feed_id, instant(event_at)),
                    )
                if db.execute(
                    "SELECT 1 FROM breaches WHERE feed_id=? AND observed_at<=?",
                    (record.feed_id, instant(event_at)),
                ).fetchone():
                    record = record.model_copy(update={"breached": True})
                    identity = record.model_dump(mode="json")
            cursor = db.execute(
                "INSERT OR IGNORE INTO observations (fingerprint,kind,feed_id,symbol,event_at,available_at,payload) VALUES (?,?,?,?,?,?,?)",
                (
                    digest(identity),
                    kind,
                    getattr(record, "feed_id", "evidence"),
                    getattr(record, "symbol", ""),
                    instant(event_at),
                    instant(available),
                    canonical(record),
                ),
            )
            return cursor.rowcount == 1

    def records(self, kind, feed_id, symbol, as_of, *, start=None):
        models = {"quote": Quote, "bar": Bar, "account": AccountSnapshot, "evidence": Evidence}
        with self.connect() as db:
            rows = db.execute(
                """SELECT payload FROM observations
                WHERE kind=? AND feed_id=? AND symbol=? AND event_at<=? AND available_at<=?
                AND event_at>=? ORDER BY event_at, id""",
                (
                    kind,
                    feed_id,
                    symbol,
                    instant(as_of),
                    instant(as_of),
                    instant(start) if start else "",
                ),
            ).fetchall()
            breach = (
                db.execute(
                    "SELECT 1 FROM breaches WHERE feed_id=? AND observed_at<=?",
                    (feed_id, instant(as_of)),
                ).fetchone()
                if kind == "account"
                else None
            )
        records = [models[kind].model_validate_json(row[0]) for row in rows]
        if breach:
            records = [record.model_copy(update={"breached": True}) for record in records]
        return records

    def claim(self, event_key, timestamp, snapshot):
        with self.connect() as db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO decisions VALUES (?, 'running', ?, ?)",
                (event_key, instant(timestamp), canonical(snapshot)),
            )
            return cursor.rowcount == 1

    def complete(self, event_key, result, *, status="complete"):
        with self.connect() as db:
            db.execute(
                "UPDATE decisions SET status=?, payload=? WHERE event_key=? AND status='running'",
                (status, canonical(result), event_key),
            )

    def decisions(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT event_key,status,timestamp,payload FROM decisions ORDER BY timestamp"
            ).fetchall()
        return [
            {"event_key": k, "status": s, "timestamp": t, "data": json.loads(p)}
            for k, s, t, p in rows
        ]

    def save_execution_review(self, decision_key, result):
        with self.connect() as db:
            db.execute(
                "INSERT INTO execution_reviews VALUES (?, ?) "
                "ON CONFLICT(decision_key) DO UPDATE SET payload=excluded.payload",
                (decision_key, canonical(result)),
            )

    def execution_review(self, decision_key):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM execution_reviews WHERE decision_key=?", (decision_key,)
            ).fetchone()
        return json.loads(row[0]) if row else None
