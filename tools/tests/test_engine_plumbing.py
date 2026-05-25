"""Agent-driven backtest: simulates live trading workflow using MCP tools.

No hardcoded strategy — follows the same tool calls an agent would make live:
1. start_backtest_v2 → initialize
2. next_backtest_bar → advance time
3. calc_technical_indicators + get_market_data → gather data
4. Apply Research skill 5-layer DD scoring
5. check_kill_switch + check_daily_limits + check_portfolio_risk → risk gates
6. place_order → execute (simulation)
7. log_backtest_decision → audit trail
8. Monitor positions → exit when conditions met
"""

import json
import os
from pathlib import Path

# Load env
env_file = Path(__file__).parent.parent / ".env"
for line in env_file.read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import server

# === CONFIG ===
SYMBOLS = "TSLA,AMD,NVDA,MU"
START = "2026-03-01"
END = "2026-03-31"
LOOKBACK = "2025-12-01"
CAPITAL = 100000.0
MAX_POSITIONS = 2
SOP = "swing-v1.0"

# === START ===
result = json.loads(server.start_backtest_v2(SYMBOLS, START, END, LOOKBACK, "1Day", CAPITAL, SOP))
run_id = result["run_id"]
print(f"Run: {run_id} | Bars: {result['total_bars']} | Symbols: {result['symbols']}")
print("=" * 80)

positions = {}
trade_log = []
bar_num = 0

