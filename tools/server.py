"""Trading Tools MCP Server.

Exposes broker, data, analysis, risk, and persistence tools
to the trading system agents via Model Context Protocol.
"""

import json
import os
from pathlib import Path
from datetime import datetime

# Load .env from project root
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from mcp.server.fastmcp import FastMCP

from broker.alpaca import AlpacaBrokerAdapter
from broker.retry import RetryConfig, with_retry
from models import to_json
from persistence.repository import Repository

mcp = FastMCP("trading-tools")

# --- Globals (initialized lazily) ---

_broker: AlpacaBrokerAdapter | None = None
_repo: Repository | None = None
_retry_config = RetryConfig()


def get_broker() -> AlpacaBrokerAdapter:
    global _broker
    if _broker is None:
        _broker = AlpacaBrokerAdapter(
            api_key=os.environ.get("ALPACA_API_KEY"),
            secret_key=os.environ.get("ALPACA_SECRET_KEY"),
            paper="paper" in os.environ.get("ALPACA_BASE_URL", "paper"),
        )
    return _broker


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository()
    return _repo


def _get_platform() -> str:
    from broker.simulation import SimulationBrokerAdapter
    if isinstance(_broker, SimulationBrokerAdapter):
        return "simulation"
    url = os.environ.get("ALPACA_BASE_URL", "paper")
    if "paper" in url:
        return "alpaca_paper"
    return "alpaca_live"


def _log_to_ledger(
    action: str, symbol: str, quantity: int, order_type: str,
    price: float, status: str, broker_order_id: str = "",
    plan_id: str = "", decision_id: str = "", sop_version: str = "",
    trigger: str = "agent", notes: str = "",
    pnl: float | None = None, pnl_pct: float | None = None,
    entry_price: float | None = None,
) -> None:
    """Write a single ledger entry. Fire-and-forget — never raises."""
    from models import LedgerEntry
    try:
        broker = get_broker()
        acct = broker.get_account()
    except Exception:
        acct = {"equity": 0, "cash": 0, "buying_power": 0}
    try:
        get_repo().save_ledger_entry(LedgerEntry(
            action=action, symbol=symbol, quantity=quantity,
            order_type=order_type, price=price,
            total_cost=round(price * quantity, 2) if price and quantity else 0,
            status=status, broker_order_id=broker_order_id,
            account_equity=acct.get("equity", 0),
            account_cash=acct.get("cash", 0),
            buying_power=acct.get("buying_power", 0),
            pnl=pnl, pnl_pct=pnl_pct, entry_price=entry_price,
            plan_id=plan_id, decision_id=decision_id,
            sop_version=sop_version, platform=_get_platform(),
            trigger=trigger, notes=notes,
        ))
    except Exception:
        pass  # never block trading


def _track_tool(name: str) -> None:
    """Register a tool call with the backtest harness (if active) for server-side validation."""
    if _harness is not None:
        _harness.record_tool_call(name)


# --- Broker Tools ---


@mcp.tool()
def get_positions() -> str:
    """Get all open positions from the broker.

    When to use: Monitor agent checking current holdings, or before placing trades to assess exposure.

    Sample input: (no arguments)

    Expected output:
    [{"symbol": "NVDA", "quantity": 10, "side": "long", "entry_price": 220.50,
      "current_price": 225.30, "unrealized_pnl": 48.00, "unrealized_pnl_pct": 2.2}]
    """
    _track_tool("get_positions")
    broker = get_broker()
    positions = with_retry(broker.get_positions, _retry_config)()
    return json.dumps(positions)


@mcp.tool()
def get_account() -> str:
    """Get account summary including equity, cash, buying power, and daily P&L.

    When to use: Before trading to check available capital, or during monitoring to track daily performance.

    Sample input: (no arguments)

    Expected output:
    {"equity": 101936.54, "cash": 93363.45, "buying_power": 195299.99,
     "portfolio_value": 101936.54, "daily_pnl": -78.10}
    """
    broker = get_broker()
    account = with_retry(broker.get_account, _retry_config)()
    return json.dumps(account)


@mcp.tool()
def place_order(
    symbol: str, side: str, order_type: str, quantity: int,
    limit_price: float | None = None, stop_price: float | None = None,
    plan_id: str = "",
) -> str:
    """Place a buy or sell order via the broker. Blocked when kill switch is active.

    When to use: Trader agent executing entries/exits, or Monitor agent triggering stop-loss exits.

    Sample input: place_order("NVDA", "buy", "market", 10)
                  place_order("AAPL", "sell", "limit", 5, limit_price=310.00, plan_id="plan-001")

    Expected output:
    {"transaction_id": "3e9a466d-...", "plan_id": "plan-001", "symbol": "NVDA",
     "side": "buy", "order_type": "market", "quantity": 10, "price": 0.0,
     "broker_order_id": "3e9a466d-...", "status": "pending_new", "timestamp": "..."}

    If kill switch active:
    {"error": "Kill switch is active", "reason": "daily loss limit breached"}
    """
    if _kill_switch_state["active"]:
        return json.dumps({"error": "Kill switch is active", "reason": _kill_switch_state["reason"]})
    broker = get_broker()
    tx = with_retry(broker.place_order, _retry_config)(
        symbol=symbol, side=side, order_type=order_type,
        quantity=quantity, limit_price=limit_price, stop_price=stop_price,
    )
    tx.plan_id = plan_id
    if plan_id:
        get_repo().save_transaction(tx)
    # Auto-log to transaction ledger
    _log_to_ledger(
        action=side, symbol=symbol, quantity=quantity,
        order_type=order_type, price=tx.price, status=tx.status,
        broker_order_id=tx.broker_order_id, plan_id=plan_id,
    )
    return to_json(tx)


@mcp.tool()
def cancel_order(order_id: str) -> str:
    """Cancel a pending order by its broker order ID.

    When to use: Cancelling unfilled limit/stop orders, or during kill switch cleanup.

    Sample input: cancel_order("3e9a466d-1f1f-4038-acaa-b62954d29780")

    Expected output:
    {"cancelled": true, "order_id": "3e9a466d-1f1f-4038-acaa-b62954d29780"}
    """
    broker = get_broker()
    success = with_retry(broker.cancel_order, _retry_config)(order_id)
    # Auto-log to transaction ledger
    _log_to_ledger(
        action="cancel", symbol="", quantity=0, order_type="",
        price=0, status="cancelled" if success else "cancel_failed",
        broker_order_id=order_id, trigger="agent",
    )
    return json.dumps({"cancelled": success, "order_id": order_id})


# --- Data Tools ---


@mcp.tool()
def get_market_data(symbol: str) -> str:
    """Get the current real-time quote (bid, ask, mid price) for a symbol.

    When to use: Research agent scanning candidates, Monitor agent checking current price against stop/target levels.

    Sample input: get_market_data("AAPL")

    Expected output:
    {"symbol": "AAPL", "bid": 303.67, "ask": 303.69, "mid": 303.68,
     "bid_size": 200, "ask_size": 100, "timestamp": "2026-05-21T17:00:00+00:00"}
    """
    _track_tool("get_market_data")
    broker = get_broker()
    data = with_retry(broker.get_market_data, _retry_config)(symbol)
    return json.dumps(data)


@mcp.tool()
def get_historical_data(symbol: str, start: str, end: str, timeframe: str = "1Day") -> str:
    """Get historical OHLCV bars directly from the broker (not cached).

    When to use: One-off lookups for a specific date range. For bulk loading or repeated queries, use load_price_cache + query_price_cache instead.

    Sample input: get_historical_data("NVDA", "2026-05-01", "2026-05-21", "1Day")
                  get_historical_data("AAPL", "2026-05-21T09:30:00", "2026-05-21T16:00:00", "5Min")

    Expected output:
    [{"symbol": "NVDA", "timestamp": "2026-05-01T04:00:00+00:00", "open": 200.5,
      "high": 205.3, "low": 199.8, "close": 204.1, "volume": 45000000, "timeframe": "1Day"}, ...]

    Timeframe options: 1Min, 5Min, 15Min, 1Hour, 1Day.
    """
    broker = get_broker()
    bars = with_retry(broker.get_historical_data, _retry_config)(
        symbol=symbol,
        start=datetime.fromisoformat(start),
        end=datetime.fromisoformat(end),
        timeframe=timeframe,
    )
    return json.dumps(bars)


