#!/usr/bin/env python3
"""Read-only installation planner for the video-knowledge runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

from runtime_config import (  # noqa: E402
    default_config_path,
    find_workspace,
    resolve_runtime_paths,
)


MODEL_ESTIMATE_MB = 500
PYTHON_ENV_ESTIMATE_MB = 300
FFMPEG_ESTIMATE_MB = 150


def redact_sensitive_text(value: str) -> str:
    text = re.sub(
        r"(?i)\b(https?://)([^/\s:@]+):([^@\s/]+)@",
        r"\1***:***@",
        value,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", "Bearer ***", text)
    text = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
        r"(\s*[:=]\s*)['\"]?([^\s,'\"]{8,})",
        r"\1\2***",
        text,
    )
    text = re.sub(
        r"\b(sk-[A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        "***",
        text,
    )
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a read-only installation plan for video-knowledge."
    )
    parser.add_argument("--plan", action="store_true", help="Generate the read-only plan.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the complete installation after confirmation.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the previously reviewed paths and changes.",
    )
    parser.add_argument(
        "--stage",
        choices=("all", "runtime-dependencies", "model", "ffmpeg", "skill", "verify"),
        default="all",
        help="Developer/recovery override; ordinary installation uses all.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--workspace", help="Workspace root for formal output.")
    parser.add_argument("--config", help="Runtime config path.")
    parser.add_argument("--data-root", help="Shared root for models, downloads, and cache.")
    parser.add_argument("--download-dir", help="Media download directory.")
    parser.add_argument("--cache-dir", help="Temporary analysis cache directory.")
    parser.add_argument("--output-dir", help="Formal Markdown output directory.")
    parser.add_argument("--model-dir", help="Whisper model root directory.")
    parser.add_argument(
        "--lock",
        default=str(Path(__file__).resolve().parent.parent / "requirements-windows-py312.lock"),
        help="Locked dependency file used by --apply.",
    )
    parser.add_argument(
        "--model-manifest",
        default=str(Path(__file__).resolve().parent.parent / "references" / "model-manifest.json"),
        help="Pinned model manifest used by the model stage.",
    )
    parser.add_argument("--skill-source", help="Source Skill directory; defaults to this package.")
    parser.add_argument("--skill-target", help="User Skill installation directory.")
    parser.add_argument(
        "--skill-backup-root",
        help="Non-discoverable directory for versioned Skill backups.",
    )
    parser.add_argument(
        "--simulate-empty",
        action="store_true",
        help="Developer test: plan against a synthetic blank machine without changing it.",
    )
    return parser.parse_args()


class ApplyFailure(RuntimeError):
    def __init__(
        self,
        *,
        error_code: str,
        component: str,
        operation: str,
        detail: str,
        exit_code: int | None = None,
        supported_fixes: list[str] | None = None,
        paths_changed: list[str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.payload = {
            "status": "failed",
            "error_code": error_code,
            "component": component,
            "platform": platform.system(),
            "architecture": platform.machine(),
            "operation": operation,
            "exit_code": exit_code,
            "stderr_tail": redact_sensitive_text(detail)[-4000:],
            "attempt": 1,
            "supported_fixes": supported_fixes or [],
            "paths_changed": paths_changed or [],
        }


def doctor_command(args: argparse.Namespace, workspace: Path) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "doctor.py"),
        "--json",
        "--workspace",
        str(workspace),
    ]
    for option, value in (
        ("--config", args.config),
        ("--data-root", args.data_root),
        ("--download-dir", args.download_dir),
        ("--cache-dir", args.cache_dir),
        ("--output-dir", args.output_dir),
        ("--model-dir", args.model_dir),
    ):
        if value:
            command.extend([option, value])
    return command


def run_doctor(args: argparse.Namespace, workspace: Path) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        doctor_command(args, workspace),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=environment,
    )
    if completed.returncode not in (0, 1):
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"Doctor could not create a report: {detail}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Doctor returned invalid JSON") from exc


def synthetic_empty_report(
    workspace: Path,
    paths: dict[str, dict[str, Any]],
    config_path: Path,
) -> dict[str, Any]:
    checks = [
        {
            "id": "python",
            "label": "Python",
            "status": "pass",
            "required": True,
            "detail": f"{platform.python_implementation()} {platform.python_version()}",
            "path": sys.executable,
        },
        {
            "id": "ffmpeg",
            "label": "ffmpeg",
            "status": "missing",
            "required": True,
            "detail": "Synthetic blank environment: ffmpeg is absent.",
        },
        {
            "id": "ffprobe",
            "label": "ffprobe",
            "status": "missing",
            "required": True,
            "detail": "Synthetic blank environment: ffprobe is absent.",
        },
        {
            "id": "faster_whisper",
            "label": "Faster-Whisper",
            "status": "missing",
            "required": True,
            "detail": "Synthetic blank environment: transcription backend is absent.",
        },
        {
            "id": "whisper_model",
            "label": "Whisper model",
            "status": "missing",
            "required": True,
            "detail": "Synthetic blank environment: model is absent.",
            "path": str(paths["model_dir"]["path"]),
        },
        {
            "id": "cache_dir",
            "label": "Analysis cache",
            "status": "warning",
            "required": True,
            "detail": "Synthetic blank environment: directory will need to be created.",
            "path": str(paths["cache_dir"]["path"]),
        },
        {
            "id": "output_dir",
            "label": "Formal output",
            "status": "warning",
            "required": True,
            "detail": "Synthetic blank environment: directory will need to be created.",
            "path": str(paths["output_dir"]["path"]),
        },
        {
            "id": "platform_collector",
            "label": "Douyin/Xiaohongshu collector",
            "status": "warning",
            "required": False,
            "detail": "Optional platform adapter is absent.",
        },
        {
            "id": "yt_dlp",
            "label": "yt-dlp",
            "status": "warning",
            "required": False,
            "detail": "Optional generic public-video adapter is absent.",
        },
    ]
    storage: list[dict[str, Any]] = []
    seen: set[str] = set()
    for key in ("data_root", "output_dir"):
        path = Path(paths[key]["path"])
        anchor = path.anchor or str(path)
        if anchor in seen:
            continue
        seen.add(anchor)
        try:
            usage = shutil.disk_usage(anchor)
        except OSError:
            continue
        storage.append(
            {
                "path": anchor,
                "free_gb": round(usage.free / (1024**3), 2),
                "total_gb": round(usage.total / (1024**3), 2),
            }
        )
    return {
        "schema_version": 1,
        "tool": "video-knowledge-doctor",
        "mode": "synthetic-empty",
        "read_only": True,
        "overall": "blocked",
        "workspace": str(workspace),
        "config_path": str(config_path),
        "config_exists": False,
        "paths": {
            key: {"path": str(value["path"]), "source": value["source"]}
            for key, value in paths.items()
        },
        "checks": checks,
        "storage": storage,
        "summary": {"pass": 1, "warning": 4, "missing_required": 4},
    }


def check_by_id(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in report.get("checks", [])}


def skill_candidates() -> list[Path]:
    return [
        Path.home() / ".codex" / "skills" / "video-knowledge" / "SKILL.md",
        Path.home() / ".agents" / "skills" / "video-knowledge" / "SKILL.md",
    ]


def action(
    kind: str,
    description: str,
    *,
    estimated_mb: int = 0,
    network: bool = False,
    admin: bool = False,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "description": description,
        "estimated_mb": estimated_mb,
        "requires_network": network,
        "requires_admin": admin,
    }


def build_actions(
    report: dict[str, Any],
    *,
    simulated: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    checks = check_by_id(report)
    actions: list[dict[str, Any]] = []
    reuse: list[str] = []

    if checks.get("python", {}).get("status") == "pass":
        reuse.append("Python")

    ffmpeg_missing = any(
        checks.get(name, {}).get("status") == "missing" for name in ("ffmpeg", "ffprobe")
    )
    if ffmpeg_missing:
        actions.append(
            action(
                "install_ffmpeg",
                "安装 FFmpeg 与 FFprobe",
                estimated_mb=FFMPEG_ESTIMATE_MB,
                network=True,
                admin=True,
            )
        )
    else:
        reuse.append("FFmpeg／FFprobe")

    if checks.get("faster_whisper", {}).get("status") == "missing":
        actions.append(
            action(
                "install_transcription_backend",
                "创建独立 Python 环境并安装 Faster-Whisper 依赖",
                estimated_mb=PYTHON_ENV_ESTIMATE_MB,
                network=True,
            )
        )
    else:
        reuse.append("Faster-Whisper")

    if checks.get("whisper_model", {}).get("status") == "missing":
        actions.append(
            action(
                "download_model",
                "下载 Whisper Small 模型",
                estimated_mb=MODEL_ESTIMATE_MB,
                network=True,
            )
        )
    else:
        reuse.append("Whisper 模型")

    if simulated or not report.get("config_exists"):
        actions.append(action("write_config", "写入用户运行配置"))
    else:
        reuse.append("现有运行配置")

    path_map = report.get("paths", {})
    for key, label in (
        ("model_dir", "模型目录"),
        ("download_dir", "下载目录"),
        ("cache_dir", "缓存目录"),
        ("output_dir", "正式输出目录"),
    ):
        raw_path = path_map.get(key, {}).get("path")
        if not raw_path:
            continue
        if simulated or not Path(raw_path).is_dir():
            actions.append(action("create_directory", f"创建{label}：{raw_path}"))

    installed = False if simulated else any(path.is_file() for path in skill_candidates())
    if installed:
        reuse.append("已安装的 Video Knowledge Skill")
    else:
        actions.append(action("install_skill", "安装 Video Knowledge Skill"))

    return actions, reuse


def optional_warnings(report: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for item in report.get("checks", []):
        if item.get("required") or item.get("status") != "warning":
            continue
        if item.get("id") == "yt_dlp":
            warnings.append("未安装 yt-dlp；不影响本地视频分析。")
        elif item.get("id") == "platform_collector":
            warnings.append("未安装抖音／小红书适配器；不影响本地视频分析。")
        else:
            warnings.append(str(item.get("detail", "存在可选警告。")))
    return warnings


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    workspace = find_workspace(args.workspace)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else default_config_path()
    )
    overrides = {
        "data_root": args.data_root,
        "download_dir": args.download_dir,
        "cache_dir": args.cache_dir,
        "output_dir": args.output_dir,
        "model_dir": args.model_dir,
    }

    if args.simulate_empty:
        synthetic_config = workspace / ".video-knowledge-synthetic-missing.json"
        paths, _ = resolve_runtime_paths(
            workspace,
            config_path=synthetic_config,
            overrides=overrides,
        )
        report = synthetic_empty_report(workspace, paths, synthetic_config)
    else:
        report = run_doctor(args, workspace)

    actions, reuse = build_actions(report, simulated=args.simulate_empty)
    warnings = optional_warnings(report)
    estimated_mb = sum(item["estimated_mb"] for item in actions)
    network_required = any(item["requires_network"] for item in actions)
    admin_required = any(item["requires_admin"] for item in actions)

    data_root = Path(report["paths"]["data_root"]["path"])
    try:
        data_free_gb = round(shutil.disk_usage(data_root.anchor or data_root).free / (1024**3), 2)
    except OSError:
        data_free_gb = None

    status = "already_ready" if not actions else "confirmation_required"
    if sys.version_info < (3, 10):
        status = "blocked"
        actions.insert(0, action("unsupported_python", "需要 Python 3.10 或更高版本"))

    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "plan",
        "read_only": True,
        "simulated": args.simulate_empty,
        "status": status,
        "confirmation_required": status == "confirmation_required",
        "doctor_overall": report.get("overall"),
        "workspace": str(workspace),
        "config_path": report.get("config_path", str(config_path)),
        "reuse": reuse,
        "actions": actions,
        "paths": report.get("paths", {}),
        "estimate": {
            "new_disk_mb": estimated_mb,
            "data_drive_free_gb": data_free_gb,
            "requires_network": network_required,
            "requires_admin": admin_required,
            "note": "体积为安装计划估算，实际依赖版本可能略有变化。",
        },
        "optional_warnings": warnings,
    }


def safe_install_path(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if str(resolved) == resolved.anchor or resolved == Path.home().resolve():
        raise ApplyFailure(
            error_code="unsafe_install_path",
            component="storage",
            operation=f"validate {label}",
            detail=f"Refusing to use a broad path for {label}: {resolved}",
            supported_fixes=["Choose a dedicated subdirectory for Video Knowledge."],
        )
    return resolved


def read_lock(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise ApplyFailure(
            error_code="dependency_lock_missing",
            component="python_dependencies",
            operation="read dependency lock",
            detail=f"Dependency lock not found: {path}",
            supported_fixes=["Restore requirements-windows-py312.lock from the project."],
        )
    packages: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("--hash="):
            continue
        requirement = line.split(" --hash=", 1)[0]
        if "==" not in requirement:
            raise ApplyFailure(
                error_code="dependency_lock_invalid",
                component="python_dependencies",
                operation="parse dependency lock",
                detail=f"Unsupported lock entry: {line}",
                supported_fixes=["Regenerate the lock from a verified clean environment."],
            )
        if "--hash=sha256:" not in line:
            raise ApplyFailure(
                error_code="dependency_lock_unhashed",
                component="python_dependencies",
                operation="parse dependency lock",
                detail=f"Dependency entry has no SHA-256 hash: {requirement}",
                supported_fixes=["Regenerate the Windows lock from exact verified wheels."],
            )
        name, version = requirement.split("==", 1)
        packages[name.strip()] = version.strip()
    if not packages:
        raise ApplyFailure(
            error_code="dependency_lock_empty",
            component="python_dependencies",
            operation="parse dependency lock",
            detail="Dependency lock has no packages.",
        )
    return packages


def venv_python(venv_root: Path) -> Path:
    if os.name == "nt":
        return venv_root / "Scripts" / "python.exe"
    return venv_root / "bin" / "python"


def installed_versions(python: Path, packages: dict[str, str]) -> dict[str, str | None]:
    names_json = json.dumps(list(packages), ensure_ascii=True)
    code = (
        "import importlib.metadata as m,json;"
        f"names={names_json};"
        "out={};"
        "\nfor n in names:\n"
        "  try: out[n]=m.version(n)\n"
        "  except m.PackageNotFoundError: out[n]=None\n"
        "print(json.dumps(out))"
    )
    completed = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise ApplyFailure(
            error_code="venv_inspection_failed",
            component="python_environment",
            operation="inspect installed package versions",
            detail=completed.stderr.strip() or completed.stdout.strip(),
            exit_code=completed.returncode,
            supported_fixes=["Repair or recreate only the project virtual environment."],
        )
    return json.loads(completed.stdout)


def lock_matches(python: Path, packages: dict[str, str]) -> tuple[bool, dict[str, Any]]:
    versions = installed_versions(python, packages)
    mismatches = {
        name: {"expected": expected, "actual": versions.get(name)}
        for name, expected in packages.items()
        if versions.get(name) != expected
    }
    return not mismatches, mismatches


def run_checked(
    command: list[str],
    *,
    component: str,
    operation: str,
    paths_changed: list[str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ApplyFailure(
            error_code=f"{component}_failed",
            component=component,
            operation=operation,
            detail=detail,
            exit_code=completed.returncode,
            supported_fixes=[
                "Inspect the exact package or Python error using official documentation.",
                "Reuse the partial virtual environment only if its package state can be verified.",
            ],
            paths_changed=paths_changed,
        )
    return completed


def atomic_write_json(path: Path, payload: dict[str, Any]) -> tuple[str, str | None]:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return "reused", None

    backup: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.with_name(f"{path.name}.backup-{stamp}")
        shutil.copy2(path, backup)

    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return "written", str(backup) if backup else None


def stage_receipt_payload(
    *,
    paths: dict[str, dict[str, Any]],
    python: Path,
    lock_path: Path,
    lock_hash: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "runtime_dependencies_ready",
        "stage": "runtime_dependencies",
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": str(python),
        "python_version": platform.python_version(),
        "lock_file": str(lock_path),
        "lock_sha256": lock_hash,
        "paths": {key: str(value["path"]) for key, value in paths.items()},
        "next_required": [
            "verify or install FFmpeg/FFprobe",
            "download and verify the pinned Whisper model",
            "install or confirm the Skill",
            "run full Doctor and save the final installation receipt",
        ],
    }


def apply_runtime_dependencies(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply runtime-dependencies stage",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, review the paths, then rerun --apply --yes."],
        )
    if args.simulate_empty:
        raise ApplyFailure(
            error_code="invalid_apply_mode",
            component="setup",
            operation="apply runtime-dependencies stage",
            detail="--simulate-empty is only valid with --plan.",
        )
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ApplyFailure(
            error_code="platform_not_verified",
            component="python_environment",
            operation="select dependency lock",
            detail=f"No verified lock for {platform.system()} {platform.machine()}.",
            supported_fixes=[
                "Use the platform remediation protocol and create a clean-environment lock before Apply."
            ],
        )
    if sys.version_info[:2] != (3, 12):
        raise ApplyFailure(
            error_code="python_version_not_verified",
            component="python_environment",
            operation="create virtual environment",
            detail=f"Windows v0.1 Apply requires verified Python 3.12; current is {platform.python_version()}.",
            supported_fixes=["Install or select Python 3.12 x64, then rerun Apply."],
        )

    workspace = find_workspace(args.workspace)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else default_config_path()
    )
    paths, _ = resolve_runtime_paths(
        workspace,
        config_path=config_path,
        overrides={
            "data_root": args.data_root,
            "download_dir": args.download_dir,
            "cache_dir": args.cache_dir,
            "output_dir": args.output_dir,
            "model_dir": args.model_dir,
        },
    )
    for key in paths:
        paths[key]["path"] = safe_install_path(Path(paths[key]["path"]), key)

    data_root = Path(paths["data_root"]["path"])
    runtime_root = safe_install_path(data_root / "runtime", "runtime_root")
    venv_root = safe_install_path(runtime_root / "venv", "venv_root")
    lock_path = Path(args.lock).expanduser().resolve()
    packages = read_lock(lock_path)
    lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest().upper()
    changed_paths: list[str] = []
    action_results: list[dict[str, Any]] = []

    directory_paths = [
        data_root,
        Path(paths["model_dir"]["path"]),
        Path(paths["download_dir"]["path"]),
        Path(paths["cache_dir"]["path"]),
        Path(paths["output_dir"]["path"]),
        runtime_root,
    ]
    for path in directory_paths:
        if path.is_dir():
            action_results.append({"kind": "directory", "path": str(path), "result": "reused"})
        elif path.exists():
            raise ApplyFailure(
                error_code="path_not_directory",
                component="storage",
                operation="create runtime directories",
                detail=f"Path exists but is not a directory: {path}",
                supported_fixes=["Choose a dedicated directory path."],
                paths_changed=changed_paths,
            )
        else:
            path.mkdir(parents=True, exist_ok=False)
            changed_paths.append(str(path))
            action_results.append({"kind": "directory", "path": str(path), "result": "created"})

    python = venv_python(venv_root)
    if python.is_file():
        action_results.append({"kind": "venv", "path": str(venv_root), "result": "reused"})
    else:
        print("[setup] Creating Python 3.12 virtual environment...", file=sys.stderr)
        run_checked(
            [sys.executable, "-m", "venv", str(venv_root)],
            component="python_environment",
            operation="create virtual environment",
            paths_changed=changed_paths + [str(venv_root)],
            timeout=300,
        )
        changed_paths.append(str(venv_root))
        action_results.append({"kind": "venv", "path": str(venv_root), "result": "created"})

    matching, mismatches = lock_matches(python, packages)
    if matching:
        action_results.append(
            {
                "kind": "python_dependencies",
                "path": str(lock_path),
                "result": "reused",
                "packages": len(packages),
            }
        )
    else:
        print("[setup] Installing locked Python dependencies...", file=sys.stderr)
        run_checked(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--require-hashes",
                "-r",
                str(lock_path),
            ],
            component="python_dependencies",
            operation="install locked dependencies",
            paths_changed=changed_paths,
            timeout=1800,
        )
        matching, remaining = lock_matches(python, packages)
        if not matching:
            raise ApplyFailure(
                error_code="dependency_verification_failed",
                component="python_dependencies",
                operation="verify locked dependencies",
                detail=json.dumps(remaining, ensure_ascii=False),
                supported_fixes=["Inspect the incompatible wheel or package using official package metadata."],
                paths_changed=changed_paths,
            )
        action_results.append(
            {
                "kind": "python_dependencies",
                "path": str(lock_path),
                "result": "installed",
                "packages": len(packages),
                "previous_mismatches": mismatches,
            }
        )

    config_payload = {
        "schema_version": 1,
        "data_root": str(data_root),
        "model_dir": str(paths["model_dir"]["path"]),
        "download_dir": str(paths["download_dir"]["path"]),
        "cache_dir": str(paths["cache_dir"]["path"]),
        "output_dir": str(paths["output_dir"]["path"]),
    }
    config_result, config_backup = atomic_write_json(config_path, config_payload)
    if config_result == "written":
        changed_paths.append(str(config_path))
    action_results.append(
        {
            "kind": "config",
            "path": str(config_path),
            "result": config_result,
            "backup": config_backup,
        }
    )

    receipt_path = runtime_root / "runtime-dependencies-receipt.json"
    receipt = stage_receipt_payload(
        paths=paths,
        python=python,
        lock_path=lock_path,
        lock_hash=lock_hash,
    )
    receipt_result, _ = atomic_write_json(receipt_path, receipt)
    if receipt_result == "written":
        changed_paths.append(str(receipt_path))

    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "apply",
        "status": "stage_complete",
        "stage": "runtime_dependencies",
        "complete_installation": False,
        "config_path": str(config_path),
        "runtime_root": str(runtime_root),
        "venv_python": str(python),
        "lock_file": str(lock_path),
        "lock_sha256": lock_hash,
        "actions": action_results,
        "receipt": str(receipt_path),
        "receipt_result": receipt_result,
        "next_required": receipt["next_required"],
    }


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_model_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ApplyFailure(
            error_code="model_manifest_missing",
            component="model",
            operation="read model manifest",
            detail=f"Model manifest not found: {path}",
            supported_fixes=["Restore references/model-manifest.json from the project."],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyFailure(
            error_code="model_manifest_invalid",
            component="model",
            operation="parse model manifest",
            detail=str(exc),
            supported_fixes=["Restore the verified model manifest."],
        ) from exc
    model = payload.get("default_model")
    if payload.get("schema_version") != 1 or not isinstance(model, dict):
        raise ApplyFailure(
            error_code="model_manifest_invalid",
            component="model",
            operation="parse model manifest",
            detail="Unsupported model manifest schema.",
        )
    return model


def inspect_model_snapshot(snapshot: Path, model: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    mismatched: list[dict[str, Any]] = []
    verified: list[dict[str, Any]] = []
    for expected in model["files"]:
        path = snapshot / expected["name"]
        if not path.is_file():
            missing.append(expected["name"])
            continue
        actual_size = path.stat().st_size
        if actual_size != expected["bytes"]:
            mismatched.append(
                {
                    "name": expected["name"],
                    "reason": "size",
                    "expected": expected["bytes"],
                    "actual": actual_size,
                }
            )
            continue
        actual_hash = hash_file(path)
        if actual_hash != expected["sha256"].upper():
            mismatched.append(
                {
                    "name": expected["name"],
                    "reason": "sha256",
                    "expected": expected["sha256"].upper(),
                    "actual": actual_hash,
                }
            )
            continue
        verified.append(
            {
                "name": expected["name"],
                "bytes": actual_size,
                "sha256": actual_hash,
            }
        )
    return {"missing": missing, "mismatched": mismatched, "verified": verified}


def apply_model(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply model stage",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, review the paths, then rerun --apply --yes --stage model."],
        )
    if args.simulate_empty:
        raise ApplyFailure(
            error_code="invalid_apply_mode",
            component="setup",
            operation="apply model stage",
            detail="--simulate-empty is only valid with --plan.",
        )
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ApplyFailure(
            error_code="platform_not_verified",
            component="model",
            operation="download pinned model",
            detail=f"Model Apply is not verified for {platform.system()} {platform.machine()}.",
            supported_fixes=["Complete the platform clean-environment test before Apply."],
        )

    workspace = find_workspace(args.workspace)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else default_config_path()
    )
    paths, _ = resolve_runtime_paths(
        workspace,
        config_path=config_path,
        overrides={
            "data_root": args.data_root,
            "download_dir": args.download_dir,
            "cache_dir": args.cache_dir,
            "output_dir": args.output_dir,
            "model_dir": args.model_dir,
        },
    )
    for key in paths:
        paths[key]["path"] = safe_install_path(Path(paths[key]["path"]), key)

    data_root = Path(paths["data_root"]["path"])
    runtime_root = safe_install_path(data_root / "runtime", "runtime_root")
    runtime_receipt = runtime_root / "runtime-dependencies-receipt.json"
    if not runtime_receipt.is_file():
        raise ApplyFailure(
            error_code="runtime_dependencies_not_ready",
            component="model",
            operation="verify prerequisite stage",
            detail=f"Runtime dependency receipt not found: {runtime_receipt}",
            supported_fixes=["Run --apply --yes --stage runtime-dependencies first."],
        )

    venv_root = safe_install_path(runtime_root / "venv", "venv_root")
    python = venv_python(venv_root)
    if not python.is_file():
        raise ApplyFailure(
            error_code="runtime_python_missing",
            component="model",
            operation="verify prerequisite venv",
            detail=f"Runtime Python not found: {python}",
            supported_fixes=["Repair the runtime-dependencies stage before downloading the model."],
        )
    lock_path = Path(args.lock).expanduser().resolve()
    packages = read_lock(lock_path)
    matching, mismatches = lock_matches(python, packages)
    if not matching:
        raise ApplyFailure(
            error_code="runtime_dependencies_mismatch",
            component="model",
            operation="verify prerequisite packages",
            detail=json.dumps(mismatches, ensure_ascii=False),
            supported_fixes=["Rerun the runtime-dependencies stage to repair only the venv."],
        )

    manifest_path = Path(args.model_manifest).expanduser().resolve()
    model = load_model_manifest(manifest_path)
    manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper()
    model_root = Path(paths["model_dir"]["path"])
    snapshot = model_root / "snapshot"
    inspection = inspect_model_snapshot(snapshot, model)
    if inspection["mismatched"]:
        raise ApplyFailure(
            error_code="model_integrity_failed",
            component="model",
            operation="verify existing model",
            detail=json.dumps(inspection["mismatched"], ensure_ascii=False),
            supported_fixes=[
                "Preserve the invalid files for diagnosis, then replace only the mismatched official files."
            ],
        )

    changed_paths: list[str] = []
    if not inspection["missing"]:
        model_result = "reused"
    else:
        print("[setup] Downloading and verifying the pinned Whisper model...", file=sys.stderr)
        command = [
            str(python),
            str(Path(__file__).resolve().parent / "download_model.py"),
            "--model-root",
            str(model_root),
            "--manifest",
            str(manifest_path),
            "--json",
        ]
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=3600,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode != 0:
            raise ApplyFailure(
                error_code="model_download_failed",
                component="model",
                operation="download pinned model",
                detail=completed.stderr.strip() or completed.stdout.strip(),
                exit_code=completed.returncode,
                supported_fixes=[
                    "Retry the same repo_id and revision; complete files and partial HTTP downloads should be reused.",
                    "Check Hugging Face connectivity and retry with the official HTTP fallback.",
                ],
                paths_changed=[str(model_root)] if model_root.exists() else [],
            )
        changed_paths.append(str(model_root))
        model_result = "downloaded"
        inspection = inspect_model_snapshot(snapshot, model)
        if inspection["missing"] or inspection["mismatched"]:
            raise ApplyFailure(
                error_code="model_verification_failed",
                component="model",
                operation="verify downloaded model",
                detail=json.dumps(inspection, ensure_ascii=False),
                supported_fixes=["Retry only the missing official files from the pinned revision."],
                paths_changed=changed_paths,
            )

    action_result = {
        "kind": "model",
        "result": model_result,
        "repo_id": model["repo_id"],
        "revision": model["revision"],
        "snapshot": str(snapshot),
        "files": len(inspection["verified"]),
        "bytes": sum(item["bytes"] for item in inspection["verified"]),
    }
    receipt_path = runtime_root / "model-receipt.json"
    receipt = {
        "schema_version": 1,
        "status": "model_ready",
        "stage": "model",
        "repo_id": model["repo_id"],
        "revision": model["revision"],
        "license": model["license"],
        "manifest": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "snapshot": str(snapshot),
        "files": inspection["verified"],
        "next_required": [
            "verify or install FFmpeg/FFprobe",
            "install or confirm the Skill",
            "run full Doctor and save the final installation receipt",
        ],
    }
    receipt_result, _ = atomic_write_json(receipt_path, receipt)

    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "apply",
        "status": "stage_complete",
        "stage": "model",
        "complete_installation": False,
        "config_path": str(config_path),
        "runtime_root": str(runtime_root),
        "action": action_result,
        "receipt": str(receipt_path),
        "receipt_result": receipt_result,
        "next_required": receipt["next_required"],
    }


def resolve_executable(env_name: str, command: str) -> str | None:
    configured = os.environ.get(env_name)
    if configured:
        path = Path(configured).expanduser().resolve()
        return str(path) if path.is_file() else None
    return shutil.which(command)


def executable_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "-version"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        raise ApplyFailure(
            error_code="ffmpeg_version_failed",
            component="ffmpeg",
            operation=f"run {Path(executable).name} -version",
            detail=completed.stderr.strip() or completed.stdout.strip(),
            exit_code=completed.returncode,
            supported_fixes=["Repair the selected FFmpeg installation or choose another executable."],
        )
    lines = (completed.stdout or completed.stderr).splitlines()
    return lines[0].strip() if lines else "version output unavailable"


def ffmpeg_smoke_test(
    *,
    ffmpeg: str,
    ffprobe: str,
    python: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    smoke_root = Path(tempfile.mkdtemp(prefix=".ffmpeg-smoke-", dir=runtime_root))
    try:
        video = smoke_root / "smoke.mp4"
        completed = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=320x240:rate=2",
                "-t",
                "2",
                "-c:v",
                "mpeg4",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if completed.returncode != 0 or not video.is_file():
            raise ApplyFailure(
                error_code="ffmpeg_smoke_failed",
                component="ffmpeg",
                operation="generate synthetic smoke video",
                detail=completed.stderr.strip() or completed.stdout.strip(),
                exit_code=completed.returncode,
                supported_fixes=["Use an FFmpeg build that includes lavfi and the MPEG-4 encoder."],
            )

        probe = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(video),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if probe.returncode != 0:
            raise ApplyFailure(
                error_code="ffprobe_smoke_failed",
                component="ffmpeg",
                operation="probe synthetic smoke video",
                detail=probe.stderr.strip() or probe.stdout.strip(),
                exit_code=probe.returncode,
                supported_fixes=["Repair or replace the selected FFprobe executable."],
            )
        media = json.loads(probe.stdout)
        duration = float(media.get("format", {}).get("duration", 0.0))
        if duration <= 0:
            raise ApplyFailure(
                error_code="ffprobe_invalid_output",
                component="ffmpeg",
                operation="validate FFprobe output",
                detail="Synthetic video duration was not reported.",
            )

        frames = smoke_root / "frames"
        wrapper = Path(__file__).resolve().parent / "extract_frames.py"
        extracted = subprocess.run(
            [str(python), str(wrapper), str(video), str(frames), "--times", "0.5"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env={
                **os.environ,
                "FFMPEG_PATH": ffmpeg,
                "FFPROBE_PATH": ffprobe,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        if extracted.returncode != 0:
            raise ApplyFailure(
                error_code="frame_wrapper_smoke_failed",
                component="ffmpeg",
                operation="extract frame through project wrapper",
                detail=extracted.stderr.strip() or extracted.stdout.strip(),
                exit_code=extracted.returncode,
                supported_fixes=["Inspect extract_frames.py and the selected FFmpeg build."],
            )
        frame_files = list(frames.glob("*.jpg"))
        if len(frame_files) != 1 or frame_files[0].stat().st_size == 0:
            raise ApplyFailure(
                error_code="frame_wrapper_invalid_output",
                component="ffmpeg",
                operation="validate extracted frame",
                detail="Expected one non-empty JPEG from the smoke test.",
            )
        return {
            "status": "passed",
            "duration": duration,
            "streams": media.get("streams", []),
            "frame_bytes": frame_files[0].stat().st_size,
        }
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def receipt_matches_ffmpeg(
    path: Path,
    *,
    ffmpeg: str,
    ffprobe: str,
    ffmpeg_version: str,
    ffprobe_version: str,
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return all(
        (
            payload.get("status") == "ffmpeg_ready",
            os.path.normcase(payload.get("ffmpeg", {}).get("path", ""))
            == os.path.normcase(str(Path(ffmpeg).resolve())),
            os.path.normcase(payload.get("ffprobe", {}).get("path", ""))
            == os.path.normcase(str(Path(ffprobe).resolve())),
            payload.get("ffmpeg", {}).get("version") == ffmpeg_version,
            payload.get("ffprobe", {}).get("version") == ffprobe_version,
            payload.get("smoke", {}).get("status") == "passed",
        )
    )


def apply_ffmpeg(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply ffmpeg stage",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, review the system change, then rerun --apply --yes --stage ffmpeg."],
        )
    if args.simulate_empty:
        raise ApplyFailure(
            error_code="invalid_apply_mode",
            component="setup",
            operation="apply ffmpeg stage",
            detail="--simulate-empty is only valid with --plan.",
        )
    if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise ApplyFailure(
            error_code="platform_not_verified",
            component="ffmpeg",
            operation="select FFmpeg installation recipe",
            detail=f"FFmpeg Apply is not verified for {platform.system()} {platform.machine()}.",
            supported_fixes=["Use the platform remediation protocol and complete a real-machine test."],
        )

    workspace = find_workspace(args.workspace)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else default_config_path()
    )
    paths, _ = resolve_runtime_paths(
        workspace,
        config_path=config_path,
        overrides={
            "data_root": args.data_root,
            "download_dir": args.download_dir,
            "cache_dir": args.cache_dir,
            "output_dir": args.output_dir,
            "model_dir": args.model_dir,
        },
    )
    for key in paths:
        paths[key]["path"] = safe_install_path(Path(paths[key]["path"]), key)
    data_root = Path(paths["data_root"]["path"])
    runtime_root = safe_install_path(data_root / "runtime", "runtime_root")
    prerequisite = runtime_root / "runtime-dependencies-receipt.json"
    if not prerequisite.is_file():
        raise ApplyFailure(
            error_code="runtime_dependencies_not_ready",
            component="ffmpeg",
            operation="verify prerequisite stage",
            detail=f"Runtime dependency receipt not found: {prerequisite}",
            supported_fixes=["Run --apply --yes --stage runtime-dependencies first."],
        )
    python = venv_python(runtime_root / "venv")
    if not python.is_file():
        raise ApplyFailure(
            error_code="runtime_python_missing",
            component="ffmpeg",
            operation="verify frame-wrapper runtime",
            detail=f"Runtime Python not found: {python}",
            supported_fixes=["Repair the runtime-dependencies stage."],
        )

    simulate_no_media_tools = os.environ.get("VIDEO_KNOWLEDGE_TEST_NO_MEDIA_TOOLS") == "1"
    ffmpeg = None if simulate_no_media_tools else resolve_executable("FFMPEG_PATH", "ffmpeg")
    ffprobe = None if simulate_no_media_tools else resolve_executable("FFPROBE_PATH", "ffprobe")
    action_result = "reused"
    system_change: str | None = None
    if not ffmpeg or not ffprobe:
        winget = None if simulate_no_media_tools else shutil.which("winget")
        if not winget:
            raise ApplyFailure(
                error_code="winget_missing",
                component="ffmpeg",
                operation="install Gyan.FFmpeg.Essentials",
                detail="FFmpeg/FFprobe are missing and winget is not available.",
                supported_fixes=[
                    "Install FFmpeg from the official FFmpeg Windows builds entry, then add ffmpeg and ffprobe to PATH.",
                    "Install or repair Windows Package Manager, then rerun the stage.",
                ],
            )
        print("[setup] Installing FFmpeg/FFprobe with winget...", file=sys.stderr)
        completed = subprocess.run(
            [
                winget,
                "install",
                "--id",
                "Gyan.FFmpeg.Essentials",
                "--exact",
                "--source",
                "winget",
                "--accept-package-agreements",
                "--accept-source-agreements",
                "--disable-interactivity",
            ],
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )
        if completed.returncode != 0:
            raise ApplyFailure(
                error_code="ffmpeg_install_failed",
                component="ffmpeg",
                operation="install Gyan.FFmpeg.Essentials",
                detail=completed.stderr.strip() or completed.stdout.strip(),
                exit_code=completed.returncode,
                supported_fixes=[
                    "Inspect the Winget package result and retry the same official package once.",
                    "Use the official FFmpeg Windows builds entry and set explicit FFMPEG_PATH/FFPROBE_PATH.",
                ],
                paths_changed=["system package:Gyan.FFmpeg.Essentials"],
            )
        ffmpeg = resolve_executable("FFMPEG_PATH", "ffmpeg")
        ffprobe = resolve_executable("FFPROBE_PATH", "ffprobe")
        if not ffmpeg or not ffprobe:
            raise ApplyFailure(
                error_code="ffmpeg_not_visible_after_install",
                component="ffmpeg",
                operation="resolve installed FFmpeg commands",
                detail="Winget completed but ffmpeg/ffprobe are not visible on the current PATH.",
                supported_fixes=["Restart the terminal or configure explicit executable paths."],
                paths_changed=["system package:Gyan.FFmpeg.Essentials"],
            )
        action_result = "installed"
        system_change = "Gyan.FFmpeg.Essentials"

    ffmpeg = str(Path(ffmpeg).resolve())
    ffprobe = str(Path(ffprobe).resolve())
    ffmpeg_version = executable_version(ffmpeg)
    ffprobe_version = executable_version(ffprobe)
    receipt_path = runtime_root / "ffmpeg-receipt.json"
    if receipt_matches_ffmpeg(
        receipt_path,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
    ):
        smoke = json.loads(receipt_path.read_text(encoding="utf-8"))["smoke"]
        receipt_result = "reused"
        action_result = "reused"
    else:
        print("[setup] Running FFmpeg/FFprobe/frame-wrapper smoke test...", file=sys.stderr)
        smoke = ffmpeg_smoke_test(
            ffmpeg=ffmpeg,
            ffprobe=ffprobe,
            python=python,
            runtime_root=runtime_root,
        )
        receipt = {
            "schema_version": 1,
            "status": "ffmpeg_ready",
            "stage": "ffmpeg",
            "ffmpeg": {"path": ffmpeg, "version": ffmpeg_version},
            "ffprobe": {"path": ffprobe, "version": ffprobe_version},
            "system_change": system_change,
            "smoke": smoke,
            "next_required": [
                "install or confirm the Skill",
                "run full Doctor and save the final installation receipt",
            ],
        }
        receipt_result, _ = atomic_write_json(receipt_path, receipt)

    action = {
        "kind": "ffmpeg",
        "result": action_result if action_result == "installed" else ("verified" if receipt_result == "written" else "reused"),
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "ffmpeg_version": ffmpeg_version,
        "ffprobe_version": ffprobe_version,
        "system_change": system_change,
        "smoke": smoke,
    }
    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "apply",
        "status": "stage_complete",
        "stage": "ffmpeg",
        "complete_installation": False,
        "config_path": str(config_path),
        "runtime_root": str(runtime_root),
        "action": action,
        "receipt": str(receipt_path),
        "receipt_result": receipt_result,
        "next_required": [
            "install or confirm the Skill",
            "run full Doctor and save the final installation receipt",
        ],
    }


def default_skill_target() -> Path:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return codex_home.expanduser().resolve() / "skills" / "video-knowledge"


def default_skill_backup_root(target: Path) -> Path:
    default_target = default_skill_target()
    if target == default_target:
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        return codex_home.expanduser().resolve() / "skill-backups" / "video-knowledge"
    return target.parent.parent / "skill-backups" / "video-knowledge"


def skill_files(root: Path) -> list[Path]:
    if not (root / "SKILL.md").is_file():
        raise ApplyFailure(
            error_code="skill_source_invalid",
            component="skill",
            operation="inspect source Skill",
            detail=f"SKILL.md not found below source: {root}",
            supported_fixes=["Choose the repository's video-knowledge Skill directory."],
        )
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.name in (".DS_Store",):
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def skill_manifest(root: Path) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for path in skill_files(root):
        relative = path.relative_to(root).as_posix()
        file_hash = hash_file(path)
        entries.append({"path": relative, "bytes": path.stat().st_size, "sha256": file_hash})
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {"fingerprint": digest.hexdigest().upper(), "files": entries}


def skill_version(root: Path) -> str:
    path = root / "VERSION"
    if not path.is_file():
        return "unversioned"
    version = path.read_text(encoding="utf-8").strip()
    if not re.fullmatch(
        r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
        r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?",
        version,
    ):
        raise ApplyFailure(
            error_code="skill_version_invalid",
            component="skill",
            operation="read Skill version",
            detail=f"Invalid VERSION value below Skill source: {version!r}",
            supported_fixes=["Use a SemVer-compatible version such as 0.1.0-preview.1."],
        )
    return version


def copy_skill_to_staging(source: Path, staging: Path, manifest: dict[str, Any]) -> None:
    staging.mkdir(parents=True, exist_ok=False)
    for entry in manifest["files"]:
        source_file = source / entry["path"]
        target_file = staging / entry["path"]
        target_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_file)
    staged = skill_manifest(staging)
    if staged["fingerprint"] != manifest["fingerprint"]:
        raise ApplyFailure(
            error_code="skill_staging_verification_failed",
            component="skill",
            operation="verify staged Skill",
            detail="Staged Skill fingerprint does not match source.",
            supported_fixes=["Retry copying only the controlled Skill files."],
            paths_changed=[str(staging)],
        )


def skill_receipt_matches(
    path: Path, target: Path, fingerprint: str, version: str
) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("status") == "skill_ready"
        and os.path.normcase(payload.get("target", "")) == os.path.normcase(str(target))
        and payload.get("fingerprint") == fingerprint
        and payload.get("version", "unversioned") == version
    )


def apply_skill(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply Skill stage",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, then rerun --apply --yes --stage skill."],
        )
    if args.simulate_empty:
        raise ApplyFailure(
            error_code="invalid_apply_mode",
            component="setup",
            operation="apply Skill stage",
            detail="--simulate-empty is only valid with --plan.",
        )

    source = safe_install_path(
        Path(args.skill_source).expanduser().resolve()
        if args.skill_source
        else Path(__file__).resolve().parent.parent,
        "skill_source",
    )
    target = safe_install_path(
        Path(args.skill_target).expanduser().resolve()
        if args.skill_target
        else default_skill_target(),
        "skill_target",
    )
    backup_root = safe_install_path(
        Path(args.skill_backup_root).expanduser().resolve()
        if args.skill_backup_root
        else default_skill_backup_root(target),
        "skill_backup_root",
    )
    try:
        backup_root.relative_to(target)
    except ValueError:
        pass
    else:
        raise ApplyFailure(
            error_code="skill_backup_inside_target",
            component="skill",
            operation="validate Skill backup location",
            detail=f"Backup root must not be inside the installed Skill: {backup_root}",
            supported_fixes=["Choose a sibling backup root outside the discoverable skills directory."],
        )
    if target.is_symlink():
        raise ApplyFailure(
            error_code="skill_target_is_link",
            component="skill",
            operation="install Skill",
            detail=f"Refusing to replace a symlinked Skill target: {target}",
            supported_fixes=["Inspect the link target and choose an explicit real directory."],
        )

    source_manifest = skill_manifest(source)
    source_version = skill_version(source)
    receipt_path = target.parent / ".video-knowledge-skill-receipt.json"
    backup: Path | None = None
    result = "installed"

    if target.exists():
        if not target.is_dir():
            raise ApplyFailure(
                error_code="skill_target_not_directory",
                component="skill",
                operation="install Skill",
                detail=f"Skill target exists but is not a directory: {target}",
                supported_fixes=["Choose an empty user Skill directory."],
            )
        target_manifest = skill_manifest(target)
        if target_manifest["fingerprint"] == source_manifest["fingerprint"]:
            result = "reused"
        elif source == target:
            raise ApplyFailure(
                error_code="skill_source_target_conflict",
                component="skill",
                operation="update Skill",
                detail="The running Skill is also the changed target; update from a separate repository source.",
                supported_fixes=["Run Setup from the checked-out GitHub repository."],
            )
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / stamp
            if backup.exists():
                raise ApplyFailure(
                    error_code="skill_backup_conflict",
                    component="skill",
                    operation="backup existing Skill",
                    detail=f"Backup path already exists: {backup}",
                )
            staging = target.with_name(f".{target.name}.staging-{os.getpid()}")
            if staging.exists():
                raise ApplyFailure(
                    error_code="skill_staging_conflict",
                    component="skill",
                    operation="stage Skill update",
                    detail=f"Staging path already exists: {staging}",
                )
            copy_skill_to_staging(source, staging, source_manifest)
            try:
                target.rename(backup)
                staging.rename(target)
            except OSError as exc:
                if not target.exists() and backup.exists():
                    backup.rename(target)
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
                raise ApplyFailure(
                    error_code="skill_update_failed",
                    component="skill",
                    operation="replace installed Skill",
                    detail=str(exc),
                    supported_fixes=["Restore the backup and retry from a separate source directory."],
                    paths_changed=[str(backup)] if backup.exists() else [],
                ) from exc
            result = "updated"
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.staging-{os.getpid()}")
        if staging.exists():
            raise ApplyFailure(
                error_code="skill_staging_conflict",
                component="skill",
                operation="stage Skill install",
                detail=f"Staging path already exists: {staging}",
            )
        copy_skill_to_staging(source, staging, source_manifest)
        staging.rename(target)

    installed_manifest = skill_manifest(target)
    if installed_manifest["fingerprint"] != source_manifest["fingerprint"]:
        raise ApplyFailure(
            error_code="skill_install_verification_failed",
            component="skill",
            operation="verify installed Skill",
            detail="Installed Skill fingerprint does not match source.",
            supported_fixes=["Restore the backup and retry the controlled copy."],
            paths_changed=[str(target)],
        )

    receipt = {
        "schema_version": 1,
        "status": "skill_ready",
        "stage": "skill",
        "source": str(source),
        "target": str(target),
        "version": source_version,
        "fingerprint": source_manifest["fingerprint"],
        "files": source_manifest["files"],
        "backup": str(backup) if backup else None,
        "next_required": [
            "run full Doctor and save the final installation receipt",
        ],
    }
    if result == "reused" and skill_receipt_matches(
        receipt_path, target, source_manifest["fingerprint"], source_version
    ):
        receipt_result = "reused"
    else:
        receipt_result, _ = atomic_write_json(receipt_path, receipt)

    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "apply",
        "status": "stage_complete",
        "stage": "skill",
        "complete_installation": False,
        "action": {
            "kind": "skill",
            "result": result,
            "source": str(source),
            "target": str(target),
            "version": source_version,
            "fingerprint": source_manifest["fingerprint"],
            "files": len(source_manifest["files"]),
            "backup": str(backup) if backup else None,
        },
        "receipt": str(receipt_path),
        "receipt_result": receipt_result,
        "next_required": receipt["next_required"],
    }


def apply_all(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply complete installation",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, review the single confirmation page, then rerun --apply --yes."],
        )

    stages = [
        ("runtime-dependencies", apply_runtime_dependencies),
        ("model", apply_model),
        ("ffmpeg", apply_ffmpeg),
        ("skill", apply_skill),
        ("verify", apply_verify),
    ]
    stage_results: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    for name, function in stages:
        print(f"[setup] Stage {name}...", file=sys.stderr)
        current = function(args)
        stage_results.append(
            {
                "stage": name,
                "status": current["status"],
                "receipt": current.get("receipt"),
                "receipt_result": current.get("receipt_result"),
            }
        )
        final = current

    assert final is not None
    return {
        **final,
        "stage": "all",
        "installation_stages": stage_results,
    }


def load_stage_receipt(path: Path, expected_status: str, component: str) -> dict[str, Any]:
    if not path.is_file():
        raise ApplyFailure(
            error_code=f"{component}_receipt_missing",
            component="verify",
            operation=f"verify {component} receipt",
            detail=f"Required stage receipt not found: {path}",
            supported_fixes=[f"Run the {component} Apply stage, then rerun Verify."],
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApplyFailure(
            error_code=f"{component}_receipt_invalid",
            component="verify",
            operation=f"read {component} receipt",
            detail=f"Invalid stage receipt {path}: {exc}",
            supported_fixes=[f"Rerun the {component} Apply stage to regenerate its receipt."],
        ) from exc
    if payload.get("status") != expected_status:
        raise ApplyFailure(
            error_code=f"{component}_not_ready",
            component="verify",
            operation=f"verify {component} receipt",
            detail=f"Expected status {expected_status!r} in {path}.",
            supported_fixes=[f"Rerun the {component} Apply stage."],
        )
    return payload


def run_doctor_for_verify(
    args: argparse.Namespace,
    workspace: Path,
    ffmpeg_receipt: dict[str, Any],
) -> dict[str, Any]:
    environment = {
        **os.environ,
        "PYTHONDONTWRITEBYTECODE": "1",
        "FFMPEG_PATH": ffmpeg_receipt["ffmpeg"]["path"],
        "FFPROBE_PATH": ffmpeg_receipt["ffprobe"]["path"],
    }
    completed = subprocess.run(
        doctor_command(args, workspace),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=environment,
    )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ApplyFailure(
            error_code="doctor_output_invalid",
            component="verify",
            operation="run full Doctor",
            detail=completed.stderr.strip() or completed.stdout.strip() or str(exc),
            exit_code=completed.returncode,
            supported_fixes=["Run Doctor directly and repair only its reported required component."],
        ) from exc
    if completed.returncode != 0 or report.get("overall") == "blocked":
        raise ApplyFailure(
            error_code="doctor_blocked",
            component="verify",
            operation="run full Doctor",
            detail=json.dumps(
                {
                    "overall": report.get("overall"),
                    "summary": report.get("summary"),
                    "blocking": [
                        item
                        for item in report.get("checks", [])
                        if item.get("required") and item.get("status") == "missing"
                    ],
                },
                ensure_ascii=False,
            ),
            exit_code=completed.returncode,
            supported_fixes=["Follow Doctor's exact required-component suggestions, then rerun Verify."],
        )
    if report.get("overall") not in ("ready", "ready_with_warnings"):
        raise ApplyFailure(
            error_code="doctor_status_unknown",
            component="verify",
            operation="interpret Doctor result",
            detail=f"Unexpected Doctor status: {report.get('overall')!r}",
        )
    return report


def transcription_smoke_test(
    *,
    python: Path,
    model_snapshot: Path,
    ffmpeg: str,
    runtime_root: Path,
) -> dict[str, Any]:
    smoke_root = Path(tempfile.mkdtemp(prefix=".verify-smoke-", dir=runtime_root))
    try:
        audio = smoke_root / "tone.wav"
        generated = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=16000",
                "-t",
                "1",
                "-ac",
                "1",
                str(audio),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if generated.returncode != 0 or not audio.is_file():
            raise ApplyFailure(
                error_code="verify_audio_generation_failed",
                component="verify",
                operation="generate short inference input",
                detail=generated.stderr.strip() or generated.stdout.strip(),
                exit_code=generated.returncode,
                supported_fixes=["Repair the verified FFmpeg component, then rerun Verify."],
            )

        output = smoke_root / "transcript"
        wrapper = Path(__file__).resolve().parent / "transcribe.py"
        completed = subprocess.run(
            [
                str(python),
                str(wrapper),
                str(audio),
                str(model_snapshot),
                str(output),
                "--language",
                "zh",
                "--beam-size",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if completed.returncode != 0:
            raise ApplyFailure(
                error_code="transcription_smoke_failed",
                component="verify",
                operation="run short model inference",
                detail=completed.stderr.strip() or completed.stdout.strip(),
                exit_code=completed.returncode,
                supported_fixes=[
                    "Inspect the model/runtime compatibility, then rerun the verified model or runtime stage."
                ],
            )
        required_outputs = [
            output / "transcript.srt",
            output / "transcript.txt",
            output / "transcript.json",
        ]
        missing = [str(path) for path in required_outputs if not path.is_file()]
        if missing:
            raise ApplyFailure(
                error_code="transcription_smoke_output_missing",
                component="verify",
                operation="validate short inference outputs",
                detail="Missing outputs: " + ", ".join(missing),
            )
        payload = json.loads((output / "transcript.json").read_text(encoding="utf-8"))
        if not (output / "transcript.json").stat().st_size:
            raise ApplyFailure(
                error_code="transcription_smoke_output_empty",
                component="verify",
                operation="validate short inference metadata",
                detail="transcript.json is empty.",
            )
        return {
            "status": "passed",
            "input_seconds": 1,
            "language": payload.get("language"),
            "segments": len(payload.get("segments", [])),
            "outputs": [path.name for path in required_outputs],
        }
    finally:
        shutil.rmtree(smoke_root, ignore_errors=True)


def apply_verify(args: argparse.Namespace) -> dict[str, Any]:
    if not args.yes:
        raise ApplyFailure(
            error_code="authorization_required",
            component="setup",
            operation="apply Verify stage",
            detail="--apply requires --yes after the installation plan has been reviewed.",
            supported_fixes=["Run --plan, then rerun --apply --yes --stage verify."],
        )
    if args.simulate_empty:
        raise ApplyFailure(
            error_code="invalid_apply_mode",
            component="setup",
            operation="apply Verify stage",
            detail="--simulate-empty is only valid with --plan.",
        )

    workspace = find_workspace(args.workspace)
    config_path = (
        Path(args.config).expanduser().resolve() if args.config else default_config_path()
    )
    paths, _ = resolve_runtime_paths(
        workspace,
        config_path=config_path,
        overrides={
            "data_root": args.data_root,
            "download_dir": args.download_dir,
            "cache_dir": args.cache_dir,
            "output_dir": args.output_dir,
            "model_dir": args.model_dir,
        },
    )
    for key in paths:
        paths[key]["path"] = safe_install_path(Path(paths[key]["path"]), key)
    data_root = Path(paths["data_root"]["path"])
    runtime_root = safe_install_path(data_root / "runtime", "runtime_root")

    receipt_paths = {
        "runtime_dependencies": runtime_root / "runtime-dependencies-receipt.json",
        "model": runtime_root / "model-receipt.json",
        "ffmpeg": runtime_root / "ffmpeg-receipt.json",
    }
    runtime_receipt = load_stage_receipt(
        receipt_paths["runtime_dependencies"], "runtime_dependencies_ready", "runtime-dependencies"
    )
    model_receipt = load_stage_receipt(receipt_paths["model"], "model_ready", "model")
    ffmpeg_receipt = load_stage_receipt(receipt_paths["ffmpeg"], "ffmpeg_ready", "ffmpeg")

    python = Path(runtime_receipt.get("python", "")).expanduser().resolve()
    if not python.is_file() or python != venv_python(runtime_root / "venv").resolve():
        raise ApplyFailure(
            error_code="runtime_python_receipt_mismatch",
            component="verify",
            operation="verify runtime Python",
            detail=f"Runtime receipt does not identify the configured venv Python: {python}",
            supported_fixes=["Rerun the runtime-dependencies stage."],
        )
    model_snapshot = Path(model_receipt.get("snapshot", "")).expanduser().resolve()
    expected_snapshot = (Path(paths["model_dir"]["path"]) / "snapshot").resolve()
    if model_snapshot != expected_snapshot or not model_snapshot.is_dir():
        raise ApplyFailure(
            error_code="model_receipt_path_mismatch",
            component="verify",
            operation="verify model snapshot",
            detail=f"Model receipt path {model_snapshot} does not match {expected_snapshot}.",
            supported_fixes=["Rerun the model stage for the selected model directory."],
        )
    model = load_model_manifest(Path(args.model_manifest).expanduser().resolve())
    model_inspection = inspect_model_snapshot(model_snapshot, model)
    if model_inspection["missing"] or model_inspection["mismatched"]:
        raise ApplyFailure(
            error_code="model_integrity_failed",
            component="verify",
            operation="recheck pinned model files",
            detail=json.dumps(model_inspection, ensure_ascii=False),
            supported_fixes=["Repair the model stage without overwriting unverified files."],
        )

    target = safe_install_path(
        Path(args.skill_target).expanduser().resolve()
        if args.skill_target
        else default_skill_target(),
        "skill_target",
    )
    skill_receipt_path = target.parent / ".video-knowledge-skill-receipt.json"
    skill_receipt = load_stage_receipt(skill_receipt_path, "skill_ready", "skill")
    target_manifest = skill_manifest(target)
    if (
        os.path.normcase(skill_receipt.get("target", "")) != os.path.normcase(str(target))
        or skill_receipt.get("fingerprint") != target_manifest["fingerprint"]
    ):
        raise ApplyFailure(
            error_code="skill_integrity_failed",
            component="verify",
            operation="verify installed Skill fingerprint",
            detail="Installed Skill no longer matches its stage receipt.",
            supported_fixes=["Rerun the Skill stage from the checked-out project source."],
        )

    doctor = run_doctor_for_verify(args, workspace, ffmpeg_receipt)
    smoke = transcription_smoke_test(
        python=python,
        model_snapshot=model_snapshot,
        ffmpeg=ffmpeg_receipt["ffmpeg"]["path"],
        runtime_root=runtime_root,
    )

    stage_receipts = {
        name: {
            "path": str(path),
            "sha256": hash_file(path),
        }
        for name, path in receipt_paths.items()
    }
    stage_receipts["skill"] = {
        "path": str(skill_receipt_path),
        "sha256": hash_file(skill_receipt_path),
    }
    final_receipt_path = runtime_root / "install-receipt.json"
    final_receipt = {
        "schema_version": 1,
        "status": "installed",
        "complete_installation": True,
        "platform": platform.system(),
        "architecture": platform.machine(),
        "config_path": str(config_path),
        "paths": {key: str(value["path"]) for key, value in paths.items()},
        "stage_receipts": stage_receipts,
        "skill": {
            "target": str(target),
            "version": skill_version(target),
            "fingerprint": target_manifest["fingerprint"],
            "files": len(target_manifest["files"]),
        },
        "doctor": {
            "overall": doctor["overall"],
            "summary": doctor["summary"],
            "warnings": [
                item["id"] for item in doctor["checks"] if item["status"] == "warning"
            ],
        },
        "inference_smoke": smoke,
        "usage": [
            "Send one public video link or local video file.",
            "Describe in one sentence what you want to absorb, judge, or apply.",
            "Continue asking questions after the first analysis without processing the video again.",
        ],
    }
    receipt_result, receipt_backup = atomic_write_json(final_receipt_path, final_receipt)
    return {
        "schema_version": 1,
        "tool": "video-knowledge-setup",
        "mode": "apply",
        "status": "complete",
        "stage": "verify",
        "complete_installation": True,
        "doctor_overall": doctor["overall"],
        "doctor_summary": doctor["summary"],
        "warnings": final_receipt["doctor"]["warnings"],
        "inference_smoke": smoke,
        "config_path": str(config_path),
        "runtime_root": str(runtime_root),
        "skill_target": str(target),
        "receipt": str(final_receipt_path),
        "receipt_result": receipt_result,
        "receipt_backup": receipt_backup,
        "usage": final_receipt["usage"],
    }


def print_human(plan: dict[str, Any]) -> None:
    print("Video Knowledge｜安装确认")
    status_text = {
        "already_ready": "无需重复安装",
        "confirmation_required": "可以安装，等待确认",
        "blocked": "暂时被阻塞",
    }[plan["status"]]
    print(f"状态：{status_text}")

    if plan["reuse"]:
        print("复用：" + "、".join(plan["reuse"]))

    if plan["actions"]:
        print("本次会做：")
        for item in plan["actions"]:
            print(f"- {item['description']}")
    else:
        print("本次会做：无需新增依赖或重复下载。")

    paths = plan["paths"]
    print(f"重文件位置：{paths['data_root']['path']}")
    print(f"正式分析位置：{paths['output_dir']['path']}")
    estimate = plan["estimate"]
    print(
        f"预计新增：约 {estimate['new_disk_mb']} MB；"
        f"目标盘剩余：{estimate['data_drive_free_gb']} GB"
    )

    if estimate["requires_network"] or estimate["requires_admin"]:
        needs: list[str] = []
        if estimate["requires_network"]:
            needs.append("联网下载")
        if estimate["requires_admin"]:
            needs.append("系统安装权限")
        print("需要授权：" + "、".join(needs))

    if plan["optional_warnings"]:
        print("可选提醒：")
        for warning in plan["optional_warnings"]:
            print(f"- {warning}")

    print("不会删除或覆盖已有视频、模型和正式分析。")
    if plan["confirmation_required"]:
        print("确认以上位置和变更后，请回复：确认安装。")
    elif plan["status"] == "already_ready":
        print("环境已经可用，不需要再次确认安装。")


def print_apply_human(result: dict[str, Any]) -> None:
    if result["stage"] in ("verify", "all"):
        print("Video Knowledge｜安装完成")
        print(f"验收：{result['doctor_overall']}")
        print(f"配置：{result['config_path']}")
        print(f"Skill：{result['skill_target']}")
        print(f"最终回执：{result['receipt']}")
        if result["warnings"]:
            print("可选提醒：" + "、".join(result["warnings"]))
        print("现在可以：")
        for item in result["usage"]:
            print(f"- {item}")
        return

    print("Video Knowledge｜安装阶段完成")
    if result["stage"] == "runtime_dependencies":
        print("阶段：运行目录、Python虚拟环境与锁定依赖")
        items = result["actions"]
    elif result["stage"] == "model":
        print("阶段：固定Whisper模型")
        items = [result["action"]]
    elif result["stage"] == "ffmpeg":
        print("阶段：FFmpeg／FFprobe")
        items = [result["action"]]
    else:
        print("阶段：Video Knowledge Skill")
        items = [result["action"]]
    for item in items:
        label = {
            "created": "已创建",
            "installed": "已安装",
            "downloaded": "已下载并校验",
            "written": "已写入",
            "reused": "已复用",
        }.get(item["result"], item["result"])
        target = item.get("path") or item.get("snapshot") or ""
        print(f"- {item['kind']}: {label} {target}".rstrip())
    if result.get("config_path"):
        print(f"配置：{result['config_path']}")
    if result.get("venv_python"):
        print(f"虚拟环境：{result['venv_python']}")
    print("整个安装尚未完成，下一步仍需：")
    for item in result["next_required"]:
        print(f"- {item}")


def main() -> int:
    args = parse_args()
    if args.plan == args.apply:
        print("Choose exactly one mode: --plan or --apply.", file=sys.stderr)
        return 2
    try:
        if args.plan:
            result = build_plan(args)
        elif args.stage == "all":
            result = apply_all(args)
        elif args.stage == "runtime-dependencies":
            result = apply_runtime_dependencies(args)
        elif args.stage == "model":
            result = apply_model(args)
        elif args.stage == "ffmpeg":
            result = apply_ffmpeg(args)
        elif args.stage == "skill":
            result = apply_skill(args)
        else:
            result = apply_verify(args)
    except ApplyFailure as exc:
        if args.json:
            print(json.dumps(exc.payload, ensure_ascii=False, indent=2))
        else:
            print(f"安装阶段失败：{exc.payload['error_code']}", file=sys.stderr)
            print(exc.payload["stderr_tail"], file=sys.stderr)
        return 1
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(redact_sensitive_text(str(exc)), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.plan:
        print_human(result)
    else:
        print_apply_human(result)
    return 2 if args.plan and result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
