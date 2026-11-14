#!/usr/bin/env python3
"""Entry point.

Usage:
  python3 main.py [--host 127.0.0.1] [--port 8080]

Environment:
  BABELFISH_FIXTURE=1        offline fixture mode (no RPC calls at all)
  BABELFISH_REFRESH_SECONDS  cache/refresh interval (default 60)
  BABELFISH_DB               SQLite snapshot path (default ./babelfish.db)
  BABELFISH_RPC_SLEEP        seconds between eth_calls in live mode (default 1.0)
"""

import argparse

from babelfish.server import serve


def main():
    parser = argparse.ArgumentParser(description="Babel Fish Prices (Phase 0)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
