"""What this machine can run (plan §10: hardware profile on first run).

Deliberately dependency-free: total RAM from the OS, core count, and the
platform key that selects the llama.cpp archive. GPU capability is not
probed up front — the Vulkan build is tried first and the server falls
back to the CPU build if it cannot start (see server.py)."""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass

from src.backend.runtime.config import CatalogModel, RuntimeConfig

GIB = 1024**3


@dataclass(frozen=True)
class Hardware:
    os: str
    arch: str
    ram_bytes: int
    logical_cores: int

    @property
    def ram_gb(self) -> float:
        return self.ram_bytes / GIB

    def asset_keys(self) -> list[str]:
        """llama.cpp archives to try, best first."""
        if self.os == "windows" and self.arch == "x64":
            return ["windows-x64-vulkan", "windows-x64-cpu"]
        if self.os == "macos" and self.arch == "arm64":
            return ["macos-arm64"]  # Metal is built in
        if self.os == "linux" and self.arch == "x64":
            return ["linux-x64-vulkan", "linux-x64-cpu"]
        return []


def _total_ram_bytes() -> int:
    if sys.platform == "win32":

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [  # noqa: RUF012 - ctypes layout, not a mutable default
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined,unused-ignore]
        return int(status.ullTotalPhys)
    if sys.platform == "darwin":
        import subprocess

        output = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, check=True
        ).stdout
        return int(output.strip())
    return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))


def detect() -> Hardware:
    system = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return Hardware(
        os=system,
        arch=arch,
        ram_bytes=_total_ram_bytes(),
        logical_cores=os.cpu_count() or 1,
    )


def fits(model: CatalogModel, hardware: Hardware) -> bool:
    return hardware.ram_gb + 0.5 >= model.min_ram_gb


def recommended_model(config: RuntimeConfig, hardware: Hardware) -> CatalogModel:
    """The default for this machine: the first starter model (the catalog
    orders them by preference). Larger tiers are opt-in, never automatic
    — a bigger model is slower, and speed is what a first run needs."""
    starters = [m for m in config.models if m.tier == "starter" and fits(m, hardware)]
    return starters[0] if starters else config.models[0]
