from __future__ import annotations

import sys
import types
from pathlib import Path


def _ensure_bt_common_package() -> None:
    # Allow running tests without installing `bt_common` into the active environment.
    if "bt_common" in sys.modules:
        return

    package_root = Path(__file__).resolve().parents[1] / "src"
    module = types.ModuleType("bt_common")
    module.__file__ = str(package_root / "__init__.py")
    module.__path__ = [str(package_root)]  # type: ignore[attr-defined]
    sys.modules["bt_common"] = module


_ensure_bt_common_package()

