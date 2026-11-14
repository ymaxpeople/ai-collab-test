#!/usr/bin/env python3
"""Plain-assert test runner (no pytest required).

Usage: python3 run_tests.py
Exits non-zero if any test fails. All tests run offline in fixture mode.
"""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tests import test_engine


def main():
    tests = [(name, fn) for name, fn in sorted(vars(test_engine).items())
             if name.startswith("test_") and callable(fn)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception:
            failures += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
