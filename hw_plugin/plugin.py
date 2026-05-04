"""Poetry ApplicationPlugin: hardware-aware variant selector."""

from __future__ import annotations

import json
import os
import re
import platform
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reuse-import]

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cleo.events.console_command_event import ConsoleCommandEvent
from cleo.events.console_events import COMMAND, TERMINATE
from cleo.events.console_terminate_event import ConsoleTerminateEvent
from cleo.io.io import IO
from poetry.console.commands.install import InstallCommand
from poetry.console.commands.lock import LockCommand
from poetry.console.commands.update import UpdateCommand
from poetry.plugins.application_plugin import ApplicationPlugin

from .command import HwInfoCommand
from .detector import detect_variant
from .hooks import run_pre_install, run_post_install
from .scaffold import create_placeholder, create_variant
from .state import read_last_variant, write_last_variant

_HOOKED_COMMANDS = (InstallCommand, LockCommand, UpdateCommand)
_console = Console()


class HwSelectPlugin(ApplicationPlugin):
    """Switch pyproject.toml and poetry.lock based on detected hardware."""

    def __init__(self) -> None:
        """Initialise per-instance state so multiple instances don't share data."""
        self._root: Path | None = None
        self._variant: str | None = None

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

        io = event.io
        cwd = Path.cwd().resolve()
        resolved_root = Path(event.command.poetry.file.path).resolve().parent

        # ── A: Poetry resolved to a parent directory ──────────────────────
        if resolved_root != cwd:
            if sys.stdin.isatty():
                _console.print(Panel(
                    f"[yellow]Project root resolved to:[/yellow]\n"
                    f"  [cyan]{resolved_root}[/cyan]\n\n"
                    f"No [bold]pyproject.toml[/bold] found in current directory:\n"
                    f"  [cyan]{cwd}[/cyan]",
                    title="[yellow bold]⚠  hw-plugin[/yellow bold]",
                    expand=False,
                ))
                confirmed = questionary.confirm(
                    "Create pyproject.toml here and abort this run?",
                    default=True,
                ).ask()
                if confirmed:
                    _bootstrap_root_pyproject(cwd)
                    _ensure_venv_in_project(cwd, io)
                    _console.print("Run [bold]poetry install[/bold] again to continue.")
            else:
                _bootstrap_root_pyproject(cwd)
                _ensure_venv_in_project(cwd, io)
                io.write_line(
                    f"<info>[hw-plugin] Created pyproject.toml in {cwd} from detected variant. "
                    "Re-run 'poetry install' to continue.</info>"
                )
            event.disable_command()
            return

        # ── B: Correct root, no variants/ → not a hw-plugin project ──────
        variants_dir = cwd / "variants"
        if not variants_dir.exists():
            return

        # ── C: hw-plugin project ──────────────────────────────────────────
        variant = detect_variant()
        variant_dir = variants_dir / variant
        last_variant = read_last_variant(cwd)

        if not variant_dir.exists():
            available = [d.name for d in variants_dir.iterdir() if d.is_dir()]
            io.write_error_line(
                f"<error>[hw-plugin] Variant not found: {variant}</error>\n"
                f"  Available: {available}\n"
                f"  Set HW_VARIANT=<name> to override."
            )
            return

        if sys.stdin.isatty():
            chosen = _show_install_tui(variant, cwd, variants_dir, last_variant)
            if chosen == "cancel":
                event.disable_command()
                return
            if chosen == "as_is":
                return
            if chosen == "create":
                _run_create_variant_flow(variants_dir)
                event.disable_command()
                return
            if chosen != variant:
                variant = chosen
                variant_dir = variants_dir / variant
        else:
            venv_path = cwd / ".venv"
            venv_state = "exists" if venv_path.exists() else "will be created"
            io.write_line(
                f"<info>[hw-plugin] Detected variant: {variant} | "
                f"Virtualenv: {venv_path} ({venv_state})</info>"
            )

        # ── Staleness check ───────────────────────────────────────────────
        if _is_lock_stale(variant_dir):
            if sys.stdin.isatty():
                _console.print(Panel(
                    f"[yellow]Lock file for [bold]{variant}[/bold] is outdated.[/yellow]\n"
                    "The pyproject.toml has changed since the lock was generated.",
                    title="[yellow bold]⚠ Stale lock[/yellow bold]",
                    expand=False,
                ))
                do_lock = questionary.confirm(
                    "Run 'poetry lock' now to regenerate?",
                    default=True,
                ).ask()
                if do_lock:
                    if not _run_lock_subprocess(cwd, variant_dir):
                        _console.print("[red]✗ poetry lock failed — aborting install.[/red]")
                        event.disable_command()
                        return
                    _console.print("[green]✓[/green] Lock regenerated.")
                else:
                    _console.print("[yellow]Proceeding with stale lock — install may fail.[/yellow]")
            else:
                io.write_error_line(
                    f"<warning>[hw-plugin] Lock for '{variant}' is outdated. "
                    "Run 'poetry lock' before installing.</warning>"
                )

        # ── Sync option (install only) ────────────────────────────────────
        if isinstance(event.command, InstallCommand):
            if sys.stdin.isatty():
                use_sync = questionary.confirm(
                    "Sync: remove packages not in this lock?  (--sync)",
                    default=True,
                ).ask()
                if use_sync is None:
                    use_sync = True
            else:
                use_sync = os.environ.get("HW_NO_SYNC") != "1"
            _set_sync_option(event, use_sync)

        # ── Variant swap ──────────────────────────────────────────────────
        shutil.copy(variant_dir / "pyproject.toml", cwd / "pyproject.toml")
        io.write_line("<comment>[hw-plugin] pyproject.toml updated from variant.</comment>")

        lock_src = variant_dir / "poetry.lock"
        if lock_src.exists():
            shutil.copy(lock_src, cwd / "poetry.lock")
            io.write_line("<comment>[hw-plugin] poetry.lock loaded from variant.</comment>")
        else:
            io.write_line(
                f"<comment>[hw-plugin] No lock for {variant}, will generate.</comment>"
            )

        _ensure_gitignore(cwd, io)
        _ensure_venv_in_project(cwd, io)

        # Force Poetry to discard its cached in-memory project and reload from
        # the variant pyproject.toml we just wrote to disk.  Without this, Poetry
        # would resolve and install deps from whichever pyproject it loaded at
        # startup (which may be a different variant or the placeholder).
        _invalidate_poetry_cache(event)

        # ── pre_install hook ──────────────────────────────────────────────
        if isinstance(event.command, InstallCommand):
            run_pre_install(variant_dir, cwd, io)

        self._root = cwd
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

        write_last_variant(root, self._variant)

        # ── post_install hook ─────────────────────────────────────────────
        if isinstance(event.command, InstallCommand):
            run_post_install(variant_dir, root, event.io)

        _print_install_summary(root, self._variant)

        self._root = None
        self._variant = None