@mcp.tool()
def get_latest_bars(symbol: str, timeframe: str = "5Min", limit: int = 20) -> str:
    """Get the most recent N bars for a symbol for intraday analysis.

    When to use: Trader agent timing entries by checking recent price action, or Monitor agent evaluating intraday momentum.

    Sample input: get_latest_bars("TSLA", "5Min", 10)
                  get_latest_bars("AAPL", "1Min", 30)

    Expected output:
    [{"symbol": "TSLA", "timestamp": "2026-05-21T16:45:00+00:00", "open": 418.0,
      "high": 419.2, "low": 417.5, "close": 418.8, "volume": 120000, "timeframe": "5Min"}, ...]

    Note: Free Alpaca plan has 15-min delay on intraday data.
    Timeframe options: 1Min, 5Min, 15Min, 1Hour, 1Day.
    """
    from datetime import timedelta
    broker = get_broker()
    tf_minutes = {"1Min": 1, "5Min": 5, "15Min": 15, "1Hour": 60, "1Day": 1440}
    minutes = tf_minutes.get(timeframe, 5) * limit * 2  # buffer for market hours gaps
    # Use simulation time if in backtest mode, otherwise real time
    if hasattr(broker, 'current_time') and broker.current_time:
        end = broker.current_time
    else:
        end = datetime.utcnow() - timedelta(minutes=16)
    start = end - timedelta(minutes=minutes)
    bars = with_retry(broker.get_historical_data, _retry_config)(
        symbol=symbol, start=start, end=end, timeframe=timeframe,
    )
    return json.dumps(bars[-limit:] if len(bars) > limit else bars)


@mcp.tool()
def get_news(query: str) -> str:
    """Get recent news headlines for a symbol. Returns up to 10 articles from Alpaca News API.

    When to use: Research agent gathering sentiment and catalysts during candidate analysis.

    Sample input: get_news("NVDA")
                  get_news("AAPL")

    Expected output:
    [{"headline": "Nvidia Just Opened A $1.9 Billion Position...", "source": "benzinga",
      "symbols": ["NVDA", "AAPL"], "created_at": "2026-05-21T10:28:28+00:00",
      "url": "https://..."}, ...]
    """
    _track_tool("get_news")
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    from datetime import timedelta

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    client = NewsClient(api_key, secret_key)

    # During backtest: only fetch news published BEFORE current simulation time
    # At 9:30 AM: sees yesterday + overnight + pre-market headlines (not intraday)
    broker = get_broker()
    if hasattr(broker, "current_time") and broker.current_time:
        end_time = broker.current_time  # caps at sim clock (e.g., 9:30 AM or current bar time)
        start_time = end_time - timedelta(days=3)
        req = NewsRequest(symbols=query, start=start_time, end=end_time, limit=10)
    else:
        req = NewsRequest(symbols=query, limit=10)

    news_set = client.get_news(req)
    items = news_set.dict().get("news", [])
    return json.dumps([
        {
            "headline": item["headline"],
            "source": item["source"],
            "symbols": item["symbols"],
            "created_at": item["created_at"].isoformat() if hasattr(item["created_at"], "isoformat") else str(item["created_at"]),
            "url": item.get("url", ""),
        }
        for item in items
    ])


@mcp.tool()
def get_social_sentiment(symbol: str) -> str:
    """Get social media sentiment for a stock from Reddit and StockTwits.

    When to use: During Research DD, after get_news(), to check if retail traders
    are talking about this stock. Helps score the "convergence" dimension of catalyst
    scoring — multiple independent sources confirming = stronger signal.

    Sample input: get_social_sentiment("COP")

    Expected output:
    {"symbol": "COP", "reddit": {"mentions": 12, "sentiment": "bullish", "top_posts": [...]},
     "stocktwits": {"sentiment": "bullish", "volume": "high", "bullish_pct": 78},
     "convergence_signal": "strong"}

    Signals to look for:
    - Reddit mention spike (>5 posts in 24h for non-mega-cap) = retail attention
    - StockTwits bullish% > 70 + high volume = crowd consensus
    - Both aligned with Alpaca news = convergence score 2
    """
    _track_tool("get_social_sentiment")
    import requests

    result = {"symbol": symbol, "reddit": None, "stocktwits": None, "convergence_signal": "none"}

    # --- STOCKTWITS ---
    try:
        st_url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
        resp = requests.get(st_url, timeout=10, headers={"User-Agent": "TradingSystem/1.0"})
        if resp.status_code == 200:
            data = resp.json()
            messages = data.get("messages", [])
            if messages:
                # Sentiment field is often null — use keyword analysis on body text
                bullish_words = {"bull", "long", "calls", "moon", "buy", "rocket", "breakout", "upside", "rip"}
                bearish_words = {"bear", "short", "puts", "dump", "sell", "crash", "overvalued", "drop"}
                bullish = 0
                bearish = 0
                for m in messages:
                    # Check explicit sentiment tag first
                    sent = (m.get("entities") or {}).get("sentiment")
                    if sent and sent.get("basic") == "Bullish":
                        bullish += 1
                    elif sent and sent.get("basic") == "Bearish":
                        bearish += 1
                    else:
                        # Keyword fallback
                        body = m.get("body", "").lower()
                        if any(w in body for w in bullish_words):
                            bullish += 1
                        elif any(w in body for w in bearish_words):
                            bearish += 1

                total_sentiment = bullish + bearish
                bullish_pct = round(bullish / total_sentiment * 100) if total_sentiment > 0 else 50

                volume_label = "high" if len(messages) >= 20 else ("moderate" if len(messages) >= 8 else "low")
                sentiment_label = "bullish" if bullish_pct >= 65 else ("bearish" if bullish_pct <= 35 else "mixed")

                result["stocktwits"] = {
                    "message_count": len(messages),
                    "bullish_pct": bullish_pct,
                    "bearish_pct": 100 - bullish_pct if total_sentiment > 0 else 50,
                    "sentiment": sentiment_label,
                    "volume": volume_label,
                    "sample_messages": [m.get("body", "")[:120] for m in messages[:3]],
                }
    except Exception as e:
        result["stocktwits"] = {"error": str(e)}

    # --- REDDIT (r/wallstreetbets + r/stocks + r/investing) ---
    # Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET in .env
    # Register at: https://www.reddit.com/prefs/apps (script type app)
    try:
        reddit_client_id = os.environ.get("REDDIT_CLIENT_ID", "")
        reddit_client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")

        if not reddit_client_id:
            result["reddit"] = {"error": "REDDIT_CLIENT_ID not configured. Register at reddit.com/prefs/apps"}
        else:
            # OAuth app-only token (no user login needed for read access)
            auth = requests.auth.HTTPBasicAuth(reddit_client_id, reddit_client_secret)
            token_resp = requests.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=auth,
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": "TradingSystem/1.0"},
                timeout=10,
            )
            if token_resp.status_code != 200:
                result["reddit"] = {"error": f"Reddit auth failed: {token_resp.status_code}"}
            else:
                token = token_resp.json().get("access_token")
                reddit_headers = {
                    "Authorization": f"Bearer {token}",
                    "User-Agent": "TradingSystem/1.0",
                }

                subreddits = ["wallstreetbets", "stocks", "investing"]
                reddit_posts = []

                for sub in subreddits:
                    url = f"https://oauth.reddit.com/r/{sub}/search?q={symbol}&sort=new&t=week&limit=10&restrict_sr=on"
                    resp = requests.get(url, timeout=10, headers=reddit_headers)
                    if resp.status_code == 200:
                        posts = resp.json().get("data", {}).get("children", [])
                        for post in posts:
                            p = post.get("data", {})
                            title = p.get("title", "")
                            if symbol.upper() in title.upper() or f"${symbol}" in title:
                                reddit_posts.append({
                                    "title": title[:120],
                                    "subreddit": sub,
                                    "score": p.get("score", 0),
                                    "num_comments": p.get("num_comments", 0),
                                })

                # Deduplicate
                seen = set()
                unique = []
                for p in reddit_posts:
                    if p["title"] not in seen:
                        seen.add(p["title"])
                        unique.append(p)

                mention_count = len(unique)
                avg_score = sum(p["score"] for p in unique) / mention_count if mention_count > 0 else 0
                sentiment = "neutral"
                if mention_count >= 3 and avg_score > 50:
                    sentiment = "bullish"
                elif mention_count >= 3 and avg_score < -5:
                    sentiment = "bearish"
                elif mention_count >= 1:
                    sentiment = "mixed"

                result["reddit"] = {
                    "mentions_this_week": mention_count,
                    "avg_upvotes": round(avg_score),
                    "sentiment": sentiment,
                    "top_posts": sorted(unique, key=lambda x: -x["score"])[:5],
                }
    except Exception as e:
        result["reddit"] = {"error": str(e)}

    # --- CONVERGENCE SIGNAL ---
    st = result.get("stocktwits") or {}
    rd = result.get("reddit") or {}

    st_bullish = st.get("sentiment") == "bullish" and st.get("volume") in ("high", "moderate")
    rd_active = rd.get("mentions_this_week", 0) >= 3
    rd_bullish = rd.get("sentiment") == "bullish"

    if st_bullish and rd_bullish:
        result["convergence_signal"] = "strong"
    elif st_bullish or rd_active:
        result["convergence_signal"] = "moderate"
    else:
        result["convergence_signal"] = "weak"

    return json.dumps(result, default=str)


