"""Offline tests (fixture mode only — no network).

Runnable two ways:
  python3 run_tests.py        (plain asserts, no pytest needed)
  pytest tests/               (if pytest is installed)

Reference values are the verified 2026-11-12/13 data points documented in
babelfish/fixtures.py.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from babelfish import config
from babelfish.datasource import FixtureDataSource, PairState, pair_key
from babelfish.engine import PriceEngine, grade_pool
from babelfish.service import PriceService
from babelfish.store import SnapshotStore

DONT_REFERENCE_USD = 0.0003768   # Don't Panic display, 2026-11-12
FISH_REFERENCE_USD = 1.2658      # Don't Panic display, 2026-11-12


def _fixture_results():
    source = FixtureDataSource()
    engine = PriceEngine(source.fetch_pairs(),
                         anchor_override=source.anchor_override())
    return engine.compute_all(), source.fetch_pairs()


def test_dont_ratio_and_price():
    results, pairs = _fixture_results()
    pair = pairs[pair_key("42", "PANIC")]
    ratio = pair.reserve("PANIC") / pair.reserve("42")
    # 50651493449751846214842463 / 30082560732337007099241 = 1683.75 DONT per 42
    assert abs(ratio - 1683.75) / 1683.75 < 0.005, ratio
    panic = results["PANIC"]
    assert panic.route == ["PANIC", "42", "USDT"], panic.route
    assert panic.price is not None
    assert abs(panic.price - DONT_REFERENCE_USD) / DONT_REFERENCE_USD < 0.01, panic.price


def test_fish_via_42_price():
    results, _pairs = _fixture_results()
    fish = results["FISH"]
    assert fish.route == ["FISH", "42", "USDT"], fish.route
    assert fish.price is not None
    # Fixture reserves give ~$1.258; reference display was $1.2658 (0.61% away).
    assert abs(fish.price - 1.258) / 1.258 < 0.005, fish.price
    assert abs(fish.price - FISH_REFERENCE_USD) / FISH_REFERENCE_USD < 0.015, fish.price


def test_unpriced_is_null_not_zero():
    results, _pairs = _fixture_results()
    for symbol in ("TOWEL", "GUIDE", "SOV", "VIC", "BFOXX"):
        assert results[symbol].price is None, symbol
        assert results[symbol].confidence == "unpriced", symbol
    # Tokens without fixture pairs are unpriced in fixture mode too.
    for symbol in ("MARVIN", "ZAP", "FOXXEY", "KET"):
        assert results[symbol].price is None, symbol
    # No token anywhere may report a price of exactly 0.
    for symbol, r in results.items():
        assert r.price != 0, symbol


def test_anchor_cap():
    results, _pairs = _fixture_results()
    fish = results["FISH"]
    # FISH-42 pool is ~$61.5K in fixture -> raw grade would be A at 2 hops...
    assert fish.liquidity_usd is not None and fish.liquidity_usd >= 40_000
    assert grade_pool(fish.liquidity_usd, hops=2) == "A"
    # ...but the anchor (fixture confidence B) caps it at B.
    assert results["42"].confidence == "B"
    assert fish.confidence == "B", fish.confidence


def test_twap_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = SnapshotStore(path)
        addr = config.TOKENS["FISH"][0]
        now = 1_700_000_000.0
        # 3 snapshots spanning 3000s of a 3600s window, prices 1.0/2.0/3.0.
        store.add_snapshots(now - 3000, [("FISH", addr, 1.0)])
        store.add_snapshots(now - 1500, [("FISH", addr, 2.0)])
        store.add_snapshots(now, [("FISH", addr, 3.0)])
        t = store.twap(addr, 3600, now=now)
        assert t["twap"] == 2.0, t
        # A token with no history: twap null + explanation, never 0.
        t2 = store.twap(config.TOKENS["ZAP"][0], 3600, now=now)
        assert t2["twap"] is None and t2["note"], t2
    finally:
        os.unlink(path)


def _state(sym0, amount0, sym1, amount1):
    """Synthetic 18-decimal PairState for engine tests."""
    return PairState(
        pair_address="0x0000000000000000000000000000000000000001",
        token0_symbol=sym0, token1_symbol=sym1,
        reserve0_raw=int(amount0 * 10 ** 18),
        reserve1_raw=int(amount1 * 10 ** 18),
        decimals0=18, decimals1=18, block_timestamp=None, fetched_at=0.0)


def _anchor_and_fish_pairs():
    # 42 = $1.00 (pool $200K -> anchor grade A); FISH = 2.00 (pool $200K -> A)
    return {
        pair_key("42", "USDT"): _state("USDT", 100_000, "42", 100_000),
        pair_key("FISH", "42"): _state("FISH", 50_000, "42", 100_000),
    }


def test_usdt_decimals_not_six():
    # On InfiniteDrive the bridged USDT's decimals() is 18, not 6
    # (verified on-chain 2026-11-14). Config must not hard-code 6 again:
    # None means "read on-chain", 18 is the verified value.
    assert config.TOKENS["USDT"][1] in (None, 18)


def test_three_hop_grades():
    # The 3-hop penalty applies exactly once (regression: it used to apply
    # twice, making every 3-hop token unpriced).
    assert grade_pool(100_000, hops=3) == "B"   # A downgraded once
    assert grade_pool(20_000, hops=3) == "C"    # B downgraded once
    assert grade_pool(60_000, hops=2) == "A"    # no penalty at 2 hops
    pairs = _anchor_and_fish_pairs()
    # MARVIN via FISH: first pool ~$120K -> raw A -> 3-hop downgrade -> B.
    pairs[pair_key("MARVIN", "FISH")] = _state("MARVIN", 1_000_000_000,
                                               "FISH", 30_000)
    results = PriceEngine(pairs).compute_all()
    marvin = results["MARVIN"]
    assert marvin.route == ["MARVIN", "FISH", "42", "USDT"], marvin.route
    assert marvin.price is not None
    assert abs(marvin.price - 0.00006) / 0.00006 < 0.01, marvin.price
    assert marvin.confidence == "B", marvin.confidence


def test_unpriced_withholds_numeric_price():
    pairs = _anchor_and_fish_pairs()
    # KET-FISH with ~$129 of liquidity: computable, but below the $3K
    # unpriced threshold, so no numeric price may be reported.
    pairs[pair_key("KET", "FISH")] = _state("KET", 2.05, "FISH", 32.18)
    results = PriceEngine(pairs).compute_all()
    ket = results["KET"]
    assert ket.confidence == "unpriced", ket.confidence
    assert ket.price is None, ket.price
    assert ket.liquidity_usd is not None and ket.liquidity_usd < 3_000


def test_zero_reserve_pair_is_skipped():
    pairs = _anchor_and_fish_pairs()
    # A drained pool must not crash the engine nor yield a 0.0 price, and
    # must not take the other tokens down with it.
    pairs[pair_key("ZAP", "FISH")] = _state("ZAP", 0, "FISH", 100)
    results = PriceEngine(pairs).compute_all()
    assert results["ZAP"].price is None
    assert results["FISH"].price == 2.0
    for symbol, r in results.items():
        assert r.price != 0, symbol


def test_twap_lookup_is_case_insensitive():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        store = SnapshotStore(path)
        addr = config.TOKENS["FISH"][0]  # checksummed form
        now = 1_700_000_000.0
        store.add_snapshots(now - 3000, [("FISH", addr, 1.0)])
        store.add_snapshots(now - 1500, [("FISH", addr, 2.0)])
        store.add_snapshots(now, [("FISH", addr, 3.0)])
        # Lowercase query (as users type it) must find the same history.
        t = store.twap(addr.lower(), 3600, now=now)
        assert t["twap"] == 2.0, t
    finally:
        os.unlink(path)


def test_mode_db_paths_differ():
    if os.environ.get("BABELFISH_DB"):
        return  # explicit override intentionally shared
    assert config.FIXTURE_DB_PATH != config.DB_PATH
    assert config.FIXTURE_DB_PATH.endswith("babelfish.fixture.db")


def test_service_fixture_mode():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        service = PriceService(fixture_mode=True, db_path=path,
                               refresh_interval=3600)
        envelope = service.prices()
        assert envelope["mode"] == "fixture"
        by_symbol = {t["symbol"]: t for t in envelope["tokens"]}
        assert by_symbol["FISH"]["price"] is not None
        assert by_symbol["TOWEL"]["price"] is None
        assert by_symbol["USDT"]["price"] == 1.0
        one = service.price_by_address(config.TOKENS["FISH"][0])
        assert one is not None and one["symbol"] == "FISH"
        # TWAP right after a single refresh: not enough history yet.
        tw = service.twap(config.TOKENS["FISH"][0], "1h")
        assert tw is not None and tw["twap"] is None and tw["note"], tw
        pairs = service.pairs()
        assert len(pairs) == 2  # only the two fixture pairs exist offline
    finally:
        os.unlink(path)
