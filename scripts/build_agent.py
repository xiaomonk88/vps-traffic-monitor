"""Build a Linux agent archive with pure-Python dependencies, no target pip access."""
import hashlib
import importlib.util
import importlib.metadata
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "dist"
MODULES = ["httpx", "httpcore", "anyio", "idna", "certifi", "socksio", "h11", "typing_extensions"]
SOURCES = ["__init__.py", "agent.py", "core.py", "network.py"]


def build():
    OUT.mkdir(exist_ok=True)
    destination = OUT / "sentinel-agent.zip"
    versions = {}
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for source in SOURCES:
            archive.write(ROOT / "sentinel" / source, "sentinel/"+source)
        archive.writestr("run-agent.py", "import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))\nfrom sentinel.agent import main\nmain()\n")
        for name in MODULES:
            spec = importlib.util.find_spec(name)
            if spec is None or spec.origin is None:
                raise RuntimeError(f"missing dependency: {name}")
            path = Path(spec.origin)
            if path.name == "__init__.py":
                for item in path.parent.rglob("*"):
                    if item.is_file() and "__pycache__" not in item.parts and item.suffix != ".pyc":
                        archive.write(item, "vendor/"+name+"/"+item.relative_to(path.parent).as_posix())
            else:
                archive.write(path, "vendor/"+path.name)
            distribution = importlib.metadata.distribution(name.replace("_", "-"))
            versions[name] = distribution.version
            for file in distribution.files or []:
                if any(part.lower() in ("licenses", "license", "license.txt", "license.md", "copying") for part in file.parts):
                    actual = Path(distribution.locate_file(file))
                    if actual.is_file():
                        archive.write(actual, "licenses/"+name+"/"+actual.name)
        archive.writestr("DEPENDENCIES.json", json.dumps(versions, indent=2))
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    (OUT / "SHA256SUMS").write_text(f"{checksum}  sentinel-agent.zip\n", encoding="ascii")
    (OUT / "requirements-agent.txt").write_text("\n".join(f"{k.replace('_','-')}=={v}" for k,v in versions.items())+"\n", encoding="ascii")
    print(f"Agent package: {destination.name}, {destination.stat().st_size:,} bytes, SHA-256 verified at install")


if __name__ == "__main__":
    build()