# --- Analysis Tools ---


@mcp.tool()
def score_catalyst(
    symbol: str,
    freshness: int,
    magnitude: int,
    priced_in: int,
    convergence: int,
    relevance: int,
    headline: str,
    thesis: str,
) -> str:
    """Score a catalyst on 5 dimensions (0-2 each). Total ≥ 7 = enter, < 7 = skip.

    When to use: MANDATORY before recommending any entry. After calling get_news()
    and reviewing headlines, score the catalyst to decide enter vs skip. This replaces
    gut-feel DD with a structured, auditable assessment.

    Scoring guide (each dimension 0-2):

    freshness: How recent is the catalyst?
      0 = >5 days old or no datable event
      1 = 2-5 days old
      2 = today or yesterday

    magnitude: How significant is the event?
      0 = "maintains/reiterates" or generic commentary
      1 = single analyst upgrade, single PT raise, minor news
      2 = earnings beat, multi-analyst convergence, major contract/deal

    priced_in: Has the stock already moved on this news?
      0 = stock already ran >5% in last 5 days
      1 = stock moved 2-5% (partially priced)
      2 = stock has NOT moved much yet (<2% in 5 days)

    convergence: Do multiple sources confirm the thesis?
      0 = only one weak source (single blog post, old article)
      1 = news + moderate volume OR news + some social buzz
      2 = analyst + news + volume spike + social buzz (multiple independent confirmations)

    relevance: How directly does this impact the company's revenue/earnings?
      0 = generic sector news, macro, no direct link
      1 = direct company news but unclear revenue impact
      2 = revenue-impacting: earnings, contract with $ amount, FDA approval, deal

    Sample input: score_catalyst("COP", 2, 2, 2, 2, 1,
                    "3 analysts raise PT: $115/$133/$114",
                    "Triple analyst upgrade on strong earnings + production guidance")

    Expected output (pass):
    {"symbol": "COP", "score": 9, "threshold": 7, "verdict": "ENTER", ...}

    Expected output (fail):
    {"symbol": "RTX", "score": 4, "threshold": 7, "verdict": "SKIP", ...}
    """
    _track_tool("score_catalyst")

    scores = {
        "freshness": min(max(freshness, 0), 2),
        "magnitude": min(max(magnitude, 0), 2),
        "priced_in": min(max(priced_in, 0), 2),
        "convergence": min(max(convergence, 0), 2),
        "relevance": min(max(relevance, 0), 2),
    }
    total = sum(scores.values())
    threshold = 7
    verdict = "ENTER" if total >= threshold else "SKIP"

    result = {
        "symbol": symbol,
        "scores": scores,
        "total": total,
        "threshold": threshold,
        "verdict": verdict,
        "headline": headline,
        "thesis": thesis,
    }

    # Log to ledger if backtest is active
    global _harness
    if _harness is not None:
        _harness.trade_log.append({
            "action": "catalyst_score",
            "symbol": symbol,
            "score": total,
            "verdict": verdict,
            "headline": headline,
            "thesis": thesis,
            "day": _harness.get_current_day(),
        })

    return json.dumps(result)


@mcp.tool()
def calc_technical_indicators(symbol: str, timeframe: str = "1Day") -> str:
    """Calculate technical indicators for a symbol using locally cached price data.

    When to use: Research agent scoring candidates on technical setup. Requires load_price_cache to be called first.

    Sample input: calc_technical_indicators("AAPL", "1Day")
                  calc_technical_indicators("NVDA", "5Min")

    Expected output:
    {"rsi": 76.06, "macd": 9.71, "macd_signal": 7.2, "macd_histogram": 2.51,
     "sma_20": 285.88, "sma_50": 270.15, "sma_200": 240.30, "atr": 5.97,
     "volume_sma_20": 52000000, "last_close": 303.68}

    Note: SMA values return None if insufficient data (need 50+ bars for SMA50, 200+ for SMA200).
    """
    _track_tool("calc_technical_indicators")
    from analysis.indicators import calc_technical_indicators as _calc
    from datetime import timedelta
    broker = get_broker()
    # Use simulation time if in backtest mode, otherwise real time
    if hasattr(broker, 'current_time') and broker.current_time:
        end = broker.current_time.strftime("%Y-%m-%d")
        start = (broker.current_time - timedelta(days=365)).strftime("%Y-%m-%d")
    else:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
    result = _calc(get_repo(), symbol, start, end, timeframe)
    return json.dumps(result)


@mcp.tool()
def load_price_cache(symbols: str, start: str, end: str, timeframe: str = "1Day") -> str:
    """Bulk load historical price data from broker into local SQLite cache.

    When to use: At the start of a research session to pre-load data for multiple symbols, enabling fast repeated queries and indicator calculations without hitting the broker API.

    Sample input: load_price_cache("AAPL,NVDA,TSLA", "2026-03-01", "2026-05-21", "1Day")
                  load_price_cache("SPY", "2026-05-21", "2026-05-21", "5Min")

    Expected output:
    {"symbols": ["AAPL", "NVDA", "TSLA"], "bars_loaded": 126, "timeframe": "1Day"}

    Timeframe options: 1Min, 5Min, 15Min, 1Hour, 1Day.
    """
    from data.cache import load_price_cache as _load
    symbol_list = [s.strip() for s in symbols.split(",")]
    result = _load(get_broker(), get_repo(), symbol_list, start, end, timeframe)
    return json.dumps(result)


@mcp.tool()
def query_price_cache(symbol: str, start: str, end: str, timeframe: str = "1Day") -> str:
    """Query locally cached price data. Returns OHLCV bars from SQLite (no broker API call).

    When to use: After load_price_cache, use this for fast repeated lookups during analysis or backtesting.

    Sample input: query_price_cache("AAPL", "2026-04-01", "2026-05-21", "1Day")

    Expected output:
    [{"symbol": "AAPL", "timestamp": "2026-04-01", "open": 280.5, "high": 283.1,
      "low": 279.2, "close": 282.0, "volume": 48000000, "timeframe": "1Day"}, ...]
    """
    from data.cache import query_price_cache as _query
    bars = _query(get_repo(), symbol, start, end, timeframe)
    return json.dumps(bars)


