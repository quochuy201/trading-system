"""Options data source adapter — fetch perishable options data LIVE, sanity-gated.

Default = Alpaca (INDICATIVE feed). Swappable via env `TRADING_OPTIONS_SOURCE`.
The ONLY persisted options data is iv_history (see capture_iv_universe); chains,
greeks, and quotes are never stored.
"""

import os
from abc import ABC, abstractmethod

from data.options_validate import sanity_check_quote


class OptionsDataSource(ABC):
    @abstractmethod
    def get_chain(self, symbol: str, dte_min: int = 30, dte_max: int = 45) -> list[dict]:
        """Live option chain for symbol, filtered to [dte_min, dte_max] and sanity-gated."""

    @abstractmethod
    def get_snapshot(self, option_symbols: list[str]) -> list[dict]:
        """Live quote+greeks+IV for specific contracts, sanity-gated."""


class AlpacaOptionsSource(OptionsDataSource):
    def __init__(self, broker):
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


def get_options_source(broker, name: str | None = None) -> OptionsDataSource:
    """Return the configured options data source (env `TRADING_OPTIONS_SOURCE`, default alpaca)."""
    name = (name or os.environ.get("TRADING_OPTIONS_SOURCE", "alpaca")).lower()
    if name == "alpaca":
        return AlpacaOptionsSource(broker)
    raise ValueError(f"unknown options data source: {name!r}")
