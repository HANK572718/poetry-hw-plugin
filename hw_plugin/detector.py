"""Hardware variant detection for the hw-select Poetry plugin."""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path


def detect_variant() -> str:
    """Return the hardware variant string for the current machine.

    Priority:
      1. ``HW_VARIANT`` environment variable (bypasses all detection)
      2. macOS → ``mac``
      3. ARM vs x86_64 architecture
      4. GPU detection: CUDA / XPU / CPU-only
    """
    forced = os.environ.get("HW_VARIANT", "").strip()
    if forced:
        return forced

    os_name = platform.system()
    arch = platform.machine()

    if os_name == "Darwin":
        return "mac"

    is_arm = arch in ("aarch64", "arm64", "armv7l")
    is_win = os_name == "Windows"
    gpu = _detect_gpu(is_win=is_win, is_arm=is_arm)

    if is_win:
        return f"win-{gpu}"

    prefix = "linux-arm" if is_arm else "linux-x86"
    return f"{prefix}-{gpu}"


def _detect_gpu(*, is_win: bool, is_arm: bool) -> str:
    if _cmd_ok(["nvidia-smi"]):
        return "cuda"

    # Jetson fallback: nvidia-smi may not be in PATH on some JetPack versions
    if is_arm and _is_jetson():
        return "cuda"

    if not is_win:
        if _cmd_ok(["xpu-smi"]) or _intel_gpu_via_sycl():
            return "xpu"
    else:
        if _intel_gpu_via_wmi():
            return "xpu"

    return "cpu"


def _cmd_ok(cmd: list[str], timeout: int = 5) -> bool:
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=timeout)
        return True
    except Exception:
        return False


def _is_jetson() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_text()
        return "jetson" in model.lower()
    except Exception:
        return False


def _intel_gpu_via_sycl() -> bool:
    try:
        r = subprocess.run(["sycl-ls"], capture_output=True, text=True, timeout=5)
        return "Intel" in r.stdout
    except Exception:
        return False


def _intel_gpu_via_wmi() -> bool:
    try:
        r = subprocess.run(
            [
                "powershell",
                "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
        out = r.stdout
        # Only match discrete Arc GPU; Iris Xe is integrated and lacks XPU torch support
        return "Intel" in out and "Arc" in out
    except Exception:
        return False
