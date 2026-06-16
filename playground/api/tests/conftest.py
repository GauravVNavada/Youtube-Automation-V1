from __future__ import annotations

import sys
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("PLAYGROUND_DATABASE_URL", "sqlite+pysqlite:///:memory:")
