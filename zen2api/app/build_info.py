"""Runtime build fingerprint helpers."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RuntimeBuildInfo:
    runtime: str
    fingerprint: str
    executable: str


def _run_git(args: list[str]) -> Optional[str]:
    """Run git command and return output."""
    try:
        result = subprocess.run(
            ["git"] + args,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _resolve_source_fingerprint() -> str:
    """Resolve fingerprint from source checkout."""
    revision = _run_git(["rev-parse", "--short", "HEAD"]) or "unknown"
    dirty = _run_git(["status", "--untracked-files=no", "--porcelain"])
    suffix = "-dirty" if dirty else ""
    return f"git:{revision}{suffix}"


def _resolve_frozen_fingerprint() -> str:
    """Resolve fingerprint from frozen executable."""
    try:
        exe = Path(sys.executable)
        stat = exe.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )
        size = stat.st_size
        return f"frozen:{exe.name}:{mtime}:{size}"
    except OSError:
        return "frozen:unknown"


@lru_cache(maxsize=1)
def get_runtime_build_info() -> RuntimeBuildInfo:
    """Get runtime build information."""
    source = _resolve_source_fingerprint()
    return RuntimeBuildInfo(
        runtime=f"python/{sys.version.split()[0]}",
        fingerprint=source,
        executable=sys.executable,
    )


def format_build_label(version: str) -> str:
    """Format build label string."""
    info = get_runtime_build_info()
    return f"{version} | runtime={info.runtime} | build={info.fingerprint}"
