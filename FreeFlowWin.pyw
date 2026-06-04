import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import freeflow_win


if __name__ == "__main__":
    raise SystemExit(freeflow_win.main([]))
