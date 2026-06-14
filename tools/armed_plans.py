"""Armed-plan store: pre-market trade plans that are armed but UNFILLED.

An armed plan carries an entry trigger + invalidation + cutoff. The monitor
sentinel watches these intraday and only fills (via the LLM monitor) when the
breakout confirms. Kept in its own JSON store so the live trade_plans DB table
is untouched. Statuses: armed -> filled | cancelled.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent / "armed_plans.json"


def _new_id() -> str:
    return f"armed_{uuid.uuid4().hex[:10]}"


@dataclass
class ArmedPlan:
    symbol: str
    direction: str          # "long" only for v1.1.0
    structure: str          # "long_call" | "call_debit"
    trigger_price: float    # underlying level that must confirm
    invalidation_price: float
    cutoff_et: str          # e.g. "11:00"
    rationale: str
    dte_target: int = 40
    delta_target: float = 0.60
    status: str = "armed"   # armed | filled | cancelled
    cancel_reason: str = ""
    plan_id: str = field(default_factory=_new_id)


class ArmedPlanStore:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or _DEFAULT_PATH)

    def _read(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return []

    def _write(self, rows: list[dict]) -> None:
        self.path.write_text(json.dumps(rows, indent=2, default=str))

    def arm(self, plan: ArmedPlan) -> None:
        rows = self._read()
        rows.append(asdict(plan))
        self._write(rows)

    def list_active(self) -> list[ArmedPlan]:
        return [ArmedPlan(**r) for r in self._read() if r.get("status") == "armed"]

    def get(self, plan_id: str) -> ArmedPlan | None:
        for r in self._read():
            if r.get("plan_id") == plan_id:
                return ArmedPlan(**r)
        return None

    def _set_status(self, plan_id: str, status: str, reason: str = "") -> bool:
        """Set a plan's status. Returns True if a matching plan was found.

        A False return means the plan_id did not match any stored row (typo,
        already-rotated, or never armed). Callers should treat that as a signal,
        not a silent no-op — e.g. the sentinel must not assume a fill applied.
        """
        rows = self._read()
        found = False
        for r in rows:
            if r.get("plan_id") == plan_id:
                r["status"] = status
                if reason:
                    r["cancel_reason"] = reason
                found = True
        if found:
            self._write(rows)
        return found

    def cancel(self, plan_id: str, reason: str = "") -> bool:
        return self._set_status(plan_id, "cancelled", reason)

    def fill(self, plan_id: str) -> bool:
        return self._set_status(plan_id, "filled")
