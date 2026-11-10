#!/usr/bin/env python3
"""Add finished days of measured sunshine to data/weather/sunshine.csv."""

from __future__ import annotations

from src.app.sunshine import HISTORY_PATH, extend_history


def main() -> int:
    added = extend_history()
    print(f"Added {added} days to {HISTORY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
