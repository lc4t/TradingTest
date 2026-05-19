"""Backward-compat shim. Use `python -m tradingtest.cli.digest` directly if you can."""
import sys

from tradingtest.io.digest import main

if __name__ == "__main__":
    sys.exit(main())
