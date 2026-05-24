"""Validates that the agent called required tools before making a decision."""

REQUIRED_TOOLS = {
    "research": {
        "enter": ["calc_technical_indicators", "get_market_data"],
        "skip": ["calc_technical_indicators", "get_market_data"],
    },
    "trader": {
        "enter": ["check_kill_switch", "check_daily_limits", "check_portfolio_risk", "calc_position_size"],
    },
    "monitor": {
        "hold": ["get_positions", "get_market_data"],
        "exit": ["get_positions", "get_market_data"],
    },
}


class WorkflowValidator:
    def __init__(self):
        self._calls: list[str] = []

    def record_tool_call(self, tool_name: str) -> None:
        self._calls.append(tool_name)

    def validate(self, phase: str, decision: str) -> dict:
        required = REQUIRED_TOOLS.get(phase, {}).get(decision, [])
        called_set = set(self._calls)
        missing = [t for t in required if t not in called_set]
        return {
            "valid": len(missing) == 0,
            "missing": missing,
            "required": required,
            "called": list(called_set),
        }

    def get_calls(self) -> list[str]:
        return list(self._calls)

    def reset(self) -> None:
        self._calls = []
