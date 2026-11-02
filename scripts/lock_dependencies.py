"""Record the installed runtime dependency closure, excluding test/browser tools."""
import importlib.metadata as metadata
import tomllib
from pathlib import Path
from packaging.requirements import Requirement
from packaging.markers import default_environment
from packaging.utils import canonicalize_name

root = Path(__file__).resolve().parent.parent
project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
pending = [Requirement(s) for s in project["project"]["dependencies"]]
visited, versions = set(), {}
while pending:
    requirement = pending.pop()
    name = canonicalize_name(requirement.name)
    extras = tuple(sorted(requirement.extras))
    if (name, extras) in visited:
        continue
    visited.add((name, extras))
    package = metadata.distribution(name)
    versions[name] = package.version
    for raw in package.requires or []:
        child = Requirement(raw)
        # Include runtime dependencies for both the local and container targets.
        environments = [dict(default_environment(), sys_platform=platform,
                             platform_system=system, python_version=version, extra=extra)
                        for platform, system in (("win32", "Windows"), ("linux", "Linux"))
                        for version in ("3.11", "3.13", "3.14")
                        for extra in ("", *extras)]
        if child.marker is None or any(child.marker.evaluate(env) for env in environments):
            pending.append(child)
(root / "requirements-lock.txt").write_text(
    "# Runtime versions validated on Windows; Linux image build is pending.\n" +
    "\n".join(f"{name}=={version}" for name, version in sorted(versions.items())) + "\n",
    encoding="utf-8")
print(f"Locked {len(versions)} runtime dependencies")