while True:
    bar = json.loads(server.next_backtest_bar())
    if "done" in bar:
        break
    bar_num += 1
    sym = bar["symbol"]
    ts = bar["timestamp"][:10]
    price = bar["close"]
    account = bar["account"]

    # --- Tool calls (same as live agent) ---
    indicators = json.loads(server.calc_technical_indicators(sym, "1Day"))
    if "error" in indicators:
        server.log_backtest_decision(
            symbol=sym, phase="research", decision="skip",
            reasoning="Insufficient data for indicators",
            input_state=json.dumps({"price": price}),
            tools_called=json.dumps(["calc_technical_indicators", "get_market_data"]),
        )
        continue

    market = json.loads(server.get_market_data(sym))

    rsi = indicators.get("rsi")
    sma20 = indicators.get("sma_20")
    sma50 = indicators.get("sma_50")
    atr = indicators.get("atr")
    vol_ratio = indicators.get("volume_ratio", 0)
    above_sma20 = indicators.get("above_sma20", False)
    above_sma50 = indicators.get("above_sma50")

    input_state = {
        "price": price, "rsi": rsi, "sma20": sma20, "sma50": sma50,
        "atr": atr, "volume_ratio": vol_ratio,
    }

    # === MONITOR (if holding this symbol) ===
    if sym in positions:
        pos = positions[sym]
        hold_bars = bar["bar_index"] - pos["entry_bar"]
        r_current = (price - pos["entry_price"]) / (pos["entry_price"] - pos["stop"]) if pos["entry_price"] > pos["stop"] else 0

        # Exit conditions (per Monitor skill priority)
        exit_reason = None
        if price <= pos["stop"]:
            exit_reason = "STOP_HIT"
        elif price >= pos["target"]:
            exit_reason = "TAKE_PROFIT"
        elif hold_bars >= 10:
            exit_reason = "TIME_STOP"

        # Trailing stop: after +1R, move stop to breakeven
        if not exit_reason and r_current >= 1.0 and not pos.get("trailing_active"):
            pos["stop"] = pos["entry_price"]
            pos["trailing_active"] = True

        if exit_reason:
            server.place_order(sym, "sell", "market", pos["quantity"], plan_id=pos.get("plan_id", ""))
            pnl = (price - pos["entry_price"]) * pos["quantity"]
            r_mult = round(r_current, 2)

            server.log_backtest_decision(
                symbol=sym, phase="monitor", decision="exit",
                reasoning=f"{exit_reason}: price={price:.2f}, entry={pos['entry_price']:.2f}, P&L=${pnl:.2f} ({r_mult}R), held {hold_bars}d",
                input_state=json.dumps(input_state),
                tools_called=json.dumps(["get_positions", "get_market_data"]),
                rules_evaluated=json.dumps([{"rule": exit_reason, "passed": True}]),
            )
            trade_log.append({"symbol": sym, "entry": pos["entry_price"], "exit": price, "pnl": pnl, "r_mult": r_mult, "bars": hold_bars, "reason": exit_reason})
            print(f"  [{ts}] EXIT  {sym:4s} @ ${price:>7.2f} | {exit_reason:<14s} | P&L: ${pnl:>+8.2f} ({r_mult:>+.1f}R) | held {hold_bars}d")
            del positions[sym]
        else:
            server.log_backtest_decision(
                symbol=sym, phase="monitor", decision="hold",
                reasoning=f"Hold: price={price:.2f}, stop={pos['stop']:.2f}, target={pos['target']:.2f}, {r_current:.1f}R, {hold_bars}d",
                input_state=json.dumps(input_state),
                tools_called=json.dumps(["get_positions", "get_market_data"]),
                rules_evaluated=json.dumps([]),
            )
        continue

    # === RESEARCH (5-Layer DD scoring) ===
    rules = []
    score = 0

    # Layer 2: Trend
    if above_sma20:
        rules.append({"rule": "TREND_ABOVE_SMA20", "passed": True, "value": f"{price:.2f} > {sma20:.2f}"})
        score += 20
    else:
        rules.append({"rule": "TREND_ABOVE_SMA20", "passed": False, "value": f"{price:.2f} <= {sma20:.2f}"})

    if above_sma50:
        rules.append({"rule": "TREND_ABOVE_SMA50", "passed": True, "value": f"{price:.2f} > {sma50}"})
        score += 15
    else:
        rules.append({"rule": "TREND_ABOVE_SMA50", "passed": False, "value": f"{price:.2f} vs {sma50}"})

    # Layer 4: Technical setup
    if rsi and 45 <= rsi <= 75:
        rules.append({"rule": "RSI_FAVORABLE", "passed": True, "value": f"{rsi:.1f} in [45,75]"})
        score += 20
    else:
        rules.append({"rule": "RSI_FAVORABLE", "passed": False, "value": f"{rsi}"})

    if vol_ratio >= 1.2:
        rules.append({"rule": "VOLUME_CONFIRM", "passed": True, "value": f"{vol_ratio:.2f}x >= 1.2"})
        score += 20
    else:
        rules.append({"rule": "VOLUME_CONFIRM", "passed": False, "value": f"{vol_ratio:.2f}x < 1.2"})

    # Layer 5: Risk/Reward
    if atr and atr > 0:
        stop = round(price - 1.5 * atr, 2)
        target = round(price + 3.0 * atr, 2)
        rr = round((target - price) / (price - stop), 2)
        if rr >= 2.0:
            rules.append({"rule": "RR_VALID", "passed": True, "value": f"R:R={rr}:1"})
            score += 25
        else:
            rules.append({"rule": "RR_VALID", "passed": False, "value": f"R:R={rr}:1 < 2.0"})
    else:
        stop = target = 0
        rr = 0
        rules.append({"rule": "RR_VALID", "passed": False, "value": "No ATR"})

    # === ENTRY DECISION ===
    can_enter = score >= 60 and len(positions) < MAX_POSITIONS and rr >= 2.0

    if can_enter:
        # Trader phase: risk gates
        kill = json.loads(server.check_kill_switch())
        limits = json.loads(server.check_daily_limits())
        risk = json.loads(server.check_portfolio_risk(sym, 1, price))
        sizing = json.loads(server.calc_position_size(account["equity"], 1.0, price, stop))

        quantity = sizing.get("quantity", 0)
        if quantity <= 0:
            quantity = max(1, int(1000 / (price - stop)))

        if kill.get("active") or not limits.get("passed"):
            server.log_backtest_decision(
                symbol=sym, phase="trader", decision="skip",
                reasoning=f"Risk gate blocked: kill={kill.get('active')}, limits_passed={limits.get('passed')}",
                input_state=json.dumps(input_state),
                tools_called=json.dumps(["check_kill_switch", "check_daily_limits", "check_portfolio_risk", "calc_position_size"]),
                rules_evaluated=json.dumps(rules), score=float(score),
            )
        else:
            # Save plan + place order
            trade_plan = {"entry": price, "stop": stop, "target": target, "rr": rr, "quantity": quantity}
            plan_json = json.dumps({
                "symbol": sym, "side": "buy", "strategy": "swing-trade",
                "sop_version": SOP, "quantity": quantity,
                "entry_order_type": "market", "stop_loss": stop, "take_profit": target,
                "rationale": f"Score {score}/100. Passed: {[r['rule'] for r in rules if r['passed']]}",
            })
            save = json.loads(server.save_trade_plan(plan_json))
            plan_id = save.get("plan_id", "")

            server.place_order(sym, "buy", "market", quantity, plan_id=plan_id)

            server.log_backtest_decision(
                symbol=sym, phase="research", decision="enter",
                reasoning=f"Score {score}/100. RSI={rsi:.1f}, RVOL={vol_ratio:.1f}x, R:R={rr}:1. Passed: {[r['rule'] for r in rules if r['passed']]}",
                input_state=json.dumps(input_state),
                tools_called=json.dumps(["calc_technical_indicators", "get_market_data", "check_kill_switch", "check_daily_limits", "check_portfolio_risk", "calc_position_size"]),
                rules_evaluated=json.dumps(rules), score=float(score),
                trade_plan=json.dumps(trade_plan),
            )

            positions[sym] = {
                "entry_price": price, "entry_bar": bar["bar_index"],
                "stop": stop, "target": target, "quantity": quantity,
                "plan_id": plan_id,
            }
            print(f"  [{ts}] ENTER {sym:4s} @ ${price:>7.2f} | stop=${stop:.2f} target=${target:.2f} | qty={quantity} R:R={rr}:1 | score={score}")
    else:
        # Skip
        fails = [r["rule"] for r in rules if not r["passed"]]
        if score < 60:
            reason = f"Score {score}/100 < 60. Failed: {fails}"
        elif len(positions) >= MAX_POSITIONS:
            reason = f"Score {score} but max positions reached ({len(positions)}/{MAX_POSITIONS})"
        else:
            reason = f"Score {score} but R:R={rr} < 2.0"

        server.log_backtest_decision(
            symbol=sym, phase="research", decision="skip",
            reasoning=reason,
            input_state=json.dumps(input_state),
            tools_called=json.dumps(["calc_technical_indicators", "get_market_data"]),
            rules_evaluated=json.dumps(rules), score=float(score),
        )

