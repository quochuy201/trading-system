# Alpaca API Research

## Overview
Alpaca is a developer-first trading API for stocks, options, and crypto. It's the most popular broker API for retail algorithmic trading.

---

## Paper Trading
- **Free real-time simulation** environment
- Same API endpoints as live trading (just different base URL)
- Simulates crypto trading as well
- Can reset and test algorithms unlimited times
- Uses real-time market data
- **Perfect for MVP development and testing**

---

## Asset Classes Supported
- **Stocks & ETFs**: Full support, 24/5 trading
- **Options**: Multi-leg (Level 3) trading available
- **Crypto**: Supported in paper and live

---

## Real-Time Data
- **WebSocket streaming** for trade, account, and order updates (RFC6455)
- **Real-time stock data**: Trades, quotes, bars via WebSocket
- **Real-time options data**: Options market data streaming
- **Free real-time market data** included with account
- Event streaming via WebSockets for ultra-low latency

---

## Order Types
- Market orders
- Limit orders
- Stop orders
- Stop-limit orders
- Trailing stop orders
- Multi-leg options orders (spreads, iron condors, etc.)

---

## Key Features for Our System
1. **Paper trading API** — identical to live, perfect for MVP
2. **WebSocket streaming** — real-time price data for agents
3. **Options support** — multi-leg strategies available
4. **CLI for Trading API** (May 2026) — 108 trading functions, designed for agentic AI
5. **24/5 access** — always-on trading with session-aware routing
6. **Historical data** — available for backtesting

---

## API Architecture
- REST API for orders, positions, account
- WebSocket for real-time streaming (market data + trade updates)
- Python SDK available (`alpaca-trade-api`)
- Simple authentication (API key + secret)

---

## Relevance to Our System
- **MVP broker**: Paper trading for development, same code goes live
- **Broker abstraction**: Clean REST + WebSocket API makes it easy to abstract
- **Real-time streaming**: Feeds directly into agent monitoring loop
- **Options**: Supports our future options trading agents
- **CLI + Agentic AI**: Alpaca explicitly building for AI agent use cases

---

## Sources
- https://alpaca.markets/docs/paper-trading
- https://docs.alpaca.markets/docs/real-time-option-data
- https://docs.alpaca.markets/v1.1/docs/websocket-streaming
- https://blog.alpaca.markets/blog/alpaca-introduces-cli-for-trading-api/
- https://alpaca.markets/learn/how-to-trade-options-with-alpaca/
