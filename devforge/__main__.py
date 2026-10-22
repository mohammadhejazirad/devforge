"""Allow `python -m devforge`."""

from __future__ import annotations

import sys

from devforge.cli import main

if __name__ == "__main__":
    sys.exit(main())