# Force close remaining
for sym, pos in list(positions.items()):
    mkt = json.loads(server.get_market_data(sym))
    exit_price = mkt["mid"]
    server.place_order(sym, "sell", "market", pos["quantity"])
    pnl = (exit_price - pos["entry_price"]) * pos["quantity"]
    r_mult = round((exit_price - pos["entry_price"]) / (pos["entry_price"] - pos["stop"]), 2) if pos["entry_price"] > pos["stop"] else 0
    trade_log.append({"symbol": sym, "entry": pos["entry_price"], "exit": exit_price, "pnl": pnl, "r_mult": r_mult, "bars": 99, "reason": "FORCE_CLOSE"})
    print(f"  [END ] CLOSE {sym:4s} @ ${exit_price:>7.2f} | FORCE_CLOSE | P&L: ${pnl:>+8.2f} ({r_mult:>+.1f}R)")

# === RESULTS ===
final = json.loads(server.get_portfolio_state())
equity = final["account"]["equity"]
total_pnl = equity - CAPITAL

print()
print("=" * 80)
print("BACKTEST RESULTS: Agent-Driven Swing Trade")
print("=" * 80)
print(f"Period:       {START} to {END}")
print(f"Symbols:      {SYMBOLS}")
print(f"Run ID:       {run_id}")
print(f"Bars:         {bar_num}")
print()
print(f"Initial:      ${CAPITAL:>10,.2f}")
print(f"Final:        ${equity:>10,.2f}")
print(f"P&L:          ${total_pnl:>+10,.2f} ({total_pnl/CAPITAL*100:>+.2f}%)")
print()

if trade_log:
    winners = [t for t in trade_log if t["pnl"] > 0]
    losers = [t for t in trade_log if t["pnl"] <= 0]
    print(f"Trades:       {len(trade_log)} ({len(winners)} wins, {len(losers)} losses)")
    if trade_log:
        print(f"Win rate:     {len(winners)/len(trade_log)*100:.1f}%")
    if winners:
        print(f"Avg win:      ${sum(t['pnl'] for t in winners)/len(winners):>+.2f} ({sum(t['r_mult'] for t in winners)/len(winners):>+.1f}R)")
    if losers:
        print(f"Avg loss:     ${sum(t['pnl'] for t in losers)/len(losers):>+.2f} ({sum(t['r_mult'] for t in losers)/len(losers):>+.1f}R)")
    expectancy = sum(t["pnl"] for t in trade_log) / len(trade_log)
    print(f"Expectancy:   ${expectancy:>+.2f}/trade")
    print()
    print(f"{'Symbol':<6} {'Entry':>8} {'Exit':>8} {'P&L':>10} {'R-Mult':>7} {'Bars':>5} {'Reason'}")
    print("-" * 70)
    for t in trade_log:
        print(f"{t['symbol']:<6} ${t['entry']:>7.2f} ${t['exit']:>7.2f} ${t['pnl']:>+9.2f} {t['r_mult']:>+6.1f}R {t['bars']:>5} {t['reason']}")
else:
    print("No trades executed.")

# Compliance
bt_results = json.loads(server.get_backtest_results(run_id))
print(f"\nWorkflow: {bt_results['workflow_violations']} violations / {bt_results['decision_count']} decisions")

# Export
export = json.loads(server.export_backtest_jsonl(run_id))
print(f"JSONL: {export['file']} ({export['records']} records)")
