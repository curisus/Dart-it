from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SafeOutputRoot:
    path: Path


@dataclass(frozen=True, slots=True)
class UnsafeOutputPath:
    pass


type OutputPathOutcome = SafeOutputRoot | UnsafeOutputPath


def prepare_safe_output_root(configured: Path) -> OutputPathOutcome:
    root = Path(os.path.abspath(configured))
    if _has_reparse_traversal(root):
        return UnsafeOutputPath()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return UnsafeOutputPath()
    if not root.is_dir() or _has_reparse_traversal(root):
        return UnsafeOutputPath()
    try:
        resolved = root.resolve(strict=True)
    except OSError:
        return UnsafeOutputPath()
    if os.path.normcase(str(resolved)) != os.path.normcase(str(root)):
        return UnsafeOutputPath()
    return SafeOutputRoot(resolved)


def is_safe_output_child(root: SafeOutputRoot, child: Path) -> bool:
    if Path(os.path.abspath(child.parent)) != root.path:
        return False
    try:
        if child.parent.resolve(strict=True) != root.path:
            return False
    except OSError:
        return False
    return not _is_reparse(child)


def path_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _has_reparse_traversal(path: Path) -> bool:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if _is_reparse(current):
            return True
    return False


def _is_reparse(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    try:
        status = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(status.st_mode) or path.is_junction():
        return True
    if sys.platform != "win32":
        return False
    return bool(status.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
