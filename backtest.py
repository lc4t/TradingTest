"""Backward-compat shim. Use `python -m trading.cli.backtest` directly if you can."""
from trading.cli.backtest import main

if __name__ == "__main__":
    main()
