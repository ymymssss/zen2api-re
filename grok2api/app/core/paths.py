from __future__ import annotations

import os
from pathlib import Path


GROK2API_VENDOR_ROOT = Path(
    os.getenv("GROK2API_VENDOR_ROOT", "").strip() or Path(__file__).resolve().parents[2]
)
VENDOR_ROOT = GROK2API_VENDOR_ROOT
APP_ROOT = VENDOR_ROOT / "app"
TEMPLATE_DIR = APP_ROOT / "templates"
RUNTIME_ROOT = Path(
    os.getenv("GROK2API_RUNTIME_DIR", "").strip() or Path.cwd()
)
DATA_ROOT = RUNTIME_ROOT / "data"
LOG_ROOT = RUNTIME_ROOT / "logs"
TEMP_ROOT = RUNTIME_ROOT / "temp"


def ensure_runtime_dirs() -> None:
    for path in (DATA_ROOT, LOG_ROOT, TEMP_ROOT):
        path.mkdir(parents=True, exist_ok=True)
