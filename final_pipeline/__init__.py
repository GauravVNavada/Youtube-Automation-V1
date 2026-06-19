"""Shared video generation pipeline package."""

from pathlib import Path
import sys


_PACKAGE_ROOT = Path(__file__).resolve().parent
if str(_PACKAGE_ROOT) not in sys.path:
    sys.path.append(str(_PACKAGE_ROOT))
