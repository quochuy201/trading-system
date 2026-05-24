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

    def test_harness_advance_bar_returns_data(self):
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        bar_data = harness.advance_bar()
        assert bar_data is not None
        assert "timestamp" in bar_data
        assert "close" in bar_data
        assert bar_data["bar_index"] == 0

    def test_harness_log_decision_records(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        harness.record_decision(
            symbol="NVDA", phase="research", decision="skip",
            reasoning="No setup", input_state={"price": 200.0},
            tools_called=["calc_technical_indicators", "get_market_data"],
            rules_evaluated=[], score=None, trade_plan=None,
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 1
        assert decisions[0]["decision"] == "skip"

    def test_harness_workflow_validation(self):
        harness = BacktestHarness(self.repo)
        run_id = harness.start(symbols=["NVDA"], start_date="2026-01-02",
                               end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        harness.advance_bar()
        harness.record_decision(
            symbol="NVDA", phase="research", decision="enter",
            reasoning="Looks good", input_state={"price": 200.0},
            tools_called=[],
            rules_evaluated=[], score=80, trade_plan={"entry": 200, "stop": 195, "target": 210},
        )
        decisions = self.repo.get_backtest_decisions(run_id)
        assert decisions[0]["workflow_valid"] == 0

    def test_harness_done_after_all_bars(self):
        harness = BacktestHarness(self.repo)
        harness.start(symbols=["NVDA"], start_date="2026-01-02",
                      end_date="2026-01-21", timeframe="1Day", initial_capital=100000.0)
        count = 0
        while True:
            bar = harness.advance_bar()
            if bar is None:
                break
            harness.record_decision(
                symbol="NVDA", phase="research", decision="skip",
                reasoning="No setup", input_state={"price": bar["close"]},
                tools_called=["calc_technical_indicators", "get_market_data"],
                rules_evaluated=[], score=None, trade_plan=None,
            )
            count += 1
        assert count == 20


class TestBacktestIntegration:
    """End-to-end test: simulate a simple strategy through the harness."""

    def setup_method(self):
        self.repo = Repository(":memory:")
        _load_sample_bars(self.repo, "NVDA", 30)

    def teardown_method(self):
        self.repo.close()

    def test_full_run_with_simple_strategy(self):
        """A trivial strategy: buy when price > SMA5, sell when price < SMA5."""
        from backtest.logger import BacktestLogger

        harness = BacktestHarness(self.repo)
        run_id = harness.start(
            symbols=["NVDA"],
            start_date="2026-01-02",
            end_date="2026-01-31",
            timeframe="1Day",
            initial_capital=100000.0,
        )

        prices = []
        in_position = False
        trades_completed = 0

        while True:
            bar = harness.advance_bar()
            if bar is None:
                break

            prices.append(bar["close"])
            sma5 = sum(prices[-5:]) / min(len(prices), 5)

            if not in_position and len(prices) >= 5 and bar["close"] > sma5:
                harness.record_decision(
                    symbol="NVDA", phase="research", decision="enter",
                    reasoning=f"Price {bar['close']:.2f} > SMA5 {sma5:.2f}",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=["calc_technical_indicators", "get_market_data"],
                    rules_evaluated=[{"rule": "ABOVE_SMA5", "passed": True}],
                    score=75.0,
                    trade_plan={"entry": bar["close"], "stop": bar["close"] * 0.97, "target": bar["close"] * 1.06},
                )
                harness.get_broker().place_order("NVDA", "buy", "market", 100)
                in_position = True

            elif in_position and bar["close"] < sma5:
                harness.record_decision(
                    symbol="NVDA", phase="monitor", decision="exit",
                    reasoning=f"Price {bar['close']:.2f} < SMA5 {sma5:.2f}",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=["get_positions", "get_market_data"],
                    rules_evaluated=[{"rule": "BELOW_SMA5", "passed": True}],
                )
                harness.get_broker().place_order("NVDA", "sell", "market", 100)
                in_position = False
                trades_completed += 1

            else:
                action = "hold" if in_position else "skip"
                phase = "monitor" if in_position else "research"
                tools = (["get_positions", "get_market_data"] if in_position
                         else ["calc_technical_indicators", "get_market_data"])
                harness.record_decision(
                    symbol="NVDA", phase=phase, decision=action,
                    reasoning=f"Price {bar['close']:.2f} vs SMA5 {sma5:.2f} - no signal",
                    input_state={"price": bar["close"], "sma5": round(sma5, 2)},
                    tools_called=tools,
                    rules_evaluated=[],
                )

        decisions = self.repo.get_backtest_decisions(run_id)
        assert len(decisions) == 30
        assert trades_completed >= 1
        violations = [d for d in decisions if d["workflow_valid"] == 0]
        assert len(violations) == 0

        logger = BacktestLogger(self.repo)
        lines = logger.export_jsonl(run_id)
        assert len(lines) == 30
