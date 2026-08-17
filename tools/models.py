"""Data models for the trading system."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
import json
import uuid


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- Research Models ---


@dataclass
class ScanCandidate:
    symbol: str
    score: float
    signals: list[str]
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanReport:
    candidates: list[ScanCandidate]
    market_context: str = ""
    sop_version: str = ""
    timestamp: datetime = field(default_factory=_now)


@dataclass
class AnalysisReport:
    symbol: str
    technical_score: float
    overall_score: float
    recommendation: str  # strong_buy, buy, neutral, avoid
    signals: list[str] = field(default_factory=list)
    key_levels: dict[str, float] = field(default_factory=dict)
    fundamental_score: float | None = None
    sentiment_score: float | None = None
    sop_version: str = ""
    timestamp: datetime = field(default_factory=_now)


# --- Trading Models ---


@dataclass
class TradePlan:
    plan_id: str = field(default_factory=_new_id)
    symbol: str = ""
    strategy: str = ""
    sop_version: str = ""
    side: str = ""  # buy, sell_short
    quantity: int = 0
    entry_order_type: str = "market"
    entry_limit_price: float | None = None
    take_profit: float = 0.0
    stop_loss: float = 0.0
    trailing_stop: float | None = None
    time_stop: datetime | None = None
    risk_assessment: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    created_at: datetime = field(default_factory=_now)
    # Market regime when the decision was made — captured here, at plan
    # creation, from the session's preflight value. Orders inherit it rather
    # than recomputing: the regime calculation is versioned, so a later lookup
    # would quietly rewrite history. None when unknown; never fabricated.
    regime: str | None = None


@dataclass
class TradeTransaction:
    transaction_id: str = field(default_factory=_new_id)
    plan_id: str = ""
    symbol: str = ""
    side: str = ""  # buy, sell
    order_type: str = ""
    quantity: int = 0
    price: float = 0.0
    broker_order_id: str = ""
    status: str = ""  # filled, partial, rejected, cancelled
    timestamp: datetime = field(default_factory=_now)


@dataclass
class Order:
    """An order we submitted — INTENT, recorded at submit time.

    Separate from `Fill` on purpose: an order says what we asked for, a fill
    says what the market gave us. Conflating them is what made the old
    `trade_transactions` table unable to answer "what did we actually pay".

    `regime_at_entry` is inherited from the plan (denormalized deliberately —
    orders must stand alone as facts, plans can be edited). No plan ⇒ None,
    never fabricated. Same for the gate fields, which stay None until the
    governance gate ships.
    """
    order_id: str = field(default_factory=_new_id)
    plan_id: str | None = None
    broker_order_id: str | None = None
    symbol: str = ""
    side: str = ""  # buy, sell
    order_type: str = ""
    qty_requested: int = 0
    intended_price: float | None = None  # limit/signal price → slippage reference
    submitted_at: datetime = field(default_factory=_now)
    terminal_status: str | None = None  # None until terminal; then filled, partially_filled, cancelled, rejected, expired, unknown_historical
    gate_verdict: str | None = None  # APPROVED, REDUCED, REJECTED, PENDING
    gate_rule_id: str | None = None
    regime_at_entry: str | None = None
    mode: str = ""  # paper, live


@dataclass
class Fill:
    """One execution as reported by the broker — REALITY, append-only.

    `fill_id` is the broker's own activity id and has NO default factory: it
    must come from the broker so that replaying the activity feed collides on
    the primary key instead of appending a duplicate. Minting one here would
    make idempotency a thing we have to code correctly rather than a thing the
    schema guarantees.

    `qty` is THIS execution only — never the cumulative filled quantity. A
    partially filled order is two Fill rows, not one row updated twice.
    """
    fill_id: str = ""  # broker activity id — never generated locally
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # buy, sell
    qty: int = 0  # this execution only, NOT cum_qty
    price: float = 0.0
    fill_type: str = ""  # fill, partial_fill
    filled_at: datetime = field(default_factory=_now)
    mode: str = ""  # paper, live


@dataclass
class ExecutionReport:
    transactions: list[TradeTransaction] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_now)


# --- Monitoring Models ---


@dataclass
class PositionStatus:
    symbol: str
    quantity: int
    entry_price: float
    current_price: float
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    exit_triggered: bool = False
    exit_reason: str | None = None


@dataclass
class MonitorReport:
    positions: list[PositionStatus] = field(default_factory=list)
    portfolio_value: float = 0.0
    daily_pnl: float = 0.0
    alerts: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=_now)


# --- Review Models ---


@dataclass
class JournalEntry:
    plan_id: str = ""
    symbol: str = ""
    strategy: str = ""
    sop_version: str = ""
    entry_transactions: list[str] = field(default_factory=list)
    exit_transactions: list[str] = field(default_factory=list)
    pnl: float = 0.0
    pnl_pct: float = 0.0
    rationale: str = ""
    exit_reason: str = ""
    lessons: str = ""
    timestamp: datetime = field(default_factory=_now)


# --- Workflow Models ---


@dataclass
class WorkflowCheckpoint:
    workflow_run_id: str = field(default_factory=_new_id)
    status: str = "PENDING"
    sop_name: str = ""
    sop_version: str = ""
    checkpoint_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    started_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)


@dataclass
class KillSwitchState:
    active: bool = False
    triggered_at: datetime | None = None
    trigger_reason: str | None = None
    orders_cancelled: int = 0
    positions_closed: int = 0


# --- Audit & Performance Models ---


@dataclass
class DecisionLogEntry:
    decision_id: str = field(default_factory=_new_id)
    timestamp: datetime = field(default_factory=_now)
    agent: str = ""  # research, trader, monitor, orchestrator
    action: str = ""  # enter, exit, hold, skip, adjust
    symbol: str = ""
    rules_triggered: list[str] = field(default_factory=list)
    rules_considered: list[str] = field(default_factory=list)
    reasoning: str = ""
    sop_version: str = ""
    plan_id: str = ""
    market_context: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)


@dataclass
class LedgerEntry:
    ledger_id: str = field(default_factory=_new_id)
    timestamp: datetime = field(default_factory=_now)
    action: str = ""  # buy, sell, cancel
    symbol: str = ""
    quantity: int = 0
    order_type: str = ""
    price: float = 0.0
    total_cost: float = 0.0
    fees: float = 0.0
    status: str = ""  # filled, partial, pending, cancelled, rejected
    broker_order_id: str = ""
    account_equity: float = 0.0
    account_cash: float = 0.0
    buying_power: float = 0.0
    pnl: float | None = None
    pnl_pct: float | None = None
    entry_price: float | None = None
    plan_id: str = ""
    decision_id: str = ""
    sop_version: str = ""
    platform: str = ""
    trigger: str = "agent"  # agent, kill_switch, trailing_stop, manual
    notes: str = ""


@dataclass
class PerformanceReport:
    report_id: str = field(default_factory=_new_id)
    report_type: str = ""  # daily, weekly, on_demand
    start_date: datetime = field(default_factory=_now)
    end_date: datetime = field(default_factory=_now)
    sop_version: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=_now)


# --- Serialization ---


def to_json(obj) -> str:
    """Serialize a dataclass to JSON string."""
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        raise TypeError(f"Not serializable: {type(o)}")
    return json.dumps(asdict(obj), default=default)


def from_json(cls, data: str):
    """Deserialize a JSON string to a dataclass instance."""
    raw = json.loads(data)
    # Convert ISO datetime strings back to datetime objects
    hints = cls.__dataclass_fields__
    for k, f in hints.items():
        if k in raw and raw[k] is not None:
            if f.type == "datetime" or f.type is datetime:
                raw[k] = datetime.fromisoformat(raw[k])
            elif f.type == "datetime | None":
                raw[k] = datetime.fromisoformat(raw[k]) if raw[k] else None
    return cls(**raw)
