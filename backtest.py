"""Backward-compat shim. Use `python -m tradingtest.cli.backtest` directly if you can."""
from tradingtest.cli.backtest import main

if __name__ == "__main__":
    main()
