#!/usr/bin/env python3
"""
k2rad.py  –  repo-root shim for the LS-DYNA .k → OpenRadioss .rad converter CLI.

The real command-line implementation lives in the package module
``k2rad.cli`` (so it can be exposed as the installed ``k2rad`` console
script). This shim keeps ``python k2rad.py model.k`` working directly from a
checkout with nothing installed.

Examples
--------
    python k2rad.py model.k
    python k2rad.py model.k output/model
    python k2rad.py model.k --units Mg mm s
"""

import sys
from pathlib import Path

try:
    from k2rad.cli import main
except ImportError:                              # running from an odd CWD
    sys.path.insert(0, str(Path(__file__).parent))
    from k2rad.cli import main


if __name__ == "__main__":
    sys.exit(main())
