"""Validate public installer's argument handling without root or machine changes."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.fixture
def bash():
    if os.name == "nt":
        path = Path("C:/Program Files/Git/bin/bash.exe")
        if path.exists():
            return str(path)
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not installed")
    return found


def test_installer_help_is_safe_without_root(bash):
    result = subprocess.run([bash, "install.sh", "--help"], capture_output=True, encoding="utf-8", timeout=10)
    assert result.returncode == 0
    assert "Debian 12 / 13" in result.stdout


@pytest.mark.parametrize("args", [
    ["--domain"],
    ["--version", "../../main"],
    ["--domain", "https://example.com"],
    ["--domain", "example.com\nANOTHER=value"],
    ["--email", "bad@example.com\nTOKEN=value"],
    ["--unexpected"],
])
def test_installer_rejects_invalid_arguments_before_system_changes(bash, args):
    result = subprocess.run([bash, "install.sh", *args, "--check"], capture_output=True, encoding="utf-8", timeout=10)
    assert result.returncode != 0
    assert "错误" in result.stderr