# ------------------------------------------------------------------
# Install-time TUI
# ------------------------------------------------------------------


def _show_install_tui(
    detected: str,
    cwd: Path,
    variants_dir: Path,
    last: str | None,
) -> str:
    """Show compact status panel + variant chooser.

    Returns a variant name to install, 'as_is', 'cancel', or 'create'.
    """
    venv_path = cwd / ".venv"
    venv_note = (
        f"[cyan]{venv_path}[/cyan]  [green](exists)[/green]"
        if venv_path.exists()
        else f"[cyan]{venv_path}[/cyan]  [dim](will be created)[/dim]"
    )

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", min_width=22)
    grid.add_column()
    grid.add_row("Detected variant", f"[green bold]{detected}[/green bold]")
    grid.add_row("Platform", f"{platform.system()} / {platform.machine()}")
    grid.add_row("Python", platform.python_version())
    grid.add_row("Virtualenv", venv_note)
    if last and last != detected:
        grid.add_row("Last installed", f"[dim]{last}[/dim]")
    _console.print(Panel(grid, title="[bold cyan]hw-plugin[/bold cyan]", expand=False))

    available = (
        sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
        if variants_dir.exists()
        else []
    )
    others = [v for v in available if v != detected]

    choices: list = [
        questionary.Choice(title=f"Install: {detected}  (detected)", value=detected),
    ]
    if others:
        choices.append(questionary.Choice(title="Other variants...", value="__other__"))
    choices += [
        questionary.Separator(),
        questionary.Choice(title="Create new variant", value="create"),
        questionary.Choice(
            title="Install as-is  (skip variant swap, use root pyproject.toml)",
            value="as_is",
        ),
        questionary.Choice(title="Cancel", value="cancel"),
    ]

    chosen = questionary.select("How would you like to proceed?", choices=choices).ask()
    if chosen is None:
        return "cancel"

    if chosen == "__other__":
        sub_choices = [questionary.Choice(title=v, value=v) for v in others]
        sub_choices.append(questionary.Choice(title="← Back", value="__back__"))
        sub = questionary.select("Select variant:", choices=sub_choices).ask()
        if sub is None or sub == "__back__":
            return "cancel"
        return sub

    return chosen


