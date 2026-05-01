"""Scaffold new variant directories with template pyproject.toml."""

from __future__ import annotations

import shutil
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-reuse-import]

_TEMPLATE = """\
[tool.poetry]
name         = "{name}"
version      = "{version}"
description  = ""
authors      = {authors}
package-mode = false

[tool.poetry.dependencies]
python = "{python}"
# ── {variant} specific dependencies ────────────────────────────────────────

[build-system]
requires      = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
"""


_PLACEHOLDER = """\
# Managed by hw-plugin — overwritten on every `poetry install` / `poetry lock`.
# Edit platform-specific deps in variants/<platform>/pyproject.toml, not here.

[tool.poetry]
name         = "{name}"
version      = "0.1.0"
description  = ""
authors      = []
package-mode = false

[tool.poetry.dependencies]
python = ">=3.10"

[build-system]
requires      = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
"""


def create_placeholder(directory: Path) -> Path:
    """Create a minimal hw-plugin managed pyproject.toml placeholder in directory."""
    target = directory / "pyproject.toml"
    target.write_text(_PLACEHOLDER.format(name=directory.name), encoding="utf-8")
    return target


def create_variant(variants_dir: Path, variant_name: str, copy_from: str | None = None) -> Path:
    """Create a variant directory with a pyproject.toml template or copied from an existing variant."""
    variant_dir = variants_dir / variant_name
    variant_dir.mkdir(parents=True, exist_ok=True)
    target = variant_dir / "pyproject.toml"

    if copy_from:
        shutil.copy(variants_dir / copy_from / "pyproject.toml", target)
        return variant_dir

    data: dict = {}
    root_toml = variants_dir.parent / "pyproject.toml"
    if root_toml.exists():
        data = tomllib.loads(root_toml.read_text(encoding="utf-8"))

    poetry = data.get("tool", {}).get("poetry", {})
    name = poetry.get("name", "my-project")
    version = poetry.get("version", "0.1.0")
    python = poetry.get("dependencies", {}).get("python", ">=3.10")
    authors = repr(poetry.get("authors", []))

    target.write_text(
        _TEMPLATE.format(
            name=name,
            version=version,
            python=python,
            authors=authors,
            variant=variant_name,
        ),
        encoding="utf-8",
    )
    return variant_dir
