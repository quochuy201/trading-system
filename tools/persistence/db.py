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
    created_at TEXT NOT NULL,
    regime TEXT
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

CREATE TABLE IF NOT EXISTS iv_history (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    iv REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

-- orders = INTENT (what we asked for), fills = REALITY (what we got).
-- Kept apart so "what did we actually pay" is answerable. See
-- docs/product/features/go-live-metrics/go-live-metrics-design.md §3a/§3b.
CREATE TABLE IF NOT EXISTS orders (
    order_id         TEXT PRIMARY KEY,
    plan_id          TEXT,
    broker_order_id  TEXT UNIQUE,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    order_type       TEXT NOT NULL,
    qty_requested    INTEGER NOT NULL,
    intended_price   REAL,
    submitted_at     TEXT NOT NULL,
    terminal_status  TEXT,
    gate_verdict     TEXT,
    gate_rule_id     TEXT,
    regime_at_entry  TEXT,
    mode             TEXT NOT NULL
);

-- fill_id is the broker's activity id, so a replayed activity feed collides on
-- the primary key. Dedup is structural. INSERT only — never UPDATE, never
-- DELETE. qty is THIS execution, not cum_qty.
--
-- The column is broker_order_id, not order_id, because that is what it holds:
-- the id the BROKER put on the execution. It joins orders.broker_order_id, NOT
-- orders.order_id (which is ours). Naming it order_id is how "fills.order_id
-- joins orders.order_id" became a claim that matches zero rows.
CREATE TABLE IF NOT EXISTS fills (
    fill_id          TEXT PRIMARY KEY,
    broker_order_id  TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    side             TEXT NOT NULL,
    qty              INTEGER NOT NULL,
    price            REAL NOT NULL,
    fill_type        TEXT NOT NULL,
    filled_at        TEXT NOT NULL,
    mode             TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fills_broker_order ON fills(broker_order_id);

-- Where incremental syncs remember how far they got. One row per stream, e.g.
-- key='fills:FILL'. The cursor is the broker's own activity id, so rewinding it
-- re-imports through the same code path that does the daily sync.
CREATE TABLE IF NOT EXISTS sync_state (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_funnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    universe_size INTEGER,
    loaded INTEGER,
    scanned INTEGER,
    passed INTEGER,
    passed_m INTEGER,
    passed_r INTEGER,
    data_stale INTEGER,
    as_of TEXT,
    candidates TEXT
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


# Columns added to tables that already exist in deployed databases.
# `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so a new column
# never reaches it — these need a real ALTER. Guarded, so re-running is safe.
# (table, column, declaration)
_COLUMN_MIGRATIONS = [
    ("trade_plans", "regime", "TEXT"),
]


def _apply_column_migrations(conn: sqlite3.Connection) -> None:
    """Add any missing columns listed in _COLUMN_MIGRATIONS.

    Existing rows get NULL — the honest value for "we were not recording this
    when that row was written", never a backfilled guess.
    """
    for table, column, decl in _COLUMN_MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if existing and column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _rename_fills_order_column(conn: sqlite3.Connection) -> None:
    """Rename the legacy `fills.order_id` to `broker_order_id` (idempotent).

    The column always held the broker's order id; `order_id` invited the join
    against `orders.order_id` (ours), which matches zero rows. Renaming makes
    the join key self-describing.

    Refuses to touch a table that already holds rows — `fills` is append-only,
    and no migration of this feature's data should ever be silent. In practice
    the rename runs against an empty table.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(fills)")}
    if not cols or "order_id" not in cols or "broker_order_id" in cols:
        return
    count = conn.execute("SELECT COUNT(*) AS n FROM fills").fetchone()["n"]
    if count:
        raise RuntimeError(
            f"fills has {count} rows under the legacy column name 'order_id'; "
            "refusing to auto-rename append-only data — migrate deliberately"
        )
    conn.execute("ALTER TABLE fills RENAME COLUMN order_id TO broker_order_id")
    conn.execute("DROP INDEX IF EXISTS idx_fills_order")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_fills_broker_order ON fills(broker_order_id)"
    )


def init_db(conn: sqlite3.Connection) -> None:
    """Create all tables and apply migrations (idempotent).

    Renames run BEFORE the schema script: SCHEMA creates
    `idx_fills_broker_order`, which cannot be built against a table still
    carrying the legacy column name.
    """
    _rename_fills_order_column(conn)
    conn.executescript(SCHEMA)
    _apply_column_migrations(conn)
    conn.commit()
