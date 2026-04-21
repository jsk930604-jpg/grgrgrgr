#!/usr/bin/env python3
"""Entry point for market regime alert script."""

import sys

from market_alert_kr import main


if __name__ == "__main__":
    argv = sys.argv[1:]
    if not argv:
        argv = ["--auto"]
    raise SystemExit(main(argv))
