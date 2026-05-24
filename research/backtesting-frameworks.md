# Python Backtesting Frameworks Research

## Landscape Overview (2026)

Two paradigms dominate:
1. **Vectorized** — array-based, fast parameter sweeps (VectorBT)
2. **Event-driven** — realistic execution simulation (NautilusTrader, Backtrader)

---

## Recommended Stack for Our System

### Phase 1 (Discovery): VectorBT PRO or Open Source
- Ultra-fast parameter sweeps across many assets
- NumPy broadcasting + Numba JIT compilation
- 100K+ backtests in seconds
- Great for: "Does this signal have edge?"

### Phase 2 (Validation): NautilusTrader
- Production-grade event-driven simulation
- Rust core + Python API
- Order book realism, latency modeling
- Same code runs in backtest AND live

### Phase 3 (Live): Alpaca API
- Direct broker connection
- Same strategy logic as backtest

---

## Framework Comparison

| Framework | Speed | Execution Realism | Live Trading | Best For |
|-----------|-------|-------------------|--------------|----------|
| **VectorBT PRO** | Extreme | Medium | DIY | Parameter sweeps, research |
| **NautilusTrader** | Very High (Rust) | High | Native | Production execution |
| **Backtrader** | Low | Medium | Legacy | ⚠️ Legacy, avoid for new projects |
| **Zipline-Reloaded** | Medium | Medium | No | Equity factor models |
| **Backtesting.py** | Medium | Low | No | Quick single-asset prototyping |
| **PyBroker** | High (Numba) | Medium | DIY | ML-first strategies |
| **Freqtrade** | Medium | Medium | Native (crypto) | Crypto bot automation |

---

## Top Picks for Our System

### VectorBT (Open Source) — Research Phase
- **Why**: Fast signal validation, free, Python-native
- **Use for**: Testing strategy ideas, parameter optimization
- **Limitation**: Lighter execution semantics than PRO

### NautilusTrader — Validation Phase
- **Why**: Production-parity between backtest and live
- **Architecture**: Event-driven, actor-style, Rust core
- **Key feature**: Same strategy code runs in backtest AND live
- **Broker adapters**: Crypto exchanges, traditional brokers
- **Open source**: Free

### PyBroker — ML/AI Strategy Validation
- **Why**: Built for ML-driven trading research
- **Key feature**: Walkforward analysis out of the box
- **Data providers**: Alpaca, Yahoo Finance built-in
- **Numba-accelerated**: Fast experiments

---

## Key Design Decisions for Our Backtesting

1. **Event-driven for live parity**: Our backtest must behave identically to live trading (requirement from idea-honing)
2. **No look-ahead bias**: Process data sequentially, only use data available at decision time
3. **Realistic execution**: Model slippage, fees, partial fills
4. **Same code path**: Strategy logic should be identical in backtest and live modes

### Recommended Approach
```
Research (VectorBT) → Validate (NautilusTrader or custom event-driven) → Live (Alpaca)
```

Since our system is agent-driven (not traditional quant), we may need a **custom backtesting harness** that:
- Replays historical data to agents
- Agents make decisions using same SOP/tools as live
- Records all decisions and outcomes
- Measures performance metrics

This is closer to a "simulation environment" than a traditional backtester.

---

## Sources
- https://python.financial/ (comprehensive 2026 comparison)
- https://nautilustrader.io/
- https://vectorbt.pro
- https://github.com/edtechre/pybroker
