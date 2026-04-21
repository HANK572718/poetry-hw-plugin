"""Poetry ApplicationPlugin: hardware-aware variant selector."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cleo.events.console_command_event import ConsoleCommandEvent
from cleo.events.console_events import COMMAND, TERMINATE
from cleo.events.console_terminate_event import ConsoleTerminateEvent
from poetry.console.commands.install import InstallCommand
from poetry.console.commands.lock import LockCommand
from poetry.plugins.application_plugin import ApplicationPlugin

from .command import HwInfoCommand
from .detector import detect_variant

_HOOKED_COMMANDS = (InstallCommand, LockCommand)


class HwSelectPlugin(ApplicationPlugin):
    """Switch pyproject.toml and poetry.lock based on detected hardware."""

    _root: Path | None = None
    _variant: str | None = None

    def activate(self, application) -> None:  # type: ignore[override]
        application.add(HwInfoCommand())
        application.event_dispatcher.add_listener(COMMAND, self.before_command)
        application.event_dispatcher.add_listener(TERMINATE, self.after_command)

    # ------------------------------------------------------------------
    # COMMAND event
    # ------------------------------------------------------------------

    def before_command(
        self,
        event: ConsoleCommandEvent,
        _event_name: str,
        _dispatcher: object,
    ) -> None:
        if not isinstance(event.command, _HOOKED_COMMANDS):
            return

        if os.environ.get("HW_PLUGIN_DISABLE") == "1":
            return

        root = Path(event.command.poetry.file.path).parent
        io = event.io

        # Silently skip projects that are not managed by this plugin
        variants_dir = root / "variants"
        if not variants_dir.exists():
            return

        variant = detect_variant()
        variant_dir = variants_dir / variant

        if not variant_dir.exists():
            available = [d.name for d in variants_dir.iterdir() if d.is_dir()]
            io.write_error_line(
                f"<error>[hw-plugin] Variant not found: {variant}</error>\n"
                f"  Available: {available}\n"
                f"  Set HW_VARIANT=<name> to override."
            )
            return

        io.write_line(f"<info>[hw-plugin] Detected variant: {variant}</info>")

        shutil.copy(variant_dir / "pyproject.toml", root / "pyproject.toml")
        io.write_line("<comment>[hw-plugin] pyproject.toml updated from variant.</comment>")

        lock_src = variant_dir / "poetry.lock"
        if lock_src.exists():
            shutil.copy(lock_src, root / "poetry.lock")
            io.write_line("<comment>[hw-plugin] poetry.lock loaded from variant.</comment>")
        else:
            io.write_line(
                f"<comment>[hw-plugin] No lock for {variant}, will generate.</comment>"
            )

        _ensure_gitignore(root, io)
        _ensure_venv_in_project(root, io)

        self._root = root
        self._variant = variant

    # ------------------------------------------------------------------
    # TERMINATE event
    # ------------------------------------------------------------------

    def after_command(
        self,
        event: ConsoleTerminateEvent,
        _event_name: str,
        _dispatcher: object,
    ) -> None:
        if not isinstance(event.command, _HOOKED_COMMANDS):
            return

        if event.exit_code != 0:
            return

        if self._root is None or self._variant is None:
            return

        root = self._root
        variant_dir = root / "variants" / self._variant
        lock_src = root / "poetry.lock"

        if lock_src.exists():
            shutil.copy(lock_src, variant_dir / "poetry.lock")
            event.io.write_line(
                f"<info>[hw-plugin] poetry.lock synced → variants/{self._variant}/</info>"
            )
        else:
            event.io.write_line(
                "<comment>[hw-plugin] No root poetry.lock to sync back.</comment>"
            )

        self._root = None
        self._variant = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _ensure_gitignore(root: Path, io: object) -> None:
    """Append /poetry.lock to .gitignore if not already present."""
    gitignore = root / ".gitignore"
    entry = "/poetry.lock"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in content.splitlines()]
        if entry in lines or "poetry.lock" in lines:
            return
        gitignore.write_text(
            content.rstrip() + f"\n\n# hw-plugin: root lock is variant-specific\n{entry}\n",
            encoding="utf-8",
        )
    else:
        gitignore.write_text(
            f"# hw-plugin: root lock is variant-specific\n{entry}\n",
            encoding="utf-8",
        )
    io.write_line(f"<comment>[hw-plugin] Added '{entry}' to .gitignore</comment>")  # type: ignore[attr-defined]


def _ensure_venv_in_project(root: Path, io: object) -> None:
    """Write poetry.toml to pin virtualenv inside the project directory."""
    poetry_toml = root / "poetry.toml"
    desired = "[virtualenvs]\nin-project = true\n"

    if poetry_toml.exists():
        content = poetry_toml.read_text(encoding="utf-8")
        if "in-project" in content:
            return
        poetry_toml.write_text(content.rstrip() + "\n\n" + desired, encoding="utf-8")
    else:
        poetry_toml.write_text(desired, encoding="utf-8")

    io.write_line(  # type: ignore[attr-defined]
        "<comment>[hw-plugin] poetry.toml: virtualenvs.in-project = true</comment>"
    )
