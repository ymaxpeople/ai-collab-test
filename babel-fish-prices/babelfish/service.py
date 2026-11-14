"""Price service: refresh orchestration, in-memory cache, response assembly.

Refresh is lazy (on read, when the cache is older than the interval) and
can also be driven by a background thread (see server.py). Every refresh
appends spot snapshots to the store, which is what TWAP reads.
"""

import threading
import time

from . import config
from .datasource import make_data_source
from .engine import PriceEngine
from .store import WINDOWS, SnapshotStore


class PriceService:
    def __init__(self, fixture_mode: bool | None = None, db_path: str | None = None,
                 refresh_interval: float | None = None, source=None):
        self.fixture_mode = config.FIXTURE_MODE if fixture_mode is None else fixture_mode
        self.source = source if source is not None else make_data_source(self.fixture_mode)
        # Fixture and live snapshots live in separate DBs by default, so
        # fixture values can never leak into live TWAP history.
        self.store = SnapshotStore(
            db_path or (config.FIXTURE_DB_PATH if self.fixture_mode
                        else config.DB_PATH))
        self.refresh_interval = (config.REFRESH_INTERVAL_SECONDS
                                 if refresh_interval is None else refresh_interval)
        self._lock = threading.Lock()
        self._cache = None        # {symbol: PriceResult}
        self._pairs = {}          # pair_key -> PairState
        self._cache_ts = 0.0
        self._last_error = None
        self._pair_errors = []    # per-pair failures of the last fetch

    # -- refresh -----------------------------------------------------------

    def refresh(self, force: bool = False) -> bool:
        with self._lock:
            if (not force and self._cache is not None
                    and time.time() - self._cache_ts < self.refresh_interval):
                return True
            try:
                pairs = self.source.fetch_pairs()
                engine = PriceEngine(pairs, anchor_override=self.source.anchor_override())
                results = engine.compute_all()
            except Exception as exc:  # noqa: BLE001 - keep serving stale cache
                self._last_error = str(exc)
                self._pair_errors = list(
                    getattr(self.source, "last_errors", []) or [])
                return self._cache is not None
            self._pairs = pairs
            self._cache = results
            self._cache_ts = time.time()
            self._last_error = None
            # Partial failures stay visible instead of being swallowed.
            self._pair_errors = list(
                getattr(self.source, "last_errors", []) or [])
            rows = [(r.symbol, r.address, r.price) for r in results.values()
                    if r.price is not None and r.address]
            if rows:
                self.store.add_snapshots(self._cache_ts, rows)
            return True

    def _ensure_fresh(self):
        if self._cache is None or time.time() - self._cache_ts >= self.refresh_interval:
            self.refresh()

    # -- queries -------------------------------------------------------------

    def health(self) -> dict:
        degraded = self._last_error is not None or bool(self._pair_errors)
        return {
            "status": "degraded" if degraded else "ok",
            "chain_id": config.CHAIN_ID,
            "mode": "fixture" if self.fixture_mode else "live",
            "last_refresh_ts": self._cache_ts or None,
            "last_error": self._last_error,
            "pair_errors": self._pair_errors,
            "tokens_priced": (sum(1 for r in self._cache.values()
                                  if r.price is not None)
                              if self._cache else 0),
        }

    def _with_divergence(self, result_dict: dict, address: str | None) -> dict:
        result_dict["divergence_warning"] = False
        if address and result_dict.get("price") is not None:
            t = self.store.twap(address, WINDOWS["1h"])
            if t["twap"]:
                spot = result_dict["price"]
                if abs(spot - t["twap"]) / t["twap"] > config.DIVERGENCE_THRESHOLD:
                    result_dict["divergence_warning"] = True
        return result_dict

    def prices(self) -> dict:
        self._ensure_fresh()
        if self._cache is None:
            return {"chain_id": config.CHAIN_ID,
                    "mode": "fixture" if self.fixture_mode else "live",
                    "reference_only": True, "generated_at": None,
                    "stale": False, "error": self._last_error,
                    "partial": bool(self._pair_errors),
                    "pair_errors": self._pair_errors, "tokens": []}
        tokens = []
        for symbol in self._ordered_symbols():
            r = self._cache[symbol]
            tokens.append(self._with_divergence(r.to_dict(), r.address))
        return {
            "chain_id": config.CHAIN_ID,
            "mode": "fixture" if self.fixture_mode else "live",
            "reference_only": True,  # prices are indicative, not lending-grade
            "generated_at": self._cache_ts,
            "stale": self._last_error is not None and self._cache is not None,
            "partial": bool(self._pair_errors),
            "pair_errors": self._pair_errors,
            "tokens": tokens,
        }

    def _ordered_symbols(self):
        head = ["USDT", "42", "FISH", "PANIC", "MARVIN", "ZAP", "FOXXEY", "KET"]
        rest = [s for s in self._cache if s not in head]
        return [s for s in head if s in self._cache] + sorted(rest)

    def price_by_address(self, address: str):
        self._ensure_fresh()
        if not self._cache:
            return None
        for r in self._cache.values():
            if r.address and r.address.lower() == address.lower():
                return self._with_divergence(r.to_dict(), r.address)
        return None

    def twap(self, address: str, window: str) -> dict | None:
        self._ensure_fresh()
        if not self._cache:
            return None
        match = None
        for r in self._cache.values():
            if r.address and r.address.lower() == address.lower():
                match = r
                break
        if match is None:
            return None
        # Look up by the token's canonical address, not the raw user input
        # (whose casing may differ from what was stored).
        t = self.store.twap(match.address, WINDOWS[window])
        spot = match.price
        divergence = False
        if t["twap"] and spot is not None:
            divergence = (abs(spot - t["twap"]) / t["twap"]
                          > config.DIVERGENCE_THRESHOLD)
        return {
            "symbol": match.symbol,
            "address": match.address,
            "window": window,
            "twap": t["twap"],
            "spot": spot,
            "divergence_warning": divergence,
            "snapshots": t["snapshots"],
            "note": t["note"],
        }

    def pairs(self) -> list:
        self._ensure_fresh()
        out = []
        for _key, s in sorted(self._pairs.items()):
            out.append({
                "pair": f"{s.token0_symbol}-{s.token1_symbol}",
                "pair_address": s.pair_address,
                "token0": s.token0_symbol,
                "token1": s.token1_symbol,
                "reserve0": s.reserve(s.token0_symbol),
                "reserve1": s.reserve(s.token1_symbol),
                "block_timestamp": s.block_timestamp,
            })
        return out