# --- Risk Tools ---


@mcp.tool()
def calc_position_size(
    account_value: float, risk_pct: float, entry_price: float, stop_loss: float
) -> str:
    """Calculate how many shares to buy based on account size and risk tolerance.

    When to use: Trader agent determining position size before placing an order. Ensures no single trade risks more than the specified percentage of account value.

    Sample input: calc_position_size(100000.0, 1.0, 220.0, 215.0)
                  (meaning: $100K account, risk 1%, enter at $220, stop at $215)

    Expected output:
    {"quantity": 200, "risk_amount": 1000.0, "risk_per_share": 5.0}
    (meaning: buy 200 shares, risking $1000 total, $5 per share to stop)
    """
    _track_tool("calc_position_size")
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share == 0:
        return json.dumps({"error": "Entry and stop loss cannot be the same"})
    risk_amount = account_value * (risk_pct / 100)
    quantity = int(risk_amount / risk_per_share)
    return json.dumps({
        "quantity": quantity,
        "risk_amount": round(risk_amount, 2),
        "risk_per_share": round(risk_per_share, 2),
    })


@mcp.tool()
def check_portfolio_risk(symbol: str, quantity: int, entry_price: float) -> str:
    """Validate a proposed trade against portfolio risk limits before execution.

    When to use: Trader agent must call this before every trade. Checks concentration limits (max % in one symbol), total exposure, and max number of positions.

    Sample input: check_portfolio_risk("NVDA", 10, 220.0)

    Expected output (passing):
    {"passed": true, "portfolio_value": 101950.12, "proposed_value": 2200.0,
     "checks": {"concentration": {"limit": 20.0, "actual": 2.16, "passed": true},
                "total_symbol_exposure": {"limit": 20.0, "actual": 2.16, "passed": true},
                "max_positions": {"limit": 5, "actual": 4, "passed": true}}}

    Expected output (failing):
    {"passed": false, ...checks with "passed": false for the breached limit...}
    """
    _track_tool("check_portfolio_risk")
    from risk.checks import check_portfolio_risk as _check
    result = _check(get_broker(), symbol, quantity, entry_price)
    return json.dumps(result)


@mcp.tool()
def check_daily_limits() -> str:
    """Check if the daily loss limit has been breached. Default limit: 3% of portfolio value.

    When to use: Orchestrator checks this before starting new trades. If failed, no new trades should be placed for the rest of the day.

    Sample input: (no arguments)

    Expected output (passing):
    {"passed": true, "daily_pnl": -64.72, "daily_pnl_pct": -0.06,
     "limit_pct": 3.0, "limit_amount": 3058.50, "remaining_budget": 2993.78}

    Expected output (failing):
    {"passed": false, "daily_pnl": -3200.00, "daily_pnl_pct": -3.14, ...}
    """
    _track_tool("check_daily_limits")
    from risk.checks import check_daily_limits as _check
    result = _check(get_broker())
    return json.dumps(result)


@mcp.tool()
def get_portfolio_state() -> str:
    """Get complete portfolio snapshot: account summary plus all open positions.

    When to use: Orchestrator getting full context before delegating to Trader or Monitor agents. Combines get_account + get_positions in one call.

    Sample input: (no arguments)

    Expected output:
    {"account": {"equity": 101936.54, "cash": 93363.45, "buying_power": 195299.99,
                 "portfolio_value": 101936.54, "daily_pnl": -78.10},
     "positions": [{"symbol": "NVDA", "quantity": 10, "side": "long",
                    "entry_price": 220.50, "current_price": 225.30,
                    "unrealized_pnl": 48.00, "unrealized_pnl_pct": 2.2}, ...]}
    """
    broker = get_broker()
    account = with_retry(broker.get_account, _retry_config)()
    positions = with_retry(broker.get_positions, _retry_config)()
    return json.dumps({"account": account, "positions": positions})


# --- Persistence Tools ---


@mcp.tool()
def save_trade_plan(plan_json: str) -> str:
    """Save a trade plan to the database for tracking and journaling.

    When to use: Trader agent saves the plan before executing, so Monitor agent can later reference stop/target levels and the EOD review can journal the rationale.

    Sample input: save_trade_plan('{"plan_id": "plan-001", "symbol": "NVDA", "side": "buy", "strategy": "day-trade-momentum", "sop_version": "v1.0.0", "quantity": 10, "entry_order_type": "market", "stop_loss": 215.0, "take_profit": 235.0, "rationale": "Strong RSI breakout with volume confirmation"}')

    Expected output:
    {"saved": true, "plan_id": "plan-001"}

    Required fields: symbol, side. Optional: plan_id (auto-generated if omitted), strategy, sop_version, quantity, entry_order_type, entry_limit_price, stop_loss, take_profit, trailing_stop, rationale.
    """
    from models import TradePlan, from_json
    plan = from_json(TradePlan, plan_json)
    get_repo().save_trade_plan(plan)
    return json.dumps({"saved": True, "plan_id": plan.plan_id})


@mcp.tool()
def save_transaction(transaction_json: str) -> str:
    """Save a trade transaction (execution record) to the database.

    When to use: After place_order succeeds, save the transaction linked to its trade plan for audit trail and EOD review.

    Sample input: save_transaction('{"transaction_id": "3e9a466d-...", "plan_id": "plan-001", "symbol": "NVDA", "side": "buy", "order_type": "market", "quantity": 10, "price": 220.50, "broker_order_id": "3e9a466d-...", "status": "filled"}')

    Expected output:
    {"saved": true, "transaction_id": "3e9a466d-..."}
    """
    from models import TradeTransaction, from_json
    tx = from_json(TradeTransaction, transaction_json)
    get_repo().save_transaction(tx)
    return json.dumps({"saved": True, "transaction_id": tx.transaction_id})


@mcp.tool()
def get_trade_plan(plan_id: str) -> str:
    """Retrieve a saved trade plan by its ID.

    When to use: Monitor agent looking up stop-loss/take-profit levels for an open position, or EOD review retrieving the original rationale.

    Sample input: get_trade_plan("plan-001")

    Expected output:
    {"plan_id": "plan-001", "symbol": "NVDA", "strategy": "day-trade-momentum",
     "sop_version": "v1.0.0", "side": "buy", "quantity": 10, "entry_order_type": "market",
     "entry_limit_price": null, "take_profit": 235.0, "stop_loss": 215.0,
     "trailing_stop": null, "time_stop": null, "risk_assessment": {},
     "rationale": "Strong RSI breakout...", "created_at": "2026-05-21T17:15:15"}

    If not found: {"error": "Plan not found"}
    """
    plan = get_repo().get_trade_plan(plan_id)
    if plan is None:
        return json.dumps({"error": "Plan not found"})
    return to_json(plan)


# --- Notifications ---


@mcp.tool()
def send_notification(message: str, severity: str = "info") -> str:
    """Send a Slack notification. Fire-and-forget — never blocks trading operations.

    When to use: After trade execution, position exits, daily summaries, or alerts. Severity controls the emoji prefix in the message.

    Sample input: send_notification("BUY 10 NVDA @ $220.50", "info")
                  send_notification("Daily loss limit at 80%", "warning")
                  send_notification("Kill switch activated", "critical")

    Expected output (webhook configured):
    {"sent": true, "status": 200}

    Expected output (no webhook):
    {"sent": false, "reason": "no webhook configured"}
    """
    from notifications.slack import send_slack_message, format_alert
    text = format_alert(message, severity) if severity != "info" else message
    result = send_slack_message(text)
    return json.dumps(result)


# --- Kill Switch ---

_kill_switch_state = {"active": False, "triggered_at": None, "reason": None}