def _run_create_variant_flow(variants_dir: Path) -> None:
    """Interactive create-variant sub-flow invoked from the install TUI."""
    name = questionary.text(
        "New variant name:",
        validate=lambda v: (
            True if v and v.replace("-", "").replace("_", "").isalnum()
            else "Use only letters, numbers, hyphens, underscores"
        ),
    ).ask()
    if not name:
        return

    if (variants_dir / name).exists():
        _console.print(f"[yellow]⚠ Variant [bold]{name}[/bold] already exists.[/yellow]")
        return

    copy_from: str | None = None
    if variants_dir.exists():
        existing = sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
        if existing:
            choice = questionary.select(
                "Start from:",
                choices=["Fresh template"] + existing,
            ).ask()
            if choice and choice != "Fresh template":
                copy_from = choice

    variant_dir = create_variant(variants_dir, name, copy_from=copy_from)
    _console.print(
        f"\n[green]✓[/green] Created [bold]{variant_dir.relative_to(variants_dir.parent)}[/bold]\n"
        f"  Edit [cyan]{variant_dir / 'pyproject.toml'}[/cyan] to add deps,\n"
        "  then re-run [bold]poetry install[/bold]."
    )


# ------------------------------------------------------------------
# Lock staleness helpers
# ------------------------------------------------------------------

# Mirror of Poetry's Locker._relevant_keys / _legacy_keys / _relevant_project_keys
# (Poetry 2.x — verified against installed source)
_LOCK_RELEVANT_KEYS = ("dependencies", "source", "extras", "dev-dependencies", "group")
_LOCK_LEGACY_KEYS   = ("dependencies", "source", "extras", "dev-dependencies")
_LOCK_PROJECT_KEYS  = ("requires-python", "dependencies", "optional-dependencies")


def _compute_content_hash(pyproject_data: dict) -> str:
    """Replicate Poetry's Locker._get_content_hash for staleness detection."""
    project = pyproject_data.get("project", {})
    tool_poetry = pyproject_data.get("tool", {}).get("poetry", {})

    relevant_project: dict = {}
    for key in _LOCK_PROJECT_KEYS:
        val = project.get(key)
        if val is not None:
            relevant_project[key] = val

    relevant_poetry: dict = {}
    for key in _LOCK_RELEVANT_KEYS:
        val = tool_poetry.get(key)
        if val is None and (key not in _LOCK_LEGACY_KEYS or relevant_project):
            continue
        relevant_poetry[key] = val

    if relevant_project:
        content: dict = {"project": relevant_project, "tool": {"poetry": relevant_poetry}}
    else:
        content = relevant_poetry

    return sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _is_lock_stale(variant_dir: Path) -> bool:
    """Return True if variant/poetry.lock content-hash mismatches variant/pyproject.toml."""
    lock_path = variant_dir / "poetry.lock"
    if not lock_path.exists():
        return False
    try:
        pyproject_data = tomllib.loads(
            (variant_dir / "pyproject.toml").read_text(encoding="utf-8")
        )
        lock_data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        stored = lock_data.get("metadata", {}).get("content-hash", "")
        return _compute_content_hash(pyproject_data) != stored
    except Exception:
        return False


def _run_lock_subprocess(cwd: Path, variant_dir: Path) -> bool:
    """Run poetry lock with HW_PLUGIN_DISABLE=1, sync result to variant dir.

    The root pyproject.toml must already contain the variant's content before
    calling this — the subprocess uses whatever file is at cwd/pyproject.toml.
    Returns True on success.
    """
    shutil.copy(variant_dir / "pyproject.toml", cwd / "pyproject.toml")
    env = {**os.environ, "HW_PLUGIN_DISABLE": "1"}
    result = subprocess.run(["poetry", "lock"], cwd=str(cwd), env=env)
    if result.returncode == 0:
        lock_dst = cwd / "poetry.lock"
        if lock_dst.exists():
            shutil.copy(lock_dst, variant_dir / "poetry.lock")
            return True
    return False


# ------------------------------------------------------------------
# Misc helpers
# ------------------------------------------------------------------


