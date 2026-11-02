"""Validate the Linux artifact's Python imports without the machine site packages."""
import hashlib
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
bundle = root / "dist" / "sentinel-agent.zip"
expected = (bundle.parent / "SHA256SUMS").read_text().split()[0]
assert hashlib.sha256(bundle.read_bytes()).hexdigest() == expected
with tempfile.TemporaryDirectory(prefix="sentinel-bundle-") as directory:
    with zipfile.ZipFile(bundle) as archive:
        archive.extractall(directory)
    result = subprocess.run([sys.executable, "-S", str(Path(directory) / "run-agent.py"), "--help"],
                            cwd=directory, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    assert "enroll" in result.stdout and "diagnose" in result.stdout
print("Agent archive checksum and isolated imports passed (Linux runtime remains untested)")
