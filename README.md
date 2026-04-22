# poetry-hw-plugin

A Poetry `ApplicationPlugin` that auto-detects the current hardware and
automatically switches `pyproject.toml` and `poetry.lock` to the matching
platform variant before `poetry install` / `poetry lock`.

> Install once, works everywhere — Windows + CUDA, Jetson, Linux x86, macOS.

---

## How it works

```
poetry install / poetry lock
        │
        ▼  [COMMAND event]
detect_variant()          → e.g. "win-cuda"
copy variants/win-cuda/pyproject.toml  → ./pyproject.toml
copy variants/win-cuda/poetry.lock     → ./poetry.lock  (if exists)
write ./poetry.toml                    → virtualenvs.in-project = true
append /poetry.lock to .gitignore
        │
        ▼  Poetry core runs install / lock
        │
        ▼  [TERMINATE event]  (only on success)
copy ./poetry.lock  →  variants/win-cuda/poetry.lock
```

Projects **without** a `variants/` directory are silently skipped —
the plugin is safe to install globally.

---

## Requirements

- Poetry **≥ 2.0**
- Python **≥ 3.10** in the project

---

## Installation

> **Note:** This is a private repo. Use the SSH URL (requires SSH key
> configured for GitHub).

```bash
# New machine — one-time global install
poetry self add git+ssh://git@github.com/HANK572718/poetry-hw-plugin.git

# Pin to a specific tag for reproducibility
poetry self add git+ssh://git@github.com/HANK572718/poetry-hw-plugin.git@v0.1.0

# Local development of the plugin itself
poetry self add /path/to/poetry-hw-plugin/
```

> ⚠️ **Windows cross-drive limitation:** `poetry self add <local-path>` fails
> when the plugin is on a different drive (e.g. plugin on `D:\` but Poetry on `C:\`).
> Use the SSH git URL instead.

### Uninstall

```bash
poetry self remove poetry-hw-plugin
```

---

## Quickstart: set up a project to use this plugin

### 1  Create the `variants/` directory structure

```
my-project/
└── variants/
    ├── win-cuda/
    │   └── pyproject.toml   ← Windows + NVIDIA GPU deps
    └── linux-arm-cuda/
        └── pyproject.toml   ← Jetson / Linux ARM deps
```

Each `variants/<name>/pyproject.toml` is a **complete, standalone**
`pyproject.toml` with the platform-specific dependencies merged directly
into `[tool.poetry.dependencies]` (no groups needed).

### 2  Write a variant `pyproject.toml`

```toml
# variants/win-cuda/pyproject.toml
[tool.poetry]
name    = "my-project"
version = "1.0.0"

[tool.poetry.dependencies]
python  = ">=3.10,<3.11"
numpy   = "==1.26.4"
# ── Windows CUDA 12.8 ──────────────────────────────────────
torch      = { url = "https://download.pytorch.org/whl/cu128/torch-2.10.0%2Bcu128-cp310-cp310-win_amd64.whl" }
torchvision = { url = "https://download.pytorch.org/whl/cu128/torchvision-0.25.0%2Bcu128-cp310-cp310-win_amd64.whl" }
tensorrt-cu12 = "^10.15.1.29"

[build-system]
requires      = ["poetry-core>=2.0.0"]
build-backend = "poetry.core.masonry.api"
```

### 3  Add the source variant's `poetry.lock` (optional)

If you already have a working lock file, copy it in:

```bash
cp poetry.lock variants/win-cuda/poetry.lock
```

If the lock is absent, the plugin will generate it on the first run.

### 4  Update `.gitignore`

The root `poetry.lock` is now variant-managed; commit only the ones
inside `variants/`:

```gitignore
/poetry.lock   # managed by hw-plugin; each variant/ has its own copy
```

> The plugin writes this entry automatically on first run.

### 5  Run as normal

```bash
poetry install   # plugin detects variant, copies files, then installs
poetry lock      # same for lock regeneration
```

---

## `poetry hw` — Status & Help

```
$ poetry hw

  hw-plugin  Hardware Detection Status
  ──────────────────────────────────────────────────
  Detected variant : win-cuda
  Platform         : Windows / AMD64
  Python           : 3.10.x

  Project Variants  (variants/ — 2 found)
  ──────────────────────────────────────────────────
  Variant                  Lock   Note
  ──────────────────────────────  ──────────────
  linux-arm-cuda            ✗
  win-cuda                  ✓    ← current

  Usage
  ──────────────────────────────────────────────────
  poetry install
    auto-detect and install matching variant
  HW_VARIANT=<name> poetry install
    force a specific variant
  HW_PLUGIN_DISABLE=1 poetry install
    bypass plugin entirely
  poetry hw --detect
    print variant name (for scripts)

  Variant Reference
  ──────────────────────────────────────────────────
  win-cuda              Windows + NVIDIA GPU ★
  win-xpu               Windows + Intel Arc
  ...
```

```bash
# Print only the variant name (for scripting / CI)
poetry hw --detect
# → win-cuda
```

---

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
| `mac` | macOS (arm64 / x86\_64) |

---

## Manual override

```bash
# Linux / macOS — force a specific variant
HW_VARIANT=linux-arm-cuda poetry install

# Windows PowerShell
$env:HW_VARIANT = "win-cuda"; poetry install

# Disable plugin entirely for this run
HW_PLUGIN_DISABLE=1 poetry install
```

---

## Adding a new variant

1. Create `variants/<new-name>/pyproject.toml` with the platform deps.
2. Leave `variants/<new-name>/poetry.lock` absent — it will be generated
   on the first `poetry install` on that platform.
3. Optionally test the detection offline:

```bash
HW_VARIANT=<new-name> poetry hw
HW_VARIANT=<new-name> poetry install --dry-run
```

---

## CI / GitHub Actions example

```yaml
- name: Install Python deps
  run: poetry install
  env:
    HW_VARIANT: linux-x86-cuda   # force GPU variant on runner with GPU
```

---

## Project layout (consumer side)

```
my-project/
├── pyproject.toml        ← overwritten by plugin on each run (don't edit directly)
├── poetry.lock           ← overwritten by plugin; listed in .gitignore
├── poetry.toml           ← created by plugin: virtualenvs.in-project = true
└── variants/
    ├── win-cuda/
    │   ├── pyproject.toml   ← edit here to change Windows deps
    │   └── poetry.lock      ← commit this
    └── linux-arm-cuda/
        ├── pyproject.toml   ← edit here to change Jetson deps
        └── poetry.lock      ← generated on first Jetson run, then commit
```

> **Rule of thumb:** Never edit the root `pyproject.toml` or root `poetry.lock`
> directly. Always edit inside `variants/<name>/`.
