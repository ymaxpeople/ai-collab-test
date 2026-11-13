"""Price engine: spot prices from pair reserves, route resolution,
liquidity estimates and confidence labels.

Rules (design draft v0.1, approved 2026-11-12):
- Route priority: direct USDT pair -> via 42 -> via FISH -> price null.
  A price is NEVER reported as 0; unroutable tokens get price None.
- Confidence grades from the token's first-hop pool liquidity and hop
  count, with a 1-grade downgrade at 3 hops. When 24h volume or last-trade
  age are known they can only lower the grade (in Phase 0 they are mostly
  unknown and are then ignored — see README "limits").
- Anchor cap: no derived price's confidence may exceed the confidence of
  the 42 anchor itself.
"""

import time
from dataclasses import dataclass, field

from . import config
from .datasource import pair_key

GRADE_RANK = {"unpriced": 0, "C": 1, "B": 2, "A": 3}
RANK_GRADE = {v: k for k, v in GRADE_RANK.items()}


def _min_grade(a: str, b: str) -> str:
    return a if GRADE_RANK[a] <= GRADE_RANK[b] else b


def _downgrade(grade: str, steps: int = 1) -> str:
    return RANK_GRADE[max(0, GRADE_RANK[grade] - steps)]


def grade_pool(liquidity_usd, hops, volume_24h_usd=None, last_trade_age_s=None):
    """Confidence grade for one token price from its first-hop pool."""
    if liquidity_usd is None or liquidity_usd < config.CONF_C_MIN_LIQUIDITY:
        return "unpriced"
    if liquidity_usd >= config.CONF_A_MIN_LIQUIDITY and hops <= 2:
        grade = "A"
    elif liquidity_usd >= config.CONF_B_MIN_LIQUIDITY and hops <= 2:
        grade = "B"
    else:
        grade = "C"
    if hops >= 3:
        grade = _downgrade(grade, 1)
    if volume_24h_usd is not None:
        if volume_24h_usd < config.CONF_B_MIN_VOLUME_24H:
            grade = _min_grade(grade, "C")
        elif volume_24h_usd < config.CONF_A_MIN_VOLUME_24H:
            grade = _min_grade(grade, "B")
    if last_trade_age_s is not None:
        if last_trade_age_s > 7 * 86400:
            return "unpriced"
        if last_trade_age_s > 86400:
            grade = _min_grade(grade, "C")
        elif last_trade_age_s > 6 * 3600:
            grade = _min_grade(grade, "B")
    return grade


@dataclass
class PriceResult:
    symbol: str
    address: str | None
    price: float | None = None
    liquidity_usd: float | None = None
    staleness_seconds: float | None = None
    confidence: str = "unpriced"
    route: list = field(default_factory=list)
    note: str | None = None

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "address": self.address,
            "price": self.price,
            "liquidity_usd": self.liquidity_usd,
            "staleness_seconds": self.staleness_seconds,
            "confidence": self.confidence,
            "route": self.route,
        }


