PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_name TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    parameters_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(strategy_name, symbol)
);

CREATE TABLE IF NOT EXISTS trade_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('BUY', 'HOLD', 'SELL')),
    confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    thesis TEXT NOT NULL DEFAULT '',
    strategy_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol
    ON trade_decisions(symbol, created_at);

CREATE INDEX IF NOT EXISTS idx_trade_decisions_strategy
    ON trade_decisions(strategy_name, created_at);

CREATE TABLE IF NOT EXISTS trade_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES trade_decisions(id) ON DELETE CASCADE,
    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    exit_price REAL NOT NULL CHECK (exit_price > 0),
    raw_return REAL NOT NULL,
    decision_return REAL NOT NULL,
    evaluated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(decision_id, horizon_days)
);

CREATE TABLE IF NOT EXISTS decision_replay_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL REFERENCES trade_decisions(id) ON DELETE CASCADE,
    horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
    entry_date TEXT NOT NULL,
    exit_date TEXT NOT NULL,
    entry_price REAL NOT NULL CHECK (entry_price > 0),
    exit_price REAL NOT NULL CHECK (exit_price > 0),
    decision_return REAL NOT NULL,
    buy_hold_return REAL NOT NULL,
    benchmark_return REAL,
    alpha_vs_buy_hold REAL NOT NULL,
    alpha_vs_benchmark REAL,
    asset_max_drawdown REAL NOT NULL,
    stop_loss REAL,
    stop_hit INTEGER NOT NULL DEFAULT 0,
    stop_date TEXT,
    evaluated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(decision_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_decision_replay_results_decision
    ON decision_replay_results(decision_id, horizon_days);

CREATE TABLE IF NOT EXISTS fake_traders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fake_trader_id TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    profile_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    result_json TEXT NOT NULL
);