@mcp.tool()
def check_kill_switch() -> str:
    """Check if the kill switch is active. Also detects KILL_SWITCH file in cwd or home directory.

    When to use: Orchestrator must call this before every workflow step. If active, halt all trading operations immediately.

    Sample input: (no arguments)

    Expected output (inactive):
    {"active": false, "triggered_at": null, "reason": null}

    Expected output (active):
    {"active": true, "triggered_at": "2026-05-21T17:15:47", "reason": "daily loss limit breached"}
    """
    _track_tool("check_kill_switch")
    import os
    from pathlib import Path
    # Check file-based trigger
    if Path("KILL_SWITCH").exists() or Path(os.path.expanduser("~/KILL_SWITCH")).exists():
        if not _kill_switch_state["active"]:
            _kill_switch_state["active"] = True
            _kill_switch_state["reason"] = "KILL_SWITCH file detected"
            _kill_switch_state["triggered_at"] = datetime.utcnow().isoformat()
    return json.dumps(_kill_switch_state)


@mcp.tool()
def activate_kill_switch(reason: str) -> str:
    """Emergency halt: closes all positions at market, blocks future orders, sends Slack alert.

    When to use: When daily loss limit is breached, circuit breaker triggers (10 consecutive broker failures), or manual emergency stop needed.

    Sample input: activate_kill_switch("daily loss limit breached")
                  activate_kill_switch("10 consecutive broker failures")

    Expected output:
    {"reason": "daily loss limit breached", "orders_cancelled": 2, "positions_closed": 5, "errors": []}

    Side effects: All positions sold at market, kill switch state set to active, Slack alert sent.
    """
    from notifications.slack import send_slack_message, format_alert

    _kill_switch_state["active"] = True
    _kill_switch_state["reason"] = reason
    _kill_switch_state["triggered_at"] = datetime.utcnow().isoformat()

    broker = get_broker()
    results = {"reason": reason, "orders_cancelled": 0, "positions_closed": 0, "errors": []}

    # Close all positions at market
    try:
        positions = broker.get_positions()
        for pos in positions:
            try:
                broker.place_order(
                    symbol=pos["symbol"], side="sell",
                    order_type="market", quantity=pos["quantity"],
                )
                _log_to_ledger(
                    action="sell", symbol=pos["symbol"], quantity=pos["quantity"],
                    order_type="market", price=pos.get("current_price", 0),
                    status="filled", trigger="kill_switch",
                    entry_price=pos.get("entry_price"),
                    notes=f"kill_switch: {reason}",
                )
                results["positions_closed"] += 1
            except Exception as e:
                results["errors"].append(f"Failed to close {pos['symbol']}: {e}")
    except Exception as e:
        results["errors"].append(f"Failed to get positions: {e}")

    # Send alert
    send_slack_message(format_alert(
        f"KILL SWITCH ACTIVATED: {reason}. Closed {results['positions_closed']} positions.",
        "critical",
    ))

    return json.dumps(results)


@mcp.tool()
def clear_kill_switch() -> str:
    """Clear the kill switch and resume normal trading operations.

    When to use: After investigating the cause of the kill switch activation and confirming it's safe to resume. Also removes any KILL_SWITCH file.

    Sample input: (no arguments)

    Expected output:
    {"cleared": true}
    """
    import os
    from pathlib import Path
    _kill_switch_state["active"] = False
    _kill_switch_state["reason"] = None
    _kill_switch_state["triggered_at"] = None
    for p in [Path("KILL_SWITCH"), Path(os.path.expanduser("~/KILL_SWITCH"))]:
        if p.exists():
            p.unlink()
    return json.dumps({"cleared": True})


# --- Audit Tools ---


@mcp.tool()
def log_decision(
    agent: str, action: str, symbol: str,
    rules_triggered: str, reasoning: str, sop_version: str,
    rules_considered: str = "", plan_id: str = "", market_context: str = "",
) -> str:
    """Log an AI decision with reasoning and rule tags. Fire-and-forget.

    When to use: Every agent must call this at every decision point — enter, exit, hold, skip, adjust. This is how we audit AI behavior and score compliance.

    Sample input: log_decision("trader", "enter", "NVDA", "RSI_OVERSOLD,VOLUME_CONFIRM", "Strong bounce off support with 2x volume", "v1.0.0", rules_considered="MACD_CROSS", plan_id="plan-001", market_context='{"price":220.5,"rsi":28}')

    Expected output:
    {"logged": true, "decision_id": "abc123def456"}
    """
    from models import DecisionLogEntry
    try:
        d = DecisionLogEntry(
            agent=agent, action=action, symbol=symbol,
            rules_triggered=[r.strip() for r in rules_triggered.split(",") if r.strip()],
            rules_considered=[r.strip() for r in rules_considered.split(",") if r.strip()],
            reasoning=reasoning, sop_version=sop_version,
            plan_id=plan_id,
            market_context=json.loads(market_context) if market_context else {},
        )
        get_repo().save_decision(d)
        return json.dumps({"logged": True, "decision_id": d.decision_id})
    except Exception as e:
        return json.dumps({"logged": False, "error": str(e)})


@mcp.tool()
def query_decisions(
    symbol: str = "", agent: str = "", action: str = "",
    sop_version: str = "", start_date: str = "", end_date: str = "",
    limit: int = 50,
) -> str:
    """Search and filter the AI decision log.

    When to use: Reviewing AI behavior — e.g., "show all exits for NVDA this week", "show all decisions by monitor agent", "show decisions with violations".

    Sample input: query_decisions(symbol="NVDA", action="exit", start_date="2026-05-20")
                  query_decisions(agent="trader", sop_version="v1.0.0", limit=10)

    Expected output:
    [{"decision_id": "abc123", "timestamp": "...", "agent": "trader", "action": "exit",
      "symbol": "NVDA", "rules_triggered": ["STOP_HIT"], "reasoning": "...", ...}, ...]
    """
    results = get_repo().query_decisions(
        symbol=symbol, agent=agent, action=action,
        sop_version=sop_version, start_date=start_date,
        end_date=end_date, limit=limit,
    )
    return json.dumps(results, default=str)


@mcp.tool()
def query_transaction_ledger(
    symbol: str = "", action: str = "", start_date: str = "",
    end_date: str = "", sop_version: str = "", platform: str = "",
    trigger: str = "", limit: int = 50,
) -> str:
    """Search and filter the transaction ledger (all buy/sell/cancel actions).

    When to use: Reviewing what actually happened at the broker — e.g., "show all sells triggered by kill switch", "show all AAPL transactions this week", "show all fills on alpaca_paper".

    Sample input: query_transaction_ledger(symbol="NVDA", action="buy", start_date="2026-05-20")
                  query_transaction_ledger(trigger="kill_switch")

    Expected output:
    [{"ledger_id": "...", "timestamp": "...", "action": "buy", "symbol": "NVDA",
      "quantity": 10, "price": 220.5, "account_equity": 101936.54,
      "platform": "alpaca_paper", "trigger": "agent", ...}, ...]
    """
    results = get_repo().query_ledger(
        symbol=symbol, action=action, start_date=start_date,
        end_date=end_date, sop_version=sop_version,
        platform=platform, trigger=trigger, limit=limit,
    )
    return json.dumps(results, default=str)


