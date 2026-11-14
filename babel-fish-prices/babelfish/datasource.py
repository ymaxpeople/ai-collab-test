"""Data sources: where pair states come from.

A data source returns PairState objects for the Phase 0 pairs plus an
optional anchor override. Two implementations:
- LiveDataSource: resolves pairs via Factory.getPair and reads reserves
  with eth_call (read-only). Used in normal mode.
- FixtureDataSource: serves the verified offline fixture data. Used when
  BABELFISH_FIXTURE=1 (demos and tests — no network at all).
"""

import time
from dataclasses import dataclass

from . import config, fixtures
from .rpc import RpcClient


@dataclass
class PairState:
    pair_address: str
    token0_symbol: str
    token1_symbol: str
    reserve0_raw: int
    reserve1_raw: int
    decimals0: int
    decimals1: int
    block_timestamp: int | None  # getReserves blockTimestampLast, if known
    fetched_at: float            # local time.time() of the fetch

    def reserve(self, symbol: str) -> float:
        """Human-unit reserve of one side of the pair."""
        if symbol == self.token0_symbol:
            return self.reserve0_raw / (10 ** self.decimals0)
        if symbol == self.token1_symbol:
            return self.reserve1_raw / (10 ** self.decimals1)
        raise KeyError(symbol)

    def price_of_in(self, base_symbol: str, quote_symbol: str) -> float:
        """How many `quote_symbol` one `base_symbol` buys in this pool.

        Raises ValueError on a zero reserve instead of dividing by zero or
        returning a literal 0.0 price (prices are never reported as 0).
        """
        base = self.reserve(base_symbol)
        quote = self.reserve(quote_symbol)
        if base == 0 or quote == 0:
            raise ValueError(
                f"zero reserve in pair {self.pair_address} "
                f"({self.token0_symbol}/{self.token1_symbol})")
        return quote / base


def pair_key(sym_a: str, sym_b: str):
    return tuple(sorted((sym_a, sym_b)))


class LiveDataSource:
    def __init__(self, client: RpcClient | None = None):
        self.client = client or RpcClient()
        self._decimals_cache: dict[str, int] = {}
        self.last_errors: list[str] = []  # per-pair failures of last fetch

    def _decimals(self, symbol: str, address: str) -> int:
        known = config.TOKENS.get(symbol, (None, None))[1]
        if known is not None:
            return known
        if address not in self._decimals_cache:
            self._decimals_cache[address] = self.client.token_decimals(address)
        return self._decimals_cache[address]

    def fetch_pairs(self) -> dict:
        addr_to_symbol = {}
        for symbol, (address, _dec) in config.TOKENS.items():
            if address:
                addr_to_symbol[address.lower()] = symbol
        out = {}
        self.last_errors = []
        for sym_a, sym_b in config.PAIRS:
            # One broken pair must not fail the whole refresh (review
            # finding, 2026-11-14): skip it, remember why, keep the rest.
            try:
                state = self._fetch_one(sym_a, sym_b, addr_to_symbol)
            except Exception as exc:  # noqa: BLE001 - per-pair isolation
                self.last_errors.append(f"{sym_a}-{sym_b}: {exc}")
                continue
            if state is not None:
                out[pair_key(sym_a, sym_b)] = state
        # Total failure must NOT look like success (review finding N1,
        # 2026-11-14): if nothing could be fetched, or the 42-USDT anchor
        # pair failed, raise so the service keeps serving its previous
        # cache and reports the error instead of overwriting good prices
        # with an all-null result.
        if self.last_errors and not out:
            raise RuntimeError(
                "all pair fetches failed: " + "; ".join(self.last_errors))
        if pair_key("42", "USDT") not in out and any(
                e.startswith("42-USDT") for e in self.last_errors):
            raise RuntimeError(
                "anchor pair 42-USDT fetch failed: "
                + "; ".join(self.last_errors))
        return out

    def _fetch_one(self, sym_a, sym_b, addr_to_symbol):
        token_a = config.TOKENS[sym_a][0]
        token_b = config.TOKENS[sym_b][0]
        pair = self.client.get_pair(config.FACTORY_ADDRESS, token_a, token_b)
        if pair is None:
            return None
        t0 = self.client.pair_token0(pair)
        t1 = self.client.pair_token1(pair)
        r0, r1, block_ts = self.client.pair_reserves(pair)
        sym0 = addr_to_symbol.get(t0.lower())
        sym1 = addr_to_symbol.get(t1.lower())
        if sym0 is None or sym1 is None:
            return None  # unexpected token in pair; skip rather than guess
        return PairState(
            pair_address=pair,
            token0_symbol=sym0,
            token1_symbol=sym1,
            reserve0_raw=r0,
            reserve1_raw=r1,
            decimals0=self._decimals(sym0, t0),
            decimals1=self._decimals(sym1, t1),
            block_timestamp=block_ts or None,
            fetched_at=time.time(),
        )

    def anchor_override(self):
        return None  # live mode derives the anchor from the 42-USDT pair


class FixtureDataSource:
    """Offline source: only the pairs in fixtures.FIXTURE_PAIRS exist."""

    def __init__(self):
        self.last_errors: list[str] = []  # interface parity with live source

    def fetch_pairs(self) -> dict:
        now = time.time()
        out = {}
        for (sym_a, sym_b), kw in fixtures.FIXTURE_PAIRS.items():
            out[pair_key(sym_a, sym_b)] = PairState(fetched_at=now, **kw)
        return out

    def anchor_override(self):
        """(price_usd, confidence) for 42, supplied directly in fixture mode."""
        return (fixtures.FIXTURE_ANCHOR_PRICE_USD,
                fixtures.FIXTURE_ANCHOR_CONFIDENCE)


def make_data_source(fixture_mode: bool):
    return FixtureDataSource() if fixture_mode else LiveDataSource()