def _bootstrap_root_pyproject(cwd: Path) -> None:
    """Write the detected variant's pyproject.toml to the project root.

    Must copy the real variant content — not a minimal placeholder — because Poetry
    reads pyproject.toml into memory before the COMMAND event fires.  On the next
    `poetry install` run Poetry's in-memory state must already contain the correct
    dependency graph; there is no reliable way to invalidate that cache mid-run.
    Falls back to a placeholder only when no variant directory exists yet.
    """
    variants_dir = cwd / "variants"
    variant = detect_variant()
    variant_src = variants_dir / variant / "pyproject.toml"

    if variant_src.exists():
        shutil.copy(variant_src, cwd / "pyproject.toml")
        _console.print(
            f"[green]✓[/green] Created [cyan]pyproject.toml[/cyan] "
            f"from variant [bold]{variant}[/bold]"
        )
    else:
        create_placeholder(cwd)
        _console.print("[green]✓[/green] Created placeholder [cyan]pyproject.toml[/cyan]")


def _invalidate_poetry_cache(event: ConsoleCommandEvent) -> None:
    """Clear the cached Poetry project object so the next access re-reads from disk.

    Poetry parses pyproject.toml once at startup and caches it in
    application._poetry.  After we swap the file on disk the cache is stale.
    Resetting it causes the next self.poetry access inside command.handle()
    to call Factory.create_poetry(cwd) again, which reads our swapped file.
    The hasattr guard makes this a no-op if the private attribute is renamed
    in a future Poetry release.
    """
    app = getattr(event.command, "application", None)
    if app is not None and hasattr(app, "_poetry"):
        app._poetry = None


def _print_install_summary(root: Path, variant: str) -> None:
    """Print a completion panel with variant version and .venv path."""
    version = "unknown"
    try:
        pdata = tomllib.loads(
            (root / "variants" / variant / "pyproject.toml").read_text(encoding="utf-8")
        )
        version = pdata.get("tool", {}).get("poetry", {}).get("version", "unknown")
    except Exception:
        pass

    venv_path = root / ".venv"
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold", min_width=14)
    grid.add_column()
    grid.add_row("Variant", f"[green bold]{variant}[/green bold]  [dim]v{version}[/dim]")
    grid.add_row("Virtualenv", f"[cyan]{venv_path}[/cyan]")
    _console.print(Panel(
        grid,
        title="[bold green]✓ install complete[/bold green]",
        expand=False,
    ))


def _set_sync_option(event: ConsoleCommandEvent, sync: bool) -> None:
    """Inject --sync into the install command's input options before handle() runs."""
    if not sync:
        return
    try:
        event.io.input.set_option("sync", True)  # type: ignore[attr-defined]
    except Exception:
        pass


def _ensure_gitignore(root: Path, io: object) -> None:
    """Append hw-plugin managed entries to .gitignore if not already present."""
    gitignore = root / ".gitignore"
    entries = ["/poetry.lock", "/.hw-plugin-state"]

    existing_lines: list[str] = []
    current = ""
    if gitignore.exists():
        current = gitignore.read_text(encoding="utf-8")
        existing_lines = [ln.strip() for ln in current.splitlines()]

    to_add = [
        e for e in entries
        if e not in existing_lines and e.lstrip("/") not in existing_lines
    ]
    if not to_add:
        return

    block = "\n# hw-plugin managed\n" + "\n".join(to_add) + "\n"
    if gitignore.exists():
        gitignore.write_text(current.rstrip() + block, encoding="utf-8")
    else:
        gitignore.write_text(block.lstrip(), encoding="utf-8")

    for entry in to_add:
        io.write_line(  # type: ignore[attr-defined]
            f"<comment>[hw-plugin] Added '{entry}' to .gitignore</comment>"
        )


def _ensure_venv_in_project(root: Path, io: IO) -> None:
    """Write poetry.toml to pin virtualenv inside the project directory."""
    poetry_toml = root / "poetry.toml"
    desired = "[virtualenvs]\nin-project = true\n"

    if poetry_toml.exists():
        content = poetry_toml.read_text(encoding="utf-8")
        if re.search(r"in-project\s*=\s*true", content):
            return
        poetry_toml.write_text(content.rstrip() + "\n\n" + desired, encoding="utf-8")
    else:
        poetry_toml.write_text(desired, encoding="utf-8")

    io.write_line(
        "<comment>[hw-plugin] poetry.toml: virtualenvs.in-project = true</comment>"
    )
