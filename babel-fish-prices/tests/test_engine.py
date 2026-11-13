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
from babelfish.datasource import FixtureDataSource, pair_key
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
