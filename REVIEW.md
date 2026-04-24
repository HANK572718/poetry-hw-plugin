# Code Review — poetry-hw-plugin

## Executive Summary

The plugin correctly handles hardware detection and variant switching, but carried several
bugs ranging from a shared-state race condition across plugin instances to a fragile venv
check that silently accepted `in-project = false`.  The WMI call used a deprecated PowerShell
cmdlet, the `poetry hw` command broke when run from a subdirectory, and the test suite
patched `Path` far too broadly, creating false confidence.  All ten issues have been fixed
and two missing test cases (Linux XPU and Windows XPU) have been added.

---

## Issues Table

| ID | File | Category | Description | Risk | Fixed |
|----|------|----------|-------------|------|-------|
| A  | `plugin.py` | Bug — shared state | `_root` / `_variant` declared as class attributes; concurrent or repeated plugin use corrupts state | High | Yes |
| B  | `plugin.py` | Missing feature | `UpdateCommand` not hooked; `poetry update` skips variant switching entirely | Medium | Yes |
| C  | `plugin.py` | Logic bug | `_ensure_venv_in_project` bails out when `in-project = false` is present, leaving the wrong value | Medium | Yes |
| D  | `plugin.py` | Type safety | Helper `io` parameter typed as `object`; silences type-checker on `.write_line()` | Low | Yes |
| E  | `detector.py` | Deprecation | `Get-WmiObject` is deprecated in PowerShell 3+; replaced by `Get-CimInstance` | Low | Yes |
| F  | `command.py` | Reliability | `Path.cwd()` for variant lookup fails when the user is in a subdirectory | Medium | Yes |
| G  | `tests/test_detector.py` | Test fragility | `test_linux_arm_jetson` patches all of `hw_plugin.detector.Path`, breaking any `Path` call inside the module | High | Yes |
| H  | `tests/test_detector.py` | Missing test | No coverage for Linux x86 Intel XPU path | Low | Yes |
| I  | `tests/test_detector.py` | Missing test | No coverage for Windows Intel XPU path | Low | Yes |
| J  | `pyproject.toml` | Tooling | `mypy` and `ruff` missing from dev deps; no `[tool.mypy]` / `[tool.ruff]` config | Low | Yes |

---

## Detailed Findings

### Fix A — Instance attributes for `_root` / `_variant`

**What:** `_root: Path | None = None` and `_variant: str | None = None` were declared at class
level, meaning every instance of `HwSelectPlugin` shared the same storage.  If Poetry ever
creates more than one plugin instance (e.g. during testing, or via future API changes) the
`before_command` of one instance would overwrite the state read by the `after_command` of
another.

**Why it matters:** This is a classic mutable-class-attribute bug that is invisible under
normal single-instance use but catastrophic when two instances coexist.

**Fix:** Added `__init__` that assigns `self._root` and `self._variant` as proper instance
attributes.

---

### Fix B — Hook `UpdateCommand`

**What:** `_HOOKED_COMMANDS` only contained `(InstallCommand, LockCommand)`.  Running
`poetry update` would not trigger variant switching, so the resolved lock would be generated
against the root `pyproject.toml` rather than the correct variant file.

**Fix:** Added `from poetry.console.commands.update import UpdateCommand` and appended it to
the tuple.

---

### Fix C — Correct `in-project` detection in `_ensure_venv_in_project`

**What:** The guard was `if "in-project" in content: return`.  If `poetry.toml` already
contained `in-project = false` the function returned early without correcting it, silently
leaving the virtualenv outside the project.

**Fix:** Replaced the substring check with a regex: `re.search(r"in-project\s*=\s*true", content)`.
Only an existing `true` value is treated as "already configured correctly".

---

### Fix D — Proper `IO` type annotation for helper functions

**What:** `_ensure_gitignore` and `_ensure_venv_in_project` declared their `io` parameter
as `object`.  Mypy therefore could not verify calls to `io.write_line(...)`, and the
`# type: ignore[attr-defined]` suppressions were needed as a workaround.

**Fix:** Imported `IO` from `cleo.io.io` and used it as the parameter type.  The `# type:
ignore` comments were removed.

