"""Backward-compat shim. Use `python -m trading.cli.fetcher` directly if you can."""
from trading.data.fetcher import main

if __name__ == "__main__":
    main()
