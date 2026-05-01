"""poetry hw — interactive hardware variant TUI (rich + questionary)."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

import questionary
from cleo.commands.command import Command
from cleo.helpers import option
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reuse-import]

from .detector import detect_variant
from .scaffold import create_variant
from .state import read_last_variant

console = Console()

_VARIANT_DESCRIPTIONS: dict[str, str] = {
    "win-cuda":       "Windows + NVIDIA GPU",
    "win-xpu":        "Windows + Intel Arc",
    "win-cpu":        "Windows + no GPU",
    "linux-arm-cuda": "Linux ARM + CUDA (Jetson)",
    "linux-arm-cpu":  "Linux ARM + no GPU",
    "linux-x86-cuda": "Linux x86_64 + NVIDIA GPU",
    "linux-x86-xpu":  "Linux x86_64 + Intel Arc",
    "linux-x86-cpu":  "Linux x86_64 + no GPU",
    "mac":            "macOS (arm64 / x86_64)",
}

_OPT_CREATE_CUSTOM = "Create new variant (custom name)"
_OPT_SET_VERSION   = "Update variant version"
_OPT_HELP          = "Help & usage"
_OPT_EXIT          = "Exit"


def _find_project_root(start: Path | None = None) -> Path:
    """Walk up from *start* (default: cwd) to find the directory containing pyproject.toml.

    Returns the first ancestor directory that contains a ``pyproject.toml`` file.
    Falls back to the starting directory if none is found.
    """
    current = (start or Path.cwd()).resolve()
    for directory in (current, *current.parents):
        if (directory / "pyproject.toml").exists():
            return directory
    return current


class HwInfoCommand(Command):
    """Interactive hardware variant management."""

    name = "hw"
    description = "Show hardware detection status and manage variants"

    options = [
        option("--detect", "-d", "Print detected variant name only (for scripting)", flag=True),
        option(
            "--set-version",
            None,
            "Set a variant's version non-interactively: <variant>:<version>  [CI/CD]",
            flag=False,
        ),
    ]

    def handle(self) -> int:
        """Run the interactive TUI, or handle scripting flags."""
        variant = detect_variant()

        if self.option("detect"):
            self.line(variant)
            return 0

        set_ver = self.option("set-version")
        if set_ver:
            return self._cli_set_version(set_ver)

        self._render_status(variant)

        create_current_label = f"Create variant for current platform ({variant})"
        action = questionary.select(
            "What would you like to do?",
            choices=[
                create_current_label,
                _OPT_CREATE_CUSTOM,
                _OPT_SET_VERSION,
                _OPT_HELP,
                _OPT_EXIT,
            ],
        ).ask()

        if action is None or action == _OPT_EXIT:
            return 0
        if action == create_current_label:
            return self._flow_create_current(variant)
        if action == _OPT_CREATE_CUSTOM:
            return self._flow_create_variant()
        if action == _OPT_SET_VERSION:
            return self._flow_set_version()
        if action == _OPT_HELP:
            self._render_help()
            return 0
        return 0

    # ── Rendering ─────────────────────────────────────────────────────────

    def _render_status(self, variant: str) -> None:
        """Render hardware status and variant table using rich."""
        forced = os.environ.get("HW_VARIANT", "").strip()
        disabled = os.environ.get("HW_PLUGIN_DISABLE", "").strip()

        grid = Table.grid(padding=(0, 2))
        grid.add_column(style="bold", min_width=22)
        grid.add_column()
        grid.add_row("Detected variant", f"[green bold]{variant}[/green bold]")
        grid.add_row("Platform", f"{platform.system()} / {platform.machine()}")
        grid.add_row("Python", platform.python_version())
        if forced:
            grid.add_row("[yellow]HW_VARIANT override[/yellow]", f"[yellow]{forced}[/yellow]")
        if disabled == "1":
            grid.add_row("[red]Plugin disabled[/red]", "[red]HW_PLUGIN_DISABLE=1[/red]")

        console.print(Panel(
            grid,
            title="[bold cyan]hw-plugin[/bold cyan] Hardware Status",
            expand=False,
        ))

        # ── Project variants ──────────────────────────────────────────
        variants_dir = _find_project_root() / "variants"
        variants_dir = Path.cwd() / "variants"
        if variants_dir.exists() and variants_dir.is_dir():
            available = sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
            last_variant = read_last_variant(Path.cwd())
            table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
            table.add_column("Variant")
            table.add_column("Lock", justify="center")
            table.add_column("Description")
            table.add_column("Note")
            for v in available:
                has_lock = (variants_dir / v / "poetry.lock").exists()
                lock_col = "[green]✓[/green]" if has_lock else "[dim]✗[/dim]"
                desc = _VARIANT_DESCRIPTIONS.get(v, "")
                notes = []
                if v == variant:
                    notes.append("[green bold]← current[/green bold]")
                if v == last_variant:
                    notes.append("[dim]← last[/dim]")
                table.add_row(v, lock_col, desc, "  ".join(notes))
            console.print(Panel(
                table,
                title=f"[bold]Project Variants[/bold] [dim]({len(available)} found)[/dim]",
                expand=False,
            ))
        else:
            console.print(Panel(
                "[dim]No [bold]variants/[/bold] directory — plugin will skip this project.[/dim]\n"
                "Use [bold green]Create variant for current platform[/bold green] to scaffold one.",
                title="[bold]Project Variants[/bold]",
                expand=False,
            ))

    def _render_help(self) -> None:
        """Render plugin help: usage, project layout, variant reference."""
        usage = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        usage.add_column(style="cyan", no_wrap=True)
        usage.add_column(style="dim")
        for cmd, desc in [
            ("poetry install",                           "auto-detect and install matching variant"),
            ("poetry lock",                              "auto-detect and regenerate lock for variant"),
            ("HW_VARIANT=<name> poetry install",         "force a specific variant"),
            ("HW_PLUGIN_DISABLE=1 poetry install",       "bypass plugin entirely"),
            ("poetry hw",                                "this interactive TUI"),
            ("poetry hw --detect",                       "print variant name for scripting / CI"),
            ("poetry hw --set-version <variant>:<ver>",  "update a variant's version (CI/CD)"),
        ]:
            usage.add_row(cmd, desc)
        console.print(Panel(usage, title="[bold]Usage[/bold]", expand=False))

        tree = Tree("[bold]my-project/[/bold]")
        tree.add("[dim]pyproject.toml[/dim]   overwritten by plugin on each run")
        tree.add("[dim]poetry.lock[/dim]      overwritten by plugin; listed in .gitignore")
        tree.add("[dim]poetry.toml[/dim]      created by plugin: virtualenvs.in-project = true")
        v_branch = tree.add("[bold]variants/[/bold]")
        wc = v_branch.add("win-cuda/")
        wc.add("[cyan]pyproject.toml[/cyan]   ← edit here for Windows deps")
        wc.add("[cyan]poetry.lock[/cyan]      ← commit this")
        la = v_branch.add("linux-arm-cuda/")
        la.add("[cyan]pyproject.toml[/cyan]")
        la.add("[cyan]poetry.lock[/cyan]      ← generated on first run, then commit")
        console.print(Panel(tree, title="[bold]Project Layout[/bold]", expand=False))

        ref = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        ref.add_column("Variant")
        ref.add_column("Condition")
        for name, desc in _VARIANT_DESCRIPTIONS.items():
            ref.add_row(name, desc)
        console.print(Panel(ref, title="[bold]Variant Reference[/bold]", expand=False))

    # ── Actions ───────────────────────────────────────────────────────────

    def _flow_create_current(self, variant: str) -> int:
        """Scaffold a variant directory for the currently detected platform."""
        variants_dir = Path.cwd() / "variants"
        if (variants_dir / variant).exists():
            console.print(f"[yellow]⚠ Variant [bold]{variant}[/bold] already exists.[/yellow]")
            return 1
        variant_dir = create_variant(variants_dir, variant)
        console.print(f"\n[green]✓[/green] Created [bold]{variant_dir.relative_to(Path.cwd())}[/bold]")
        console.print(f"  Edit [cyan]{variant_dir / 'pyproject.toml'}[/cyan] to add platform-specific deps.")
        return 0

    def _flow_create_variant(self) -> int:
        """Interactive flow to scaffold a new variant with a custom name."""
        variants_dir = Path.cwd() / "variants"

        name = questionary.text(
            "New variant name:",
            validate=lambda v: (
                True if v and v.replace("-", "").replace("_", "").isalnum()
                else "Use only letters, numbers, hyphens, underscores"
            ),
        ).ask()
        if not name:
            return 0

        if (variants_dir / name).exists():
            console.print(f"[yellow]⚠ Variant [bold]{name}[/bold] already exists.[/yellow]")
            return 1

        copy_from: str | None = None
        if variants_dir.exists() and variants_dir.is_dir():
            existing = sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
            if existing:
                choice = questionary.select(
                    "Start from:",
                    choices=["Fresh template"] + existing,
                ).ask()
                if choice is None:
                    return 0
                if choice != "Fresh template":
                    copy_from = choice

        variant_dir = create_variant(variants_dir, name, copy_from=copy_from)
        console.print(f"\n[green]✓[/green] Created [bold]{variant_dir.relative_to(Path.cwd())}[/bold]")
        console.print(f"  Edit [cyan]{variant_dir / 'pyproject.toml'}[/cyan] to add platform-specific deps.")
        return 0

    def _flow_set_version(self) -> int:
        """Interactive flow to update a variant's version field."""
        variants_dir = Path.cwd() / "variants"
        if not variants_dir.exists():
            console.print("[yellow]No variants/ directory found.[/yellow]")
            return 0
        existing = sorted(d.name for d in variants_dir.iterdir() if d.is_dir())
        if not existing:
            console.print("[yellow]No variants found.[/yellow]")
            return 0

        variant = questionary.select("Select variant to update:", choices=existing).ask()
        if not variant:
            return 0

        toml_path = variants_dir / variant / "pyproject.toml"
        data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
        current = data.get("tool", {}).get("poetry", {}).get("version", "unknown")

        new_ver = questionary.text(
            f"New version (current: {current}):",
            validate=lambda v: True if v.strip() else "Version cannot be empty",
        ).ask()
        if not new_ver:
            return 0
        return self._do_set_version(variant, new_ver.strip())

    def _cli_set_version(self, spec: str) -> int:
        """Handle --set-version variant:version for non-interactive CI/CD use."""
        if ":" not in spec:
            console.print("[red]Format: --set-version <variant>:<version>  e.g. win-cuda:1.2.0[/red]")
            return 1
        variant, version = spec.split(":", 1)
        return self._do_set_version(variant.strip(), version.strip())

    def _do_set_version(self, variant: str, version: str) -> int:
        """Write a new version string into variants/<variant>/pyproject.toml."""
        variants_dir = Path.cwd() / "variants"
        toml_path = variants_dir / variant / "pyproject.toml"
        if not toml_path.exists():
            console.print(f"[red]✗ variants/{variant}/pyproject.toml not found[/red]")
            return 1
        content = toml_path.read_text(encoding="utf-8")
        new_content, count = re.subn(
            r'^(version\s*=\s*")[^"]*(")',
            rf'\g<1>{version}\g<2>',
            content,
            flags=re.MULTILINE,
        )
        if count == 0:
            console.print(f"[yellow]⚠ No version field in variants/{variant}/pyproject.toml[/yellow]")
            return 1
        toml_path.write_text(new_content, encoding="utf-8")
        console.print(f"[green]✓[/green] variants/[bold]{variant}[/bold] version → [bold green]{version}[/bold green]")
        return 0
