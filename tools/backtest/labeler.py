"""Retroactively labels backtest decisions with outcome quality."""


class OutcomeLabeler:
    @staticmethod
    def label_entry(r_multiple: float) -> str:
        if r_multiple >= 1.5:
            return "GOOD_ENTRY"
        elif r_multiple <= -0.5:
            return "BAD_ENTRY"
        return "NEUTRAL"

    @staticmethod
    def label_exit(
        exit_pnl: float,
        price_after_exit_moved: float,
        exited_at_planned_stop: bool = False,
    ) -> str:
        if exit_pnl < 0:
            if exited_at_planned_stop:
                return "EXPECTED_LOSS"
            return "BAD_EXIT"
        if price_after_exit_moved > exit_pnl:
            return "EARLY_EXIT"
        return "GOOD_EXIT"

    @staticmethod
    def compute_r_multiple(entry_price: float, exit_price: float, stop_price: float, side: str = "long") -> float:
        if side == "long":
            risk = entry_price - stop_price
            reward = exit_price - entry_price
        else:
            risk = stop_price - entry_price
            reward = entry_price - exit_price
        if risk <= 0:
            return 0.0
        return round(reward / risk, 2)
