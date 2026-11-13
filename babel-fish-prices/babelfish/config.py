"""Static configuration for Babel Fish Prices (Phase 0).

All addresses below were verified on scan.infinitedrive.xyz during the
2026-11-12/13 research (see the design draft in
~/workspace/goals/babel-fish-prices-a3-price-api/files/).
Read-only project: no wallet, no signing, no transactions, ever.
"""

import os

CHAIN_ID = 421018

# Don't Panic Factory (UniswapV2Factory) — verified 2026-11-13 via explorer.
FACTORY_ADDRESS = "0x3157C6AcA800D507af95Ab1466adBA3A6F11eE1a"

# Native token 42 has no ERC20 contract. The Factory created its pairs with
# this sentinel as the pair token (Router WETH() placeholder), so getPair is
# called with the sentinel for every 42 pair. Decimals are hard-coded to 18
# (explorer display) because the sentinel has no contract to read them from.
NATIVE_42_SENTINEL = "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"
NATIVE_42_DECIMALS = 18

RPC_ENDPOINTS = [
    "https://evm.infinitedrive.xyz",            # FishDisk preset
    "https://evm-rpc.infinitedrive.xyz",        # FoxxOne
    "https://evm-rpc-infinite.mschihuahua.org",  # ChainList-listed
    "https://evm-rpc.infinitepanda.xyz",        # community
]

# symbol -> (address, known decimals or None = read via decimals() on-chain)
# USDT is the price anchor (bridged USDT, 6 decimals).
TOKENS = {
    "USDT":   ("0xC2684966e5c95B2bc636FB4a1f3Da9Ad23d94753", 6),
    "42":     (NATIVE_42_SENTINEL, NATIVE_42_DECIMALS),
    "FISH":   ("0x2c32120a12B754272d9E85C57F64b50cA2C43513", None),
    "PANIC":  ("0xfAA842c8871f7F99c183F77871f79ce07DD056Cd", None),  # token name is DONT, DEX displays PANIC
    "MARVIN": ("0xa307362f8a756722541dde6255AECf64F35Ba337", None),
    "ZAP":    ("0x89195Ca5C954b6f99b78f4A2Aa5435A75Dc5B256", None),
    "FOXXEY": ("0x68D5A28D3bf09a32d3b9C35714aB7A6166Ae2a00", None),
    "KET":    ("0xb749D42E6004dB590b2f04F32B87485402A061E2", 18),
}

# Tokens that must appear in /v1/prices with price null in Phase 0
# (no usable pool). TOWEL's address is the DEX-listed one verified
# 2026-11-08; the others' addresses were not confirmed in the research
# record, so they are listed by symbol only (address null).
UNPRICED_TOKENS = {
    "TOWEL":  ("0xD0f48123638BD243C3a0eE49D0D7BEb7404F9DE4", None),
    "GUIDE":  (None, None),
    "SOV":    (None, None),
    "VIC":    (None, None),
    "BFOXX":  (None, None),
}

# Phase 0 pairs (symbol tuples). Pairs are ALWAYS resolved at runtime via
# Factory.getPair — pair addresses are never hard-coded.
PAIRS = [
    ("42", "USDT"),      # anchor
    ("FISH", "42"),
    ("PANIC", "42"),
    ("PANIC", "FISH"),
    ("MARVIN", "FISH"),
    ("ZAP", "FISH"),
    ("FOXXEY", "42"),
    ("KET", "FISH"),     # extra (route known: KET->FISH->42->USDT)
]

# Confidence thresholds (design draft v0.1, USD).
CONF_A_MIN_LIQUIDITY = 40_000.0
CONF_B_MIN_LIQUIDITY = 15_000.0
CONF_C_MIN_LIQUIDITY = 3_000.0
CONF_A_MIN_VOLUME_24H = 50.0
CONF_B_MIN_VOLUME_24H = 10.0

# Spot vs TWAP divergence that raises divergence_warning (20%).
DIVERGENCE_THRESHOLD = 0.20

# Runtime knobs (environment overridable).
REFRESH_INTERVAL_SECONDS = float(os.environ.get("BABELFISH_REFRESH_SECONDS", "60"))
RPC_TIMEOUT_SECONDS = float(os.environ.get("BABELFISH_RPC_TIMEOUT", "20"))
# Pause between consecutive eth_calls (the RPC rate-limited with 403s on
# 2026-11-12 when calls were fired back-to-back).
RPC_SLEEP_BETWEEN_CALLS = float(os.environ.get("BABELFISH_RPC_SLEEP", "1.0"))
DB_PATH = os.environ.get(
    "BABELFISH_DB",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "babelfish.db"),
)
FIXTURE_MODE = os.environ.get("BABELFISH_FIXTURE", "") == "1"