@mcp.tool()
def generate_performance_report(
    start_date: str, end_date: str, sop_version: str = "",
    export_format: str = "summary",
) -> str:
    """Generate a combined trading performance + AI compliance report.

    When to use: EOD review, weekly review, or on-demand evaluation of strategy performance and AI behavior. Compares SOP versions when multiple exist in the date range.

    Sample input: generate_performance_report("2026-05-01", "2026-05-21")
                  generate_performance_report("2026-05-01", "2026-05-21", sop_version="v1.0.0", export_format="markdown")

    Expected output (summary):
    {"trading": {"win_rate": 0.6, "profit_factor": 1.8, ...},
     "compliance": {"compliance_rate": 0.92, "violations": {...}},
     "report_id": "...", "saved": true}

    export_format options: "summary" (JSON in response), "markdown" (writes file, returns path)
    """
    from audit.compliance import score_decisions
    from audit.performance import calc_performance
    from models import PerformanceReport

    perf = calc_performance(get_repo(), start_date, end_date, sop_version)
    comp = score_decisions(get_repo(), start_date, end_date)

    metrics = {
        "trading": perf,
        "compliance": {
            "total_decisions": comp["total"],
            "compliant": comp["compliant"],
            "compliance_rate": comp["compliance_rate"],
            "by_type": comp["by_type"],
        },
    }

    # Save to DB
    report = PerformanceReport(
        report_type="on_demand", sop_version=sop_version,
        metrics=metrics,
    )
    from datetime import datetime
    report.start_date = datetime.fromisoformat(start_date) if start_date else report.start_date
    report.end_date = datetime.fromisoformat(end_date) if end_date else report.end_date
    get_repo().save_report(report)

    if export_format == "markdown":
        path = _write_report_markdown(report, metrics, start_date, end_date)
        return json.dumps({"report_id": report.report_id, "saved": True, "file": path})

    return json.dumps({"report_id": report.report_id, "saved": True, **metrics}, default=str)


@mcp.tool()
def get_compliance_score(start_date: str = "", end_date: str = "", sop_version: str = "") -> str:
    """Quick compliance percentage for a date range.

    When to use: Fast check on AI behavior without generating a full report.

    Sample input: get_compliance_score("2026-05-20", "2026-05-21")

    Expected output:
    {"compliance_rate": 0.92, "total_decisions": 25, "violations": 2, "by_type": {"PANIC_SELL": 1, "EARLY_EXIT": 1}}
    """
    from audit.compliance import score_decisions
    comp = score_decisions(get_repo(), start_date, end_date)
    return json.dumps({
        "compliance_rate": comp["compliance_rate"],
        "total_decisions": comp["total"],
        "violations": len(comp["violations"]),
        "by_type": comp["by_type"],
    })



def export_decisions(
    start_date: str, end_date: str, format: str = "json",
    symbol: str = "", sop_version: str = "",
) -> str:
    """Export decision log and transaction ledger as JSON or CSV file.

    When to use: Extracting data for external analysis in spreadsheets, notebooks, or dashboards.

    Sample input: export_decisions("2026-05-01", "2026-05-21", format="csv")
                  export_decisions("2026-05-15", "2026-05-21", format="json", symbol="NVDA")

    Expected output:
    {"file": "/path/to/exports/decisions_2026-05-01_to_2026-05-21.csv", "decisions": 25, "transactions": 12}
    """
    from pathlib import Path
    import csv

    repo = get_repo()
    decisions = repo.query_decisions(symbol=symbol, sop_version=sop_version,
                                     start_date=start_date, end_date=end_date, limit=10000)
    ledger = repo.query_ledger(symbol=symbol, sop_version=sop_version,
                               start_date=start_date, end_date=end_date, limit=10000)

    exports_dir = Path(__file__).parent.parent / "exports"
    exports_dir.mkdir(exist_ok=True)
    base = f"export_{start_date}_to_{end_date}"

    if format == "csv":
        # Decisions CSV
        dec_path = exports_dir / f"{base}_decisions.csv"
        if decisions:
            with open(dec_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=decisions[0].keys())
                w.writeheader()
                w.writerows(decisions)
        # Ledger CSV
        led_path = exports_dir / f"{base}_ledger.csv"
        if ledger:
            with open(led_path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=ledger[0].keys())
                w.writeheader()
                w.writerows(ledger)
        return json.dumps({"files": [str(dec_path), str(led_path)],
                          "decisions": len(decisions), "transactions": len(ledger)})
    else:
        path = exports_dir / f"{base}.json"
        path.write_text(json.dumps({"decisions": decisions, "transactions": ledger}, default=str, indent=2))
        return json.dumps({"file": str(path), "decisions": len(decisions), "transactions": len(ledger)})


def _write_report_markdown(report, metrics: dict, start_date: str, end_date: str) -> str:
    """Write a performance report as markdown file."""
    from pathlib import Path
    reports_dir = Path(__file__).parent.parent / "reports"
    reports_dir.mkdir(exist_ok=True)
    filename = f"report_{start_date}_to_{end_date}.md"
    path = reports_dir / filename

    trading = metrics["trading"]
    compliance = metrics["compliance"]

    lines = [
        f"# Performance Report: {start_date} to {end_date}",
        "",
        "## Trading Performance",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total Trades | {trading['total_trades']} |",
        f"| Win Rate | {trading['win_rate']:.1%} |",
        f"| Profit Factor | {trading['profit_factor']:.2f} |",
        f"| Expectancy | ${trading['expectancy']:.2f} |",
        f"| Total P&L | ${trading['total_pnl']:.2f} |",
        f"| Avg Winner | ${trading['avg_winner']:.2f} |",
        f"| Avg Loser | ${trading['avg_loser']:.2f} |",
        f"| Max Drawdown | ${trading['max_drawdown']:.2f} |",
        "",
        "## AI Compliance",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Compliance Rate | {compliance['compliance_rate']:.1%} |",
        f"| Total Decisions | {compliance['total_decisions']} |",
        f"| Violations | {compliance['total_decisions'] - compliance['compliant']} |",
        "",
    ]

    if compliance["by_type"]:
        lines.append("### Violations by Type")
        lines.append("")
        for vtype, count in compliance["by_type"].items():
            lines.append(f"- **{vtype}**: {count}")
        lines.append("")

    if trading.get("by_symbol"):
        lines.append("## By Symbol")
        lines.append("")
        lines.append("| Symbol | Trades | Win Rate | P&L |")
        lines.append("|--------|--------|----------|-----|")
        for sym, data in trading["by_symbol"].items():
            lines.append(f"| {sym} | {data['trades']} | {data['win_rate']:.1%} | ${data['total_pnl']:.2f} |")
        lines.append("")

    lines.append(f"*Generated: {report.generated_at.isoformat()}*")

    path.write_text("\n".join(lines))
    return str(path)


# --- Backtest v3 Tools ---

_harness = None
_original_broker = None  # saved before backtest, restored after


@mcp.tool()
def start_backtest_v2(
    symbols: str, start_date: str, end_date: str,
    lookback_start: str = "",
    timeframe: str = "1Hour", initial_capital: float = 100000.0,
    sop_version: str = "",
) -> str:
    """Initialize a backtest with daily-cycle + mechanical monitoring.

    When to use: Starting a new backtest session. Two modes:
    - Mode A (fixed list): symbols="NVDA,AMD" — skip scanner, DD these tickers each day
    - Mode B (scanner):    symbols="" — scan full config.yaml universe each day

    Sample input: start_backtest_v2("", "2026-02-03", "2026-02-28", "", "1Hour", 100000.0)
                  start_backtest_v2("NVDA,AMD", "2026-02-03", "2026-02-28", "", "1Hour", 100000.0)

    Expected output:
    {"run_id": "bt-abc123", "status": "ready", "mode": "scanner", "trading_days": 19, "monitor_timeframe": "1Hour"}

    IMPORTANT: lookback_start should be 3+ months before start_date so indicators can warm up.
    If omitted, defaults to 4 months before start_date.

    After calling this, use advance_to_next_day() to begin the first trading day.
    """
    from backtest.harness import BacktestHarness
    from datetime import datetime as dt, timedelta
    global _harness, _broker, _original_broker

    scanner_mode = not symbols.strip()

    if scanner_mode:
        # Full-market scan: use all symbols that have data in DB
        repo = get_repo()
        symbol_list = [
            r["symbol"] for r in
            repo.conn.execute(
                "SELECT DISTINCT symbol FROM price_data WHERE timeframe = '1Day'"
            ).fetchall()
        ]
        if "SPY" not in symbol_list:
            symbol_list.append("SPY")
    else:
        symbol_list = [s.strip() for s in symbols.split(",")]
        if "SPY" not in symbol_list:
            symbol_list.append("SPY")

    # Default lookback: 4 months before start
    if not lookback_start:
        start_dt = dt.fromisoformat(start_date)
        lookback_start = (start_dt - timedelta(days=120)).strftime("%Y-%m-%d")

    # Save original broker for restoration after backtest
    _original_broker = _broker

    # Load DAILY data for scanner (full universe + lookback)
    from data.cache import load_price_cache as _load
    _load(get_broker(), get_repo(), symbol_list, lookback_start, end_date, "1Day")

    # Also load intraday data for the monitor timeframe
    if timeframe != "1Day":
        _load(get_broker(), get_repo(), symbol_list, start_date, end_date, timeframe)

    _harness = BacktestHarness(get_repo())
    run_id = _harness.start(
        start_date=start_date,
        end_date=end_date,
        monitor_timeframe=timeframe,
        initial_capital=initial_capital,
        scanner_mode=scanner_mode,
        symbols=symbol_list if not scanner_mode else None,
        sop_version=sop_version,
    )

    # Swap global broker to simulation
    _broker = _harness.broker

    return json.dumps({
        "run_id": run_id,
        "status": "ready",
        "mode": "scanner" if scanner_mode else "fixed_list",
        "symbols_in_universe": len(symbol_list),
        "trading_days": len(_harness._trading_days),
        "monitor_timeframe": timeframe,
        "lookback_start": lookback_start,
    })


