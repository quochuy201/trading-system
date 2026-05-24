"""Compliance scorer — detects SOP violations from the decision log."""

from persistence.repository import Repository


def score_decisions(repo: Repository, start_date: str = "", end_date: str = "") -> dict:
    """Score all decisions in a date range for compliance violations.

    Returns: {"total": N, "compliant": N, "violations": [{"decision_id", "type", "detail"}...],
              "by_type": {"PANIC_SELL": N, ...}, "compliance_rate": 0.0-1.0}
    """
    decisions = repo.query_decisions(start_date=start_date, end_date=end_date, limit=10000)
    violations = []

    for d in decisions:
        v = _check_decision(d, repo)
        if v:
            violations.extend(v)
            # Write violations back to the decision record
            existing = d.get("violations", [])
            new_types = [x["type"] for x in v]
            if set(new_types) != set(existing):
                from models import DecisionLogEntry
                entry = DecisionLogEntry(
                    decision_id=d["decision_id"], timestamp=d["timestamp"],
                    agent=d["agent"], action=d["action"], symbol=d["symbol"],
                    rules_triggered=d["rules_triggered"],
                    rules_considered=d["rules_considered"],
                    reasoning=d["reasoning"], sop_version=d["sop_version"],
                    plan_id=d["plan_id"], market_context=d["market_context"],
                    violations=new_types,
                )
                # Re-parse timestamp if string
                if isinstance(entry.timestamp, str):
                    from datetime import datetime
                    entry.timestamp = datetime.fromisoformat(entry.timestamp)
                repo.save_decision(entry)

    total = len(decisions)
    violated_ids = set(v["decision_id"] for v in violations)
    compliant = total - len(violated_ids)
    by_type: dict[str, int] = {}
    for v in violations:
        by_type[v["type"]] = by_type.get(v["type"], 0) + 1

    return {
        "total": total,
        "compliant": compliant,
        "compliance_rate": round(compliant / total, 3) if total else 1.0,
        "violations": violations,
        "by_type": by_type,
    }


def _check_decision(d: dict, repo: Repository) -> list[dict]:
    """Check a single decision for violations. Returns list of violations found."""
    violations = []
    action = d.get("action", "")
    rules = d.get("rules_triggered", [])
    plan_id = d.get("plan_id", "")
    ctx = d.get("market_context", {})
    decision_id = d["decision_id"]

    # UNTAGGED_DECISION: action is enter/exit but no rules tagged
    if action in ("enter", "exit") and not rules:
        violations.append({
            "decision_id": decision_id,
            "type": "UNTAGGED_DECISION",
            "detail": f"{action} action with no rules_triggered",
        })

    # PANIC_SELL: exit but price is above stop_loss
    if action == "exit" and plan_id and ctx:
        plan = repo.get_trade_plan(plan_id)
        if plan and plan.stop_loss and ctx.get("price"):
            price = ctx["price"]
            if plan.side == "buy" and price > plan.stop_loss:
                # Sold above stop — check if a valid exit rule was tagged
                valid_exit_rules = {"STOP_HIT", "TAKE_PROFIT", "TIME_STOP", "TRAILING_STOP"}
                if not set(rules) & valid_exit_rules:
                    violations.append({
                        "decision_id": decision_id,
                        "type": "PANIC_SELL",
                        "detail": f"Exited at ${price:.2f} above stop ${plan.stop_loss:.2f} without valid exit rule",
                    })

    # EARLY_EXIT: exit but price hasn't hit target and no valid rule
    if action == "exit" and plan_id and ctx:
        plan = repo.get_trade_plan(plan_id)
        if plan and plan.take_profit and ctx.get("price"):
            price = ctx["price"]
            if plan.side == "buy" and price < plan.take_profit:
                valid_exit_rules = {"STOP_HIT", "TAKE_PROFIT", "TIME_STOP", "TRAILING_STOP", "KILL_SWITCH"}
                if not set(rules) & valid_exit_rules:
                    violations.append({
                        "decision_id": decision_id,
                        "type": "EARLY_EXIT",
                        "detail": f"Exited at ${price:.2f} below target ${plan.take_profit:.2f} without valid exit rule",
                    })

    # RULE_CONFLICT: contradicting rules in same decision
    conflicts = [
        ({"STOP_HIT", "TAKE_PROFIT"}),  # can't hit both
        ({"HOLD_SIGNAL", "STOP_HIT"}),  # hold vs exit
    ]
    rule_set = set(rules)
    for conflict_pair in conflicts:
        if conflict_pair.issubset(rule_set):
            violations.append({
                "decision_id": decision_id,
                "type": "RULE_CONFLICT",
                "detail": f"Conflicting rules: {conflict_pair}",
            })

    return violations
