#!/usr/bin/env python3
"""Audit ~/.colab permissions (ts-proxy style)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path


def check_path(path: Path, expected_dir_mode: int | None, expected_file_mode: int | None) -> list[str]:
    issues: list[str] = []
    if not path.exists():
        return issues
    mode = path.stat().st_mode
    if path.is_dir() and expected_dir_mode is not None:
        if stat.S_IMODE(mode) != expected_dir_mode:
            issues.append(f"{path}: dir mode {oct(stat.S_IMODE(mode))} expected {oct(expected_dir_mode)}")
    if path.is_file() and expected_file_mode is not None:
        if stat.S_IMODE(mode) != expected_file_mode:
            issues.append(f"{path}: file mode {oct(stat.S_IMODE(mode))} expected {oct(expected_file_mode)}")
    return issues


def main() -> int:
    data = Path.home() / ".colab"
    issues: list[str] = []
    if data.exists():
        issues.extend(check_path(data, 0o700, None))
        for child in data.iterdir():
            if child.is_dir():
                issues.extend(check_path(child, 0o700, None))
            else:
                issues.extend(check_path(child, None, 0o600))
    if issues:
        for i in issues:
            print(f"⚠️  {i}", file=sys.stderr)
        return 1
    print(f"✅ {data} OK (or not created yet)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
