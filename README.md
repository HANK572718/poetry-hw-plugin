# poetry-hw-plugin

A Poetry `ApplicationPlugin` that auto-detects hardware and switches the project's
`pyproject.toml` and `poetry.lock` to the matching variant before running
`poetry install` or `poetry lock`.

## How it works

1. On `poetry install` / `poetry lock`, the plugin detects the current hardware variant
   (e.g. `win-cuda`, `linux-arm-cpu`, `mac`).
2. It copies `variants/<variant>/pyproject.toml` → project root.
3. It copies `variants/<variant>/poetry.lock` → project root (if it exists).
4. After the command completes, it syncs the updated `poetry.lock` back to
   `variants/<variant>/poetry.lock`.

Projects without a `variants/` directory are silently skipped.

## Variant naming

| Variant | Condition |
|---------|-----------|
| `win-cuda` | Windows + NVIDIA GPU |
| `win-xpu` | Windows + Intel Arc |
| `win-cpu` | Windows + no GPU |
| `linux-arm-cuda` | Linux ARM + CUDA (Jetson) |
| `linux-arm-cpu` | Linux ARM + no GPU |
| `linux-x86-cuda` | Linux x86\_64 + NVIDIA GPU |
| `linux-x86-xpu` | Linux x86\_64 + Intel Arc |
| `linux-x86-cpu` | Linux x86\_64 + no GPU |
| `mac` | macOS |

## Installation

```bash
# From GitHub (single command on a new machine)
poetry self add git+https://github.com/HANK572718/poetry-hw-plugin.git

# Pin to a specific tag
poetry self add git+https://github.com/HANK572718/poetry-hw-plugin.git@v0.1.0

# Local development
poetry self add /path/to/poetry-hw-plugin/
```

## Manual override

Set `HW_VARIANT` to bypass auto-detection:

```bash
# Linux / macOS
HW_VARIANT=linux-x86-cuda poetry install

# Windows PowerShell
$env:HW_VARIANT = "win-cuda"; poetry install
```

Set `HW_PLUGIN_DISABLE=1` to disable the plugin entirely for a single run:

```bash
HW_PLUGIN_DISABLE=1 poetry install
```

## Project layout (consumer side)

```
my-project/
├── pyproject.toml        ← overwritten by plugin on each run
├── poetry.lock           ← overwritten by plugin, add /poetry.lock to .gitignore
├── poetry.toml           ← created by plugin (virtualenvs.in-project = true)
└── variants/
    ├── win-cuda/
    │   ├── pyproject.toml
    │   └── poetry.lock
    └── linux-arm-cpu/
        ├── pyproject.toml
        └── poetry.lock   ← generated on first run
```

## Uninstall

```bash
poetry self remove poetry-hw-plugin
```
