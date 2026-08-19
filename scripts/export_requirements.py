"""Regenerate requirements.txt for Vercel with the local package line intact.

``uv export`` rewrites the whole file from the lock, so the trailing ``.`` that
tells pip to install this repository's own package is dropped every time it
runs. Vercel then deploys a function whose dependencies are all present but
whose ``dart_crawler`` import fails. Exporting through this script is what keeps
the two halves together: the generated dependency list, then the local package.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

_REPOSITORY_ROOT: Final = Path(__file__).resolve().parent.parent
_REQUIREMENTS_PATH: Final = _REPOSITORY_ROOT / "requirements.txt"
_LOCAL_PACKAGE_COMMENT: Final = (
    "# local package (do not remove; see scripts/export_requirements.py)"
)
_LOCAL_PACKAGE_LINE: Final = "."
_EXPORT_ARGUMENTS: Final = (
    "export",
    "--format",
    "requirements-txt",
    "--no-dev",
    "--no-emit-project",
    "--no-hashes",
    "-o",
    "requirements.txt",
)


def export_requirements() -> Path:
    """Run ``uv export`` and append the local package line, idempotently."""
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        message = "uv를 PATH에서 찾지 못했습니다."
        raise RuntimeError(message)
    command = (uv_executable, *_EXPORT_ARGUMENTS)
    print(f"$ {' '.join(command)}")
    # uv writes the export to the file and echoes it, so its stdout is dropped;
    # anything that goes wrong still arrives on stderr and through check=True.
    subprocess.run(  # noqa: S603
        command,
        cwd=_REPOSITORY_ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    lines = _REQUIREMENTS_PATH.read_text(encoding="utf-8").splitlines()
    # uv rewrote the file, so at most one pass of stripping is ever needed, but
    # stripping first is what makes a second run leave the file unchanged.
    while lines and lines[-1].strip() in {"", _LOCAL_PACKAGE_LINE}:
        lines.pop()
    while lines and lines[-1].strip() == _LOCAL_PACKAGE_COMMENT:
        lines.pop()
    lines.extend((_LOCAL_PACKAGE_COMMENT, _LOCAL_PACKAGE_LINE))
    _REQUIREMENTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return _REQUIREMENTS_PATH


def main() -> int:
    """Regenerate the file and print the tail that proves the line survived."""
    stream = sys.stdout
    if isinstance(stream, io.TextIOWrapper):
        stream.reconfigure(encoding="utf-8")
    path = export_requirements()
    tail = path.read_text(encoding="utf-8").splitlines()[-3:]
    print(f"{path.name} 재생성 완료 — 마지막 3줄:")
    for line in tail:
        print(f"  {line}")
    if tail[-1] != _LOCAL_PACKAGE_LINE:
        print(f"로컬 패키지 줄('{_LOCAL_PACKAGE_LINE}')이 없습니다.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