@mcp.tool()
def advance_to_next_day() -> str:
    """Move the backtest to the next trading day. Returns day info and portfolio state.

    When to use: At the start of each trading day in the backtest loop.
    After this returns, run the scanner (Mode B) or evaluate fixed tickers (Mode A),
    then call load_day_bars() with candidates, then step_bar() loop.

    Sample input: advance_to_next_day()

    Expected output:
    {"date": "2026-02-03", "day_number": 1, "total_days": 19, "open_positions": [...], "account": {...}}

    Returns {"done": true} when all trading days are exhausted.
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    result = _harness.advance_to_next_day()
    if result is None:
        return json.dumps({"done": True, "run_id": _harness.run_id})

    return json.dumps(result, default=str)


@mcp.tool()
def load_day_bars(symbols: str) -> str:
    """Load intraday bars for specific symbols for the current trading day.

    When to use: After scanner returns candidates (or for fixed list tickers),
    load their intraday data for monitoring. Also include symbols of open positions.

    Sample input: load_day_bars("NVDA,COP,MRK")

    Expected output:
    {"day": "2026-02-03", "symbols_loaded": {"NVDA": 7, "COP": 7, "MRK": 7}, "total_bars_per_symbol": 7}
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    symbol_list = [s.strip() for s in symbols.split(",")]
    result = _harness.load_day_bars(symbol_list)
    return json.dumps(result)


@mcp.tool()
def step_bar() -> str:
    """Advance one intraday bar and run mechanical checks on all open positions.

    When to use: After entries are decided for the day, call this repeatedly to
    step through intraday bars. Mechanical monitoring (stop/target/trail/time)
    runs automatically. You only need to act when events are returned.

    Sample input: step_bar()

    Expected output (nothing happened):
    {"status": "nothing", "bar_index": 3, "timestamp": "2026-02-03T17:00:00", "bars_remaining_today": 4}

    Expected output (exit triggered mechanically):
    {"status": "exits", "exits": [{"symbol": "NVDA", "exit_price": 186.24, "reason": "stop_loss", "pnl": -1017.70, ...}], ...}

    Expected output (event needs LLM judgment):
    {"status": "events", "events": [{"type": "large_drop", "symbol": "NVDA", "pct_change": -3.5, ...}], ...}

    Expected output (day is done):
    {"status": "day_complete", "day": "2026-02-03"}

    MECHANICAL CHECKS (automatic, no LLM needed):
    - Stop loss: previous bar closed below stop → exit at this bar's open
    - Take profit: bar high reaches target → exit at target price
    - Trailing stop: updates automatically; exits when broken
    - Time stop: exceeded max hold → exit at bar open

    EVENT TRIGGERS (LLM must evaluate):
    - large_drop: price dropped > 3% in one bar
    - approaching_stop: within 0.5% of stop loss
    - dead_money: held 5+ days, never reached +0.5R
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    result = _harness.step_bar()
    return json.dumps(result, default=str)


@mcp.tool()
def backtest_enter(
    symbol: str, side: str, entry_price: float, quantity: int,
    stop_loss: float, take_profit: float, atr: float,
    reasoning: str, time_stop_bars: int = 105,
) -> str:
    """Log a simulated trade entry during backtest.

    When to use: After DD passes and risk gates are clear. This replaces place_order
    during backtest — it logs the entry without sending a real order.

    Sample input: backtest_enter("NVDA", "long", 196.31, 101, 186.41, 226.01, 6.60,
                                 "MODERATE catalyst: gap +0.8% with 1.3x vol, RSI 58", 105)

    Expected output:
    {"action": "entry", "symbol": "NVDA", "price": 196.31, "quantity": 101, "stop_loss": 186.41, ...}

    The position will be monitored automatically by step_bar() mechanical checks.
    time_stop_bars default 105 = 15 trading days × 7 hourly bars/day.
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    result = _harness.enter_position(
        symbol=symbol, side=side, entry_price=entry_price,
        quantity=quantity, stop_loss=stop_loss, take_profit=take_profit,
        atr=atr, reasoning=reasoning, time_stop_bars=time_stop_bars,
    )
    return json.dumps(result, default=str)


@mcp.tool()
def backtest_exit(symbol: str, exit_price: float, reason: str) -> str:
    """Manually exit a position during backtest (LLM judgment call).

    When to use: When the LLM decides to exit a position that hasn't been
    mechanically stopped out (e.g., dead money, thesis broken, discretionary exit).

    Sample input: backtest_exit("NVDA", 192.50, "dead_money: 5 days, never reached +0.5R")

    Expected output:
    {"symbol": "NVDA", "exit_price": 192.50, "reason": "dead_money", "pnl": -385.81, ...}
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    result = _harness.exit_position(symbol, exit_price, reason)
    if result is None:
        return json.dumps({"error": f"No open position for {symbol}"})
    return json.dumps(result, default=str)


@mcp.tool()
def get_backtest_positions() -> str:
    """Get current open positions with full monitoring state.

    When to use: To see current positions, their stops, trails, and unrealized P&L.

    Sample input: get_backtest_positions()

    Expected output:
    [{"symbol": "NVDA", "entry_price": 196.31, "stop_loss": 186.41, "trailing_stop": 190.5, "bars_held": 15, ...}]
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active."})
    return json.dumps(_harness.get_open_positions())


@mcp.tool()
def log_backtest_decision(
    symbol: str, phase: str, decision: str, reasoning: str,
    input_state: str, rules_evaluated: str = "[]",
    score: float | None = None, trade_plan: str = "",
) -> str:
    """Log a decision during backtest. Only needed for entries, exits, and events.

    When to use: After making an entry/exit decision, or when responding to an event
    from step_bar(). NOT needed for routine "nothing happened" bars.

    Sample input: log_backtest_decision("NVDA", "research", "enter", "Strong catalyst...",
                  '{"price": 196.31, "rsi": 58}',
                  '[{"rule": "CATALYST_FRESH", "passed": true}]', 78,
                  '{"entry": 196.31, "stop": 186.41, "target": 226.01}')

    Phases: "research" (scan/DD), "trader" (entry execution), "monitor" (hold/exit)
    Decisions: "enter", "skip", "hold", "exit"
    """
    global _harness
    if _harness is None:
        return json.dumps({"error": "No backtest active. Call start_backtest_v2 first."})

    decision_id = _harness.logger.log_decision(
        run_id=_harness.run_id,
        bar_index=_harness._global_bar_idx,
        timestamp=_harness.get_current_day() or "",
        symbol=symbol,
        phase=phase,
        input_state=json.loads(input_state),
        tools_called=[],
        rules_evaluated=json.loads(rules_evaluated),
        score=score,
        decision=decision,
        reasoning=reasoning,
        trade_plan=json.loads(trade_plan) if trade_plan else None,
        workflow_valid=True,
        violation_details="",
    )

    return json.dumps({"decision_id": decision_id, "logged": True})


