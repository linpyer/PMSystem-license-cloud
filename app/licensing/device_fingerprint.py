from __future__ import annotations

import ctypes
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass

from app.licensing.constants import FINGERPRINT_VERSION
from app.licensing.errors import DeviceFingerprintError


INVALID_HARDWARE_VALUES = {
    "TO BE FILLED BY O.E.M.",
    "DEFAULT STRING",
    "UNKNOWN",
    "NONE",
    "NOT SPECIFIED",
    "SYSTEM SERIAL NUMBER",
    "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
}


def normalize_identifier(value: object) -> str:
    normalized = " ".join(str(value or "").strip().upper().split())
    if not normalized or normalized in INVALID_HARDWARE_VALUES:
        return ""
    return normalized


def build_device_id(identifiers: Mapping[str, object]) -> str:
    normalized = {
        str(key).strip().lower(): normalize_identifier(value)
        for key, value in identifiers.items()
    }
    parts = [f"{key}={value}" for key, value in sorted(normalized.items()) if value]
    if not parts:
        raise DeviceFingerprintError("No stable Windows hardware identifiers are available")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    device_id: str
    fingerprint_version: str = FINGERPRINT_VERSION
    device_name: str = ""
    os_version: str = ""


class WindowsDeviceFingerprint:
    def __init__(self, *, query_timeout_seconds: float = 3.0) -> None:
        self.query_timeout_seconds = max(0.5, float(query_timeout_seconds))

    def collect(self) -> DeviceIdentity:
        if sys.platform != "win32":
            raise DeviceFingerprintError("Windows device fingerprinting is only available on Windows")
        identifiers = {"machineGuid": self._machine_guid(), "systemVolume": self._volume_serial()}
        identifiers.update(self._cim_identifiers())
        return DeviceIdentity(
            device_id=build_device_id(identifiers),
            device_name=platform.node()[:120],
            os_version=f"Windows {platform.release()} {platform.version()}"[:160],
        )

    @staticmethod
    def _machine_guid() -> str:
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                value, _ = winreg.QueryValueEx(key, "MachineGuid")
            return normalize_identifier(value)
        except OSError:
            return ""

    def _cim_identifiers(self) -> dict[str, str]:
        command = (
            "$ErrorActionPreference='Stop';"
            "$c=Get-CimInstance Win32_ComputerSystemProduct | Select-Object -First 1 UUID;"
            "$b=Get-CimInstance Win32_BaseBoard | Select-Object -First 1 SerialNumber;"
            "@{biosUuid=$c.UUID;baseBoard=$b.SerialNumber}|ConvertTo-Json -Compress"
        )
        try:
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=self.query_timeout_seconds,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            if completed.returncode != 0 or not completed.stdout.strip():
                return {}
            payload = json.loads(completed.stdout)
            return {
                "biosUuid": normalize_identifier(payload.get("biosUuid")),
                "baseBoard": normalize_identifier(payload.get("baseBoard")),
            }
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return {}

    @staticmethod
    def _volume_serial() -> str:
        root = os.environ.get("SystemDrive", "C:") + "\\"
        serial = ctypes.c_uint32()
        try:
            success = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                None,
                0,
                ctypes.byref(serial),
                None,
                None,
                None,
                0,
            )
            return f"{serial.value:08X}" if success else ""
        except (AttributeError, OSError):
            return ""
