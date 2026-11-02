"""Create a source/deployment bundle using an explicit allowlist; never include state."""
import hashlib
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
files = ["pyproject.toml", "requirements-lock.txt", "Dockerfile", "compose.yaml", "install.sh", ".gitattributes",
         ".dockerignore", ".env.example", ".gitignore", "启动本地测试.cmd",
         "README.md", "TESTING.md", "DEPLOY.md", "VPS流量监控系统设计方案.md"]
patterns = ["sentinel/*.py", "tests/*.py", "scripts/*.py", "scripts/*.sh", "scripts/*.ps1", ".github/workflows/*.yml",
            "deploy/*", "frontend/package*.json", "frontend/tsconfig*.json",
            "frontend/vite.config.ts", "frontend/index.html", "frontend/src/**/*"]
paths = {root / name for name in files}
for pattern in patterns:
    paths.update(p for p in root.glob(pattern) if p.is_file())
output = root / "dist" / "traffic-sentinel-0.1.0-source.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(paths):
        archive.write(path, "traffic-sentinel/" + path.relative_to(root).as_posix())
    for name in ("sentinel-agent.zip", "SHA256SUMS", "requirements-agent.txt"):
        archive.write(root / "dist" / name, "traffic-sentinel/dist/"+name)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
print(f"Release: {output.name} ({output.stat().st_size:,} bytes); excludes local data, secrets, caches and dependencies")