@mcp.tool()
def get_backtest_results(run_id: str = "") -> str:
    """Get the full results for a completed or active backtest.

    When to use: After a backtest completes (or while active), retrieve trades, metrics,
    and performance summary. If run_id is empty and a backtest is active, returns live results.

    Sample input: get_backtest_results("")          — current active backtest
                  get_backtest_results("bt-abc123") — historical run from DB

    Expected output:
    {"initial_capital": 100000, "final_equity": 102415, "total_pnl": 2415, "win_rate": 60.0, "trades": [...], ...}
    """
    global _harness

    # If active harness and no specific run_id (or matches active), use in-memory results
    if _harness is not None and (not run_id or run_id == _harness.run_id):
        _harness.force_close_all()
        results = _harness.get_results()
        results["run_id"] = _harness.run_id
        return json.dumps(results, default=str)

    # Otherwise query from DB
    repo = get_repo()
    run = repo.get_backtest_run(run_id)
    if not run:
        return json.dumps({"error": f"Run {run_id} not found"})
    trades = repo.get_backtest_trades(run_id)
    decisions = repo.get_backtest_decisions(run_id)
    violations = sum(1 for d in decisions if d["workflow_valid"] == 0)

    return json.dumps({
        "run": dict(run),
        "trades": trades,
        "decision_count": len(decisions),
        "workflow_violations": violations,
    }, default=str)


@mcp.tool()
def export_backtest_jsonl(run_id: str) -> str:
    """Export all decisions from a backtest run as a JSONL file for training pipelines.

    When to use: After a backtest, export structured decision logs for prompt engineering or fine-tuning.

    Sample input: export_backtest_jsonl("bt-abc123def456")

    Expected output:
    {"file": "/path/to/exports/bt-abc123def456.jsonl", "records": 84}
    """
    from backtest.logger import BacktestLogger

    repo = get_repo()
    logger = BacktestLogger(repo)

    lines = logger.export_jsonl(run_id)
    exports_dir = Path(__file__).parent.parent / "exports"
    exports_dir.mkdir(exist_ok=True)
    path = exports_dir / f"{run_id}.jsonl"
    path.write_text("\n".join(lines))

    return json.dumps({"file": str(path), "records": len(lines)})


@mcp.tool()
def load_market_data(
    symbols: str = "", start_date: str = "", end_date: str = "",
    timeframe: str = "1Day",
) -> str:
    """Bulk-load historical price data from the broker into the local cache.

    When to use: Before running a backtest on new symbols, or to expand the
    data universe for full-market scanning. Only loads symbols not already cached.

    Sample input: load_market_data("", "2025-10-01", "2026-02-28", "1Day")
                  — loads ALL tradeable symbols for the date range
                  load_market_data("NVDA,AMD", "2025-10-01", "2026-02-28", "1Hour")
                  — loads specific symbols with hourly data

    Expected output:
    {"loaded": 67, "skipped": 0, "total_bars": 13601, "timeframe": "1Day"}
    """
    from data.cache import load_price_cache

    broker = get_broker()
    repo = get_repo()

    if symbols.strip():
        symbol_list = [s.strip() for s in symbols.split(",")]
    else:
        symbol_list = broker.get_tradeable_universe()

    if not start_date or not end_date:
        return json.dumps({"error": "start_date and end_date are required"})

    # Skip symbols already cached for this range/timeframe
    to_load = []
    for sym in symbol_list:
        existing = repo.query_price_data(sym, start_date, end_date + "T23:59:59", timeframe)
        if len(existing) < 10:
            to_load.append(sym)

    result = load_price_cache(broker, repo, to_load, start_date, end_date, timeframe)
    return json.dumps({
        "loaded": len(to_load),
        "skipped": len(symbol_list) - len(to_load),
        "total_bars": result["bars_loaded"],
        "timeframe": timeframe,
    })


@mcp.tool()
def scan_for_candidates(symbols: str = "", lookback_days: int = 120) -> str:
    """Scan the market through the 4-layer filter to find tradeable candidates.

    When to use: At the start of each trading day (or backtest day) to identify
    stocks that pass quantitative filters. Candidates are then evaluated by the
    AI agent for Due Diligence (news, catalyst, final decision).

    This is the SAME code path used in both live trading and backtesting.

    Sample input: scan_for_candidates("", 120)         — scan entire market
                  scan_for_candidates("NVDA,AMD", 120) — scan specific tickers only

    If symbols is empty: scans the FULL tradeable market (all symbols with data).
    Always includes SPY for relative strength calculation.

    Expected output:
    {"candidates": [{"symbol": "NVDA", "price": 220.50, "atr": 8.34, "rvol": 1.8, "rs_10d": 5.2, "rsi": 58.3, ...}], "scanned": 67, "passed": 3}

    Filters applied (always on DAILY bars):
    1. Liquidity: price $10-500, avg vol > 2M, ATR 1.5-5%, RVOL > 1.1x
    2. Relative Strength: outperforming SPY by > 2% over 10 days
    3. Trend: above SMA20, SMA20 > SMA50 (aligned)
    4. Momentum: RSI 40-70, MACD bullish, not at upper Bollinger
    5. Anti-chase: reject if near 10d high AND ran >5% in 5 days
    """
    _track_tool("scan_for_candidates")
    import pandas as pd
    from scanner.filters import scan_universe

    broker = get_broker()
    repo = get_repo()

    if symbols.strip():
        symbol_list = [s.strip() for s in symbols.split(",")]
    else:
        symbol_list = broker.get_tradeable_universe()

    if "SPY" not in symbol_list:
        symbol_list.append("SPY")

    # Load data for all symbols
    from datetime import timedelta
    if hasattr(broker, "current_time") and broker.current_time:
        end = broker.current_time
    else:
        end = datetime.utcnow()
    start = end - timedelta(days=lookback_days)

    stock_data = {}
    for sym in symbol_list:
        bars = repo.query_price_data(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%dT%H:%M:%S"), "1Day")
        if len(bars) >= 50:
            df = pd.DataFrame(bars)
            df["close"] = df["close"].astype(float)
            df["high"] = df["high"].astype(float)
            df["low"] = df["low"].astype(float)
            df["volume"] = df["volume"].astype(float)
            stock_data[sym] = df

    spy_data = stock_data.get("SPY")
    candidates = scan_universe(stock_data, spy_data)

    return json.dumps({
        "candidates": candidates,
        "scanned": len(stock_data) - (1 if "SPY" in stock_data else 0),
        "passed": len(candidates),
    })


@mcp.tool()
def end_backtest() -> str:
    """End the current backtest and restore the live/paper broker.

    When to use: After a backtest is complete, call this to restore normal trading mode.
    All subsequent MCP tool calls will use the real broker (live or paper) again.

    Sample input: end_backtest()

    Expected output:
    {"ended": true, "run_id": "bt-abc123", "broker_restored": true}
    """
    global _harness, _broker, _original_broker
    if _harness is None:
        return json.dumps({"error": "No backtest active."})

    run_id = _harness.run_id

    # Restore original broker
    if _original_broker is not None:
        _broker = _original_broker
        _original_broker = None
        restored = True
    else:
        _broker = None  # will be lazily re-initialized
        restored = True

    _harness = None

    return json.dumps({"ended": True, "run_id": run_id, "broker_restored": restored})


if __name__ == "__main__":
    mcp.run()
