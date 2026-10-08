"""支持 ``python gui/__main__.py`` 与 ``python -m gui``（后者要求父目录是合法模块名）。"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
