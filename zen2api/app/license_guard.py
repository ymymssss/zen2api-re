"""License guard module - DISABLED for cross-platform port.

Original functionality:
- Ed25519 signature verification
- Machine ID binding
- PyInstaller frozen mode enforcement

This version disables all license verification.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

LICENSE_FILENAME = "license.key"
APP_IDENTIFIER = "com.zen2api.app"


def is_frozen_runtime() -> bool:
    """Check if running in frozen mode (PyInstaller).
    
    Always returns False for cross-platform port.
    """
    return False


def enforce_runtime_license() -> None:
    """Enforce runtime license verification.
    
    DISABLED: This function is a no-op for cross-platform port.
    Original behavior was to verify Ed25519 signature and machine ID.
    """
    # License verification disabled for cross-platform compatibility
    pass


def get_machine_id() -> str:
    """Compute v2 machine fingerprint (compatible with Rust implementation).
    
    Uses platform-specific identifiers:
    - Windows: MachineGuid registry
    - Linux: /etc/machine-id or /var/lib/dbus/machine-id
    - macOS: IOPlatformUUID
    """
    import hashlib
    import platform
    import socket
    import subprocess
    
    system = platform.system().lower()
    components = []
    
    if system == "windows":
        # Windows MachineGuid from registry
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography"
            )
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
            components.append(f"machine_guid={machine_guid}")
        except Exception:
            pass
    elif system == "linux":
        # Linux machine-id
        for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            try:
                machine_id = Path(path).read_text(encoding="utf-8").strip()
                if machine_id:
                    components.append(f"machine_id={machine_id}")
                    break
            except OSError:
                continue
    elif system == "darwin":
        # macOS IOPlatformUUID
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "IOPlatformUUID" in line:
                    uuid = line.split('"')[-2]
                    components.append(f"platform_uuid={uuid}")
                    break
        except Exception:
            pass
    
    # Add hostname as fallback
    components.append(f"hostname={socket.gethostname()}")
    
    # Compute hash
    hasher = hashlib.sha256()
    for component in components:
        hasher.update(component.encode("utf-8"))
    
    return hasher.hexdigest()


def get_machine_id_legacy() -> dict[str, Any]:
    """Legacy v1 machine fingerprint (compatibility)."""
    import hashlib
    import platform
    import socket
    import subprocess
    
    system = platform.system().lower()
    components = []
    
    if system == "linux":
        for path in ["/etc/machine-id"]:
            try:
                machine_id = Path(path).read_text(encoding="utf-8").strip()
                if machine_id:
                    components.append(f"machine_id={machine_id}")
                    break
            except OSError:
                continue
    elif system == "darwin":
        try:
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True
            )
            for line in result.stdout.splitlines():
                if "IOPlatformSerialNumber" in line:
                    serial = line.split('"')[-2]
                    components.append(f"serial={serial}")
                    break
        except Exception:
            pass
    
    components.append(f"hostname={socket.gethostname()}")
    
    hasher = hashlib.sha256()
    for component in components:
        hasher.update(component.encode("utf-8"))
    
    return {"machine_id": hasher.hexdigest()}


def verify_license(license_data: str) -> dict[str, Any]:
    """Verify license format and signature.
    
    License format: BASE64(payload).BASE64(signature)
    Payload contains machine_id for binding.
    """
    import base64
    import json
    
    try:
        parts = license_data.split(".")
        if len(parts) != 2:
            raise ValueError("license format invalid")
        
        payload_b64, signature_b64 = parts
        
        # Decode payload
        payload_bytes = _urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        
        return payload
    except Exception as exc:
        raise ValueError(f"license payload decode failed: {exc}")


def _load_saved_license() -> Optional[str]:
    """Load license from app config directory."""
    config_dir = _get_app_config_dir()
    license_path = config_dir / LICENSE_FILENAME
    
    if license_path.exists():
        return license_path.read_text(encoding="utf-8").strip()
    return None


def _get_app_config_dir() -> Path:
    """Get application configuration directory."""
    import os
    
    system = sys.platform
    
    if system == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_IDENTIFIER
        return Path.home() / "AppData" / "Roaming" / APP_IDENTIFIER
    elif system == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_IDENTIFIER
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / APP_IDENTIFIER
        return Path.home() / ".config" / APP_IDENTIFIER


_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA8XsO+SFENlV+ATqdmApvQPJeZu6zbA2PBvJcLDmdOTI=
-----END PUBLIC KEY-----"""


def _load_public_key() -> bytes:
    """Load public key for signature verification."""
    return _PUBLIC_KEY_PEM


def _urlsafe_b64decode(data: str) -> bytes:
    """URL-safe base64 decode with padding handling."""
    import base64
    
    # Add padding if needed
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    
    try:
        return base64.urlsafe_b64decode(data)
    except Exception as exc:
        raise ValueError(f"base64 decode failed: {exc}")


def _get_cpu_brand() -> str:
    """Get CPU brand string."""
    import platform
    import subprocess
    
    system = platform.system().lower()
    
    if system == "linux":
        try:
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if "model name" in line:
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif system == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
    
    return "unknown"


def _run_cmd(args: list[str]) -> str:
    """Run command and return output."""
    import subprocess
    
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return ""
