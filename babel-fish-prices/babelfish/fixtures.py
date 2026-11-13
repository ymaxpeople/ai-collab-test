"""Offline fixture data (BABELFISH_FIXTURE=1).

Every number here is a VERIFIED data point from the 2026-11-12/13 research —
this is demo/regression data, NOT live market data:

(a) 42/DONT pair 0x80baCFb358a3C7D7D1b549c2028001E2BA3acdAC
    reserves read on-chain 2026-11-12 (the one pair that got through before
    the RPC started returning 403s). Token order on-chain is not recorded,
    so the fixture assigns token0 = 42 (sentinel), token1 = PANIC (DONT);
    the price math is symmetric under swapping both sides, so the derived
    prices are unaffected.
    reserve (42 side)   = 30082560732337007099241   (~30,082.56 42)
    reserve (DONT side) = 50651493449751846214842463 (~50,651,493.45 DONT)
    -> DONT/42 ratio = 1683.75, DONT price at the fixture anchor = $0.0003768,
       matching Don't Panic's display on 2026-11-12.

(b) FISH-42 pair 0x46cce7b6b48e1627d7e3f69a68f425cba833dcc3
    explorer balances observed 2026-11-13 15:00 JST (balances move; this is
    a sanity-check snapshot): 48,505.55 42 / 24,463.89 FISH.
    PairCreated log shows token0 = FISH, token1 = 42 sentinel.
    -> FISH = 1.9827 42 = ~$1.258 at the fixture anchor (Don't Panic
       displayed $1.2658 on 2026-11-12; difference 0.61%).

(c) Fixture anchor: 42 = $0.6345 (Don't Panic / DriveStats, 2026-11-12).
    In fixture mode the 42-USDT pair itself has no fixture reserves, so the
    anchor price is supplied directly here, clearly marked as fixture data.
    Its confidence is fixed at "B": the real anchor pool measured
    $20.69K liquidity on 2026-11-12, which grades B under the draft
    thresholds — this is also the anchor-cap every derived price obeys.
"""

from decimal import Decimal

from . import config

FIXTURE_ANCHOR_PRICE_USD = 0.6345
FIXTURE_ANCHOR_CONFIDENCE = "B"
FIXTURE_ANCHOR_REFERENCE = "Don't Panic / DriveStats, 2026-11-12 (fixture)"


def _raw(amount: str, decimals: int) -> int:
    return int(Decimal(amount) * (Decimal(10) ** decimals))


# key: frozenset-like sorted symbol tuple -> PairState kwargs
FIXTURE_PAIRS = {
    ("42", "PANIC"): {
        "pair_address": "0x80baCFb358a3C7D7D1b549c2028001E2BA3acdAC",
        "token0_symbol": "42",
        "token1_symbol": "PANIC",
        "reserve0_raw": 30082560732337007099241,
        "reserve1_raw": 50651493449751846214842463,
        "decimals0": 18,
        "decimals1": 18,
        "block_timestamp": None,  # unknown for fixture data
    },
    ("42", "FISH"): {
        "pair_address": "0x46cce7b6b48e1627d7e3f69a68f425cba833dcc3",
        "token0_symbol": "FISH",
        "token1_symbol": "42",
        "reserve0_raw": _raw("24463.89", 18),
        "reserve1_raw": _raw("48505.55", 18),
        "decimals0": 18,
        "decimals1": 18,
        "block_timestamp": None,
    },
}


def fixture_pair_key(sym_a: str, sym_b: str):
    key = tuple(sorted((sym_a, sym_b)))
    # FIXTURE_PAIRS keys are stored sorted as well ("42" sorts before letters).
    return key if key in FIXTURE_PAIRS else None
