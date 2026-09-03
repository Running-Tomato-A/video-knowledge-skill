#!/usr/bin/env python3
"""Read-only runtime readiness check for the video-knowledge skill."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from runtime_config import ENV_PREFIX, find_workspace, resolve_runtime_paths


def check(
    check_id: str,
    label: str,
    status: str,
    detail: str,
    *,
    required: bool,
    suggestion: str | None = None,
    path: Path | str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": check_id,
        "label": label,
        "status": status,
        "required": required,
        "detail": detail,
    }
    if suggestion:
        item["suggestion"] = suggestion
    if path is not None:
        item["path"] = str(path)
    return item


def nearest_existing_parent(path: Path) -> Path | None:
    candidate = path.expanduser()
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return None
        candidate = parent
    return candidate


def free_gb(path: Path) -> float | None:
    existing = nearest_existing_parent(path)
    if existing is None:
        return None
    try:
        return round(shutil.disk_usage(existing).free / (1024**3), 2)
    except OSError:
        return None


def directory_check(
    check_id: str,
    label: str,
    path: Path,
    *,
    required: bool,
    warn_below_gb: float,
) -> dict[str, Any]:
    existing = nearest_existing_parent(path)
    available = free_gb(path)
    available_text = "unknown"
    if available is not None:
        available_text = f"{available:.2f} GB free"

    if path.exists() and not path.is_dir():
        return check(
            check_id,
            label,
            "missing",
            "Configured path exists but is not a directory.",
            required=required,
            suggestion="Choose a directory path.",
            path=path,
        )

    writable = existing is not None and os.access(existing, os.W_OK)
    if not writable:
        return check(
            check_id,
            label,
            "missing",
            f"No writable existing parent was found; free space: {available_text}.",
            required=required,
            suggestion="Choose a writable storage location.",
            path=path,
        )

    if available is not None and available < warn_below_gb:
        return check(
            check_id,
            label,
            "warning",
            f"Path is writable but storage is low: {available_text}.",
            required=required,
            suggestion="Choose a drive with more free space before processing long videos.",
            path=path,
        )

    if path.exists():
        return check(
            check_id,
            label,
            "pass",
            f"Directory is available and writable; {available_text}.",
            required=required,
            path=path,
        )

    return check(
        check_id,
        label,
        "warning",
        f"Directory does not exist yet, but its parent is writable; {available_text}.",
        required=required,
        suggestion="Let the installer create this directory before first use.",
        path=path,
    )


def command_version(executable: str) -> str | None:
    try:
        completed = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    first_line = (completed.stdout or completed.stderr).splitlines()
    return first_line[0].strip() if first_line else None


def command_check(name: str) -> dict[str, Any]:
    configured_name = f"{name.upper()}_PATH"
    configured = os.environ.get(configured_name)
    executable = None
    if configured:
        candidate = Path(configured).expanduser().resolve()
        executable = str(candidate) if candidate.is_file() else None
    if not executable:
        executable = shutil.which(name)
    if not executable:
        return check(
            name,
            name,
            "missing",
            f"{name} was not found on PATH.",
            required=True,
            suggestion=(
                f"Install {name} and make it available on PATH, or set {configured_name}."
            ),
        )
    version = command_version(executable)
    detail = version or "Executable found."
    return check(name, name, "pass", detail, required=True, path=executable)


def runtime_venv_python(data_root: Path) -> Path:
    if os.name == "nt":
        return data_root / "runtime" / "venv" / "Scripts" / "python.exe"
    return data_root / "runtime" / "venv" / "bin" / "python"


def faster_whisper_check(
    workspace: Path, data_root: Path
) -> tuple[dict[str, Any], Path | None]:
    runtime_python = runtime_venv_python(data_root)
    if runtime_python.is_file():
        try:
            completed = subprocess.run(
                [str(runtime_python), "-c", "import faster_whisper; print('ok')"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return (
                check(
                    "faster_whisper",
                    "Faster-Whisper",
                    "missing",
                    f"Configured runtime venv could not be checked: {exc}",
                    required=True,
                    suggestion="Repair the runtime-dependencies stage.",
                    path=runtime_python,
                ),
                None,
            )
        if completed.returncode == 0:
            return (
                check(
                    "faster_whisper",
                    "Faster-Whisper",
                    "pass",
                    "Importable from the configured runtime virtual environment.",
                    required=True,
                    path=runtime_python,
                ),
                runtime_python,
            )
        return (
            check(
                "faster_whisper",
                "Faster-Whisper",
                "missing",
                "The configured runtime virtual environment exists but cannot import faster-whisper.",
                required=True,
                suggestion="Rerun the runtime-dependencies stage to repair only the project venv.",
                path=runtime_python,
            ),
            None,
        )

    spec = importlib.util.find_spec("faster_whisper")
    if spec is not None:
        origin = spec.origin or "current Python environment"
        return (
            check(
                "faster_whisper",
                "Faster-Whisper",
                "pass",
                "Importable from the current Python environment.",
                required=True,
                path=origin,
            ),
            Path(origin).parent if spec.origin else None,
        )

    configured = os.environ.get(f"{ENV_PREFIX}PYTHONPATH")
    package_root = (
        Path(configured).expanduser().resolve()
        if configured
        else (workspace / ".codex-tools" / "faster-whisper").resolve()
    )
    if package_root.is_dir():
        return (
            check(
                "faster_whisper",
                "Faster-Whisper",
                "pass",
                "Standalone package directory found; the runtime must add it to PYTHONPATH.",
                required=True,
                path=package_root,
            ),
            package_root,
        )

    return (
        check(
            "faster_whisper",
            "Faster-Whisper",
            "missing",
            "No importable package or configured standalone package directory was found.",
            required=True,
            suggestion=(
                "Install faster-whisper or set VIDEO_KNOWLEDGE_PYTHONPATH to a reusable package directory."
            ),
        ),
        None,
    )


def model_check(model_root: Path, *, quick: bool) -> dict[str, Any]:
    if not model_root.is_dir():
        return check(
            "whisper_model",
            "Whisper model",
            "missing",
            "Configured model directory does not exist.",
            required=True,
            suggestion=(
                "Download a supported Whisper model during setup, or set VIDEO_KNOWLEDGE_MODEL_DIR."
            ),
            path=model_root,
        )

    if quick:
        return check(
            "whisper_model",
            "Whisper model",
            "pass",
            "Configured model directory exists; deep file validation was skipped in quick mode.",
            required=True,
            path=model_root,
        )

    try:
        model_files = list(model_root.rglob("model.bin"))
    except OSError as exc:
        return check(
            "whisper_model",
            "Whisper model",
            "warning",
            f"Model directory exists but could not be inspected: {exc}",
            required=True,
            suggestion="Re-run Doctor outside a restricted sandbox or check directory permissions.",
            path=model_root,
        )

    if not model_files:
        return check(
            "whisper_model",
            "Whisper model",
            "missing",
            "No model.bin was found below the configured model directory.",
            required=True,
            suggestion="Complete the model download or choose the correct model directory.",
            path=model_root,
        )

    largest = max(model_files, key=lambda item: item.stat().st_size)
    size_mb = largest.stat().st_size / (1024**2)
    return check(
        "whisper_model",
        "Whisper model",
        "pass",
        f"Model weights found ({size_mb:.1f} MB).",
        required=True,
        path=largest.parent,
    )


def optional_adapters(workspace: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    collector = workspace / "tools" / "douyin-collector"
    if (collector / "app.py").is_file():
        items.append(
            check(
                "platform_collector",
                "Douyin/Xiaohongshu collector",
                "pass",
                "Local optional platform adapter found.",
                required=False,
                path=collector,
            )
        )
    else:
        items.append(
            check(
                "platform_collector",
                "Douyin/Xiaohongshu collector",
                "warning",
                "Optional local platform adapter was not found.",
                required=False,
                suggestion="Local video files remain supported without this adapter.",
            )
        )

    yt_dlp = shutil.which("yt-dlp")
    if yt_dlp or importlib.util.find_spec("yt_dlp") is not None:
        items.append(
            check(
                "yt_dlp",
                "yt-dlp",
                "pass",
                "Optional generic public-video adapter found.",
                required=False,
                path=yt_dlp or "Python module",
            )
        )
    else:
        items.append(
            check(
                "yt_dlp",
                "yt-dlp",
                "warning",
                "Optional generic public-video adapter was not found.",
                required=False,
                suggestion="Local video files remain supported without yt-dlp.",
            )
        )
    return items


def storage_summary() -> list[dict[str, Any]]:
    roots: list[Path] = []
    if os.name == "nt":
        for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root = Path(f"{letter}:\\")
            if root.exists():
                roots.append(root)
    else:
        roots.append(Path("/"))

    rows: list[dict[str, Any]] = []
    for root in roots:
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue
        rows.append(
            {
                "path": str(root),
                "free_gb": round(usage.free / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 2),
            }
        )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only runtime readiness check for video-knowledge."
    )
    parser.add_argument("--quick", action="store_true", help="Run the lightweight preflight set.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--workspace", help="Workspace root used for automatic discovery.")
    parser.add_argument("--config", help="Runtime config JSON; defaults to the user config path.")
    parser.add_argument("--data-root", help="Shared root for models, downloads, and cache.")
    parser.add_argument("--download-dir", help="Media download directory.")
    parser.add_argument("--cache-dir", help="Temporary analysis cache directory.")
    parser.add_argument("--output-dir", help="Formal Markdown output directory.")
    parser.add_argument("--model-dir", help="Whisper model root directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = find_workspace(args.workspace)
    config_arg = Path(args.config).expanduser().resolve() if args.config else None
    try:
        runtime_paths, resolved_config_path = resolve_runtime_paths(
            workspace,
            config_path=config_arg,
            overrides={
                "data_root": args.data_root,
                "download_dir": args.download_dir,
                "cache_dir": args.cache_dir,
                "output_dir": args.output_dir,
                "model_dir": args.model_dir,
            },
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    download_dir = runtime_paths["download_dir"]["path"]
    cache_dir = runtime_paths["cache_dir"]["path"]
    output_dir = runtime_paths["output_dir"]["path"]
    model_dir = runtime_paths["model_dir"]["path"]

    checks: list[dict[str, Any]] = [
        check(
            "python",
            "Python",
            "pass",
            f"{platform.python_implementation()} {platform.python_version()}",
            required=True,
            path=sys.executable,
        ),
        command_check("ffmpeg"),
        command_check("ffprobe"),
    ]
    transcription_check, _ = faster_whisper_check(
        workspace, runtime_paths["data_root"]["path"]
    )
    checks.append(transcription_check)
    checks.append(model_check(model_dir, quick=args.quick))
    checks.extend(
        [
            directory_check(
                "cache_dir",
                "Analysis cache",
                cache_dir,
                required=True,
                warn_below_gb=5.0,
            ),
            directory_check(
                "output_dir",
                "Formal output",
                output_dir,
                required=True,
                warn_below_gb=1.0,
            ),
        ]
    )
    if not args.quick:
        checks.append(
            directory_check(
                "download_dir",
                "Media downloads",
                download_dir,
                required=False,
                warn_below_gb=10.0,
            )
        )
        checks.extend(optional_adapters(workspace))

    blocking = [item for item in checks if item["required"] and item["status"] == "missing"]
    warnings = [item for item in checks if item["status"] == "warning"]
    overall = "blocked" if blocking else ("ready_with_warnings" if warnings else "ready")

    report = {
        "schema_version": 1,
        "tool": "video-knowledge-doctor",
        "mode": "quick" if args.quick else "full",
        "read_only": True,
        "overall": overall,
        "workspace": str(workspace),
        "config_path": str(resolved_config_path),
        "config_exists": resolved_config_path.is_file(),
        "paths": {
            key: {"path": str(value["path"]), "source": value["source"]}
            for key, value in runtime_paths.items()
        },
        "checks": checks,
        "storage": [] if args.quick else storage_summary(),
        "summary": {
            "pass": sum(item["status"] == "pass" for item in checks),
            "warning": len(warnings),
            "missing_required": len(blocking),
        },
    }

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("Video Knowledge Doctor v0.1 (read-only)")
        print(f"Mode: {report['mode']} | Overall: {overall}")
        print(f"Workspace: {workspace}")
        for item in checks:
            marker = {
                "pass": "PASS",
                "warning": "WARN",
                "missing": "MISS",
            }[item["status"]]
            optional = "" if item["required"] else " (optional)"
            print(f"[{marker}] {item['label']}{optional}: {item['detail']}")
            if item.get("path"):
                print(f"       Path: {item['path']}")
            if item.get("suggestion"):
                print(f"       Next: {item['suggestion']}")
        if report["storage"]:
            print("Storage:")
            for row in report["storage"]:
                print(f"  {row['path']} {row['free_gb']:.2f} GB free / {row['total_gb']:.2f} GB total")
        print(
            "Summary: "
            f"{report['summary']['pass']} pass, "
            f"{report['summary']['warning']} warning, "
            f"{report['summary']['missing_required']} required missing."
        )

    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
