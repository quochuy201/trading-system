import sys
import json
from pathlib import Path
from datetime import datetime
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.harness import BacktestHarness
from persistence.repository import Repository


def _load_sample_bars(repo, symbol="NVDA", days=20):
    """Load synthetic daily bars."""
    import random
    random.seed(123)
    price = 200.0
    bars = []
    for i in range(days):
        o = price
        h = price + random.uniform(1, 5)
        l = price - random.uniform(1, 5)
        c = price + random.uniform(-3, 4)
        price = c
        bars.append({
            "symbol": symbol,
            "timestamp": f"2026-01-{(i+2):02d}",
            "open": round(o, 2), "high": round(h, 2),
            "low": round(l, 2), "close": round(c, 2),
            "volume": 5000000 + random.randint(-1000000, 3000000),
            "timeframe": "1Day",
        })
    repo.save_price_bars(bars)


class TestBacktestHarness:
    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_bars(self.repo, "NVDA", 20)

    def teardown_method(self):
        self.repo.close()

    def test_harness_creates_run(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(
            symbols=["NVDA"],
            start_date="2026-01-02",
            end_date="2026-01-21",
            timeframe="1Day",
            initial_capital=100000.0,
        )
        assert run_id.startswith("bt-")
        run = self.repo.get_backtest_run(run_id)
        assert run["status"] == "running"

    def test_advance_bar_returns_open_only(self):
        """advance_bar must return open price but NOT close/high/low (no look-ahead)."""
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        bar = harness.advance_bar()
        assert bar is not None
        assert "open" in bar
        assert "timestamp" in bar
        assert "bar_index" in bar
        # CRITICAL: no look-ahead data
        assert "close" not in bar
        assert "high" not in bar
        assert "low" not in bar
        assert "volume" not in bar

    def test_advance_bar_includes_previous_bar_full_data(self):
        """After first bar, advance_bar should include previous bar's full OHLCV."""
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        # First bar — no previous
        bar1 = harness.advance_bar()
        harness.record_decision(symbol="NVDA", phase="research", decision="skip",
                                reasoning="first bar", input_state={"price": bar1["open"]},
                                rules_evaluated=[])
        # Second bar — should have previous
        bar2 = harness.advance_bar()
        assert "previous_bar" in bar2
        assert "close" in bar2["previous_bar"]
        assert "high" in bar2["previous_bar"]
        assert "low" in bar2["previous_bar"]

    def test_decision_required_before_advance(self):
        """Harness refuses to advance if no decision logged for current bar."""
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        # Try to advance without logging decision
        result = harness.advance_bar()
        assert result is not None
        assert "error" in result
        assert "Must log a decision" in result["error"]

    def test_decision_allows_advance(self):
        """After logging decision, advance_bar works."""
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        bar1 = harness.advance_bar()
        harness.record_decision(symbol="NVDA", phase="research", decision="skip",
                                reasoning="no setup", input_state={"price": bar1["open"]},
                                rules_evaluated=[])
        bar2 = harness.advance_bar()
        assert bar2 is not None
        assert "error" not in bar2

    def test_record_decision_uses_server_tracked_tools(self):
        """record_decision doesn't accept tools_called — uses internal tracking."""
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        # Simulate server-side tool tracking (as MCP tools would do)
        harness.record_tool_call("calc_technical_indicators")
        harness.record_tool_call("get_market_data")
        # Record decision (no tools_called parameter)
        harness.record_decision(
            symbol="NVDA", phase="research", decision="skip",
            reasoning="No setup", input_state={"price": 200.0},
            rules_evaluated=[],
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 1
        tools = json.loads(decisions[0]["tools_called"])
        assert "calc_technical_indicators" in tools
        assert "get_market_data" in tools

    def test_workflow_violation_when_tools_not_called(self):
        """If agent doesn't call required tools, decision is logged with violation."""
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        # Record decision WITHOUT calling any tools first
        harness.record_decision(
            symbol="NVDA", phase="research", decision="enter",
            reasoning="Looks good", input_state={"price": 200.0},
            rules_evaluated=[], score=80,
            trade_plan={"entry": 200, "stop": 195, "target": 210},
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert decisions[0]["workflow_valid"] == 0

    def test_full_run_all_bars(self):
        """Can process all bars with proper decision logging."""
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        count = 0
        while True:
            bar = harness.advance_bar()
            if bar is None:
                break
            if "error" in bar:
                break
            # Simulate calling tools (server-side)
            harness.record_tool_call("calc_technical_indicators")
            harness.record_tool_call("get_market_data")
            harness.record_decision(
                symbol="NVDA", phase="research", decision="skip",
                reasoning="No setup", input_state={"price": bar["open"]},
                rules_evaluated=[],
            )
            count += 1
        assert count == 20


class TestBacktestIntegration:
    """End-to-end: simple strategy using the correct temporal model."""

    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_bars(self.repo, "NVDA", 30)

    def teardown_method(self):
        self.repo.close()

    def test_full_run_with_simple_strategy(self):
        """Strategy uses only data available at decision time (open + previous bars)."""
        from backtest.logger import BacktestLogger

        harness = BacktestHarness(self.repo)
        run_id = harness.start(
            symbols=["NVDA"],
            start_date="2026-01-02",
            end_date="2026-01-31",
            timeframe="1Day",
            initial_capital=100000.0,
        )

        previous_closes = []
        in_position = False
        trades_completed = 0

        while True:
            bar = harness.advance_bar()
            if bar is None:
                break
            if "error" in bar:
                break

            # Agent can see: current open + previous bars' closes
            current_open = bar["open"]
            if "previous_bar" in bar:
                previous_closes.append(bar["previous_bar"]["close"])

            # Simple strategy: buy if current open > average of last 5 previous closes
            harness.record_tool_call("calc_technical_indicators")
            harness.record_tool_call("get_market_data")

            if not in_position and len(previous_closes) >= 5:
                sma5 = sum(previous_closes[-5:]) / 5
                if current_open > sma5:
                    harness.record_tool_call("check_kill_switch")
                    harness.record_tool_call("check_daily_limits")
                    harness.record_tool_call("check_portfolio_risk")
                    harness.record_tool_call("calc_position_size")
                    harness.record_decision(
                        symbol="NVDA", phase="research", decision="enter",
                        reasoning=f"Open {current_open:.2f} > SMA5 {sma5:.2f}",
                        input_state={"open": current_open, "sma5": round(sma5, 2)},
                        rules_evaluated=[{"rule": "ABOVE_SMA5", "passed": True}],
                        score=75.0,
                        trade_plan={"entry": current_open, "stop": current_open * 0.97, "target": current_open * 1.06},
                    )
                    harness.get_broker().place_order("NVDA", "buy", "market", 100)
                    in_position = True
                    continue

            if in_position and len(previous_closes) >= 5:
                sma5 = sum(previous_closes[-5:]) / 5
                if current_open < sma5:
                    harness.record_tool_call("get_positions")
                    harness.record_decision(
                        symbol="NVDA", phase="monitor", decision="exit",
                        reasoning=f"Open {current_open:.2f} < SMA5 {sma5:.2f}",
                        input_state={"open": current_open, "sma5": round(sma5, 2)},
                        rules_evaluated=[{"rule": "BELOW_SMA5", "passed": True}],
                    )
                    harness.get_broker().place_order("NVDA", "sell", "market", 100)
                    in_position = False
                    trades_completed += 1
                    continue

            # Default: skip/hold
            phase = "monitor" if in_position else "research"
            decision = "hold" if in_position else "skip"
            if in_position:
                harness.record_tool_call("get_positions")
            harness.record_decision(
                symbol="NVDA", phase=phase, decision=decision,
                reasoning="No signal",
                input_state={"open": current_open},
                rules_evaluated=[],
            )

        # Verify
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 30
        assert trades_completed >= 1

        # All decisions should have workflow_valid = 1
        violations = [d for d in decisions if d["workflow_valid"] == 0]
        assert len(violations) == 0

        # JSONL export works
        logger = BacktestLogger(self.repo)
        lines = logger.export_jsonl(run_id)
        assert len(lines) == 30
