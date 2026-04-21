"""Unit tests for hw_plugin.detector."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hw_plugin.detector import detect_variant


# ------------------------------------------------------------------
# HW_VARIANT env override
# ------------------------------------------------------------------


def test_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HW_VARIANT", "linux-arm-cpu")
    assert detect_variant() == "linux-arm-cpu"


# ------------------------------------------------------------------
# macOS
# ------------------------------------------------------------------


def test_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with patch("platform.system", return_value="Darwin"):
        assert detect_variant() == "mac"


# ------------------------------------------------------------------
# Windows
# ------------------------------------------------------------------


def _win_no_gpu_run(cmd, **kwargs):
    raise FileNotFoundError


def test_windows_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with (
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        assert detect_variant() == "win-cuda"


def test_windows_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with (
        patch("platform.system", return_value="Windows"),
        patch("platform.machine", return_value="AMD64"),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        assert detect_variant() == "win-cpu"


# ------------------------------------------------------------------
# Linux x86_64
# ------------------------------------------------------------------


def test_linux_x86_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="x86_64"),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        assert detect_variant() == "linux-x86-cuda"


def test_linux_x86_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="x86_64"),
        patch("subprocess.run", side_effect=FileNotFoundError),
    ):
        assert detect_variant() == "linux-x86-cpu"


# ------------------------------------------------------------------
# Linux ARM (Jetson)
# ------------------------------------------------------------------


def test_linux_arm_jetson(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    model_file = tmp_path / "model"
    model_file.write_text("NVIDIA Jetson Orin NX")

    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="aarch64"),
        patch("subprocess.run", side_effect=FileNotFoundError),
        patch("hw_plugin.detector.Path") as mock_path,
    ):
        mock_path.return_value.read_text.return_value = "NVIDIA Jetson Orin NX"
        assert detect_variant() == "linux-arm-cuda"


def test_linux_arm_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HW_VARIANT", raising=False)
    with (
        patch("platform.system", return_value="Linux"),
        patch("platform.machine", return_value="aarch64"),
        patch("subprocess.run", side_effect=FileNotFoundError),
        patch("hw_plugin.detector._is_jetson", return_value=False),
    ):
        assert detect_variant() == "linux-arm-cpu"
