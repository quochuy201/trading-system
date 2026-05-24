"""SQLite database initialization and schema."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_plans (
    plan_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    strategy TEXT,
    sop_version TEXT,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    entry_order_type TEXT,
    entry_limit_price REAL,
    take_profit REAL,
    stop_loss REAL,
    trailing_stop REAL,
    time_stop TEXT,
    risk_assessment TEXT,
    rationale TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trade_transactions (
    transaction_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    broker_order_id TEXT,
    status TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES trade_plans(plan_id)
);

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_value REAL,
    cash REAL,
    daily_pnl REAL,
    total_pnl REAL,
    positions TEXT
);

CREATE TABLE IF NOT EXISTS performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period TEXT,
    strategy TEXT,
    sop_version TEXT,
    start_date TEXT,
    end_date TEXT,
    total_trades INTEGER,
    win_rate REAL,
    avg_return REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    profit_factor REAL
);

CREATE TABLE IF NOT EXISTS sop_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    version TEXT NOT NULL,
    content_hash TEXT,
    file_path TEXT,
    created_at TEXT NOT NULL,
    change_reason TEXT,
    performance_summary TEXT
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    workflow_run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    sop_name TEXT,
    sop_version TEXT,
    checkpoint_data TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    strategy TEXT,
    sop_version TEXT,
    entry_transactions TEXT,
    exit_transactions TEXT,
    pnl REAL,
    pnl_pct REAL,
    rationale TEXT,
    exit_reason TEXT,
    lessons TEXT,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (plan_id) REFERENCES trade_plans(plan_id)
);

CREATE TABLE IF NOT EXISTS price_data (
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume INTEGER,
    timeframe TEXT NOT NULL,
    PRIMARY KEY (symbol, timestamp, timeframe)
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rules_triggered TEXT,
    rules_considered TEXT,
    reasoning TEXT,
    sop_version TEXT,
    plan_id TEXT,
    market_context TEXT,
    violations TEXT
);

CREATE TABLE IF NOT EXISTS transaction_ledger (
    ledger_id TEXT PRIMARY KEY,
    timestamp TEXT NOT NULL,
    action TEXT NOT NULL,
    symbol TEXT NOT NULL,
    quantity INTEGER,
    order_type TEXT,
    price REAL,
    total_cost REAL,
    fees REAL DEFAULT 0,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    account_equity REAL,
    account_cash REAL,
    buying_power REAL,
    pnl REAL,
    pnl_pct REAL,
    entry_price REAL,
    plan_id TEXT,
    decision_id TEXT,
    sop_version TEXT,
    platform TEXT NOT NULL,
    trigger TEXT DEFAULT 'agent',
    notes TEXT
);

CREATE TABLE IF NOT EXISTS performance_reports (
    report_id TEXT PRIMARY KEY,
    report_type TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    sop_version TEXT,
    metrics TEXT NOT NULL,
    generated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    symbols TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_equity REAL,
    total_pnl REAL,
    total_pnl_pct REAL,
    total_trades INTEGER,
    win_rate REAL,
    expectancy REAL,
    max_drawdown REAL,
    sop_version TEXT,
    skill_versions TEXT,
    config_snapshot TEXT,
    status TEXT DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS backtest_decisions (
    decision_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    bar_index INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    symbol TEXT NOT NULL,
    phase TEXT NOT NULL,
    input_state TEXT NOT NULL,
    tools_called TEXT NOT NULL,
    rules_evaluated TEXT,
    score REAL,
    decision TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    trade_plan TEXT,
    workflow_valid INTEGER NOT NULL,
    violation_details TEXT,
    outcome_pnl REAL,
    outcome_pnl_pct REAL,
    outcome_r_multiple REAL,
    outcome_exit_bar INTEGER,
    outcome_exit_price REAL,
    outcome_exit_reason TEXT,
    outcome_label TEXT,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE TABLE IF NOT EXISTS backtest_trades (
    trade_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_bar INTEGER NOT NULL,
    entry_timestamp TEXT NOT NULL,
    entry_price REAL NOT NULL,
    entry_quantity INTEGER NOT NULL,
    entry_decision_id TEXT NOT NULL,
    exit_bar INTEGER,
    exit_timestamp TEXT,
    exit_price REAL,
    exit_reason TEXT,
    exit_decision_id TEXT,
    pnl REAL,
    pnl_pct REAL,
    r_multiple REAL,
    hold_bars INTEGER,
    max_favorable_excursion REAL,
    max_adverse_excursion REAL,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);
"""

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "trading.db"


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection. Uses :memory: if path is ':memory:'."""
    path = str(db_path) if db_path else str(_DEFAULT_DB_PATH)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()
