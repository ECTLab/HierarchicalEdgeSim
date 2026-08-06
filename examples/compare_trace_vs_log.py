#!/usr/bin/env python3
"""Thin CLI wrapper around the modular analysis package."""

from __future__ import annotations

import sys
from pathlib import Path

# Make `examples/analysis` importable as package `analysis`.
_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from analysis.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