---

### Fix E — Replace deprecated `Get-WmiObject` with `Get-CimInstance`

**What:** `Get-WmiObject` was deprecated in PowerShell 3.0 (released with Windows 8 / Server
2012) and removed from PowerShell 6+ (the cross-platform edition).  On modern systems the
command may be absent or produce a deprecation warning that pollutes the output.

**Fix:** Replaced with `Get-CimInstance Win32_VideoController`, the recommended modern
equivalent.

---

### Fix F — Walk up to find `pyproject.toml` in `HwInfoCommand`

**What:** `Path.cwd() / "variants"` assumes the user invokes `poetry hw` from the project
root.  Running it from `src/`, `tests/`, or any subdirectory produces an incorrect path and
the variants table is never displayed.

**Fix:** Added `_find_project_root()` which walks from `cwd()` upward until it finds a
directory containing `pyproject.toml`, falling back to `cwd()` if none is found.  The
variants lookup now uses this helper.

---

### Fix G — Narrow the `_is_jetson` patch in `test_linux_arm_jetson`

**What:** The test patched `hw_plugin.detector.Path` entirely.  This replaced the `Path`
class itself inside the module, so any code path that constructs a `Path` object (including
internal library code) would receive a `MagicMock`.  The test also carried an unused
`tmp_path` fixture and dead `model_file` setup code.

**Fix:** Changed to `patch("hw_plugin.detector._is_jetson", return_value=True)`, mirroring
the pattern already used in `test_linux_arm_cpu`.  This is precise, readable, and robust.

---

### Fix H — Add `test_linux_x86_xpu`

**What:** There was no test exercising the path where `nvidia-smi` is absent but `xpu-smi`
succeeds on Linux x86.

**Fix:** Added `test_linux_x86_xpu` with a `side_effect` function that raises
`FileNotFoundError` for `nvidia-smi` and returns a successful mock for any other command
(i.e. `xpu-smi`).  Expected result: `"linux-x86-xpu"`.

---

### Fix I — Add `test_windows_xpu`

**What:** There was no test for the Windows Intel XPU branch (`_intel_gpu_via_wmi` returns
`True` while `nvidia-smi` is absent).

**Fix:** Added `test_windows_xpu` that patches `subprocess.run` to raise `FileNotFoundError`
(covers `nvidia-smi`) and patches `hw_plugin.detector._intel_gpu_via_wmi` to return `True`.
Expected result: `"win-xpu"`.

---

### Fix J — Add mypy, ruff, and their config sections to `pyproject.toml`

**What:** The dev dependency group only listed `pytest`.  Without `mypy` and `ruff` in the
lock file there is no guarantee that CI runs the same linter/type-checker versions across
machines.  There were also no `[tool.mypy]` or `[tool.ruff]` sections, so both tools fall
back to their built-in defaults.

**Fix:**
- Added `mypy = ">=1.5"` and `ruff = ">=0.1"` to `[tool.poetry.group.dev.dependencies]`.
- Added `[tool.mypy]` with `strict = true` and `ignore_missing_imports = true`.
- Added `[tool.ruff]` with `target-version`, `line-length`, and a curated `[tool.ruff.lint]`
  `select` list covering pyflakes, pycodestyle, isort, pyupgrade, flake8-bugbear, and
  pathlib checks.

---

## What Was Already Good

- **Detection priority** (`HW_VARIANT` env → macOS → ARM/x86 → GPU probe) is logical and
  well-documented.
- **`_cmd_ok` helper** catches all exceptions cleanly; subprocess timeouts are set.
- **Lock sync-back in `after_command`** correctly checks `exit_code != 0` before writing,
  preventing corrupt locks on failed installs.
- **`.gitignore` deduplication logic** in `_ensure_gitignore` handles both `/poetry.lock`
  and bare `poetry.lock` entries.
- **`HwInfoCommand` output** is well-structured and covers env overrides, available variants,
  usage, and a full variant reference table.
- **Existing tests** cover the main happy-path and CPU-fallback cases for every platform.
- **`pyproject.toml` plugin entry-point** declaration is correct for Poetry's application
  plugin API.
