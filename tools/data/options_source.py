"""Options data source adapter — fetch perishable options data LIVE, sanity-gated.

Default = Alpaca (INDICATIVE feed). Swappable via env `TRADING_OPTIONS_SOURCE`.
The ONLY persisted options data is iv_history (see capture_iv_universe); chains,
greeks, and quotes are never stored.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from data.options_validate import sanity_check_quote

if TYPE_CHECKING:
    from persistence.repository import Repository
    from broker.adapter import BrokerAdapter


class OptionsDataSource(ABC):
    @abstractmethod
    def get_chain(self, symbol: str, dte_min: int = 30, dte_max: int = 45) -> list[dict]:
        """Live option chain for symbol, filtered to [dte_min, dte_max] and sanity-gated."""

    @abstractmethod
    def get_snapshot(self, option_symbols: list[str]) -> list[dict]:
        """Live quote+greeks+IV for specific contracts, sanity-gated."""

    @abstractmethod
    def iv_rank(self, repo: "Repository", symbol: str, min_days: int = 60) -> dict:
        """IV-rank from accrued iv_history (read-only). {symbol,iv_rank,current_iv,data_points} or {error,...}."""


class AlpacaOptionsSource(OptionsDataSource):
    def __init__(self, broker: "BrokerAdapter"):
        self._broker = broker

    def get_chain(self, symbol: str, dte_min: int = 30, dte_max: int = 45) -> list[dict]:
        chain = self._broker.get_option_chain(underlying=symbol)
        out = []
        for c in chain:
            dte = c.get("dte", 0)
            if not (dte_min <= dte <= dte_max):
                continue
            ok, _ = sanity_check_quote(c)
            if ok:
                out.append(c)
        return out

    def get_snapshot(self, option_symbols: list[str]) -> list[dict]:
        snaps = self._broker.get_option_snapshot(option_symbols)
        return [s for s in snaps if sanity_check_quote(s)[0]]

    def capture_iv(self, repo: "Repository", symbols: list[str], today: str) -> dict:
        """Capture today's ATM IV30 for each symbol into iv_history (anomaly-gated)."""
        from analysis.options import atm_iv, nearest_dte_contracts
        from data.options_validate import iv_anomaly
        rows, skipped, anomalies = [], 0, 0
        for sym in symbols:
            try:
                chain = self._broker.get_option_chain(underlying=sym)
            except Exception:
                skipped += 1
                continue
            chain = nearest_dte_contracts(chain, target_dte=30)
            iv = atm_iv(chain)
            if iv is None:
                skipped += 1
                continue
            prior = repo.query_iv_history(sym, min_days=1)
            if iv_anomaly(prior[-1] if prior else None, iv):
                anomalies += 1
                continue
            rows.append({"symbol": sym, "date": today, "iv": iv, "source": "snapshot"})
        if rows:
            repo.save_iv_data_batch(rows)
        return {"captured": len(rows), "skipped": skipped, "anomalies": anomalies}

    def iv_rank(self, repo: "Repository", symbol: str, min_days: int = 60) -> dict:
        from analysis.options import calc_iv_rank
        hist = repo.query_iv_history(symbol, min_days=min_days)
        if not hist:
            return {"error": f"insufficient IV history for {symbol}",
                    "data_points": repo.count_iv_history(symbol)}
        current_iv = hist[-1]
        return {"symbol": symbol, "iv_rank": round(calc_iv_rank(current_iv, hist), 1),
                "current_iv": round(current_iv, 4), "data_points": len(hist)}


def get_options_source(broker, name: str | None = None) -> OptionsDataSource:
    """Return the configured options data source (env `TRADING_OPTIONS_SOURCE`, default alpaca)."""
    name = (name or os.environ.get("TRADING_OPTIONS_SOURCE", "alpaca")).lower()
    if name == "alpaca":
        return AlpacaOptionsSource(broker)
    raise ValueError(f"unknown options data source: {name!r}")
