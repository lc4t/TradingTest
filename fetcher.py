"""Backward-compat shim. Use `python -m tradingtest.cli.fetcher` directly if you can."""
from tradingtest.data.fetcher import main

if __name__ == "__main__":
    main()
