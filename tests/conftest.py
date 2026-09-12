"""Makes ``helpers`` importable from the test files and keeps Qt out of CI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

TESTS = Path(__file__).parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

# Settings and calibration must never touch the real profile directory during a
# test run. Set before anything imports winduo.log, which reads it at import.
os.environ.setdefault("WINDUO_HOME", str(TESTS / ".scratch"))
