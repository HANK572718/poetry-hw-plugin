"""poetry hw — hardware variant info command."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from cleo.commands.command import Command
from cleo.helpers import option


class HwInfoCommand(Command):
    """Show hardware detection status, available variants, and usage help."""

    name = "hw"
    description = "Show hardware detection status and available variants"

    options = [
        option(
            "--detect",
            "-d",
            "Print detected variant name only (for scripting)",
            flag=True,
        ),
    ]

    def handle(self) -> int:
        """Execute the hw info command."""
        from .detector import detect_variant

        variant = detect_variant()

        if self.option("detect"):
            self.line(variant)
            return 0

        forced = os.environ.get("HW_VARIANT", "").strip()
        disabled = os.environ.get("HW_PLUGIN_DISABLE", "").strip()

        W = 50
        self.line("")
        self.line("  <b>hw-plugin</b>  Hardware Detection Status")
        self.line("  " + "─" * W)
        self.line(f"  Detected variant : <info>{variant}</info>")
        self.line(f"  Platform         : {platform.system()} / {platform.machine()}")
        self.line(f"  Python           : {platform.python_version()}")
        if forced:
            self.line(
                f"  <comment>HW_VARIANT override active → {forced}</comment>"
            )
        if disabled == "1":
            self.line(
                "  <comment>HW_PLUGIN_DISABLE=1 → plugin will be skipped</comment>"
            )

        # ── Project variants ──────────────────────────────────────────
        variants_dir = Path.cwd() / "variants"
        if variants_dir.exists() and variants_dir.is_dir():
            available = sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
            self.line("")
            self.line(
                f"  <b>Project Variants</b>  "
                f"<comment>(variants/ — {len(available)} found)</comment>"
            )
            self.line("  " + "─" * W)
            self.line(f"  {'Variant':<24}{'Lock':^6}  Note")
            self.line(f"  {'─'*24}{'─'*6}  {'─'*14}")
            for v in available:
                has_lock = (variants_dir / v / "poetry.lock").exists()
                lock_col = "<info>  ✓  </info>" if has_lock else "<comment>  ✗  </comment>"
                note = "<info>← current</info>" if v == variant else ""
                self.line(f"  {v:<24}{lock_col}  {note}")
        else:
            self.line("")
            self.line(
                "  <comment>No variants/ directory — "
                "plugin will skip this project.</comment>"
            )
            self.line(
                "  Create <info>variants/<name>/pyproject.toml</info> "
                "to enable variant switching."
            )

        # ── Usage ─────────────────────────────────────────────────────
        self.line("")
        self.line("  <b>Usage</b>")
        self.line("  " + "─" * W)
        _row = self._usage_row
        _row("poetry install",
             "auto-detect and install matching variant")
        _row("poetry lock",
             "auto-detect and regenerate lock for variant")
        _row("HW_VARIANT=<name> poetry install",
             "force a specific variant")
        _row("HW_PLUGIN_DISABLE=1 poetry install",
             "bypass plugin entirely")
        _row("poetry hw",
             "show this status page")
        _row("poetry hw --detect",
             "print variant name (for scripts)")

        # ── Variant reference ─────────────────────────────────────────
        self.line("")
        self.line("  <b>Variant Reference</b>")
        self.line("  " + "─" * W)
        _VARIANTS = [
            ("win-cuda",       "Windows + NVIDIA GPU"),
            ("win-xpu",        "Windows + Intel Arc"),
            ("win-cpu",        "Windows + no GPU"),
            ("linux-arm-cuda", "Linux ARM + CUDA  (Jetson)"),
            ("linux-arm-cpu",  "Linux ARM + no GPU"),
            ("linux-x86-cuda", "Linux x86_64 + NVIDIA GPU"),
            ("linux-x86-xpu",  "Linux x86_64 + Intel Arc"),
            ("linux-x86-cpu",  "Linux x86_64 + no GPU"),
            ("mac",            "macOS (arm64 / x86_64)"),
        ]
        for name, desc in _VARIANTS:
            is_cur = name == variant
            tag = "info" if is_cur else "comment"
            star = " ★" if is_cur else ""
            self.line(f"  <{tag}>{name:<20}</{tag}>  {desc}{star}")

        self.line("")
        return 0

    def _usage_row(self, cmd: str, note: str) -> None:
        self.line(f"  <info>{cmd}</info>")
        self.line(f"    {note}")
