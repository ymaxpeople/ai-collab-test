"""Read-only JSON-RPC client for the InfiniteDrive chain.

Multiple endpoints with failover. eth_call helpers only — this module has
no concept of wallets, keys, signing or sending transactions.
Patterns adapted from phase0-verify-single-command.py (2026-11-13).
"""

import time

import requests

from . import config

# Minimal ABI selectors.
SEL = {
    "getPair": "e6a43905",      # getPair(address,address) -> address
    "token0": "0dfe1681",       # token0() -> address
    "token1": "d21220a7",       # token1() -> address
    "getReserves": "0902f1ac",  # getReserves() -> (uint112, uint112, uint32)
    "decimals": "313ce567",     # decimals() -> uint8
}

ZERO_ADDRESS = "0x" + "0" * 40


class AllEndpointsFailed(RuntimeError):
    pass


def _addr_arg(address: str) -> str:
    return address[2:].lower().rjust(64, "0")


def _decode_address(raw: str) -> str:
    return "0x" + raw[-40:]


class RpcClient:
    """Sticky-endpoint RPC client: uses the first endpoint that works and
    fails over to the next one only when a call errors out."""

    def __init__(self, endpoints=None, timeout=None, sleep_between_calls=None):
        self.endpoints = list(endpoints or config.RPC_ENDPOINTS)
        self.timeout = timeout or config.RPC_TIMEOUT_SECONDS
        self.sleep = (config.RPC_SLEEP_BETWEEN_CALLS
                      if sleep_between_calls is None else sleep_between_calls)
        self._session = requests.Session()
        self._current = 0  # index into self.endpoints

    @property
    def current_endpoint(self):
        return self.endpoints[self._current]

    def _rpc_once(self, url, method, params):
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        resp = self._session.post(url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"{method} error from {url}: {body['error']}")
        return body["result"]

    def rpc(self, method, params):
        last_exc = None
        for offset in range(len(self.endpoints)):
            idx = (self._current + offset) % len(self.endpoints)
            url = self.endpoints[idx]
            try:
                result = self._rpc_once(url, method, params)
                self._current = idx
                return result
            except Exception as exc:  # noqa: BLE001 - fail over to next endpoint
                last_exc = exc
        raise AllEndpointsFailed(
            f"all {len(self.endpoints)} RPC endpoints failed: {last_exc}")

    def chain_id(self) -> int:
        return int(self.rpc("eth_chainId", []), 16)

    def eth_call(self, to: str, data: str) -> str:
        if self.sleep:
            time.sleep(self.sleep)
        return self.rpc("eth_call", [{"to": to, "data": "0x" + data}, "latest"])

    # --- contract helpers -------------------------------------------------

    def get_pair(self, factory: str, token_a: str, token_b: str):
        """Factory.getPair -> pair address, or None if the pair doesn't exist."""
        data = SEL["getPair"] + _addr_arg(token_a) + _addr_arg(token_b)
        pair = _decode_address(self.eth_call(factory, data))
        return None if pair.lower() == ZERO_ADDRESS else pair

    def pair_token0(self, pair: str) -> str:
        return _decode_address(self.eth_call(pair, SEL["token0"]))

    def pair_token1(self, pair: str) -> str:
        return _decode_address(self.eth_call(pair, SEL["token1"]))

    def pair_reserves(self, pair: str):
        """-> (reserve0_raw, reserve1_raw, block_timestamp_last)"""
        raw = self.eth_call(pair, SEL["getReserves"])
        body = raw[2:]
        return int(body[0:64], 16), int(body[64:128], 16), int(body[128:192], 16)

    def token_decimals(self, token: str) -> int:
        # The 42 sentinel has no contract; its decimals are hard-coded.
        if token.lower() == config.NATIVE_42_SENTINEL.lower():
            return config.NATIVE_42_DECIMALS
        return int(self.eth_call(token, SEL["decimals"]), 16)
