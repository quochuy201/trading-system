# Scan Funnel Observability Implementation Summary

## Overview
The scan-funnel observability feature has been successfully implemented in the Hermes trading system. This feature provides end-to-end visibility into the trading decision process by mechanically persisting scan funnel data that is independent of agent logging.

## Components Implemented

### 1. Database Persistence Layer
- **File:** `/Users/zelyuh/workplace/trading-system/tools/persistence/db.py`
  - Added `scan_funnel` table to the SCHEMA with fields:
    - date, timestamp, scan_type, universe_size, loaded, scanned, passed
    - passed_m, passed_r (engine-specific passes for swing scan)
    - data_stale flag, as_of timestamp, candidates JSON array
- **File:** `/Users/zelyuh/workplace/trading-system/tools/persistence/repository.py`
  - Added `save_scan_funnel(row)` and `query_scan_funnel(date)` methods

### 2. Scan Tool Modifications (Telemetry-Only)
- **File:** `/Users/zelyuh/workplace/trading-system/tools/server.py`
  - **`scan_swing_candidates()`** (lines ~2550-2572):
    - Persists funnel data with engine-specific metrics (passed_m, passed_r)
    - Stores candidate symbols with engine pass/fail flags
    - Wrapped in try/catch to ensure telemetry never breaks scanning
  - **`scan_for_candidates()`** (lines ~2438-2457):
    - Persists funnel data for 4-layer scan
    - Stores candidate symbols only (no engine flags for this scan type)
    - Wrapped in try/catch for zero-impact telemetry

### 3. Funnel Assembly & Reporting
- **File:** `/Users/zelyuh/workplace/trading-system/tools/server.py`
  - **`get_daily_funnel(date)`** MCP tool (lines 1254-1297):
    - Assembles complete decision funnel: scan data + agent decisions + orders
    - Calculates enters, skips, and orders placed
    - Generates `why_zero` field explaining lack of trades
    - Available as MCP tool for EOD agent and manual use
  - **`generate_performance_report()`** (line 1212):
    - Automatically includes funnel data in metrics
  - **`_write_report_markdown()`** (lines 1403-1426):
    - Renders formatted funnel section in markdown reports
    - Shows scanned/passed counts, engine breakdown, data freshness
    - Displays entered/skipped/ordered counts and why_zero explanation

### 4. Skill Updates (Decision Logging Requirements)
- **File:** `/Users/zelyuh/workplace/trading-system/skills/research/SKILL.md`
  - Lines 329-341: Explicitly requires logging `log_decision` for EACH candidate
  - `action="enter"` for picks AND `action="skip"` for rejections
  - Mandatory for funnel reconstruction: "One `log_decision` per candidate"
- **File:** `/Users/zelyuh/workplace/trading-system/skills/eod-review/SKILL.md`
  - Lines 110-114: Requires `get_daily_funnel(<today>)` on zero-trade days
  - Mandatory recording of `why_zero` verdict with 3 specific cases:
    - `0 passed mechanical` (no setups)
    - `N passed, 0 entered` (agent skipped all)
    - `DATA_STALE` (stale data issue)

### 5. Test Suite
- **File:** `/Users/zelyuh/workplace/trading-system/tools/tests/test_scan_funnel.py`
  - Tests repository persistence methods
  - Tests scan tools persist funnel data correctly
  - Tests report markdown includes funnel section
- **File:** `/Users/zelyuh/workplace/trading-system/tools/tests/test_daily_funnel.py`
  - Tests zero-day funnel assembly (why_zero generation)
  - Tests same-day boundary conditions for decisions/orders
- **File:** `/Users/zelyuh/workplace/trading-system/tools/tests/test_scan_funnel.py` (existing)
  - `test_report_markdown_includes_funnel` validates report rendering

## Verification
All tests pass:
- `test_scan_funnel.py`: 3/3 passed
- `test_daily_funnel.py`: 2/2 passed
- Related component tests (broker, models, scanners) continue to pass

## Key Properties
✅ **Telemetry-only**: Scan funnel persistence never affects trading decisions  
✅ **Error isolated**: Try/catch ensures DB failures don't break scanning  
✅ **Backtest/live parity**: Same code path used in both modes  
✅ **Complete audit trail**: Scan → Agent decisions → Orders → Funnel reconstruction  
✅ **Zero-trade visibility**: Explains why no trades occurred on quiet days  

## Next Steps
1. **Deployment**: Run `./install.sh hermes` to deploy to Hermes trading system
2. **Validation**: Monitor EOD reports and verify funnel data appears correctly
3. **Utilization**: EOD agent will automatically use funnel data for zero-trade day explanations

The implementation satisfies all requirements from the observability design spec and provides the transparency needed for effective trading system oversight and debugging.