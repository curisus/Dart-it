import importlib.metadata
import sys
import tomllib
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class _ProjectMetadata(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    dependencies: tuple[str, ...]


class _ProjectManifest(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    project: _ProjectMetadata


class _LockedPackage(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    name: str
    version: str | None = None


class _LockFile(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(extra="ignore", frozen=True)

    package: tuple[_LockedPackage, ...]


def test_required_excel_runtime_dependencies_are_exactly_pinned() -> None:
    # Given: the checked-in project dependency contract.
    raw_manifest = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    # When: the runtime dependency declarations and installed versions are read.
    manifest = _ProjectManifest.model_validate(raw_manifest)
    required_versions = {
        "mcp": "2.0.0",
        "openpyxl": "3.1.5",
        "pydantic": "2.13.4",
    }
    required = {
        f"{package}=={version}"
        for package, version in required_versions.items()
    }
    installed = {
        f"{package}=={importlib.metadata.version(package)}"
        for package in required_versions
    }
    lock_text = Path("uv.lock").read_text(encoding="utf-8")
    lock = _LockFile.model_validate(tomllib.loads(lock_text))
    locked = {
        package.name: package.version
        for package in lock.package
        if package.name in required_versions
    }
    requirements = set(
        Path("requirements.txt").read_text(encoding="utf-8").splitlines()
    )

    # Then: both the reproducible declaration and active environment are exact.
    assert required.issubset(set(manifest.project.dependencies))
    assert installed == required
    assert locked == required_versions
    assert required.issubset(requirements)
    for package, version in required_versions.items():
        assert (
            f'{{ name = "{package}", specifier = "=={version}" }}'
            in lock_text
        )


def test_validation_runtime_uses_python_313() -> None:
    # Given/When: the interpreter running the validation suite.
    version = sys.version_info

    # Then: the supported Python minor version is exact; the patch is evidence-recorded.
    assert (version.major, version.minor) == (3, 13)