class PriceEngine:
    """Pure computation over a set of PairStates (no I/O)."""

    def __init__(self, pairs: dict, anchor_override=None, now: float | None = None):
        self.pairs = pairs  # pair_key -> PairState
        self.anchor_override = anchor_override
        self.now = now if now is not None else time.time()

    # -- pool helpers ------------------------------------------------------

    def _pair(self, sym_a, sym_b):
        return self.pairs.get(pair_key(sym_a, sym_b))

    def _pool_liquidity_usd(self, state, prices: dict):
        """Total USD value of both sides of a pool, using prices known so
        far. Returns None if either side is unpriced."""
        total = 0.0
        for sym in (state.token0_symbol, state.token1_symbol):
            p = prices.get(sym)
            if p is None:
                return None
            total += state.reserve(sym) * p
        return total

    # -- main computation --------------------------------------------------

    def compute_all(self) -> dict:
        """-> {symbol: PriceResult} for every registered token."""
        prices: dict[str, float] = {"USDT": 1.0}
        results: dict[str, PriceResult] = {}

        usdt_addr = config.TOKENS["USDT"][0]
        results["USDT"] = PriceResult(
            symbol="USDT", address=usdt_addr, price=1.0,
            confidence="A", route=["USDT"], note="anchor numeraire")

        # --- anchor: 42 ---------------------------------------------------
        anchor_conf = None
        anchor_pair = self._pair("42", "USDT")
        if self.anchor_override is not None:
            a_price, anchor_conf = self.anchor_override
            prices["42"] = a_price
            results["42"] = PriceResult(
                symbol="42", address=config.TOKENS["42"][0], price=a_price,
                liquidity_usd=None, confidence=anchor_conf,
                route=["42", "USDT"], note="anchor price supplied by fixture")
        elif anchor_pair is not None:
            p42 = anchor_pair.price_of_in("42", "USDT")  # USDT per 42; USDT=$1
            prices["42"] = p42
            liq = self._pool_liquidity_usd(anchor_pair, prices)
            anchor_conf = grade_pool(liq, hops=1)
            results["42"] = PriceResult(
                symbol="42", address=config.TOKENS["42"][0], price=p42,
                liquidity_usd=liq, confidence=anchor_conf,
                route=["42", "USDT"],
                staleness_seconds=self._route_staleness([anchor_pair]))
        else:
            results["42"] = PriceResult(
                symbol="42", address=config.TOKENS["42"][0],
                note="anchor pair 42-USDT not available")
        if anchor_conf is None:
            anchor_conf = "unpriced"

        # --- derived tokens, in dependency order --------------------------
        # FISH first (other tokens route through it), then the rest.
        order = ["FISH", "PANIC", "FOXXEY", "MARVIN", "ZAP", "KET"]
        for symbol in order:
            results[symbol] = self._price_token(symbol, prices, anchor_conf)

        # --- explicitly unpriced tokens -----------------------------------
        for symbol, (address, _dec) in config.UNPRICED_TOKENS.items():
            results[symbol] = PriceResult(
                symbol=symbol, address=address,
                note="no usable pool in Phase 0 (listed as unpriced)")

        return results

    def _route_staleness(self, states):
        stamps = [s.block_timestamp for s in states]
        if any(ts is None for ts in stamps):
            return None
        return max(0.0, self.now - max(stamps))

    def _price_token(self, symbol, prices: dict, anchor_conf: str) -> PriceResult:
        address = config.TOKENS[symbol][0]
        candidates = []
        if self._pair(symbol, "USDT") is not None:
            candidates.append((["USDT"], 1))
        if self._pair(symbol, "42") is not None and "42" in prices:
            candidates.append((["42", "USDT"], 2))
        if self._pair(symbol, "FISH") is not None and "FISH" in prices:
            candidates.append((["FISH", "42", "USDT"], 3))
        if not candidates:
            return PriceResult(symbol=symbol, address=address,
                               note="no route to USDT with available pairs")

        via, hops = candidates[0]  # priority order as appended above
        route = [symbol] + via
        # Price = first-hop pool ratio x USD price of the next symbol on
        # the route (already computed: USDT, then 42, then FISH). This also
        # covers fixture mode, where the 42-USDT pair itself has no fixture
        # reserves and 42's price comes from the anchor override.
        next_symbol = via[0]
        state = self._pair(symbol, next_symbol)
        price = state.price_of_in(symbol, next_symbol) * prices[next_symbol]
        prices[symbol] = price
        # Remaining route pools (when they exist) only feed staleness.
        states = [state]
        for i in range(1, len(route) - 1):
            extra = self._pair(route[i], route[i + 1])
            if extra is not None:
                states.append(extra)

        first_pool_liq = self._pool_liquidity_usd(states[0], prices)
        grade = grade_pool(first_pool_liq, hops)
        grade = _min_grade(grade, anchor_conf)  # anchor cap
        return PriceResult(
            symbol=symbol, address=address, price=price,
            liquidity_usd=first_pool_liq,
            staleness_seconds=self._route_staleness(states),
            confidence=grade, route=route)
