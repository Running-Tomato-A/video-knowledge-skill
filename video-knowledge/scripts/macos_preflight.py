#!/usr/bin/env python3
"""Collect a read-only macOS support report without installing anything."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", default=".", help="Workspace used for output-path checks.")
    return parser.parse_args()


def display_path(path: Path) -> str:
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        return "~/" + resolved.relative_to(home).as_posix()
    except ValueError:
        return str(resolved)


def command_version(command: str, arguments: list[str]) -> dict[str, Any]:
    resolved = shutil.which(command)
    if not resolved:
        return {"command": command, "status": "missing", "path": None, "version": None}
    try:
        completed = subprocess.run(
            [resolved, *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        version = (completed.stdout.strip() or completed.stderr.strip()).splitlines()[0]
        return {
            "command": command,
            "status": "pass" if completed.returncode == 0 else "warning",
            "path": display_path(Path(resolved)),
            "version": version,
            "exit_code": completed.returncode,
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "command": command,
            "status": "warning",
            "path": display_path(Path(resolved)),
            "version": None,
            "detail": str(exc),
        }


def free_gb(path: Path) -> float | None:
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    try:
        return round(shutil.disk_usage(current).free / (1024**3), 2)
    except OSError:
        return None


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser().resolve()
    system = platform.system()
    architecture = platform.machine()
    apple_silicon = system == "Darwin" and architecture.lower() in ("arm64", "aarch64")
    commands = [
        command_version("python3.12", ["--version"]),
        command_version("python3", ["--version"]),
        command_version("brew", ["--version"]),
        command_version("ffmpeg", ["-version"]),
        command_version("ffprobe", ["-version"]),
        command_version("git", ["--version"]),
    ]
    by_name = {item["command"]: item for item in commands}
    blockers: list[dict[str, Any]] = []

    if not apple_silicon:
        blockers.append(
            {
                "code": "platform_not_targeted",
                "detail": f"This evidence pass targets macOS arm64; detected {system} {architecture}.",
            }
        )
    if by_name["python3.12"]["status"] == "missing":
        blockers.append(
            {
                "code": "python312_missing",
                "detail": "No Python 3.12 interpreter was found on PATH.",
            }
        )
    if by_name["ffmpeg"]["status"] == "missing" or by_name["ffprobe"]["status"] == "missing":
        blockers.append(
            {
                "code": "ffmpeg_missing",
                "detail": "FFmpeg and FFprobe are required for the smoke test.",
            }
        )

    report = {
        "schema_version": 1,
        "tool": "video-knowledge-macos-preflight",
        "read_only": True,
        "support_status": "evidence_required" if apple_silicon else "blocked",
        "platform": {
            "system": system,
            "release": platform.release(),
            "machine": architecture,
            "python_running_probe": platform.python_version(),
        },
        "workspace": display_path(workspace),
        "workspace_free_gb": free_gb(workspace),
        "commands": commands,
        "blockers": blockers,
        "next_steps": [
            "Do not run setup.py --apply on macOS yet.",
            "Return this report before installing Homebrew, Rosetta, Python, or FFmpeg.",
            "After review, create an isolated Python 3.12 environment and resolve arm64 wheels.",
            "Generate a macOS arm64 lock only after a clean download and smoke test succeeds.",
        ],
        "privacy": "No serial number, hardware UUID, hostname, or account token is collected.",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if apple_silicon else 2


if __name__ == "__main__":
    raise SystemExit(main())
