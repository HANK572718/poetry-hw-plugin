"""hw_plugin.hooks

Variant hook script runner.

每個 variant 目錄可以放可選的 hook 腳本，plugin 在對應時機用 venv python 執行：

    variants/win-xpu/
        pyproject.toml
        pre_install.py    ← poetry install 前執行（venv 尚未安裝）
        post_install.py   ← poetry install 後執行（venv 已安裝完畢）

宣告方式（優先順序）：
  1. variant 的 pyproject.toml 中 [tool.hw-plugin.hooks] 顯式宣告
  2. 慣例命名：pre_install.py / post_install.py 存在即執行

[tool.hw-plugin.hooks] 格式範例：

    [tool.hw-plugin.hooks]
    pre_install  = "scripts/before.py"
    post_install = ["scripts/after.py", "--verbose"]

執行環境：
- 使用 venv 的 python 執行（.venv/Scripts/python 或 .venv/bin/python）
- pre_install 在 variant swap 後、poetry install 前執行（venv 可能尚未存在）
  → pre_install 用系統 python 執行（sys.executable）
- post_install 在 poetry install 成功後執行（venv 保證存在）
  → post_install 用 venv python 執行，可直接 import 已安裝的套件
- stdout / stderr 直接透傳，讓用戶看到完整輸出
- 失敗（非零退出碼）印出警告，不中斷 install 流程
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reuse-import]

# 慣例 hook 檔名
_PRE_INSTALL_DEFAULT = "pre_install.py"
_POST_INSTALL_DEFAULT = "post_install.py"


def _load_hook_config(variant_dir: Path) -> dict[str, Any]:
    """從 variant 的 pyproject.toml 讀取 [tool.hw-plugin.hooks]。"""
    pyproject = variant_dir / "pyproject.toml"
    if not pyproject.exists():
        return {}
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return data.get("tool", {}).get("hw-plugin", {}).get("hooks", {})
    except Exception:
        return {}


def _resolve_hook(variant_dir: Path, config: dict[str, Any], key: str, default: str) -> tuple[Path, list[str]] | None:
    """
    解析 hook 設定，回傳 (script_path, extra_args) 或 None。

    config 優先：
      post_install = "scripts/after.py"           → (variant_dir/scripts/after.py, [])
      post_install = ["scripts/after.py", "--v"]  → (variant_dir/scripts/after.py, ["--v"])

    config 無宣告時，偵測慣例命名：
      variant_dir/post_install.py 存在 → (variant_dir/post_install.py, [])
    """
    if key in config:
        entry = config[key]
        if isinstance(entry, str):
            parts: list[str] = [entry]
        elif isinstance(entry, list):
            parts = [str(p) for p in entry]
        else:
            return None
        script = variant_dir / parts[0]
        extra = parts[1:]
    else:
        script = variant_dir / default
        extra = []

    if not script.exists():
        return None
    return script, extra


def _find_venv_python(root: Path) -> Path:
    """找到 .venv 裡的 python 執行檔（跨平台）。"""
    venv = root / ".venv"
    for candidate in (
        venv / "Scripts" / "python.exe",  # Windows
        venv / "bin" / "python",           # Linux / macOS
    ):
        if candidate.exists():
            return candidate
    # fallback：用目前 python（應該不會發生，post_install 時 venv 必定存在）
    return Path(sys.executable)


def run_pre_install(variant_dir: Path, root: Path, io: Any) -> None:
    """執行 pre_install hook（用系統 python，venv 此時可能尚未存在）。"""
    config = _load_hook_config(variant_dir)
    resolved = _resolve_hook(variant_dir, config, "pre_install", _PRE_INSTALL_DEFAULT)
    if resolved is None:
        return

    script, extra = resolved
    _run_hook(script, extra, python=Path(sys.executable), label="pre_install", io=io)


def run_post_install(variant_dir: Path, root: Path, io: Any) -> None:
    """執行 post_install hook（用 venv python，可直接 import 已安裝的套件）。"""
    config = _load_hook_config(variant_dir)
    resolved = _resolve_hook(variant_dir, config, "post_install", _POST_INSTALL_DEFAULT)
    if resolved is None:
        return

    script, extra = resolved
    python = _find_venv_python(root)
    _run_hook(script, extra, python=python, label="post_install", io=io)


def _run_hook(script: Path, extra_args: list[str], python: Path, label: str, io: Any) -> None:
    """執行單一 hook 腳本，stdout/stderr 透傳，失敗印警告不中斷。"""
    cmd = [str(python), str(script)] + extra_args
    io.write_line(f"<info>[hw-plugin] Running {label}: {script.name}</info>")

    try:
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            io.write_line(
                f"<warning>[hw-plugin] {label} exited with code {result.returncode} "
                f"— continuing anyway.</warning>"
            )
        else:
            io.write_line(f"<info>[hw-plugin] {label} completed successfully.</info>")
    except Exception as exc:
        io.write_line(
            f"<warning>[hw-plugin] {label} failed to run: {exc} — continuing anyway.</warning>"
        )
